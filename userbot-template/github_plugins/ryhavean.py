"""
==================================================
🌌 RYHAVEAN PACK v4.1 — 150 Yeni API/Fun Plugin
==================================================
Plugin Author : Ryhavean
Mövzu         : Daily use + Fun + APIs + Group tools + Media
Premium Emoji : avtomatik (emoji_utils.install_patches)
==================================================
Yükləmə      : .pinstall ryhavean_pack
Lazım olan paketlər (main.py-da):
    pip install aiohttp pillow yt-dlp psutil pyfiglet googletrans==4.0.0rc1
==================================================
"""

import io
import os
import re
import sys
import time
import json
import math
import base64
import random
import hashlib
import asyncio
import logging
import platform
import datetime
import urllib.parse
import mimetypes
import struct
from html import escape as h_escape
from pathlib import Path

import aiohttp
from telethon import events
from telethon.tl.types import (
    ChannelParticipantsAdmins,
    ChannelParticipantsKicked,
    ChannelParticipantsBots,
    Message,
)
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.channels import EditAdminRequest, EditBannedRequest
from telethon.tl.types import ChatAdminRights, ChatBannedRights

try:
    from emoji_utils import song_caption, apply_premium_emojis  # noqa
except Exception:
    def song_caption():
        return "🎵 Ryhavean Download", []
    def apply_premium_emojis(t, e=None):
        return t, e or []

log = logging.getLogger("ryhavean")

CMD_PREFIX = "."
START_TIME = time.time()

# ============================================================
# Helpers
# ============================================================
_session: aiohttp.ClientSession | None = None

async def _http() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"User-Agent": "RyhaveanBot/4.0"},
        )
    return _session


async def _get_json(url, params=None):
    s = await _http()
    async with s.get(url, params=params) as r:
        return await r.json(content_type=None)


async def _get_text(url, params=None):
    s = await _http()
    async with s.get(url, params=params) as r:
        return await r.text()


async def _get_bytes(url, params=None):
    s = await _http()
    async with s.get(url, params=params) as r:
        return await r.read()



def _normalize_url(u: str) -> str:
    """Add https:// scheme if missing; trim whitespace."""
    u = (u or "").strip()
    if not u:
        return u
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", u):
        u = "https://" + u
    return u


def _media_identity(data, content_type="", url="", fallback="media"):
    """Return a safe filename and MIME type by inspecting headers and bytes."""
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    path_name = urllib.parse.unquote(urllib.parse.urlparse(str(url)).path.rsplit("/", 1)[-1])
    path_name = re.sub(r"[^A-Za-z0-9._-]", "_", path_name)
    signatures = (
        (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
        (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
        (b"GIF87a", "image/gif", ".gif"), (b"GIF89a", "image/gif", ".gif"),
        (b"RIFF", "image/webp", ".webp"),
        (b"%PDF", "application/pdf", ".pdf"),
        (b"ID3", "audio/mpeg", ".mp3"),
        (b"OggS", "audio/ogg", ".ogg"),
    )
    detected_ext = ""
    for signature, detected_mime, ext in signatures:
        if data.startswith(signature):
            if signature != b"RIFF" or data[8:12] == b"WEBP":
                mime, detected_ext = detected_mime, ext
                break
    if len(data) > 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in {b"M4A ", b"M4B ", b"mp4a"}:
            mime, detected_ext = "audio/mp4", ".m4a"
        else:
            mime, detected_ext = "video/mp4", ".mp4"
    ext = detected_ext or mimetypes.guess_extension(mime) or Path(path_name).suffix.lower()
    if ext == ".jpe": ext = ".jpg"
    if not ext: ext = ".bin"
    stem = Path(path_name).stem if path_name and Path(path_name).suffix else fallback
    filename = f"{stem[:80] or fallback}{ext}"
    return filename, mime or mimetypes.guess_type(filename)[0] or "application/octet-stream"


async def _download_named_media(url, params=None, fallback="ryhavean_media"):
    """Download media and preserve enough metadata for Telegram to render it inline."""
    s = await _http()
    async with s.get(url, params=params, allow_redirects=True) as response:
        response.raise_for_status()
        data = await response.read()
        filename, mime = _media_identity(data, response.headers.get("Content-Type", ""), response.url, fallback)
    stream = io.BytesIO(data)
    stream.name = filename
    return stream, mime


async def _send_media(event, url=None, data=None, filename=None, mime=None, caption="", reply_to=None):
    """Send photos as photos and MP4/WebM videos as playable streaming media."""
    if url:
        stream, detected_mime = await _download_named_media(url, fallback=filename or "ryhavean_media")
        mime = mime or detected_mime
    else:
        payload = data or b""
        detected_name, detected_mime = _media_identity(payload, mime or "", filename or "", filename or "ryhavean_media")
        stream = io.BytesIO(payload)
        stream.name = filename or detected_name
        mime = mime or detected_mime
    is_photo = mime.startswith("image/") and mime not in {"image/gif", "image/webp"}
    is_video = mime.startswith("video/")
    return await event.client.send_file(
        event.chat_id,
        stream,
        caption=caption or None,
        force_document=not (is_photo or is_video),
        supports_streaming=is_video,
        reply_to=reply_to,
    )


def _fmt_uptime(sec):
    sec = int(sec)
    d, sec = divmod(sec, 86400)
    h, sec = divmod(sec, 3600)
    m, sec = divmod(sec, 60)
    parts = []
    if d: parts.append(f"{d}g")
    if h: parts.append(f"{h}s")
    if m: parts.append(f"{m}d")
    parts.append(f"{sec}san")
    return " ".join(parts)


def _info_text(cmd, usage, desc, example=None):
    txt = (
        f"ℹ️ <b>.{cmd}</b>\n\n"
        f"📝 <b>İstifadə:</b> <code>{h_escape(usage)}</code>\n"
        f"💡 <b>Açıqlama:</b> {desc}"
    )
    if example:
        txt += f"\n📌 <b>Misal:</b> <code>{h_escape(example)}</code>"
    return txt


async def _info(event, cmd, usage, desc, example=None):
    await event.edit(_info_text(cmd, usage, desc, example), parse_mode="html")


def _need_reply(event, txt="❌ Bir mesajı reply edin."):
    if not event.is_reply:
        return txt
    return None


# ============================================================
# REGISTER
# ============================================================
def register(bot, prefix="."):
    global CMD_PREFIX
    CMD_PREFIX = prefix
    P = re.escape(prefix)

    def cmd(name, args_regex=r"(?:\s+(.+))?$"):
        return events.NewMessage(pattern=rf"{P}{name}{args_regex}", outgoing=True)

    # ============================================================
    # 1. UTILITIES (1-30)
    # ============================================================

    @bot.on(cmd("ping", r"$"))
    async def _ping(e):
        t0 = time.time()
        await e.edit("🏓 Pinging...")
        dt = (time.time() - t0) * 1000
        await e.edit(f"🏓 <b>Pong!</b>\n⏱ <code>{dt:.2f} ms</code>", parse_mode="html")

    @bot.on(cmd("hsjajsjsj", r"$"))
    async def _alive(e):
        up = _fmt_uptime(time.time() - START_TIME)
        await e.edit(
            "✨ <b>Ryhavean Userbot</b>\n"
            f"⏱ Uptime: <code>{up}</code>\n"
            f"🐍 Python: <code>{platform.python_version()}</code>\n"
            f"💻 Sistem: <code>{platform.system()} {platform.release()}</code>",
            parse_mode="html",
        )

    @bot.on(cmd("id", r"$"))
    async def _id(e):
        txt = f"💬 <b>Chat ID:</b> <code>{e.chat_id}</code>\n"
        txt += f"🆔 <b>Sənin ID:</b> <code>{e.sender_id}</code>"
        if e.is_reply:
            r = await e.get_reply_message()
            txt += f"\n👤 <b>Reply User ID:</b> <code>{r.sender_id}</code>"
        await e.edit(txt, parse_mode="html")

    @bot.on(cmd("info"))
    async def _userinfo(e):
        arg = e.pattern_match.group(1)
        target = None
        if arg:
            target = arg.strip()
        elif e.is_reply:
            r = await e.get_reply_message()
            target = r.sender_id
        else:
            target = e.sender_id
        try:
            full = await e.client(GetFullUserRequest(target))
            u = full.users[0]
            name = " ".join(filter(None, [u.first_name, u.last_name])) or "—"
            txt = (
                f"👤 <b>{h_escape(name)}</b>\n"
                f"🆔 ID: <code>{u.id}</code>\n"
                f"🔗 Username: @{u.username or '—'}\n"
                f"🤖 Bot: {u.bot}\n"
                f"⭐ Premium: {bool(getattr(u,'premium',False))}\n"
                f"📝 Bio: {h_escape(full.full_user.about or '—')}"
            )
        except Exception as ex:
            txt = f"❌ {ex}"
        await e.edit(txt, parse_mode="html")

    @bot.on(cmd("whois")) 
    async def _whois(e):
        arg = e.pattern_match.group(1)
        if not arg and not e.is_reply:
            return await _info(e, "whois", ".whois <user>", "İstifadəçi haqqında məlumat.", ".whois @durov")
        return await _userinfo(e)

    @bot.on(cmd("del", r"$"))
    async def _del(e):
        if e.is_reply:
            r = await e.get_reply_message()
            await r.delete()
        await e.delete()

    @bot.on(cmd("purge", r"(?:\s+(\d+))?$"))
    async def _purge(e):
        n = e.pattern_match.group(1)
        if not e.is_reply and not n:
            return await _info(e, "purge", ".purge [say]", "Reply'dən bu yana və ya son N mesajı silir.", ".purge 50")
        msgs = []
        if e.is_reply:
            r = await e.get_reply_message()
            async for m in e.client.iter_messages(e.chat_id, min_id=r.id - 1):
                msgs.append(m.id)
        else:
            async for m in e.client.iter_messages(e.chat_id, limit=int(n)):
                msgs.append(m.id)
        await e.client.delete_messages(e.chat_id, msgs)

    @bot.on(cmd("type"))
    async def _type(e):
        text = e.pattern_match.group(1)
        if not text:
            return await _info(e, "type", ".type <mətn>", "Mətni hərfbə-hərf yazır.", ".type Salam dünya")
        cur = ""
        for ch in text:
            cur += ch
            try:
                await e.edit(cur + " ▌")
            except Exception:
                pass
            await asyncio.sleep(0.05)
        await e.edit(cur)

    @bot.on(cmd("echo"))
    async def _echo(e):
        t = e.pattern_match.group(1)
        if not t:
            return await _info(e, "echo", ".echo <mətn>", "Mətni təkrar göndərir.", ".echo Salam")
        await e.edit(t)

    @bot.on(cmd("calc"))
    async def _calc(e):
        expr = e.pattern_match.group(1)
        if not expr:
            return await _info(e, "calc", ".calc <ifadə>", "Riyazi ifadəni hesablayır.", ".calc 2+2*5")
        try:
            allowed = "0123456789+-*/.() %"
            safe = "".join(c for c in expr if c in allowed)
            res = eval(safe, {"__builtins__": {}}, {})
            await e.edit(f"🧮 <code>{h_escape(expr)}</code> = <b>{res}</b>", parse_mode="html")
        except Exception as ex:
            await e.edit(f"❌ {ex}")

    @bot.on(cmd("base64enc"))
    async def _b64e(e):
        t = e.pattern_match.group(1)
        if not t:
            return await _info(e, "base64enc", ".base64enc <mətn>", "Base64 kodlayır.", ".base64enc hello")
        await e.edit(f"🔐 <code>{base64.b64encode(t.encode()).decode()}</code>", parse_mode="html")

    @bot.on(cmd("base64dec"))
    async def _b64d(e):
        t = e.pattern_match.group(1)
        if not t:
            return await _info(e, "base64dec", ".base64dec <mətn>", "Base64-dən deşifrə.", ".base64dec aGVsbG8=")
        try:
            await e.edit(f"🔓 <code>{h_escape(base64.b64decode(t).decode())}</code>", parse_mode="html")
        except Exception as ex:
            await e.edit(f"❌ {ex}")

    for algo in ("md5", "sha1", "sha256"):
        async def _hash_handler(e, _algo=algo):
            t = e.pattern_match.group(1)
            if not t:
                return await _info(e, _algo, f".{_algo} <mətn>", f"{_algo.upper()} hash hesablayır.", f".{_algo} hello")
            h = hashlib.new(_algo, t.encode()).hexdigest()
            await e.edit(f"🔐 <code>{h}</code>", parse_mode="html")
        bot.on(cmd(algo))(_hash_handler)

    @bot.on(cmd("reverse"))
    async def _rev(e):
        t = e.pattern_match.group(1)
        if not t:
            return await _info(e, "reverse", ".reverse <mətn>", "Mətni tərsinə çevirir.", ".reverse salam")
        await e.edit(t[::-1])

    @bot.on(cmd("upper"))
    async def _up(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "upper", ".upper <mətn>", "Böyük hərfə çevirir.", ".upper salam")
        await e.edit(t.upper())

    @bot.on(cmd("lower"))
    async def _lo(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "lower", ".lower <mətn>", "Kiçik hərfə çevirir.", ".lower SALAM")
        await e.edit(t.lower())

    @bot.on(cmd("count"))
    async def _count(e):
        t = e.pattern_match.group(1)
        if not t and not e.is_reply:
            return await _info(e, "count", ".count <mətn>", "Hərf və söz sayır.", ".count salam dünya")
        if not t and e.is_reply:
            t = (await e.get_reply_message()).text or ""
        await e.edit(f"🔤 Hərf: <b>{len(t)}</b>\n📝 Söz: <b>{len(t.split())}</b>", parse_mode="html")

    @bot.on(cmd("wc", r"$"))
    async def _wc(e):
        if not e.is_reply:
            return await _info(e, "wc", ".wc (reply)", "Reply edilən mesajın söz sayını verir.")
        t = (await e.get_reply_message()).text or ""
        await e.edit(f"📊 Söz: <b>{len(t.split())}</b>\n🔤 Hərf: <b>{len(t)}</b>", parse_mode="html")

    @bot.on(cmd("time", r"$"))
    async def _time(e):
        await e.edit(f"🕐 <code>{datetime.datetime.now().strftime('%H:%M:%S')}</code>", parse_mode="html")

    @bot.on(cmd("date", r"$"))
    async def _date(e):
        await e.edit(f"📅 <code>{datetime.date.today().isoformat()}</code>", parse_mode="html")

    @bot.on(cmd("weekday", r"$"))
    async def _wd(e):
        days = ["Bazar ertəsi","Çərşənbə axşamı","Çərşənbə","Cümə axşamı","Cümə","Şənbə","Bazar"]
        await e.edit(f"📅 Bu gün: <b>{days[datetime.date.today().weekday()]}</b>", parse_mode="html")

    @bot.on(cmd("timer"))
    async def _timer(e):
        s = e.pattern_match.group(1)
        if not s or not s.isdigit():
            return await _info(e, "timer", ".timer <saniyə>", "Geri sayım taymeri.", ".timer 10")
        n = int(s)
        for i in range(n, 0, -1):
            try: await e.edit(f"⏱ <b>{i}</b>", parse_mode="html")
            except: pass
            await asyncio.sleep(1)
        await e.edit("✅ Tamam!")

    @bot.on(cmd("remind"))
    async def _remind(e):
        args = e.pattern_match.group(1)
        if not args:
            return await _info(e, "remind", ".remind <saniyə> <mətn>", "Xatırlatma qoyur.", ".remind 60 dərs başla")
        parts = args.split(maxsplit=1)
        if len(parts) < 2 or not parts[0].isdigit():
            return await e.edit("❌ Format: .remind <saniyə> <mətn>")
        sec, msg = int(parts[0]), parts[1]
        await e.edit(f"⏰ {sec}s sonra xatırladacam.")
        await asyncio.sleep(sec)
        await e.respond(f"🔔 <b>Xatırlatma:</b>\n{h_escape(msg)}", parse_mode="html")

    @bot.on(cmd("uptime", r"$"))
    async def _up2(e):
        await e.edit(f"⏱ Uptime: <code>{_fmt_uptime(time.time()-START_TIME)}</code>", parse_mode="html")

    @bot.on(cmd("sysinfo", r"$"))
    async def _sys(e):
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=0.5)
            ram = psutil.virtual_memory()
            await e.edit(
                f"💻 <b>Sistem</b>\n"
                f"🔧 CPU: <code>{cpu}%</code>\n"
                f"🧠 RAM: <code>{ram.percent}%</code> ({ram.used//1048576}MB / {ram.total//1048576}MB)\n"
                f"🐍 Python: <code>{platform.python_version()}</code>\n"
                f"🖥 OS: <code>{platform.platform()}</code>",
                parse_mode="html",
            )
        except ImportError:
            await e.edit("❌ psutil quraşdırılmayıb. <code>pip install psutil</code>", parse_mode="html")

    @bot.on(cmd("speed", r"$"))
    async def _speed(e):
        t0 = time.time()
        await _get_text("https://www.google.com")
        dt = (time.time() - t0) * 1000
        await e.edit(f"🌐 Şəbəkə: <code>{dt:.0f} ms</code>", parse_mode="html")

    @bot.on(cmd("pyver", r"$"))
    async def _pv(e):
        await e.edit(f"🐍 <code>{sys.version}</code>", parse_mode="html")

    @bot.on(cmd("pip"))
    async def _pip(e):
        pkg = e.pattern_match.group(1)
        if not pkg:
            return await _info(e, "pip", ".pip <paket>", "PyPI-də paketi axtarır.", ".pip telethon")
        try:
            data = await _get_json(f"https://pypi.org/pypi/{pkg}/json")
            i = data["info"]
            await e.edit(
                f"📦 <b>{i['name']}</b> v{i['version']}\n"
                f"📝 {h_escape((i.get('summary') or '—')[:200])}\n"
                f"🔗 {i.get('home_page') or i.get('project_url') or '—'}",
                parse_mode="html",
            )
        except Exception as ex:
            await e.edit(f"❌ Tapılmadı: {ex}")

    # ============================================================
    # 2. APIs (31-80)
    # ============================================================

    @bot.on(cmd("weather"))
    async def _weather(e):
        city = e.pattern_match.group(1)
        if not city:
            return await _info(e, "weather", ".weather <şəhər>", "Hava haqqında məlumat (wttr.in).", ".weather Baku")
        try:
            t = await _get_text(f"https://wttr.in/{urllib.parse.quote(city)}?format=4")
            await e.edit(f"🌤 <code>{h_escape(t.strip())}</code>", parse_mode="html")
        except Exception as ex:
            await e.edit(f"❌ {ex}")

    @bot.on(cmd("translate"))
    async def _tr(e):
        arg = e.pattern_match.group(1)
        text = None; lang = "az"
        if arg:
            parts = arg.split(maxsplit=1)
            if len(parts[0]) == 2 and len(parts) == 2:
                lang, text = parts[0], parts[1]
            else:
                text = arg
        elif e.is_reply:
            text = (await e.get_reply_message()).text
        if not text:
            return await _info(e, "translate", ".translate [dil] <mətn>", "Google ilə tərcümə.", ".translate en salam")
        try:
            data = await _get_json(
                "https://translate.googleapis.com/translate_a/single",
                params={"client":"gtx","sl":"auto","tl":lang,"dt":"t","q":text},
            )
            out = "".join(seg[0] for seg in data[0])
            await e.edit(f"🌐 <b>{lang}:</b>\n{h_escape(out)}", parse_mode="html")
        except Exception as ex:
            await e.edit(f"❌ {ex}")

    @bot.on(cmd("wiki"))
    async def _wiki(e):
        q = e.pattern_match.group(1)
        if not q:
            return await _info(e, "wiki", ".wiki <söz>", "Wikipedia məqaləsi.", ".wiki Python")
        try:
            data = await _get_json(f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(q)}")
            await e.edit(
                f"📚 <b>{h_escape(data.get('title','?'))}</b>\n\n"
                f"{h_escape(data.get('extract','—')[:1000])}\n\n"
                f"🔗 {data.get('content_urls',{}).get('desktop',{}).get('page','')}",
                parse_mode="html",
            )
        except Exception as ex:
            await e.edit(f"❌ {ex}")

    @bot.on(cmd("urban"))
    async def _urb(e):
        q = e.pattern_match.group(1)
        if not q:
            return await _info(e, "urban", ".urban <söz>", "Urban Dictionary tərifi.", ".urban yolo")
        try:
            data = await _get_json("https://api.urbandictionary.com/v0/define", params={"term": q})
            if not data["list"]: return await e.edit("❌ Tapılmadı.")
            d = data["list"][0]
            await e.edit(
                f"📖 <b>{h_escape(d['word'])}</b>\n\n{h_escape(d['definition'][:800])}\n\n"
                f"<i>{h_escape(d['example'][:300])}</i>",
                parse_mode="html",
            )
        except Exception as ex:
            await e.edit(f"❌ {ex}")

    @bot.on(cmd("dictionary"))
    async def _dict(e):
        q = e.pattern_match.group(1)
        if not q:
            return await _info(e, "dictionary", ".dictionary <söz>", "İngilis lüğəti.", ".dictionary hello")
        try:
            data = await _get_json(f"https://api.dictionaryapi.dev/api/v2/entries/en/{q}")
            entry = data[0]
            mean = entry["meanings"][0]
            d = mean["definitions"][0]
            await e.edit(
                f"📖 <b>{entry['word']}</b> ({mean['partOfSpeech']})\n\n"
                f"{h_escape(d['definition'])}\n\n"
                f"<i>{h_escape(d.get('example','—'))}</i>",
                parse_mode="html",
            )
        except Exception as ex:
            await e.edit(f"❌ {ex}")

    @bot.on(cmd("ip"))
    async def _ip(e):
        ip = e.pattern_match.group(1)
        if not ip:
            return await _info(e, "ip", ".ip <ünvan>", "IP məlumatı.", ".ip 8.8.8.8")
        try:
            d = await _get_json(f"http://ip-api.com/json/{ip}")
            await e.edit(
                f"🌐 <b>{d.get('query')}</b>\n"
                f"🏳 Ölkə: {d.get('country')} ({d.get('countryCode')})\n"
                f"🏙 Şəhər: {d.get('city')}, {d.get('regionName')}\n"
                f"📡 ISP: {d.get('isp')}\n"
                f"🛰 ASN: {d.get('as')}\n"
                f"📍 {d.get('lat')}, {d.get('lon')}",
                parse_mode="html",
            )
        except Exception as ex:
            await e.edit(f"❌ {ex}")

    @bot.on(cmd("qr"))
    async def _qr(e):
        t = e.pattern_match.group(1)
        if not t:
            return await _info(e, "qr", ".qr <mətn>", "QR kod yaradır.", ".qr https://t.me")
        try:
            data = await _get_bytes(
                "https://api.qrserver.com/v1/create-qr-code/",
                params={"size":"500x500","data":t},
            )
            await _send_media(e, data=data, filename="image.png", mime="image/png")
            await e.delete()
        except Exception as ex:
            await e.edit(f"❌ {ex}")

    @bot.on(cmd("short"))
    async def _short(e):
        u = e.pattern_match.group(1)
        if not u:
            return await _info(e, "short", ".short <url>", "TinyURL-ə qısaldır.", ".short https://google.com")
        try:
            t = await _get_text("https://tinyurl.com/api-create.php", params={"url": u})
            await e.edit(f"🔗 <code>{h_escape(t)}</code>", parse_mode="html")
        except Exception as ex:
            await e.edit(f"❌ {ex}")

    @bot.on(cmd("expand"))
    async def _expand(e):
        u = e.pattern_match.group(1)
        if not u:
            return await _info(e, "expand", ".expand <url>", "Qısaldılmış URL-i açır.", ".expand https://bit.ly/...")
        try:
            s = await _http()
            async with s.head(u, allow_redirects=True) as r:
                await e.edit(f"🔗 <code>{h_escape(str(r.url))}</code>", parse_mode="html")
        except Exception as ex:
            await e.edit(f"❌ {ex}")

    @bot.on(cmd("github"))
    async def _gh(e):
        u = e.pattern_match.group(1)
        if not u:
            return await _info(e, "github", ".github <user>", "GitHub user məlumatı.", ".github torvalds")
        try:
            d = await _get_json(f"https://api.github.com/users/{u}")
            await e.edit(
                f"🐙 <b>{d.get('login')}</b>\n"
                f"📛 {d.get('name','—')}\n"
                f"📝 {h_escape(d.get('bio') or '—')}\n"
                f"👥 Followers: {d.get('followers')}\n"
                f"📦 Repos: {d.get('public_repos')}\n"
                f"🔗 {d.get('html_url')}",
                parse_mode="html",
            )
        except Exception as ex:
            await e.edit(f"❌ {ex}")

    @bot.on(cmd("ghrepo"))
    async def _ghr(e):
        u = e.pattern_match.group(1)
        if not u or "/" not in u:
            return await _info(e, "ghrepo", ".ghrepo <user/repo>", "GitHub repo məlumatı.", ".ghrepo torvalds/linux")
        try:
            d = await _get_json(f"https://api.github.com/repos/{u}")
            await e.edit(
                f"📦 <b>{d['full_name']}</b>\n"
                f"⭐ {d['stargazers_count']} | 🍴 {d['forks_count']} | 👁 {d['watchers_count']}\n"
                f"📝 {h_escape(d.get('description') or '—')}\n"
                f"💻 {d.get('language','—')}\n"
                f"🔗 {d['html_url']}",
                parse_mode="html",
            )
        except Exception as ex:
            await e.edit(f"❌ {ex}")

    @bot.on(cmd("gen", r"$"))
    async def _gen(e):
        try:
            d = (await _get_json("https://randomuser.me/api/"))["results"][0]
            await e.edit(
                f"👤 {d['name']['first']} {d['name']['last']}\n"
                f"📧 {d['email']}\n"
                f"📞 {d['phone']}\n"
                f"🏠 {d['location']['city']}, {d['location']['country']}",
                parse_mode="html",
            )
        except Exception as ex:
            await e.edit(f"❌ {ex}")

    async def _send_pic(e, url, key="url"):
        try:
            d = await _get_json(url)
            link = d[key] if isinstance(d, dict) else d[0][key]
            await _send_media(e, url=link, filename="api_media")
            await e.delete()
        except Exception as ex:
            await e.edit(f"❌ {ex}")

    @bot.on(cmd("cat", r"$"))
    async def _cat(e):
        try:
            d = await _get_json("https://api.thecatapi.com/v1/images/search")
            await _send_media(e, url=d[0]["url"], filename="cat")
            await e.delete()
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("dog", r"$"))
    async def _dog(e):
        await _send_pic(e, "https://dog.ceo/api/breeds/image/random", "message")

    @bot.on(cmd("fox", r"$"))
    async def _fox(e):
        await _send_pic(e, "https://randomfox.ca/floof/", "image")

    @bot.on(cmd("duck", r"$"))
    async def _duck(e):
        await _send_pic(e, "https://random-d.uk/api/v2/random", "url")

    @bot.on(cmd("meme", r"$"))
    async def _meme(e):
        try:
            d = await _get_json("https://meme-api.com/gimme")
            await _send_media(e, url=d["url"], filename="meme", caption=h_escape(d.get("title", "")))
            await e.delete()
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("joke", r"$"))
    async def _joke(e):
        try:
            d = await _get_json("https://official-joke-api.appspot.com/random_joke")
            await e.edit(f"😂 <b>{h_escape(d['setup'])}</b>\n\n— <i>{h_escape(d['punchline'])}</i>", parse_mode="html")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("quote", r"$"))
    async def _quote(e):
        for url, parser in (
            ("https://zenquotes.io/api/random", lambda d: (d[0]["q"], d[0]["a"])),
            ("https://dummyjson.com/quotes/random", lambda d: (d["quote"], d["author"])),
            ("https://api.quotable.io/random", lambda d: (d["content"], d["author"])),
        ):
            try:
                d = await _get_json(url)
                content, author = parser(d)
                return await e.edit(f"💬 <i>«{h_escape(content)}»</i>\n— <b>{h_escape(author)}</b>", parse_mode="html")
            except Exception:
                continue
        await e.edit("❌ Quote API əlçatan deyil.")

    @bot.on(cmd("advice", r"$"))
    async def _adv(e):
        try:
            d = await _get_json("https://api.adviceslip.com/advice")
            await e.edit(f"💡 {h_escape(d['slip']['advice'])}", parse_mode="html")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("fact", r"$"))
    async def _fact(e):
        try:
            d = await _get_json("https://uselessfacts.jsph.pl/api/v2/facts/random?language=en")
            await e.edit(f"🧠 {h_escape(d['text'])}", parse_mode="html")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("bored", r"$"))
    async def _bored(e):
        for url in ("https://bored-api.appbrewery.com/random", "https://www.boredapi.com/api/activity"):
            try:
                d = await _get_json(url)
                return await e.edit(f"🎯 {h_escape(d.get('activity','—'))}\nKateqoriya: {d.get('type','—')}", parse_mode="html")
            except Exception:
                continue
        await e.edit("❌ Bored API əlçatan deyil.")

    @bot.on(cmd("pokedex"))
    async def _poke(e):
        q = e.pattern_match.group(1)
        if not q: return await _info(e, "pokedex", ".pokedex <pokemon>", "PokeAPI.", ".pokedex pikachu")
        try:
            d = await _get_json(f"https://pokeapi.co/api/v2/pokemon/{q.lower()}")
            types = ", ".join(t["type"]["name"] for t in d["types"])
            await e.edit(
                f"🎴 <b>{d['name'].title()}</b> #{d['id']}\n"
                f"📐 Boy: {d['height']/10}m | ⚖ Çəki: {d['weight']/10}kg\n"
                f"🌀 Növ: {types}",
                parse_mode="html",
            )
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("exchange"))
    async def _ex(e):
        args = e.pattern_match.group(1)
        if not args:
            return await _info(e, "exchange", ".exchange <məbləğ> <FROM> <TO>", "Valyuta konvertasiyası.", ".exchange 100 USD AZN")
        parts = args.split()
        if len(parts) != 3: return await e.edit("❌ Format: .exchange 100 USD AZN")
        try:
            amt, frm, to = float(parts[0]), parts[1].upper(), parts[2].upper()
            d = None
            for url in (f"https://open.er-api.com/v6/latest/{frm}", f"https://api.exchangerate-api.com/v4/latest/{frm}"):
                try:
                    d = await _get_json(url)
                    if d.get("rates"): break
                except Exception:
                    d = None
            if not d or "rates" not in d:
                return await e.edit("❌ Exchange API əlçatan deyil.")
            rate = d["rates"][to]
            await e.edit(f"💱 <b>{amt} {frm} = {amt*rate:.2f} {to}</b>\n📊 Rate: {rate}", parse_mode="html")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("crypto"))
    async def _cr(e):
        c = e.pattern_match.group(1)
        if not c: return await _info(e, "crypto", ".crypto <coin>", "Crypto qiyməti.", ".crypto bitcoin")
        try:
            d = await _get_json(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": c.lower(), "vs_currencies": "usd,eur"},
            )
            v = next(iter(d.values()))
            await e.edit(f"₿ <b>{c.upper()}</b>\n💵 ${v['usd']}\n💶 €{v['eur']}", parse_mode="html")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("covid"))
    async def _cov(e):
        c = e.pattern_match.group(1) or "all"
        try:
            url = "https://disease.sh/v3/covid-19/all" if c=="all" else f"https://disease.sh/v3/covid-19/countries/{c}"
            d = await _get_json(url)
            await e.edit(
                f"🦠 <b>COVID-19 — {d.get('country','Dünya')}</b>\n"
                f"😷 Cəmi: {d['cases']:,}\n"
                f"💀 Ölü: {d['deaths']:,}\n"
                f"💚 Sağalan: {d['recovered']:,}\n"
                f"🆕 Bu gün: {d.get('todayCases',0):,}",
                parse_mode="html",
            )
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("country"))
    async def _country(e):
        c = e.pattern_match.group(1)
        if not c: return await _info(e, "country", ".country <ad>", "Ölkə məlumatı.", ".country azerbaijan")
        try:
            d = (await _get_json(f"https://restcountries.com/v3.1/name/{c}"))[0]
            await e.edit(
                f"🏳 <b>{d['name']['common']}</b> {d.get('flag','')}\n"
                f"🏛 Paytaxt: {', '.join(d.get('capital',['—']))}\n"
                f"👥 Əhali: {d['population']:,}\n"
                f"📐 Sahə: {d['area']:,} km²\n"
                f"🌐 Region: {d['region']}",
                parse_mode="html",
            )
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("ipinfo", r"$"))
    async def _myip(e):
        try:
            d = await _get_json("http://ip-api.com/json/")
            await e.edit(
                f"🌐 IP: <code>{d['query']}</code>\n🏳 {d['country']}\n📡 {d['isp']}",
                parse_mode="html",
            )
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("news", r"$"))
    async def _news(e):
        try:
            ids = await _get_json("https://hacker-news.firebaseio.com/v0/topstories.json")
            stories = []
            for i in ids[:5]:
                s = await _get_json(f"https://hacker-news.firebaseio.com/v0/item/{i}.json")
                stories.append(f"▪ <a href='{s.get('url','#')}'>{h_escape(s['title'])}</a>")
            await e.edit("📰 <b>HackerNews Top 5</b>\n\n" + "\n".join(stories), parse_mode="html", link_preview=False)
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("movie"))
    async def _mov(e):
        q = e.pattern_match.group(1)
        if not q: return await _info(e, "movie", ".movie <ad>", "Film axtarışı.", ".movie inception")
        try:
            # OMDB-nin pulsuz key-i lazımdır, alternativ:
            d = await _get_json("https://www.omdbapi.com/", params={"t": q, "apikey": "thewdb"})
            if d.get("Response") != "True": return await e.edit("❌ Tapılmadı.")
            await e.edit(
                f"🎬 <b>{d['Title']}</b> ({d['Year']})\n"
                f"⭐ {d.get('imdbRating','?')} | ⏱ {d.get('Runtime','?')}\n"
                f"🎭 {d.get('Genre','—')}\n"
                f"📝 {h_escape(d.get('Plot','—')[:400])}",
                parse_mode="html",
            )
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("anime"))
    async def _anime(e):
        q = e.pattern_match.group(1)
        if not q: return await _info(e, "anime", ".anime <ad>", "Anime axtarışı (Jikan).", ".anime naruto")
        try:
            d = await _get_json("https://api.jikan.moe/v4/anime", params={"q": q, "limit": 1})
            a = d["data"][0]
            await e.edit(
                f"🎌 <b>{a['title']}</b>\n"
                f"⭐ {a.get('score','?')} | 📺 {a.get('episodes','?')} ep\n"
                f"🎭 {', '.join(g['name'] for g in a.get('genres',[]))}\n"
                f"📝 {h_escape((a.get('synopsis') or '—')[:400])}",
                parse_mode="html",
            )
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("manga"))
    async def _manga(e):
        q = e.pattern_match.group(1)
        if not q: return await _info(e, "manga", ".manga <ad>", "Manga axtarışı.", ".manga berserk")
        try:
            d = await _get_json("https://api.jikan.moe/v4/manga", params={"q": q, "limit": 1})
            a = d["data"][0]
            await e.edit(
                f"📖 <b>{a['title']}</b>\n⭐ {a.get('score','?')} | 📚 {a.get('chapters','?')} ch\n"
                f"📝 {h_escape((a.get('synopsis') or '—')[:400])}",
                parse_mode="html",
            )
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("waifu", r"$"))
    async def _waifu(e):
        await _send_pic(e, "https://api.waifu.pics/sfw/waifu", "url")

    @bot.on(cmd("lyric"))
    async def _lyric(e):
        q = e.pattern_match.group(1)
        if not q: return await _info(e, "lyric", ".lyric <artist - mahnı>", "Mahnı sözləri.", ".lyric coldplay - yellow")
        if " - " not in q: return await e.edit("❌ Format: artist - mahnı")
        a, t = q.split(" - ", 1)
        try:
            d = await _get_json(f"https://api.lyrics.ovh/v1/{urllib.parse.quote(a)}/{urllib.parse.quote(t)}")
            await e.edit(f"🎵 <b>{h_escape(a)} — {h_escape(t)}</b>\n\n{h_escape(d['lyrics'][:3500])}", parse_mode="html")
        except Exception as ex: await e.edit(f"❌ {ex}")


    @bot.on(cmd("youtube"))
    async def _yt(e):
        q = e.pattern_match.group(1)
        if not q: return await _info(e, "youtube", ".youtube <söz>", "YouTube axtarış.", ".youtube python")
        try:
            html = await _get_text(f"https://www.youtube.com/results?search_query={urllib.parse.quote(q)}")
            ids = re.findall(r'"videoId":"([^"]{11})"', html)[:5]
            if not ids: return await e.edit("❌ Tapılmadı.")
            await e.edit("📺 <b>Nəticələr:</b>\n" + "\n".join(f"▪ https://youtu.be/{i}" for i in ids), parse_mode="html", link_preview=False)
        except Exception as ex: await e.edit(f"❌ {ex}")

    async def _ytdl_generic(e, fmt, ext):
        q = e.pattern_match.group(1)
        if not q: 
            return await _info(e, "ytdl", f".ytdl/.ytmp3/.ytmp4 <url>", "YouTube yüklə.", ".ytmp3 https://youtu.be/...")
        await e.edit("⏳ Yüklənir...")
        try:
            import yt_dlp
            opts = {"format": fmt, "outtmpl": f"/tmp/{int(time.time())}.%(ext)s", "quiet": True, "no_warnings": True}
            if ext == "mp3":
                opts["postprocessors"] = [{"key":"FFmpegExtractAudio","preferredcodec":"mp3","preferredquality":"192"}]
            def _dl():
                with yt_dlp.YoutubeDL(opts) as y:
                    info = y.extract_info(q, download=True)
                    fn = y.prepare_filename(info)
                    if ext == "mp3": fn = os.path.splitext(fn)[0] + ".mp3"
                    return fn
            fn = await asyncio.get_event_loop().run_in_executor(None, _dl)
            await e.client.send_file(e.chat_id, fn, force_document=False, supports_streaming=ext == "mp4")
            try: os.remove(fn)
            except: pass
            await e.delete()
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("ytdl"))
    async def _ytdl(e): await _ytdl_generic(e, "best", "mp4")
    @bot.on(cmd("ytmp3"))
    async def _ymp3(e): await _ytdl_generic(e, "bestaudio/best", "mp3")
    @bot.on(cmd("ytmp4"))
    async def _ymp4(e): await _ytdl_generic(e, "best[ext=mp4]/best", "mp4")

    @bot.on(cmd("img"))
    async def _img(e):
        q = e.pattern_match.group(1)
        if not q: return await _info(e, "img", ".img <söz>", "DuckDuckGo şəkil.", ".img cats")
        try:
            html = await _get_text(f"https://duckduckgo.com/?q={urllib.parse.quote(q)}&iax=images&ia=images")
            vqd = re.search(r"vqd=['\"]([^'\"]+)", html)
            if not vqd: return await e.edit("❌ Tapılmadı.")
            d = await _get_json(
                "https://duckduckgo.com/i.js",
                params={"q":q,"o":"json","vqd":vqd.group(1),"f":",,,","p":"1"},
            )
            for r in d.get("results", [])[:1]:
                await _send_media(e, url=r["image"], filename="search_image")
            await e.delete()
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("screenshot"))
    async def _ss(e):
        u = e.pattern_match.group(1)
        if not u: return await _info(e, "screenshot", ".screenshot <url>", "Vebsayt screenshotu.", ".screenshot google.com")
        url = _normalize_url(u)
        bare = re.sub(r"^https?://", "", url)
        providers = [
            f"https://image.thum.io/get/width/1280/noanimate/{url}",
            f"https://s.wordpress.com/mshots/v1/{urllib.parse.quote(url, safe='')}?w=1280",
            f"https://api.microlink.io/?url={urllib.parse.quote(url, safe='')}&screenshot=true&meta=false&embed=screenshot.url",
        ]
        await e.edit("⏳ Screenshot çəkilir...")
        last_err = None
        for p_url in providers:
            try:
                stream, mime = await _download_named_media(p_url, fallback="screenshot")
                data = stream.getvalue()
                if len(data) < 1500:  # boş/placeholder
                    last_err = f"kiçik cavab ({len(data)}b)"
                    continue
                if not (mime.startswith("image/") or data[:3] == b"\xff\xd8\xff" or data.startswith(b"\x89PNG")):
                    last_err = f"şəkil deyil ({mime})"
                    continue
                await _send_media(e, data=data, filename=f"screenshot_{bare[:30]}.png", mime="image/png")
                return await e.delete()
            except Exception as ex:
                last_err = str(ex)
                continue
        await e.edit(f"❌ Screenshot alınmadı: {h_escape(str(last_err))}")

    @bot.on(cmd("domain"))
    async def _dom(e):
        d_ = (e.pattern_match.group(1) or "").strip()
        if not d_: return await _info(e, "domain", ".domain <domen>", "Domain RDAP məlumatı.", ".domain google.com")
        d_ = re.sub(r"^https?://", "", d_).split("/")[0].lower()
        try:
            r = await _get_json(f"https://rdap.org/domain/{d_}")
            handle = r.get("handle") or r.get("ldhName") or d_
            events_ = r.get("events", [])
            status = ", ".join(r.get("status", []) or ["—"])
            ns = ", ".join(n.get("ldhName", "") for n in r.get("nameservers", [])) or "—"
            ev_map = {ev.get("eventAction"): ev.get("eventDate","")[:10] for ev in events_}
            txt = (
                f"🌐 <b>{h_escape(handle)}</b>\n"
                f"📅 Yaradılıb: <code>{ev_map.get('registration','—')}</code>\n"
                f"🔄 Yenilənib: <code>{ev_map.get('last changed','—')}</code>\n"
                f"⏳ Bitir: <code>{ev_map.get('expiration','—')}</code>\n"
                f"📡 Status: {h_escape(status)}\n"
                f"🖥 NS: <code>{h_escape(ns[:300])}</code>"
            )
            await e.edit(txt, parse_mode="html")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("dns"))
    async def _dns(e):
        d_ = e.pattern_match.group(1)
        if not d_: return await _info(e, "dns", ".dns <domen>", "DNS qeydləri.", ".dns google.com")
        try:
            txt = ""
            for rtype in ("A","AAAA","MX","NS","TXT"):
                r = await _get_json(f"https://dns.google/resolve?name={d_}&type={rtype}")
                ans = r.get("Answer", [])
                txt += f"<b>{rtype}:</b>\n" + "\n".join(f"  {a['data']}" for a in ans[:5]) + "\n"
            await e.edit(txt or "❌ Yox", parse_mode="html")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("ssl"))
    async def _ssl(e):
        d_ = e.pattern_match.group(1)
        if not d_: return await _info(e, "ssl", ".ssl <domen>", "SSL məlumatı.", ".ssl google.com")
        try:
            import ssl, socket
            ctx = ssl.create_default_context()
            with socket.create_connection((d_, 443), timeout=5) as sock:
                with ctx.wrap_socket(sock, server_hostname=d_) as s:
                    cert = s.getpeercert()
            await e.edit(f"🔒 <code>{h_escape(str(cert)[:1500])}</code>", parse_mode="html")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("mac"))
    async def _mac(e):
        m = e.pattern_match.group(1)
        if not m: return await _info(e, "mac", ".mac <MAC>", "MAC vendor.", ".mac 00:11:22:33:44:55")
        try:
            t = await _get_text(f"https://api.macvendors.com/{m}")
            await e.edit(f"🔌 <b>{h_escape(t)}</b>", parse_mode="html")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("iban"))
    async def _iban(e):
        i = e.pattern_match.group(1)
        if not i: return await _info(e, "iban", ".iban <IBAN>", "IBAN validate.", ".iban DE89...")
        try:
            d = await _get_json(f"https://openiban.com/validate/{i}?getBIC=true&validateBankCode=true")
            await e.edit(f"🏦 Valid: {d.get('valid')}\nBank: {d.get('bankData',{}).get('name','—')}", parse_mode="html")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("phone"))
    async def _phone(e):
        p = e.pattern_match.group(1)
        if not p: return await _info(e, "phone", ".phone <nömrə>", "Telefon nömrəsi.", ".phone +994501234567")
        try:
            import phonenumbers
            from phonenumbers import geocoder, carrier
            n = phonenumbers.parse(p, None)
            await e.edit(
                f"📞 {phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.INTERNATIONAL)}\n"
                f"🏳 {geocoder.description_for_number(n,'en')}\n"
                f"📡 {carrier.name_for_number(n,'en')}\n"
                f"✔ Valid: {phonenumbers.is_valid_number(n)}",
                parse_mode="html",
            )
        except ImportError: await e.edit("❌ pip install phonenumbers")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("carbon"))
    async def _carb(e):
        code = e.pattern_match.group(1)
        if not code and not e.is_reply:
            return await _info(e, "carbon", ".carbon <kod>", "Kod şəkli (carbon).", ".carbon print('hi')")
        if not code: code = (await e.get_reply_message()).text
        try:
            url = "https://carbonara.solopov.dev/api/cook"
            s = await _http()
            async with s.post(url, json={"code": code}) as r:
                data = await r.read()
            await _send_media(e, data=data, filename="image.png", mime="image/png")
            await e.delete()
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("paste"))
    async def _paste(e):
        t = e.pattern_match.group(1)
        if not t and not e.is_reply: return await _info(e, "paste", ".paste <mətn>", "Dpaste.com'a yüklə.", ".paste hello")
        if not t: t = (await e.get_reply_message()).text
        try:
            s = await _http()
            async with s.post("https://dpaste.com/api/v2/", data={"content": t}) as r:
                u = (await r.text()).strip()
            await e.edit(f"📋 <code>{h_escape(u)}</code>", parse_mode="html")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("gist"))
    async def _gist(e):
        t = e.pattern_match.group(1)
        if not t and not e.is_reply: return await _info(e, "gist", ".gist <mətn>", "Anonim gist (sourceb.in).", ".gist hello")
        if not t: t = (await e.get_reply_message()).text
        try:
            s = await _http()
            async with s.post(
                "https://api.sourceb.in/bins",
                json={"files":[{"content": t}]}
            ) as r:
                d = await r.json()
            await e.edit(f"📋 https://sourceb.in/{d['key']}", parse_mode="html")
        except Exception as ex: await e.edit(f"❌ {ex}")

    # ============================================================
    # 3. FUN (81-120)
    # ============================================================

    @bot.on(cmd("dice", r"$"))
    async def _dice(e):
        await e.edit(f"🎲 <b>{random.randint(1,6)}</b>", parse_mode="html")

    @bot.on(cmd("coin", r"$"))
    async def _coin(e):
        await e.edit(f"🪙 <b>{random.choice(['Üz','Yazı'])}</b>", parse_mode="html")

    @bot.on(cmd("choose"))
    async def _ch(e):
        a = e.pattern_match.group(1)
        if not a or "|" not in a: return await _info(e, "choose", ".choose a|b|c", "Variantdan seçim.", ".choose çay|qəhvə")
        await e.edit(f"🎯 <b>{random.choice([x.strip() for x in a.split('|')])}</b>", parse_mode="html")

    @bot.on(cmd("8ball"))
    async def _8b(e):
        q = e.pattern_match.group(1)
        if not q: return await _info(e, "8ball", ".8ball <sual>", "Magic 8-ball.", ".8ball uğur var?")
        ans = ["Bəli","Xeyr","Bəlkə","Şübhəsiz","Yox","Sonra soruş","Əlbəttə","Gümanlı deyil","Aydın deyil"]
        await e.edit(f"🎱 <b>{random.choice(ans)}</b>", parse_mode="html")

    @bot.on(cmd("love"))
    async def _love(e):
        a = e.pattern_match.group(1)
        if not a or " " not in a: return await _info(e, "love", ".love <a> <b>", "Sevgi %.", ".love Ali Ayşə")
        await e.edit(f"💘 {h_escape(a)} → <b>{random.randint(0,100)}%</b>", parse_mode="html")

    @bot.on(cmd("ship"))
    async def _ship(e):
        a = e.pattern_match.group(1)
        if not a or " " not in a: return await _info(e, "ship", ".ship <a> <b>", "Ship ad.", ".ship Ali Ayşə")
        x, y = a.split(maxsplit=1)
        await e.edit(f"💞 <b>{x[:len(x)//2] + y[len(y)//2:]}</b>", parse_mode="html")

    @bot.on(cmd("slot", r"$"))
    async def _slot(e):
        sym = ["🍒","🍋","🍇","🔔","⭐","💎"]
        r = [random.choice(sym) for _ in range(3)]
        win = "🎉 QALIB!" if len(set(r))==1 else "💸 Növbəti dəfə"
        await e.edit(f"🎰 {' | '.join(r)}\n{win}", parse_mode="html")

    @bot.on(cmd("roll"))
    async def _roll(e):
        a = e.pattern_match.group(1)
        if not a: return await _info(e, "roll", ".roll <NdM>", "Zər at.", ".roll 2d6")
        m = re.match(r"(\d+)d(\d+)", a)
        if not m: return await e.edit("❌ Format: 2d6")
        n, s = int(m.group(1)), int(m.group(2))
        rs = [random.randint(1,s) for _ in range(n)]
        await e.edit(f"🎲 {rs} = <b>{sum(rs)}</b>", parse_mode="html")

    @bot.on(cmd("number"))
    async def _num(e):
        a = e.pattern_match.group(1)
        if not a or " " not in a: return await _info(e, "number", ".number <min> <max>", "Random ədəd.", ".number 1 100")
        x, y = map(int, a.split())
        await e.edit(f"🔢 <b>{random.randint(x,y)}</b>", parse_mode="html")

    @bot.on(cmd("rps"))
    async def _rps(e):
        c = e.pattern_match.group(1)
        if not c: return await _info(e, "rps", ".rps <daş/kağız/qayçı>", "Daş-kağız-qayçı.", ".rps daş")
        bot_c = random.choice(["daş","kağız","qayçı"])
        win = {"daş":"qayçı","qayçı":"kağız","kağız":"daş"}
        if c == bot_c: r = "Bərabər"
        elif win[c] == bot_c: r = "Sən qazandın 🎉"
        else: r = "Mən qazandım 😎"
        await e.edit(f"🪨 Bot: {bot_c}\nSən: {c}\n<b>{r}</b>", parse_mode="html")

    @bot.on(cmd("flip"))
    async def _flip(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "flip", ".flip <mətn>", "Mətni çevirir.", ".flip salam")
        flip_map = str.maketrans(
            "abcdefghijklmnopqrstuvwxyz",
            "ɐqɔpǝɟƃɥᴉɾʞlɯuodbɹsʇnʌʍxʎz",
        )
        await e.edit(t.lower().translate(flip_map)[::-1])

    @bot.on(cmd("small"))
    async def _small(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "small", ".small <mətn>", "Kiçik hərflər.", ".small hello")
        m = str.maketrans("abcdefghijklmnopqrstuvwxyz","ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖᵠʳˢᵗᵘᵛʷˣʸᶻ")
        await e.edit(t.lower().translate(m))

    @bot.on(cmd("bold"))
    async def _bold(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "bold", ".bold <mətn>", "Bold mətn.", ".bold salam")
        await e.edit(f"**{t}**")

    @bot.on(cmd("italic"))
    async def _it(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "italic", ".italic <mətn>", "Italic.", ".italic salam")
        await e.edit(f"__{t}__")

    @bot.on(cmd("mono"))
    async def _mono(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "mono", ".mono <mətn>", "Mono.", ".mono salam")
        await e.edit(f"`{t}`")

    @bot.on(cmd("strike"))
    async def _str(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "strike", ".strike <mətn>", "Üstüçızıq.", ".strike salam")
        await e.edit(f"~~{t}~~")

    @bot.on(cmd("spoiler"))
    async def _sp(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "spoiler", ".spoiler <mətn>", "Spoiler.", ".spoiler gizli")
        await e.edit(f"||{t}||")

    @bot.on(cmd("mock"))
    async def _mock(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "mock", ".mock <mətn>", "MoCkİnG mətn.", ".mock salam")
        await e.edit("".join(c.upper() if i%2 else c.lower() for i,c in enumerate(t)))

    @bot.on(cmd("zalgo"))
    async def _zal(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "zalgo", ".zalgo <mətn>", "Zalgo mətn.", ".zalgo salam")
        out = ""
        for c in t:
            out += c + "".join(chr(random.randint(0x0300,0x036F)) for _ in range(random.randint(1,5)))
        await e.edit(out)

    @bot.on(cmd("owo"))
    async def _owo(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "owo", ".owo <mətn>", "OwO mətn.", ".owo hello")
        t = re.sub(r"[rl]","w",t); t = re.sub(r"[RL]","W",t)
        await e.edit(t + " owo")

    @bot.on(cmd("clap"))
    async def _clap(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "clap", ".clap <mətn>", "👏 ilə ayrılmış.", ".clap hello world")
        await e.edit(" 👏 ".join(t.split()))

    @bot.on(cmd("remoji", r"$"))
    async def _re(e):
        await e.edit(random.choice("😀😎🥳🤩😻🦄🎉✨🔥💎🌈⚡🎵💖🌟"))

    @bot.on(cmd("ascii"))
    async def _asc(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "ascii", ".ascii <mətn>", "ASCII art (pyfiglet).", ".ascii hi")
        try:
            import pyfiglet
            await e.edit(f"<pre>{h_escape(pyfiglet.figlet_format(t))}</pre>", parse_mode="html")
        except ImportError: await e.edit("❌ pip install pyfiglet")

    @bot.on(cmd("figlet"))
    async def _fig(e):
        return await _asc(e)

    @bot.on(cmd("catface", r"$"))
    async def _cf(e):
        faces = ["(=^･ω･^=)","ฅ^•ﻌ•^ฅ","(=^･ｪ･^=)","(^◕ᴥ◕^)","(=｀ω´=)"]
        await e.edit(random.choice(faces))

    @bot.on(cmd("shrug", r"$"))
    async def _sh(e):
        await e.edit(r"¯\_(ツ)_/¯")

    @bot.on(cmd("tableflip", r"$"))
    async def _tf(e):
        await e.edit("(╯°□°）╯︵ ┻━┻")

    @bot.on(cmd("unflip", r"$"))
    async def _uf(e):
        await e.edit("┬─┬ ノ( ゜-゜ノ)")

    @bot.on(cmd("lenny", r"$"))
    async def _le(e):
        await e.edit("( ͡° ͜ʖ ͡°)")

    @bot.on(cmd("disapp", r"$"))
    async def _da(e):
        await e.edit("ಠ_ಠ")

    @bot.on(cmd("piglatin"))
    async def _pig(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "piglatin", ".piglatin <mətn>", "Pig Latin.", ".piglatin hello")
        out = []
        for w in t.split():
            out.append(w[1:] + w[0] + "ay" if w[0].lower() not in "aeiou" else w + "way")
        await e.edit(" ".join(out))

    MORSE = {
        'A':'.-','B':'-...','C':'-.-.','D':'-..','E':'.','F':'..-.','G':'--.','H':'....',
        'I':'..','J':'.---','K':'-.-','L':'.-..','M':'--','N':'-.','O':'---','P':'.--.',
        'Q':'--.-','R':'.-.','S':'...','T':'-','U':'..-','V':'...-','W':'.--','X':'-..-',
        'Y':'-.--','Z':'--..',
        '0':'-----','1':'.----','2':'..---','3':'...--','4':'....-','5':'.....',
        '6':'-....','7':'--...','8':'---..','9':'----.',
    }
    INV_MORSE = {v:k for k,v in MORSE.items()}

    @bot.on(cmd("morse"))
    async def _morse(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "morse", ".morse <mətn>", "Morse encode.", ".morse SOS")
        await e.edit(" ".join(MORSE.get(c.upper(),c) for c in t))

    @bot.on(cmd("unmorse"))
    async def _unm(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "unmorse", ".unmorse <kod>", "Morse decode.", ".unmorse ... --- ...")
        await e.edit("".join(INV_MORSE.get(c,c) for c in t.split()))

    @bot.on(cmd("binary"))
    async def _bin(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "binary", ".binary <mətn>", "Binary encode.", ".binary A")
        await e.edit(" ".join(format(ord(c),'08b') for c in t))

    @bot.on(cmd("unbinary"))
    async def _ub(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "unbinary", ".unbinary <kod>", "Binary decode.", ".unbinary 01000001")
        try: await e.edit("".join(chr(int(b,2)) for b in t.split()))
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("rot13"))
    async def _rot(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "rot13", ".rot13 <mətn>", "ROT13.", ".rot13 hello")
        import codecs
        await e.edit(codecs.encode(t, "rot_13"))

    @bot.on(cmd("caesar"))
    async def _ca(e):
        a = e.pattern_match.group(1)
        if not a or " " not in a: return await _info(e, "caesar", ".caesar <shift> <mətn>", "Caesar cipher.", ".caesar 3 hello")
        sh, t = a.split(maxsplit=1)
        sh = int(sh)
        out = "".join(chr((ord(c)-65+sh)%26+65) if c.isupper() else chr((ord(c)-97+sh)%26+97) if c.islower() else c for c in t)
        await e.edit(out)

    @bot.on(cmd("atbash"))
    async def _at(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "atbash", ".atbash <mətn>", "Atbash cipher.", ".atbash hello")
        out = "".join(chr(155-ord(c)) if c.islower() else chr(155-ord(c.lower())-32) if c.isupper() else c for c in t)
        await e.edit(out)

    @bot.on(cmd("leet"))
    async def _leet(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "leet", ".leet <mətn>", "1337.", ".leet hello")
        m = str.maketrans("aeilostAEILOST","43110574311057")
        await e.edit(t.translate(m))

    @bot.on(cmd("spaces"))
    async def _sp2(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "spaces", ".spaces <mətn>", "B o ş l u q.", ".spaces salam")
        await e.edit(" ".join(t))

    # ============================================================
    # 4. GROUP / CHAT (121-150)
    # ============================================================

    AFK_STATE = {"active": False, "reason": "", "since": 0}

    @bot.on(cmd("ahsjsjsj"))
    async def _afk(e):
        r = e.pattern_match.group(1) or "AFK"
        AFK_STATE.update({"active": True, "reason": r, "since": time.time()})
        await e.edit(f"💤 <b>AFK:</b> {h_escape(r)}", parse_mode="html")

    @bot.on(cmd("jsksksjs", r"$"))
    async def _unafk(e):
        AFK_STATE["active"] = False
        await e.edit("✅ AFK ləğv olundu.")

    @bot.on(events.NewMessage(incoming=True))
    async def _afk_watcher(e):
        if not AFK_STATE["active"]: return
        if not (e.mentioned or e.is_private): return
        dt = _fmt_uptime(time.time() - AFK_STATE["since"])
        await e.reply(f"💤 <b>AFK</b>\n📝 {h_escape(AFK_STATE['reason'])}\n⏱ {dt}", parse_mode="html")

    @bot.on(cmd("hakakaka"))
    async def _tag(e):
        t = e.pattern_match.group(1) or "‏‏‎ ‎"
        if not e.is_reply: return await _info(e, "tag", ".tag <mətn> (reply)", "Reply'ə görünməz tag.", ".tag salam")
        r = await e.get_reply_message()
        await e.delete()
        await e.client.send_message(e.chat_id, f"[‎](tg://user?id={r.sender_id}){t}", parse_mode="md")

    @bot.on(cmd("hahahaha"))
    async def _tagall(e):
        t = e.pattern_match.group(1) or "Hamı"
        try:
            mentions = []
            async for u in e.client.iter_participants(e.chat_id, limit=50):
                if not u.bot: mentions.append(f"[‎](tg://user?id={u.id})")
            await e.edit(f"{t} " + "".join(mentions), parse_mode="md")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("admins", r"$"))
    async def _adm(e):
        try:
            txt = "👮 <b>Adminlər:</b>\n"
            async for u in e.client.iter_participants(e.chat_id, filter=ChannelParticipantsAdmins):
                txt += f"▪ {h_escape(u.first_name or '')} (<code>{u.id}</code>)\n"
            await e.edit(txt, parse_mode="html")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("members", r"$"))
    async def _mem(e):
        try:
            ent = await e.get_chat()
            full = await e.client.get_participants(e.chat_id, limit=0)
            await e.edit(f"👥 Cəmi: <b>{full.total}</b>", parse_mode="html")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("bots", r"$"))
    async def _bots(e):
        try:
            txt = "🤖 <b>Botlar:</b>\n"
            async for u in e.client.iter_participants(e.chat_id, filter=ChannelParticipantsBots):
                txt += f"▪ @{u.username} (<code>{u.id}</code>)\n"
            await e.edit(txt or "❌ Yox", parse_mode="html")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("delusers", r"$"))
    async def _du(e):
        await e.edit("⏳ Silinən userlər təmizlənir...")
        n = 0
        try:
            async for u in e.client.iter_participants(e.chat_id):
                if u.deleted:
                    try:
                        await e.client.edit_permissions(e.chat_id, u.id, view_messages=False)
                        n += 1
                    except: pass
            await e.edit(f"✅ {n} silinmiş user atıldı.")
        except Exception as ex: await e.edit(f"❌ {ex}")

    async def _promote_demote(e, promote):
        if not e.is_reply: 
            return await _info(e, "promote" if promote else "demote",
                f".{'promote' if promote else 'demote'} (reply)", "Admin et / götür.")
        r = await e.get_reply_message()
        rights = ChatAdminRights(
            change_info=promote, post_messages=promote, edit_messages=promote,
            delete_messages=promote, ban_users=promote, invite_users=promote,
            pin_messages=promote, add_admins=False, manage_call=promote,
        )
        try:
            await e.client(EditAdminRequest(e.chat_id, r.sender_id, rights, "Admin"))
            await e.edit("✅ Edildi.")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("promote", r"$"))
    async def _pr(e): await _promote_demote(e, True)
    @bot.on(cmd("demote", r"$"))
    async def _de(e): await _promote_demote(e, False)

    async def _ban_action(e, banned):
        if not e.is_reply: return await _info(e, "ban", ".ban (reply)", "Ban et / aç.")
        r = await e.get_reply_message()
        rights = ChatBannedRights(until_date=None, view_messages=banned)
        try:
            await e.client(EditBannedRequest(e.chat_id, r.sender_id, rights))
            await e.edit("✅ " + ("Ban olundu" if banned else "Ban açıldı"))
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("ban", r"$"))
    async def _ban(e): await _ban_action(e, True)
    @bot.on(cmd("unban", r"$"))
    async def _ub2(e): await _ban_action(e, False)

    @bot.on(cmd("kick", r"$"))
    async def _kick(e):
        if not e.is_reply: return await _info(e, "kick", ".kick (reply)", "Kick et.")
        r = await e.get_reply_message()
        try:
            await e.client.kick_participant(e.chat_id, r.sender_id)
            await e.edit("👢 Kick olundu.")
        except Exception as ex: await e.edit(f"❌ {ex}")

    async def _mute_action(e, muted):
        if not e.is_reply: return await _info(e, "mute", ".mute (reply)", "Mute et / aç.")
        r = await e.get_reply_message()
        rights = ChatBannedRights(until_date=None, send_messages=muted)
        try:
            await e.client(EditBannedRequest(e.chat_id, r.sender_id, rights))
            await e.edit("🔇 " + ("Mute" if muted else "Unmute"))
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("mute", r"$"))
    async def _mu(e): await _mute_action(e, True)
    @bot.on(cmd("unmute", r"$"))
    async def _um(e): await _mute_action(e, False)

    @bot.on(cmd("pin", r"$"))
    async def _pin(e):
        if not e.is_reply: return await _info(e, "pin", ".pin (reply)", "Mesajı pin et.")
        r = await e.get_reply_message()
        try:
            await e.client.pin_message(e.chat_id, r.id, notify=True)
            await e.edit("📌 Pin olundu.")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("unpin", r"$"))
    async def _unp(e):
        try:
            await e.client.unpin_message(e.chat_id)
            await e.edit("📌 Pin açıldı.")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("lock", r"$"))
    async def _lk(e):
        from telethon.tl.functions.messages import EditChatDefaultBannedRightsRequest
        try:
            await e.client(EditChatDefaultBannedRightsRequest(
                peer=e.chat_id,
                banned_rights=ChatBannedRights(until_date=None, send_messages=True),
            ))
            await e.edit("🔒 Chat kilidləndi.")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("unlock", r"$"))
    async def _ulk(e):
        from telethon.tl.functions.messages import EditChatDefaultBannedRightsRequest
        try:
            await e.client(EditChatDefaultBannedRightsRequest(
                peer=e.chat_id,
                banned_rights=ChatBannedRights(until_date=None, send_messages=False),
            ))
            await e.edit("🔓 Chat açıldı.")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("title"))
    async def _ti(e):
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "title", ".title <ad>", "Qrup adını dəyiş.", ".title Yeni Ad")
        try:
            await e.client.edit_admin(e.chat_id, "me", title=t[:16])
            await e.edit("✅")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("setbio"))
    async def _sb(e):
        from telethon.tl.functions.account import UpdateProfileRequest
        t = e.pattern_match.group(1)
        if t is None: return await _info(e, "setbio", ".setbio <mətn>", "Bio dəyiş.", ".setbio salam")
        try:
            await e.client(UpdateProfileRequest(about=t[:70]))
            await e.edit("✅ Bio yeniləndi.")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("setname"))
    async def _sn(e):
        from telethon.tl.functions.account import UpdateProfileRequest
        t = e.pattern_match.group(1)
        if not t: return await _info(e, "setname", ".setname <ad>", "Ad dəyiş.", ".setname Ali")
        try:
            parts = t.split(maxsplit=1)
            await e.client(UpdateProfileRequest(first_name=parts[0], last_name=parts[1] if len(parts)>1 else ""))
            await e.edit("✅ Ad dəyişdi.")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("setpic", r"$"))
    async def _sp_pic(e):
        from telethon.tl.functions.photos import UploadProfilePhotoRequest
        if not e.is_reply: return await _info(e, "setpic", ".setpic (reply şəkil)", "Profil şəkli dəyiş.")
        r = await e.get_reply_message()
        try:
            f = await r.download_media(file="/tmp/pp.jpg")
            await e.client(UploadProfilePhotoRequest(await e.client.upload_file(f)))
            os.remove(f)
            await e.edit("✅ Profil şəkli dəyişdi.")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("save", r"$"))
    async def _save(e):
        if not e.is_reply: return await _info(e, "save", ".save (reply)", "Saved Messages'a göndərir (səs, video, foto da).")
        r = await e.get_reply_message()
        try:
            try:
                await r.forward_to("me")
            except Exception:
                # Restricted -> re-upload
                if r.media:
                    f = await r.download_media(file="/tmp/")
                    await e.client.send_file("me", f, caption=r.text or "")
                    try: os.remove(f)
                    except: pass
                else:
                    await e.client.send_message("me", r.text or "")
            await e.edit("💾 Saved Messages-a göndərildi.")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("dl", r"$"))
    async def _dl(e):
        if not e.is_reply: return await _info(e, "dl", ".dl (reply)", "Media yüklə.")
        r = await e.get_reply_message()
        if not r.media: return await e.edit("❌ Media yox.")
        try:
            f = await r.download_media(file="/tmp/")
            await e.edit(f"✅ Yükləndi: <code>{h_escape(f)}</code>", parse_mode="html")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("ul"))
    async def _ul(e):
        p = e.pattern_match.group(1)
        if not p: return await _info(e, "ul", ".ul <fayl>", "Fayl göndər.", ".ul /tmp/x.txt")
        if not os.path.exists(p): return await e.edit("❌ Fayl yox.")
        await e.client.send_file(e.chat_id, p)
        await e.delete()

    @bot.on(cmd("copy", r"$"))
    async def _cp(e):
        if not e.is_reply: return await _info(e, "copy", ".copy (reply)", "Mesajı kopyala (forward header'siz).")
        r = await e.get_reply_message()
        if r.media:
            await e.client.send_file(e.chat_id, r.media, caption=r.text or "")
        else:
            await e.client.send_message(e.chat_id, r.text or "")
        await e.delete()

    @bot.on(cmd("forward"))
    async def _fw(e):
        u = e.pattern_match.group(1)
        if not u or not e.is_reply: return await _info(e, "forward", ".forward <user> (reply)", "Reply'i fwd et.", ".forward @user")
        r = await e.get_reply_message()
        try:
            await e.client.forward_messages(u, r)
            await e.edit("✅")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("read", r"$"))
    async def _read(e):
        try:
            await e.client.send_read_acknowledge(e.chat_id)
            await e.edit("✅ Oxundu.")
        except Exception as ex: await e.edit(f"❌ {ex}")

    @bot.on(cmd("stats", r"$"))
    async def _st(e):
        try:
            me = await e.client.get_me()
            dialogs = await e.client.get_dialogs(limit=0)
            await e.edit(
                f"📊 <b>Stats</b>\n👤 {me.first_name}\n💬 Dialoglar: {dialogs.total}",
                parse_mode="html",
            )
        except Exception as ex: await e.edit(f"❌ {ex}")


    # ============================================================
    # 5. EXTRA API + FUN (151-300) — 150 NEW COMMANDS
    # ============================================================
    EXTRA_COMMANDS = ['triviageneral', 'hardgeneral', 'triviabooks', 'hardbooks', 'triviafilm', 'hardfilm', 'triviamusic', 'hardmusic', 'triviamusicals', 'hardmusicals', 'triviatelevision', 'hardtelevision', 'triviagames', 'hardgames', 'triviaboardgames', 'hardboardgames', 'triviascience', 'hardscience', 'triviacomputers', 'hardcomputers', 'triviamath', 'hardmath', 'triviamythology', 'hardmythology', 'triviasports', 'hardsports', 'triviageography', 'hardgeography', 'triviahistory', 'hardhistory', 'triviapolitics', 'hardpolitics', 'triviaart', 'hardart', 'triviacelebrities', 'hardcelebrities', 'triviaanimals', 'hardanimals', 'avatar1', 'avatar2', 'avatar3', 'avatar4', 'avatar5', 'avatar6', 'avatar7', 'avatar8', 'avatar9', 'avatar10', 'avatar11', 'avatar12', 'avatar13', 'avatar14', 'avatar15', 'avatar16', 'avatar17', 'avatar18', 'avatar19', 'avatar20', 'robot1', 'robot2', 'robot3', 'robot4', 'robot5', 'wallpaper1', 'wallpaper2', 'wallpaper3', 'wallpaper4', 'wallpaper5', 'wallpaper6', 'wallpaper7', 'triviafact1', 'triviafact2', 'triviafact3', 'triviafact4', 'triviafact5', 'mathfact1', 'mathfact2', 'mathfact3', 'mathfact4', 'mathfact5', 'datefact1', 'datefact2', 'datefact3', 'datefact4', 'datefact5', 'yearfact1', 'yearfact2', 'yearfact3', 'yearfact4', 'yearfact5', 'pokeinfo', 'pokestats', 'poketypes', 'pokeabilities', 'pokemoves', 'pokeheight', 'pokeweight', 'pokeexperience', 'pokesprite', 'pokeshiny', 'countryinfo', 'countrycapital', 'countryflag', 'countrypopulation', 'countrycurrency', 'countrylanguage', 'countryregion', 'countrytimezone', 'countrymap', 'countrycode', 'ghprofile', 'ghfollowers', 'ghfollowing', 'ghrepos', 'ghgists', 'ghjoined', 'ghcompany', 'ghlocation', 'ghblog', 'ghavatar', 'animesearch', 'animescore', 'animeepisodes', 'animestatus', 'animeyear', 'animegenres', 'animestudios', 'animerating', 'animeposter', 'animesynopsis', 'randomactivity', 'randomjoke2', 'randomadvice2', 'randomfact2', 'randomquote2', 'chucknorris', 'dogfact', 'catfact', 'agify', 'genderize', 'randomcat2', 'randomdog2', 'randomfox2', 'randomduck2', 'randomwaifu2', 'randomneko', 'randomhug', 'randomwink', 'randompat', 'randomsmile']
    TRIVIA_COMMANDS = {'triviageneral': (9, 'easy'), 'hardgeneral': (9, 'hard'), 'triviabooks': (10, 'easy'), 'hardbooks': (10, 'hard'), 'triviafilm': (11, 'easy'), 'hardfilm': (11, 'hard'), 'triviamusic': (12, 'easy'), 'hardmusic': (12, 'hard'), 'triviamusicals': (13, 'easy'), 'hardmusicals': (13, 'hard'), 'triviatelevision': (14, 'easy'), 'hardtelevision': (14, 'hard'), 'triviagames': (15, 'easy'), 'hardgames': (15, 'hard'), 'triviaboardgames': (16, 'easy'), 'hardboardgames': (16, 'hard'), 'triviascience': (17, 'easy'), 'hardscience': (17, 'hard'), 'triviacomputers': (18, 'easy'), 'hardcomputers': (18, 'hard'), 'triviamath': (19, 'easy'), 'hardmath': (19, 'hard'), 'triviamythology': (20, 'easy'), 'hardmythology': (20, 'hard'), 'triviasports': (21, 'easy'), 'hardsports': (21, 'hard'), 'triviageography': (22, 'easy'), 'hardgeography': (22, 'hard'), 'triviahistory': (23, 'easy'), 'hardhistory': (23, 'hard'), 'triviapolitics': (24, 'easy'), 'hardpolitics': (24, 'hard'), 'triviaart': (25, 'easy'), 'hardart': (25, 'hard'), 'triviacelebrities': (26, 'easy'), 'hardcelebrities': (26, 'hard'), 'triviaanimals': (27, 'easy'), 'hardanimals': (27, 'hard')}
    AVATAR_COMMANDS = {'avatar1': 'adventurer', 'avatar2': 'adventurer-neutral', 'avatar3': 'avataaars', 'avatar4': 'avataaars-neutral', 'avatar5': 'big-ears', 'avatar6': 'big-ears-neutral', 'avatar7': 'big-smile', 'avatar8': 'bottts', 'avatar9': 'bottts-neutral', 'avatar10': 'croodles', 'avatar11': 'croodles-neutral', 'avatar12': 'dylan', 'avatar13': 'fun-emoji', 'avatar14': 'glass', 'avatar15': 'icons', 'avatar16': 'identicon', 'avatar17': 'initials', 'avatar18': 'lorelei', 'avatar19': 'micah', 'avatar20': 'miniavs'}
    ROBOT_COMMANDS = {'robot1': 1, 'robot2': 2, 'robot3': 3, 'robot4': 4, 'robot5': 5}
    WALLPAPER_COMMANDS = {'wallpaper1': (900, 600), 'wallpaper2': (940, 630), 'wallpaper3': (980, 660), 'wallpaper4': (1020, 690), 'wallpaper5': (1060, 720), 'wallpaper6': (1100, 750), 'wallpaper7': (1140, 780)}
    NUMBER_COMMANDS = {'triviafact1': 'trivia', 'triviafact2': 'trivia', 'triviafact3': 'trivia', 'triviafact4': 'trivia', 'triviafact5': 'trivia', 'mathfact1': 'math', 'mathfact2': 'math', 'mathfact3': 'math', 'mathfact4': 'math', 'mathfact5': 'math', 'datefact1': 'date', 'datefact2': 'date', 'datefact3': 'date', 'datefact4': 'date', 'datefact5': 'date', 'yearfact1': 'year', 'yearfact2': 'year', 'yearfact3': 'year', 'yearfact4': 'year', 'yearfact5': 'year'}

    async def _extra_handler(e, command_name):
        argument = (e.pattern_match.group(1) or "").strip()
        try:
            if command_name in TRIVIA_COMMANDS:
                category, difficulty = TRIVIA_COMMANDS[command_name]
                result = await _get_json("https://opentdb.com/api.php", params={"amount": 1, "type": "multiple", "category": category, "difficulty": difficulty})
                question = result.get("results", [{}])[0]
                answers = list(question.get("incorrect_answers", [])) + [question.get("correct_answer", "")]
                random.shuffle(answers)
                body = "\n".join(f"{index + 1}. {h_escape(answer)}" for index, answer in enumerate(answers))
                return await e.edit(f"🧠 <b>{h_escape(question.get('category', 'Trivia'))}</b> · {difficulty}\n\n{h_escape(question.get('question', 'Sual tapılmadı'))}\n\n{body}\n\n✅ <tg-spoiler>{h_escape(question.get('correct_answer', '—'))}</tg-spoiler>", parse_mode="html")
            if command_name in AVATAR_COMMANDS:
                seed = urllib.parse.quote(argument or str(e.sender_id), safe="")
                style = AVATAR_COMMANDS[command_name]
                return await _send_media(e, url=f"https://api.dicebear.com/9.x/{style}/png?seed={seed}&size=768", filename=f"{command_name}.png")
            if command_name in ROBOT_COMMANDS:
                seed = urllib.parse.quote(argument or str(e.sender_id), safe="")
                robot_set = ROBOT_COMMANDS[command_name]
                return await _send_media(e, url=f"https://robohash.org/{seed}.png?set=set{robot_set}&size=768x768", filename=f"{command_name}.png")
            if command_name in WALLPAPER_COMMANDS:
                width, height = WALLPAPER_COMMANDS[command_name]
                seed = urllib.parse.quote(argument or str(random.randint(1, 999999)), safe="")
                return await _send_media(e, url=f"https://picsum.photos/seed/{seed}/{width}/{height}", filename=f"{command_name}.jpg")
            if command_name in NUMBER_COMMANDS:
                number_type = NUMBER_COMMANDS[command_name]
                value = urllib.parse.quote(argument or "random", safe="")
                text = await _get_text(f"http://numbersapi.com/{value}/{number_type}")
                return await e.edit(f"🔢 {h_escape(text)}", parse_mode="html")
            if command_name.startswith("poke"):
                if not argument: return await _info(e, command_name, f".{command_name} <pokemon>", "PokéAPI məlumatı.", f".{command_name} pikachu")
                pokemon = await _get_json(f"https://pokeapi.co/api/v2/pokemon/{urllib.parse.quote(argument.lower())}")
                if command_name == "pokesprite": return await _send_media(e, url=pokemon["sprites"]["front_default"], filename=f"{argument}.png")
                if command_name == "pokeshiny": return await _send_media(e, url=pokemon["sprites"]["front_shiny"], filename=f"{argument}_shiny.png")
                fields = {"pokeinfo": f"ID: {pokemon['id']}\nAd: {pokemon['name']}", "pokestats": ", ".join(f"{x['stat']['name']}={x['base_stat']}" for x in pokemon['stats']), "poketypes": ", ".join(x['type']['name'] for x in pokemon['types']), "pokeabilities": ", ".join(x['ability']['name'] for x in pokemon['abilities']), "pokemoves": ", ".join(x['move']['name'] for x in pokemon['moves'][:20]), "pokeheight": f"{pokemon['height']/10} m", "pokeweight": f"{pokemon['weight']/10} kg", "pokeexperience": str(pokemon.get('base_experience', '—'))}
                return await e.edit(f"⚡ <b>{h_escape(argument.title())}</b>\n{h_escape(fields.get(command_name, '—'))}", parse_mode="html")
            if command_name.startswith("country"):
                if not argument: return await _info(e, command_name, f".{command_name} <ölkə>", "REST Countries məlumatı.", f".{command_name} Azerbaijan")
                countries = await _get_json(f"https://restcountries.com/v3.1/name/{urllib.parse.quote(argument)}")
                country_data = countries[0]
                if command_name == "countryflag": return await _send_media(e, url=country_data['flags']['png'], filename=f"{argument}_flag.png")
                country_fields = {"countryinfo": f"{country_data['name']['common']} — {country_data.get('region','—')}", "countrycapital": ', '.join(country_data.get('capital', ['—'])), "countrypopulation": f"{country_data.get('population',0):,}", "countrycurrency": ', '.join(country_data.get('currencies', {}).keys()), "countrylanguage": ', '.join(country_data.get('languages', {}).values()), "countryregion": f"{country_data.get('region','—')} / {country_data.get('subregion','—')}", "countrytimezone": ', '.join(country_data.get('timezones', [])), "countrymap": country_data.get('maps', {}).get('googleMaps','—'), "countrycode": f"{country_data.get('cca2','—')} / {country_data.get('cca3','—')}"}
                return await e.edit(f"🌍 {h_escape(country_fields.get(command_name, '—'))}", parse_mode="html", link_preview=False)
            if command_name.startswith("gh"):
                if not argument: return await _info(e, command_name, f".{command_name} <username>", "GitHub API məlumatı.", f".{command_name} torvalds")
                user = await _get_json(f"https://api.github.com/users/{urllib.parse.quote(argument)}")
                if command_name == "ghavatar": return await _send_media(e, url=user['avatar_url'], filename=f"{argument}.jpg")
                github_fields = {"ghprofile": f"{user.get('name') or user['login']} — {user.get('bio') or '—'}", "ghfollowers": str(user.get('followers',0)), "ghfollowing": str(user.get('following',0)), "ghrepos": str(user.get('public_repos',0)), "ghgists": str(user.get('public_gists',0)), "ghjoined": user.get('created_at','—'), "ghcompany": user.get('company') or '—', "ghlocation": user.get('location') or '—', "ghblog": user.get('blog') or '—'}
                return await e.edit(f"🐙 <b>{h_escape(argument)}</b>\n{h_escape(github_fields.get(command_name, user.get('html_url','—')))}", parse_mode="html", link_preview=False)
            if command_name.startswith("anime"):
                if not argument: return await _info(e, command_name, f".{command_name} <anime>", "Jikan/MyAnimeList məlumatı.", f".{command_name} Naruto")
                result = await _get_json("https://api.jikan.moe/v4/anime", params={"q": argument, "limit": 1})
                anime_data = result.get('data', [{}])[0]
                if command_name == "animeposter": return await _send_media(e, url=anime_data['images']['jpg']['large_image_url'], filename=f"{argument}.jpg")
                anime_fields = {"animesearch": anime_data.get('url','—'), "animescore": str(anime_data.get('score','—')), "animeepisodes": str(anime_data.get('episodes','—')), "animestatus": anime_data.get('status','—'), "animeyear": str(anime_data.get('year','—')), "animegenres": ', '.join(x['name'] for x in anime_data.get('genres',[])), "animestudios": ', '.join(x['name'] for x in anime_data.get('studios',[])), "animerating": anime_data.get('rating','—'), "animesynopsis": (anime_data.get('synopsis') or '—')[:3000]}
                return await e.edit(f"🎌 <b>{h_escape(anime_data.get('title', argument))}</b>\n{h_escape(anime_fields.get(command_name, '—'))}", parse_mode="html", link_preview=False)
            if command_name in ['randomactivity', 'randomjoke2', 'randomadvice2', 'randomfact2', 'randomquote2', 'chucknorris', 'dogfact', 'catfact', 'agify', 'genderize']:
                if command_name == 'randomactivity': data = await _get_json('https://www.boredapi.com/api/activity'); text = data.get('activity','—')
                elif command_name == 'randomjoke2': data = await _get_json('https://official-joke-api.appspot.com/random_joke'); text = f"{data.get('setup','')} — {data.get('punchline','')}"
                elif command_name == 'randomadvice2': data = await _get_json('https://api.adviceslip.com/advice'); text = data.get('slip',{}).get('advice','—')
                elif command_name == 'randomfact2': data = await _get_json('https://uselessfacts.jsph.pl/api/v2/facts/random'); text = data.get('text','—')
                elif command_name == 'randomquote2': data = await _get_json('https://dummyjson.com/quotes/random'); text = f"{data.get('quote','—')} — {data.get('author','')}"
                elif command_name == 'chucknorris': data = await _get_json('https://api.chucknorris.io/jokes/random'); text = data.get('value','—')
                elif command_name == 'dogfact': data = await _get_json('https://dogapi.dog/api/v2/facts'); text = data.get('data',[{'attributes':{}}])[0]['attributes'].get('body','—')
                elif command_name == 'catfact': data = await _get_json('https://catfact.ninja/fact'); text = data.get('fact','—')
                elif command_name == 'agify': data = await _get_json(f"https://api.agify.io?name={urllib.parse.quote(argument or 'Ali')}"); text = f"{data.get('name')}: {data.get('age')}"
                else: data = await _get_json(f"https://api.genderize.io?name={urllib.parse.quote(argument or 'Ali')}"); text = f"{data.get('name')}: {data.get('gender')} ({data.get('probability')})"
                return await e.edit(f"✨ {h_escape(str(text))}", parse_mode="html")
            animal_urls = {'randomcat2':'https://api.thecatapi.com/v1/images/search','randomdog2':'https://dog.ceo/api/breeds/image/random','randomfox2':'https://randomfox.ca/floof/','randomduck2':'https://random-d.uk/api/v2/random','randomwaifu2':'https://api.waifu.pics/sfw/waifu','randomneko':'https://api.waifu.pics/sfw/neko','randomhug':'https://api.waifu.pics/sfw/hug','randomwink':'https://api.waifu.pics/sfw/wink','randompat':'https://api.waifu.pics/sfw/pat','randomsmile':'https://api.waifu.pics/sfw/smile'}
            api_data = await _get_json(animal_urls[command_name])
            if command_name == 'randomcat2': media_url = api_data[0]['url']
            elif command_name == 'randomdog2': media_url = api_data['message']
            elif command_name == 'randomfox2': media_url = api_data['image']
            else: media_url = api_data['url']
            return await _send_media(e, url=media_url, filename=command_name)
        except Exception as error:
            await e.edit(f"❌ <b>{h_escape(command_name)}</b>: {h_escape(str(error))}", parse_mode="html")

    def _make_extra_handler(command_name):
        async def handler(event):
            await _extra_handler(event, command_name)
        return handler

    for extra_command in EXTRA_COMMANDS:
        bot.add_event_handler(_make_extra_handler(extra_command), cmd(extra_command))

    @bot.on(cmd("helpplus"))
    async def _helpplus(e):
        raw_page = e.pattern_match.group(1)
        try: page = max(1, int(raw_page or "1"))
        except ValueError: page = 1
        per_page = 30
        pages = math.ceil(len(EXTRA_COMMANDS) / per_page)
        page = min(page, pages)
        commands_page = EXTRA_COMMANDS[(page - 1) * per_page:page * per_page]
        lines = [f"<code>.{name}</code>" for name in commands_page]
        await e.edit(f"🚀 <b>Əlavə 150 API/Fun əmri</b> — {page}/{pages}\n\n" + " · ".join(lines) + f"\n\nSəhifə: <code>.helpplus {page + 1 if page < pages else 1}</code>", parse_mode="html")

    # ============================================================
    # HELP
    # ============================================================
    # Komandaları kateqoriyalar üzrə qruplama (səliqəli .helppack üçün)
    HELP_GROUPS = [
        ("🔧 Utility", [
            "ping","alive","id","info","whois","del","purge","type","echo","calc",
            "base64enc","base64dec","md5","sha1","sha256","reverse","upper","lower",
            "count","wc","time","date","weekday","timer","remind","uptime","sysinfo",
            "speed","pyver","pip",
        ]),
        ("🌐 API", [
            "weather","translate","wiki","urban","dictionary","ip","qr","short","expand",
            "github","ghrepo","gen","cat","dog","fox","duck","meme","joke","quote",
            "advice","fact","bored","pokedex","exchange","crypto","covid","country",
            "ipinfo","news","movie","anime","manga","waifu","lyric","youtube","ytdl",
            "ytmp3","ytmp4","img","screenshot","domain","dns","ssl","mac","iban",
            "phone","carbon","paste","gist",
        ]),
        ("🎮 Fun", [
            "dice","coin","choose","8ball","love","ship","slot","roll","number","rps",
            "flip","small","bold","italic","mono","strike","spoiler","mock","zalgo",
            "owo","clap","remoji","ascii","figlet","catface","shrug","tableflip",
            "unflip","lenny","disapp","piglatin","morse","unmorse","binary","unbinary",
            "rot13","caesar","atbash","leet","spaces",
        ]),
        ("👥 Group / Chat", [
            "afk","unafk","tag","tagall","admins","members","bots","delusers",
            "promote","demote","ban","unban","kick","mute","unmute","pin","unpin",
            "lock","unlock","title","setbio","setname","setpic","save","dl","ul",
            "copy","forward","read","stats",
        ]),
        ("🚀 Extra (150)", sorted(EXTRA_COMMANDS)),
    ]

    @bot.on(cmd("helppack", r"(?:\s+(\S+))?$"))
    async def _help(e):
        query = (e.pattern_match.group(1) or "").strip().lower()
        # Kateqoriya seçimi: .helppack utility / api / fun / group / extra
        cat_alias = {"utility":0,"util":0,"u":0,"api":1,"a":1,"fun":2,"f":2,
                     "group":3,"chat":3,"g":3,"extra":4,"e":4,"plus":4}
        if query in cat_alias:
            title, cmds = HELP_GROUPS[cat_alias[query]]
            chunks = [", ".join(f"<code>.{c}</code>" for c in cmds[i:i+8]) for i in range(0, len(cmds), 8)]
            return await e.edit(
                f"📂 <b>{title}</b> — {len(cmds)} kommand\n\n" + "\n".join(chunks),
                parse_mode="html", link_preview=False,
            )
        # Default: bütün qruplar qısaldılmış formada
        lines = ["✨ <b>RYHAVEAN PACK v4.1</b> — Komandalar siyahısı\n"]
        total = 0
        for title, cmds in HELP_GROUPS:
            total += len(cmds)
            lines.append(f"\n{title} <i>({len(cmds)})</i>")
            # 8 kommand sətirdə
            for i in range(0, len(cmds), 8):
                lines.append("  " + " ".join(f"<code>.{c}</code>" for c in cmds[i:i+8]))
        lines.append(
            f"\n📊 <b>Cəmi:</b> <code>{total}</code> kommand"
            f"\n💡 Detalı: <code>.helppack &lt;kateqoriya&gt;</code> "
            f"(<code>utility/api/fun/group/extra</code>)"
            f"\n💡 Hər kommandı arqumentsiz yazsanız info çıxır."
        )
        await e.edit("\n".join(lines), parse_mode="html", link_preview=False)

    log.info("✅ Ryhavean Pack v4.1 yükləndi (düzəlişli) — mövcud paket + 150 yeni komanda aktiv.")


# ============================================================
# Standalone test
# ============================================================
if __name__ == "__main__":
    print("Bu fayl .pinstall ryhavean_pack_v4 ilə userbot'a yüklənir.")
