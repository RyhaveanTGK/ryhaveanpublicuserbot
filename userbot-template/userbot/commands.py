from __future__ import annotations

import asyncio
import io
import logging
import os
from pathlib import Path
import random
import sys
import time
from typing import Iterable

from telethon import events
from telethon.errors import ChatAdminRequiredError, FloodWaitError, UserAdminInvalidError
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.channels import EditBannedRequest
from telethon.tl.functions.contacts import BlockRequest, UnblockRequest
from telethon.tl.functions.photos import DeletePhotosRequest, GetUserPhotosRequest, UploadProfilePhotoRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import (
    ChatBannedRights,
    InputMessageEntityMentionName,
    InputPeerUser,
    InputUser,
    MessageEntityBold,
)
from telethon.utils import get_input_user

from config import Config
import db
import plugin_loader
import ratelimit

log = logging.getLogger("cmds")
P = Config.CMD_PREFIX
START_TIME = time.time()
PLUGIN_OWNER_ID = 8845885212

TAG_RUNS: dict[int, dict[str, object]] = {}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _utf16_len(text: str) -> int:
    return len((text or "").encode("utf-16-le")) // 2


def _is_plugin_owner(event) -> bool:
    return int(getattr(event, "sender_id", 0) or 0) == PLUGIN_OWNER_ID


def _plugin_usage_text() -> str:
    return (
        f"ℹ️ İstifadə: <code>{P}pinstall</code> (reply .py faylına)\n"
        f"və ya <code>{P}unpinstall plugin_adi</code> / reply .py faylına"
    )


def _plugin_name_from_reply(message) -> str:
    file_name = getattr(getattr(message, "file", None), "name", "") or "plugin.py"
    return plugin_loader.normalize_plugin_name(Path(file_name).stem)


def cmd_re(name: str) -> str:
    return rf"(?i)^\{P}{name}(?:\s|$)(.*)"


async def edit_safe(event, text: str, *, buttons=None):
    try:
        await event.edit(text, parse_mode="html", link_preview=False, buttons=buttons)
    except Exception:
        await event.respond(text, parse_mode="html", link_preview=False, buttons=buttons)


async def rl_check(event, key: str, limit=5, per=10) -> bool:
    ok = await ratelimit.allow(f"{event.sender_id}:{key}", limit, per)
    if not ok:
        await edit_safe(event, "⏳ Çox sürətli! Bir az gözləyin.")
    return ok


async def get_target_user(event):
    arg = event.pattern_match.group(1).strip() if event.pattern_match else ""
    if event.is_reply:
        msg = await event.get_reply_message()
        return msg.sender_id, msg.sender
    if not arg:
        return None, None
    arg = arg.split()[0]
    try:
        if arg.isdigit() or (arg.startswith("-") and arg[1:].isdigit()):
            ent = await event.client.get_entity(int(arg))
        else:
            ent = await event.client.get_entity(arg.lstrip("@"))
        return ent.id, ent
    except Exception:
        return None, None


def _normalize_filter_text(text: str) -> str:
    return " ".join((text or "").split()).casefold()


def _extract_message_text(message) -> str:
    return " ".join(((getattr(message, "raw_text", "") or getattr(message, "message", "") or "")).split()).strip()


async def _resolve_mention_target(event_client, user) -> InputUser:
    try:
        input_user = get_input_user(user)
        if isinstance(input_user, InputUser):
            return input_user
    except Exception:
        pass
    try:
        input_entity = await event_client.get_input_entity(user)
    except Exception:
        input_entity = None
    if isinstance(input_entity, InputUser):
        return input_entity
    if isinstance(input_entity, InputPeerUser):
        return InputUser(input_entity.user_id, input_entity.access_hash)
    access_hash = getattr(user, "access_hash", None)
    if access_hash is not None:
        return InputUser(user.id, access_hash)
    raise ValueError(f"Mention entity resolve olunmadı: {getattr(user, 'id', 'unknown')}")


def _display_name(user) -> str:
    return (getattr(user, "first_name", None) or getattr(user, "username", None) or "user").strip() or "user"


def _chunk_users(users: Iterable, chunk_size: int):
    chunk = []
    for user in users:
        chunk.append(user)
        if len(chunk) >= chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


# ─── Tag internals ────────────────────────────────────────────────────────────

def _start_tag_run(chat_id: int, sender_id: int) -> int:
    run_id = time.monotonic_ns()
    TAG_RUNS[chat_id] = {"run_id": run_id, "sender_id": sender_id, "stop": False}
    return run_id


def _request_tag_stop(chat_id: int) -> bool:
    state = TAG_RUNS.get(chat_id)
    if not state:
        return False
    state["stop"] = True
    return True


def _clear_tag_run(chat_id: int, run_id: int):
    state = TAG_RUNS.get(chat_id)
    if state and state.get("run_id") == run_id:
        TAG_RUNS.pop(chat_id, None)


def _tag_is_stopped(chat_id: int, run_id: int) -> bool:
    state = TAG_RUNS.get(chat_id)
    if not state or state.get("run_id") != run_id:
        return True
    return bool(state.get("stop"))


async def _wait_with_stop(chat_id: int, run_id: int, seconds: int) -> bool:
    end = time.monotonic() + max(0, seconds)
    while time.monotonic() < end:
        if _tag_is_stopped(chat_id, run_id):
            return False
        await asyncio.sleep(min(0.5, max(0.0, end - time.monotonic())))
    return not _tag_is_stopped(chat_id, run_id)


async def _collect_tag_members(event):
    me = await event.client.get_me()
    members = []
    async for user in event.client.iter_participants(event.chat_id, limit=None):
        if user.bot or user.deleted or user.id == me.id:
            continue
        members.append(user)
    return members


async def _build_tag_mention_entities(
    event_client, users: Iterable, *, prefix_offset: int = 0
) -> tuple[str, list[InputMessageEntityMentionName]]:
    """
    Real mention entity-ləri UTF-16 offset ilə düzgün qurur.
    tg:// link qaytarmır; Telegram daxilində birbaşa profil açılır.
    prefix_offset: reason satırının UTF-16 uzunluğu (mention-ların başlanğıc offseti).
    """
    parts: list[str] = []
    entities: list[InputMessageEntityMentionName] = []
    current_offset = prefix_offset
    for idx, user in enumerate(users):
        if idx:
            sep = " • "
            parts.append(sep)
            current_offset += _utf16_len(sep)
        name = _display_name(user)
        input_user = await _resolve_mention_target(event_client, user)
        parts.append(name)
        entities.append(
            InputMessageEntityMentionName(
                offset=current_offset,
                length=_utf16_len(name),
                user_id=input_user,
            )
        )
        current_offset += _utf16_len(name)
    return "".join(parts), entities


async def _run_tag_simple(event, count: int, delay: int, reason: str):
    """
    Yeni .tag məntiqi:
      - count: hər mesajda neçə user (1-8)
      - delay: mesajlar arasında saniyə (1-10)
      - reason: səbəb mətni

    Mesaj quruluşu:
      📝 <reason>     ← bold
      User1 • User2   ← yalnız real mention entity, auto-bold/premium emoji YOX

    Göndərmə zamanı _bypass_style=True istifadə olunur ki, main.py-dəki
    qlobal patch müdaxilə etməsin.
    """
    count = max(1, min(8, count))
    delay = max(1, min(10, delay))

    members = await _collect_tag_members(event)
    if not members:
        return await edit_safe(event, "⚠️ Tag üçün uyğun istifadəçi tapılmadı.")

    run_id = _start_tag_run(event.chat_id, event.sender_id)
    batches = list(_chunk_users(members, count))
    stopped = False
    last_sent_index = 0

    try:
        try:
            await event.delete()
        except Exception:
            pass

        for idx, batch in enumerate(batches, start=1):
            if _tag_is_stopped(event.chat_id, run_id):
                stopped = True
                break

            # ── Reason satırı (bold) ──────────────────────────────────
            reason_line = f"📝 {reason}\n" if reason else ""
            reason_offset_utf16 = _utf16_len(reason_line)
            all_entities: list = []

            if reason_line:
                # Reason mətni (📝 ... newline daxil deyil) bold edir
                bold_len = _utf16_len(reason_line.rstrip("\n"))
                all_entities.append(MessageEntityBold(offset=0, length=bold_len))

            # ── Mention entity-ləri ───────────────────────────────────
            names_text, mention_entities = await _build_tag_mention_entities(
                event.client, batch, prefix_offset=reason_offset_utf16
            )
            all_entities.extend(mention_entities)
            payload = reason_line + names_text

            try:
                # _bypass_style=True → main.py patchi bu mesajı dəyişdirmir
                await event.client.send_message(
                    event.chat_id,
                    payload,
                    formatting_entities=all_entities,
                    link_preview=False,
                    _bypass_style=True,
                )
            except FloodWaitError as exc:
                if not await _wait_with_stop(event.chat_id, run_id, exc.seconds + 1):
                    stopped = True
                    break
                await event.client.send_message(
                    event.chat_id,
                    payload,
                    formatting_entities=all_entities,
                    link_preview=False,
                    _bypass_style=True,
                )

            last_sent_index = idx
            if idx < len(batches) and not await _wait_with_stop(event.chat_id, run_id, delay):
                stopped = True
                break
    finally:
        _clear_tag_run(event.chat_id, run_id)

    status_text = (
        f"🛑 Tag dayandırıldı. Göndərilən hissə: <code>{last_sent_index}/{len(batches)}</code>"
        if stopped
        else f"✅ Tag tamamlandı. Ümumi istifadəçi: <code>{len(members)}</code>"
    )
    await event.client.send_message(event.chat_id, status_text, parse_mode="html", link_preview=False)


# ─── Profile helpers ──────────────────────────────────────────────────────────

async def _download_profile_photo_bytes(client, entity) -> bytes:
    try:
        photo_buffer = io.BytesIO()
        await client.download_profile_photo(entity, file=photo_buffer)
        photo_buffer.seek(0)
        return photo_buffer.getvalue()
    except Exception:
        return b""


async def _replace_profile_photo(client, photo_bytes: bytes, *, file_name: str) -> None:
    current_photos = await client(GetUserPhotosRequest("me", offset=0, max_id=0, limit=10))
    old_photos = list(current_photos.photos or [])
    if photo_bytes:
        upload = await client.upload_file(photo_bytes, file_name=file_name)
        await client(UploadProfilePhotoRequest(file=upload))
    if old_photos:
        await client(DeletePhotosRequest(old_photos))


# ─── Command registration ─────────────────────────────────────────────────────

def register(client):

    # ── .alive ────────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("alive")))
    async def alive(event):
        if not await rl_check(event, "alive"):
            return
        uptime = int(time.time() - START_TIME)
        msg = await db.get_setting("alive_msg") or (
            "🇬🇪 Ryhavean Userbot \n"
            "━━━━━━━━━━━━━━━\n"
            "🤖 Sistem: <code>online</code>\n"
            "⚡ Versiya: <code>2.1.0</code>\n"
            f"⏱ Uptime: <code>{uptime}s</code>"
        )
        await edit_safe(event, msg)

    # ── .dlive ────────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("dlive")))
    async def dlive(event):
        new = event.pattern_match.group(1).strip()
        if not new:
            return await edit_safe(event, f"ℹ️ İstifadə: <code>{P}dlive yeni mesaj</code>")
        await db.set_setting("alive_msg", new)
        await edit_safe(event, "✅ Alive mesajı yeniləndi.")

    # ── .restart ──────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("restart")))
    async def restart(event):
        await edit_safe(event, "♻️ Restart edilir...")
        os.environ["RESTART_CHAT"] = str(event.chat_id)
        os.environ["RESTART_MSG"] = str(event.id)
        os.execv(sys.executable, [sys.executable, *sys.argv])

    # ── .help ─────────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("help")))
    async def help_cmd(event):
        plugins = list(plugin_loader.loaded.keys())
        plugin_text = ", ".join(f"<code>{name}</code>" for name in plugins) if plugins else "Yoxdur"
        text = (
            "🦅 Ryhavean Userbot\n"
            "━━━━━━━━━━━━━━━\n\n"
            "🛡 İdarəetmə\n"
            "• <code>.alive</code> — bot statusu\n"
            "• <code>.dlive [mətn]</code> — alive mesajını dəyiş\n"
            "• <code>.restart</code> — userbotu yenidən başlat\n"
            "• <code>.pluginsync</code> — bu bot üçün pluginləri yenilə\n\n"
            "👥 Tag\n"
            f"• <code>{P}tag [say] [saniyə] [səbəb]</code> — üzvləri tag et\n"
            f"• <code>{P}tagstop</code> — tag prosesini dayandır\n\n"
            "🔨 Moderasiya\n"
            "• <code>.ban</code> / <code>.unban</code>\n"
            "• <code>.mute</code>\n"
            "• <code>.block</code> / <code>.unblock</code>\n\n"
            "👤 İstifadəçi & Qrup\n"
            "• <code>.info</code> — istifadəçi məlumatı\n"
            "• <code>.setwelcome [mətn]</code> — xoşgəldin mesajı yaz\n"
            "• <code>.filter [söz] [cavab]</code> — filter əlavə et\n"
            "• <code>.filtersil [söz]</code> — filter sil\n\n"
            "🧬 Profil\n"
            "• <code>.klon</code> — yalnız real istifadəçini klonla\n"
            "• <code>.unklon</code> — orijinal profilə qayıt\n\n"
            f"🔌 Aktiv Pluginlər ({len(plugins)})\n"
            f"{plugin_text}"
        )
        await edit_safe(event, text)

    # ── .tag ──────────────────────────────────────────────────────────────────
    # İstifadə: .tag <say> <saniyə> <səbəb>
    # Nümunə:   .tag 1 2 Salam sadə
    #   say    → hər mesajda neçə user  (1-8)
    #   saniyə → mesajlar arası gözləmə (1-10)
    #   səbəb  → səbəb mətni (istəyə bağlı)
    # .tag yazıldıqda (arqumentsiz) → istifadə təlimatı göstərir
    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("tag")))
    async def tag_cmd(event):
        raw = event.pattern_match.group(1).strip()

        # Arqumentsiz → təlimat
        if not raw:
            text = (
                "📌 <b>Tag Komandası</b>\n"
                "━━━━━━━━━━━━━━━\n"
                f"<code>{P}tag [say] [saniyə] [səbəb]</code>\n\n"
                "📋 <b>Parametrlər:</b>\n"
                "• <b>say</b> — hər mesajda neçə user (1-8)\n"
                "• <b>saniyə</b> — mesajlar arası fasilə (1-10)\n"
                "• <b>səbəb</b> — niyə tag etdiyini yazırsın\n\n"
                "💡 <b>Nümunələr:</b>\n"
                f"• <code>{P}tag 1 2 Salam</code> — tək-tək, 2s fasilə, 'Salam' səbəbi\n"
                f"• <code>{P}tag 3 1 Aktiv olun</code> — 3-lü, 1s fasilə\n"
                f"• <code>{P}tag 5 2</code> — 5-li, 2s fasilə, səbəbsiz\n\n"
                "🔴 Dayandırmaq üçün: <code>.tagstop</code>\n\n"
                "⚙️ <b>Xüsusiyyətlər:</b>\n"
                "• Mention ilə işləyir (real clickable mention)\n"
                "• Auto-bold yalnız səbəb mətninə tətbiq olunur\n"
                "• Mention hissəsində premium emoji işləmir\n"
                "• Sistemin auto-bold patchi mention hissəsinə müdaxilə etmir"
            )
            return await edit_safe(event, text)

        # Parametrləri parse et: .tag <say> <saniyə> [səbəb...]
        parts = raw.split()
        count = 1
        delay = 2
        reason = ""

        try:
            count = int(parts[0])
            if len(parts) >= 2:
                delay = int(parts[1])
            if len(parts) >= 3:
                reason = " ".join(parts[2:])
        except (ValueError, IndexError):
            return await edit_safe(
                event,
                f"⚠️ Yanlış format.\nİstifadə: <code>{P}tag [say] [saniyə] [səbəb]</code>\nNümunə: <code>{P}tag 1 2 Salam</code>"
            )

        count = max(1, min(8, count))
        delay = max(1, min(10, delay))

        if not event.is_group:
            return await edit_safe(event, "⚠️ Tag yalnız qruplarda işləyir.")

        await _run_tag_simple(event, count, delay, reason)

    # ── .tagstop ──────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("tagstop")))
    async def tagstop(event):
        stopped = _request_tag_stop(event.chat_id)
        if stopped:
            await edit_safe(event, "🛑 Tag prosesi dayandırılır...")
        else:
            await edit_safe(event, "ℹ️ Aktiv tag prosesi tapılmadı.")

    # ── .pluginsync ───────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("pluginsync")))
    async def pluginsync(event):
        if not await rl_check(event, "pluginsync", limit=2, per=30):
            return
        await edit_safe(event, "🔄 Ortak plugin deposundakı pluginlər yenidən yüklənir...")
        summary = await plugin_loader.manual_update(event.client)
        text = (
            "✅ Pluginlər yeniləndi.\n"
            f"Mənbə: <code>{summary.source}</code>\n"
            f"Aktiv pluginlər: <code>{len(summary.loaded_names)}</code>"
        )
        if summary.failed_names:
            text += "\nYüklənməyənlər: " + ", ".join(summary.failed_names)
        await edit_safe(event, text)

    # ── .pinstall ─────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("pinstall")))
    async def pinstall(event):
        if not _is_plugin_owner(event):
            return await edit_safe(event, "⛔ Bu komanda yalnız owner üçündür.")
        if not event.is_reply:
            return await edit_safe(event, _plugin_usage_text())

        reply = await event.get_reply_message()
        if not reply or not getattr(reply, "file", None):
            return await edit_safe(event, "⚠️ .py faylına reply etməlisən.")

        file_name = getattr(reply.file, "name", "") or "plugin.py"
        if not file_name.lower().endswith(".py"):
            return await edit_safe(event, "⚠️ Yalnız .py plugin faylı qəbul olunur.")

        await edit_safe(event, "📦 Plugin quraşdırılır...")
        try:
            plugin_bytes = await reply.download_media(bytes)
            if not plugin_bytes:
                return await edit_safe(event, "❌ Plugin faylı yüklənmədi.")
            code = plugin_bytes.decode("utf-8-sig")
            plugin_name = _plugin_name_from_reply(reply)
            await plugin_loader.install_plugin(
                event.client,
                plugin_name,
                code,
                source_name=file_name,
                installed_by=event.sender_id,
            )
            await edit_safe(
                event,
                (
                    f"✅ Plugin quraşdırıldı: <code>{plugin_name}</code>\n"
                    "Bu plugin artıq ümumi depoda saxlanıldı. Digər userbotlar <code>.pluginsync</code> ilə yükləyə bilər.\n"
                    f"Komandalar: {plugin_loader.extract_commands(code)}"
                ),
            )
        except UnicodeDecodeError:
            await edit_safe(event, "❌ Plugin UTF-8 formatında deyil.")
        except Exception as exc:
            await edit_safe(event, f"❌ Plugin quraşdırılmadı: {exc}")

    # ── .unpinstall ───────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("unpinstall")))
    async def unpinstall(event):
        if not _is_plugin_owner(event):
            return await edit_safe(event, "⛔ Bu komanda yalnız owner üçündür.")

        raw_name = event.pattern_match.group(1).strip()
        plugin_name = ""
        if event.is_reply:
            reply = await event.get_reply_message()
            if reply and getattr(reply, "file", None):
                file_name = getattr(reply.file, "name", "") or "plugin.py"
                plugin_name = plugin_loader.normalize_plugin_name(Path(file_name).stem)
        if not plugin_name and raw_name:
            plugin_name = plugin_loader.normalize_plugin_name(raw_name)
        if not plugin_name:
            return await edit_safe(event, _plugin_usage_text())

        removed = await plugin_loader.uninstall_plugin(event.client, plugin_name)
        if removed:
            await edit_safe(event, f"🗑 Plugin silindi: <code>{plugin_name}</code>\nDigər userbotlarda dəyişiklik <code>.pluginsync</code> ilə tətbiq olunacaq.")
        else:
            await edit_safe(event, f"ℹ️ Plugin tapılmadı: <code>{plugin_name}</code>")

    # ── .ban ──────────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("ban")))
    async def ban(event):
        uid, _ = await get_target_user(event)
        if not uid:
            return await edit_safe(event, f"ℹ️ İstifadə: <code>{P}ban</code> (reply) və ya <code>{P}ban @user</code>")
        try:
            rights = ChatBannedRights(until_date=None, view_messages=True)
            await event.client(EditBannedRequest(event.chat_id, uid, rights))
            await edit_safe(event, f"🔨 Ban olundu: <code>{uid}</code>")
        except (ChatAdminRequiredError, UserAdminInvalidError):
            await edit_safe(event, "⚠️ Yetkiniz yoxdur.")
        except FloodWaitError as exc:
            await edit_safe(event, f"⏳ FloodWait: {exc.seconds} saniyə gözləyin")
        except Exception as exc:
            await edit_safe(event, f"❌ Xəta: {exc}")

    # ── .unban ────────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("unban")))
    async def unban(event):
        uid, _ = await get_target_user(event)
        if not uid:
            return await edit_safe(event, f"ℹ️ İstifadə: <code>{P}unban @user</code>")
        try:
            rights = ChatBannedRights(until_date=None, view_messages=False)
            await event.client(EditBannedRequest(event.chat_id, uid, rights))
            await edit_safe(event, f"✅ Ban açıldı: <code>{uid}</code>")
        except FloodWaitError as exc:
            await edit_safe(event, f"⏳ FloodWait: {exc.seconds} saniyə gözləyin")
        except Exception as exc:
            await edit_safe(event, f"❌ Xəta: {exc}")

    # ── .mute ─────────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("mute")))
    async def mute(event):
        uid, _ = await get_target_user(event)
        if not uid:
            return await edit_safe(event, f"ℹ️ İstifadə: <code>{P}mute</code> (reply/id/username)")
        try:
            rights = ChatBannedRights(until_date=None, send_messages=True)
            await event.client(EditBannedRequest(event.chat_id, uid, rights))
            await edit_safe(event, f"🔇 Mute olundu: <code>{uid}</code>")
        except FloodWaitError as exc:
            await edit_safe(event, f"⏳ FloodWait: {exc.seconds} saniyə gözləyin")
        except Exception as exc:
            await edit_safe(event, f"❌ Xəta: {exc}")

    # ── .block ────────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("block")))
    async def block(event):
        uid, _ = await get_target_user(event)
        if not uid:
            return await edit_safe(event, f"ℹ️ İstifadə: <code>{P}block</code> (reply/id/username)")
        try:
            await event.client(BlockRequest(uid))
            await db.add_block(uid)
            await edit_safe(event, f"⛔ Bloklandı: <code>{uid}</code>")
        except FloodWaitError as exc:
            await edit_safe(event, f"⏳ FloodWait: {exc.seconds} saniyə gözləyin")
        except Exception as exc:
            await edit_safe(event, f"❌ Xəta: {exc}")

    # ── .unblock ──────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("unblock")))
    async def unblock(event):
        uid, _ = await get_target_user(event)
        if not uid:
            return await edit_safe(event, f"ℹ️ İstifadə: <code>{P}unblock</code>")
        try:
            await event.client(UnblockRequest(uid))
            await db.remove_block(uid)
            await edit_safe(event, f"✅ Blok açıldı: <code>{uid}</code>")
        except FloodWaitError as exc:
            await edit_safe(event, f"⏳ FloodWait: {exc.seconds} saniyə gözləyin")
        except Exception as exc:
            await edit_safe(event, f"❌ Xəta: {exc}")

    # ── .info ─────────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("info")))
    async def info(event):
        _, ent = await get_target_user(event)
        if not ent:
            ent = await event.get_sender()
        full = await event.client.get_entity(ent.id)
        try:
            fu = await event.client(GetFullUserRequest(full.id))
            bio = fu.full_user.about or "—"
        except Exception:
            bio = "—"
        premium = "✅" if getattr(full, "premium", False) else "❌"
        text = (
            "👤 İstifadəçi məlumatı\n"
            "━━━━━━━━━━━━━━━\n"
            f"🪪 Ad: {full.first_name or ''} {full.last_name or ''}\n"
            f"🔗 Username: @{full.username or '—'}\n"
            f"🆔 ID: <code>{full.id}</code>\n"
            f"💬 Bio: <i>{bio}</i>\n"
            f"⭐ Premium: {premium}"
        )
        await edit_safe(event, text)

    # ── .filter ───────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("filter")))
    async def add_filter(event):
        if not event.is_group:
            return await edit_safe(event, "⚠️ Yalnız qruplarda işləyir.")
        trigger = event.pattern_match.group(1).strip()
        if not trigger:
            return await edit_safe(
                event,
                f"ℹ️ İstifadə: <code>{P}filter Salam</code> və ya cavab verib <code>{P}filter Salam</code>",
            )
        response_text = trigger
        if event.is_reply:
            reply = await event.get_reply_message()
            reply_text = _extract_message_text(reply)
            if not reply_text:
                return await edit_safe(event, "⚠️ Reply etdiyin mesajda mətn olmalıdır.")
            response_text = reply_text
        await db.save_filter(event.chat_id, trigger, response_text)
        await edit_safe(event, f"✅ Filter aktivləşdi: <code>{trigger}</code>")

    # ── .filtersil ────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("filtersil")))
    async def remove_filter_cmd(event):
        if not event.is_group:
            return await edit_safe(event, "⚠️ Yalnız qruplarda işləyir.")
        trigger = event.pattern_match.group(1).strip()
        if not trigger:
            return await edit_safe(event, f"ℹ️ İstifadə: <code>{P}filtersil Salam</code>")
        removed = await db.remove_filter(event.chat_id, trigger)
        if removed:
            await edit_safe(event, f"🗑 Filter silindi: <code>{trigger}</code>")
        else:
            await edit_safe(event, f"ℹ️ Filter tapılmadı: <code>{trigger}</code>")

    @client.on(events.NewMessage(incoming=True))
    async def filter_listener(event):
        if not event.is_group:
            return
        message_text = _extract_message_text(event.message)
        if not message_text:
            return
        response_text = await db.get_filter(event.chat_id, message_text)
        if not response_text:
            return
        try:
            await event.reply(response_text)
        except Exception as exc:
            log.warning("filter reply err: %s", exc)

    # ── .setwelcome ───────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("setwelcome")))
    async def setwelcome(event):
        text = event.pattern_match.group(1).strip()
        if not text:
            return await edit_safe(event, f"ℹ️ İstifadə: <code>{P}setwelcome Salam {{mention}}, xoş gəldin</code>")
        await db.save_welcome(event.chat_id, text)
        await edit_safe(event, "✅ Xoş gəldin mesajı yaddaşda saxlanıldı.")

    @client.on(events.ChatAction())
    async def welcome_handler(event):
        if not event.user_added and not event.user_joined:
            return
        message = await db.get_welcome(event.chat_id)
        if not message:
            return
        try:
            user = await event.get_user()
            mention = f"<a href='tg://user?id={user.id}'>{user.first_name or 'dost'}</a>"
            msg = message.replace("{mention}", mention).replace("{name}", user.first_name or "")
            await event.client.send_message(event.chat_id, msg, parse_mode="html")
        except Exception as exc:
            log.warning("welcome err: %s", exc)

    # ── .klon ─────────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("klon")))
    async def klon(event):
        _, ent = await get_target_user(event)
        if not ent:
            return await edit_safe(event, f"ℹ️ İstifadə: <code>{P}klon</code> (reply və ya id)")
        if getattr(ent, "bot", False):
            return await edit_safe(event, "⛔ Bot hesabları klonlana bilməz. Yalnız real istifadəçiləri klonlaya bilərsən.")
        if getattr(ent, "deleted", False):
            return await edit_safe(event, "⛔ Silinmiş hesab klonlana bilməz. Yalnız real istifadəçiləri klonlaya bilərsən.")
        if not any(hasattr(ent, field) for field in ("first_name", "last_name", "username")):
            return await edit_safe(event, "⛔ Bu obyekt real istifadəçi deyil. Yalnız real istifadəçiləri klonlaya bilərsən.")
        await edit_safe(event, "🧬 Klonlanır...")
        me = await event.client.get_me()
        existing_snapshot = await db.get_clone(me.id)
        if existing_snapshot is None:
            full_me = await event.client(GetFullUserRequest(me.id))
            photo_bytes = b""
            try:
                photo_bytes = await _download_profile_photo_bytes(event.client, "me")
            except Exception:
                pass
            await db.save_clone(
                me.id,
                me.first_name or "",
                me.last_name or "",
                full_me.full_user.about or "",
                photo_bytes,
            )
        target_full = await event.client(GetFullUserRequest(ent.id))
        target_name = (getattr(ent, "first_name", None) or getattr(ent, "username", None) or str(ent.id)).strip()
        try:
            await event.client(
                UpdateProfileRequest(
                    first_name=ent.first_name or "‎",
                    last_name=ent.last_name or "",
                    about=(target_full.full_user.about or "")[:70],
                )
            )
            target_photo = await _download_profile_photo_bytes(event.client, ent)
            await _replace_profile_photo(event.client, target_photo, file_name="klon.jpg")
            await edit_safe(event, f"Səni Klonladım ⚡️: {target_name}")
        except FloodWaitError as exc:
            await edit_safe(event, f"⏳ FloodWait: {exc.seconds} saniyə gözləyin")
        except Exception as exc:
            await edit_safe(event, f"❌ Xəta: {exc}")

    # ── .unklon ───────────────────────────────────────────────────────────────
    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("unklon")))
    async def unklon(event):
        me = await event.client.get_me()
        row = await db.get_clone(me.id)
        if not row:
            return await edit_safe(event, "ℹ️ Klon məlumatı tapılmadı.")
        try:
            await event.client(
                UpdateProfileRequest(
                    first_name=row.original_first or "‎",
                    last_name=row.original_last or "",
                    about=row.original_bio or "",
                )
            )
            await _replace_profile_photo(event.client, row.original_photo, file_name="orig.jpg")
            await db.delete_clone(me.id)
            await edit_safe(event, "Original profil geri qaytarıldı ⚡️")
        except FloodWaitError as exc:
            await edit_safe(event, f"⏳ FloodWait: {exc.seconds} saniyə gözləyin")
        except Exception as exc:
            await edit_safe(event, f"❌ Xəta: {exc}")

    log.info("🚀 Raven Userbot komandaları qeydiyyatdan keçdi.")
