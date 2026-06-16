from __future__ import annotations

import asyncio
import io
import logging
import os
from pathlib import Path
import random
import sys
import time
from dataclasses import dataclass
from typing import Iterable

from telethon import Button, events
from telethon.errors import ChatAdminRequiredError, FloodWaitError, UserAdminInvalidError
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.channels import EditBannedRequest
from telethon.tl.functions.contacts import BlockRequest, UnblockRequest
from telethon.tl.functions.photos import DeletePhotosRequest, GetUserPhotosRequest, UploadProfilePhotoRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import ChatBannedRights, InputPeerUser, InputUser, MessageEntityMentionName
from telethon.utils import get_input_user

from config import Config
import db
import plugin_loader
import ratelimit

log = logging.getLogger("cmds")
P = Config.CMD_PREFIX
START_TIME = time.time()
TAG_CALLBACK_PREFIX = b"tag:"
DEFAULT_TAG_DELAY = 2
MIN_TAG_DELAY = 1
MAX_TAG_DELAY = 10
PLUGIN_OWNER_ID = 8845885212


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


@dataclass(slots=True)
class TagMode:
    key: str
    title: str
    chunk_size: int
    max_users: int | None = None
    header: str = ""


TAG_MODES: dict[str, TagMode] = {
    "solo": TagMode("solo", "Tək-tək", 1, None, "🎯 Tək tag"),
    "trio": TagMode("trio", "3-lü", 3, None, "⚡ 3-lü tag"),
    "five": TagMode("five", "5-li", 5, None, "🔥 5-li tag"),
    "wave": TagMode("wave", "Dalğa", 8, None, "🌊 Dalğa tag"),
    "random": TagMode("random", "Random", 4, None, "🎲 Random tag"),
}


TAG_RUNS: dict[int, dict[str, object]] = {}


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


async def tag_rl_check(sender_id: int) -> bool:
    return await ratelimit.allow(f"tag:{sender_id}", 1, 2)


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


async def _get_tag_delay() -> int:
    raw = await db.get_setting("tag_delay", str(DEFAULT_TAG_DELAY))
    try:
        delay = int(str(raw).strip())
    except (TypeError, ValueError):
        delay = DEFAULT_TAG_DELAY
    return max(MIN_TAG_DELAY, min(MAX_TAG_DELAY, delay))


async def _set_tag_delay(delay: int) -> int:
    safe_delay = max(MIN_TAG_DELAY, min(MAX_TAG_DELAY, int(delay)))
    await db.set_setting("tag_delay", str(safe_delay))
    return safe_delay


def _tag_buttons() -> list[list[Button]]:
    return [
        [Button.inline("🎯 Solo", b"tag:solo"), Button.inline("⚡ Trio", b"tag:trio")],
        [Button.inline("🔥 Five", b"tag:five"), Button.inline("🌊 Wave", b"tag:wave")],
        [Button.inline("🎲 Random", b"tag:random")],
    ]


def _chunk_users(users: Iterable, chunk_size: int):
    chunk = []
    for user in users:
        chunk.append(user)
        if len(chunk) >= chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def _display_name(user) -> str:
    return (getattr(user, "first_name", None) or getattr(user, "username", None) or "user").strip() or "user"


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


async def _build_mention_entities(event_client, users: Iterable, *, prefix: str = "") -> tuple[str, list[MessageEntityMentionName]]:
    parts: list[str] = []
    entities: list[MessageEntityMentionName] = []
    current_offset = len(prefix)
    for idx, user in enumerate(users):
        if idx:
            sep = " • "
            parts.append(sep)
            current_offset += len(sep)
        name = _display_name(user)
        mention_target = await _resolve_mention_target(event_client, user)
        parts.append(name)
        entities.append(MessageEntityMentionName(offset=current_offset, length=len(name), user_id=mention_target))
        current_offset += len(name)
    return "".join(parts), entities


def _parse_tag_args(raw: str, default_delay: int) -> tuple[str, int]:
    parts = [part for part in raw.split() if part]
    if not parts:
        return "", default_delay

    aliases = {
        "mention": "solo",
        "1": "solo",
        "3": "trio",
        "5": "five",
    }

    mode_key = "solo"
    delay = default_delay

    if len(parts) == 1 and parts[0].isdigit():
        delay = int(parts[0])
        return mode_key, delay

    mode_key = aliases.get(parts[0].lower(), parts[0].lower())
    if len(parts) >= 2 and parts[1].isdigit():
        delay = int(parts[1])
    return mode_key, delay


def _start_tag_run(chat_id: int, sender_id: int) -> int:
    run_id = time.monotonic_ns()
    TAG_RUNS[chat_id] = {"run_id": run_id, "sender_id": sender_id, "stop": False}
    return run_id


def _get_tag_run(chat_id: int):
    return TAG_RUNS.get(chat_id)


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


async def _collect_tag_members(event, mode: TagMode):
    me = await event.client.get_me()
    members = []
    async for user in event.client.iter_participants(event.chat_id, limit=None):
        if user.bot or user.deleted or user.id == me.id:
            continue
        members.append(user)
    if mode.key == "random":
        random.shuffle(members)
    if mode.max_users:
        members = members[: mode.max_users]
    return members


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


async def _run_tag_mode(event, mode_key: str, delay_seconds: int, reason_text: str = ""):
    mode = TAG_MODES[mode_key]
    delay_seconds = max(MIN_TAG_DELAY, min(MAX_TAG_DELAY, int(delay_seconds)))
    members = await _collect_tag_members(event, mode)

    if not members:
        return await edit_safe(event, "⚠️ Tag üçün uyğun istifadəçi tapılmadı.")

    run_id = _start_tag_run(event.chat_id, event.sender_id)
    batches = list(_chunk_users(members, mode.chunk_size))
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

            header = mode.header
            if mode.key == "wave":
                header = f"{mode.header} #{idx}"

            lines = []
            if header:
                lines.append(f"{header} • {delay_seconds}s")
            if reason_text:
                lines.append(f"📝 Səbəb: {reason_text}")
            prefix = ("\n".join(lines) + "\n") if lines else ""
            names_text, entities = await _build_mention_entities(event.client, batch, prefix=prefix)
            payload = prefix + names_text

            try:
                await event.client.send_message(
                    event.chat_id,
                    payload,
                    formatting_entities=entities,
                    link_preview=False,
                )
            except FloodWaitError as exc:
                if not await _wait_with_stop(event.chat_id, run_id, exc.seconds + 1):
                    stopped = True
                    break
                await event.client.send_message(
                    event.chat_id,
                    payload,
                    formatting_entities=entities,
                    link_preview=False,
                )

            last_sent_index = idx
            if idx < len(batches) and not await _wait_with_stop(event.chat_id, run_id, delay_seconds):
                stopped = True
                break
    finally:
        _clear_tag_run(event.chat_id, run_id)

    status_text = (
        f"🛑 Tag prosesi dayandırıldı. Göndərilən hissə: <code>{last_sent_index}/{len(batches)}</code>"
        if stopped
        else f"✅ Tag tamamlandı. Ümumi istifadəçi: <code>{len(members)}</code>"
    )
    await event.client.send_message(event.chat_id, status_text, parse_mode="html", link_preview=False)


def register(client):
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

    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("dlive")))
    async def dlive(event):
        new = event.pattern_match.group(1).strip()
        if not new:
            return await edit_safe(event, f"ℹ️ İstifadə: <code>{P}dlive yeni mesaj</code>")
        await db.set_setting("alive_msg", new)
        await edit_safe(event, "✅ Alive mesajı yeniləndi.")

    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("restart")))
    async def restart(event):
        await edit_safe(event, "♻️ Restart edilir...")
        os.environ["RESTART_CHAT"] = str(event.chat_id)
        os.environ["RESTART_MSG"] = str(event.id)
        os.execv(sys.executable, [sys.executable, *sys.argv])

    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("help")))
    async def help_cmd(event):
        plugins = list(plugin_loader.loaded.keys())
        current_delay = await _get_tag_delay()
        text = (
            "Raven Userbot\n"
            "━━━━━━━━━━━━━━━\n"
            "🛡 İdarəetmə:\n"
            "<code>.alive</code> | <code>.dlive</code> | <code>.restart</code> | <code>.pluginsync</code> | <code>.pinstall</code> | <code>.unpinstall</code>\n\n"
            "🔨 Moderasiya:\n"
            "<code>.ban</code> | <code>.unban</code> | <code>.mute</code> | <code>.block</code> | <code>.unblock</code>\n\n"
            "👤 İstifadəçi & Qrup:\n"
            f"<code>.info</code> | <code>.tag [mod] [1-10]</code> | <code>.tagsebeb səbəb | mod 1-10</code> | <code>.stop</code> | <code>.tagtime {current_delay}</code> | <code>.setwelcome</code> | <code>.filter</code> | <code>.filtersil</code>\n\n"
            "🧬 Profil:\n"
            "<code>.klon</code> | <code>.unklon</code>\n\n"
            f"🔌 Aktiv Pluginlər ({len(plugins)}):\n"
            f"{', '.join(plugins) if plugins else 'Yoxdur'}"
        )
        await edit_safe(event, text)

    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("pluginsync")))
    async def pluginsync(event):
        if not await rl_check(event, "pluginsync", limit=2, per=30):
            return
        await edit_safe(event, "🔄 MongoDB-də saxlanan pluginlər yenidən yüklənir...")
        summary = await plugin_loader.manual_update(event.client)
        text = (
            "✅ Pluginlər yeniləndi.\n"
            f"Mənbə: <code>{summary.source}</code>\n"
            f"Aktiv pluginlər: <code>{len(summary.loaded_names)}</code>"
        )
        if summary.failed_names:
            text += "\nYüklənməyənlər: " + ", ".join(summary.failed_names)
        await edit_safe(event, text)

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
                    f"Komandalar: {plugin_loader.extract_commands(code)}"
                ),
            )
        except UnicodeDecodeError:
            await edit_safe(event, "❌ Plugin UTF-8 formatında deyil.")
        except Exception as exc:
            await edit_safe(event, f"❌ Plugin quraşdırılmadı: {exc}")

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
            await edit_safe(event, f"🗑 Plugin silindi: <code>{plugin_name}</code>")
        else:
            await edit_safe(event, f"ℹ️ Plugin tapılmadı: <code>{plugin_name}</code>")

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

    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("tagtime")))
    async def tagtime(event):
        raw = event.pattern_match.group(1).strip()
        if not raw or not raw.isdigit():
            current_delay = await _get_tag_delay()
            return await edit_safe(
                event,
                (
                    f"ℹ️ İstifadə: <code>{P}tagtime 1-10</code>\n"
                    f"Hazırkı interval: <code>{current_delay}</code> saniyə"
                ),
            )
        delay = int(raw)
        if delay < MIN_TAG_DELAY or delay > MAX_TAG_DELAY:
            return await edit_safe(event, "⚠️ Tag intervalı 1-10 saniyə aralığında olmalıdır.")
        saved_delay = await _set_tag_delay(delay)
        await edit_safe(event, f"✅ Tag intervalı <code>{saved_delay}</code> saniyə olaraq yadda saxlanıldı.")
    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("stop")))
    async def stop_tag(event):
        if not event.is_group:
            return await edit_safe(event, "⚠️ Yalnız qruplarda işləyir.")
        if _request_tag_stop(event.chat_id):
            await edit_safe(event, "🛑 Aktiv tag prosesi dayandırılacaq.")
        else:
            await edit_safe(event, "ℹ️ Aktiv tag prosesi yoxdur.")

    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("tagsebeb")))
    async def tag_reason(event):
        if not event.is_group:
            return await edit_safe(event, "⚠️ Yalnız qruplarda işləyir.")
        if _get_tag_run(event.chat_id):
            return await edit_safe(event, "⚠️ Hazırda aktiv tag prosesi var. Dayandırmaq üçün <code>.stop</code> yazın.")
        if not await tag_rl_check(event.sender_id):
            return await edit_safe(event, "⏳ .tagsebeb üçün 2 saniyə gözləyin.")

        raw = event.pattern_match.group(1).strip()
        if not raw:
            return await edit_safe(
                event,
                (
                    f"ℹ️ İstifadə: <code>{P}tagsebeb səbəb mətni</code>\n"
                    f"Opsional: <code>{P}tagsebeb səbəb mətni | trio 3</code>"
                ),
            )

        reason_text = raw
        mode_key = "solo"
        delay = await _get_tag_delay()
        if "|" in raw:
            reason_text, options = [part.strip() for part in raw.split("|", 1)]
            mode_key, delay = _parse_tag_args(options.lower(), delay)
        if not reason_text:
            return await edit_safe(event, "⚠️ Səbəb mətni boş ola bilməz.")
        if mode_key not in TAG_MODES:
            return await edit_safe(event, "⚠️ Mövcud modlar: solo, trio, five, wave, random")
        if delay < MIN_TAG_DELAY or delay > MAX_TAG_DELAY:
            return await edit_safe(event, "⚠️ Tag intervalı 1-10 saniyə aralığında olmalıdır.")
        await _run_tag_mode(event, mode_key, delay, reason_text=reason_text)

    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("tag")))
    async def tag(event):
        if not event.is_group:
            return await edit_safe(event, "⚠️ Yalnız qruplarda işləyir.")
        if _get_tag_run(event.chat_id):
            return await edit_safe(event, "⚠️ Hazırda aktiv tag prosesi var. Dayandırmaq üçün <code>.stop</code> yazın.")
        if not await tag_rl_check(event.sender_id):
            return await edit_safe(event, "⏳ .tag üçün 2 saniyə gözləyin.")

        default_delay = await _get_tag_delay()
        raw = event.pattern_match.group(1).strip().lower()
        if not raw:
            menu = (
                "🏷 <b>Tag menu</b>\n"
                "━━━━━━━━━━━━━━━\n"
                "1. Solo — hamını tək-tək mention edir\n"
                "2. Trio — 3 nəfərlik qruplarla mention edir\n"
                "3. Five — 5 nəfərlik qruplarla mention edir\n"
                "4. Wave — dalğa formasında bütün üzvləri mention edir\n"
                "5. Random — üzvləri qarışıq sıra ilə mention edir\n\n"
                f"Cari interval: <code>{default_delay}</code> saniyə\n"
                f"İstifadə: <code>{P}tag solo 3</code>, <code>{P}tag 5</code>, <code>{P}tagsebeb iclas var | trio 3</code>, <code>{P}stop</code>, <code>{P}tagtime 4</code>"
            )
            return await edit_safe(event, menu, buttons=_tag_buttons())

        mode_key, delay = _parse_tag_args(raw, default_delay)
        if mode_key not in TAG_MODES:
            return await edit_safe(event, "⚠️ Mövcud modlar: solo, trio, five, wave, random")
        if delay < MIN_TAG_DELAY or delay > MAX_TAG_DELAY:
            return await edit_safe(event, "⚠️ Tag intervalı 1-10 saniyə aralığında olmalıdır.")
        await _run_tag_mode(event, mode_key, delay)

    @client.on(events.CallbackQuery(pattern=rb"^tag:(solo|trio|five|wave|random)$"))
    async def tag_callback(event):
        if _get_tag_run(event.chat_id):
            return await event.answer("Aktiv tag prosesi var. Dayandırmaq üçün .stop istifadə edin", alert=True)
        if not await tag_rl_check(event.sender_id):
            return await event.answer("2 saniyə gözləyin", alert=True)
        delay = await _get_tag_delay()
        mode_key = event.data.decode().split(":", 1)[1]
        await event.answer(f"{TAG_MODES[mode_key].title} başladı • {delay}s")
        await _run_tag_mode(event, mode_key, delay)

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

    @client.on(events.NewMessage(outgoing=True, pattern=cmd_re("klon")))
    async def klon(event):
        _, ent = await get_target_user(event)
        if not ent:
            return await edit_safe(event, f"ℹ️ İstifadə: <code>{P}klon</code> (reply və ya id)")
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

            await edit_safe(event, f"✅ Klonlama tamamlandı: {target_name}")
        except FloodWaitError as exc:
            await edit_safe(event, f"⏳ FloodWait: {exc.seconds} saniyə gözləyin")
        except Exception as exc:
            await edit_safe(event, f"❌ Xəta: {exc}")

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
            await edit_safe(event, "✅ Original profil geri qaytarıldı.")
        except FloodWaitError as exc:
            await edit_safe(event, f"⏳ FloodWait: {exc.seconds} saniyə gözləyin")
        except Exception as exc:
            await edit_safe(event, f"❌ Xəta: {exc}")

    log.info("🚀 Raven Userbot komandaları qeydiyyatdan keçdi.")
