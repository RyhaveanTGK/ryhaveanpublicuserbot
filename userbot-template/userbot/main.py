"""Ryhavean Userbot - Render üçün yüngül web service entrypoint."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

import emoji_utils  # noqa: F401
import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from telethon import TelegramClient
from telethon.tl.custom import Message
from telethon.sessions import StringSession
from telethon.tl.types import MessageEntityBold, MessageEntityCode, MessageEntityPre

from config import Config
import commands
import db
import plugin_loader
import quotly
import security

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("ryhavean")

tg_client: TelegramClient | None = None
keepalive_task: asyncio.Task | None = None
runtime_state = {"status": "booting", "summary": "Başlanır"}


HEALTH_HEADERS = {"Cache-Control": "no-store"}


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return default


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


async def _set_runtime_state(status: str, summary: str) -> None:
    runtime_state["status"] = status
    runtime_state["summary"] = summary
    try:
        await db.set_runtime_status(status, summary)
    except Exception as exc:
        log.debug("Runtime status yaddaşa yazılmadı: %s", exc)


def _utf16_len(value: str) -> int:
    return len((value or "").encode("utf-16-le")) // 2


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not ranges:
        return []
    ranges = sorted(ranges)
    merged = [list(ranges[0])]
    for start, end in ranges[1:]:
        last = merged[-1]
        if start <= last[1]:
            last[1] = max(last[1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def _build_auto_bold_entities(text: str, entities: list) -> list[MessageEntityBold]:
    total_length = _utf16_len(text)
    if total_length <= 0:
        return []

    excluded = []
    for entity in entities:
        if isinstance(entity, (MessageEntityCode, MessageEntityPre)):
            start = max(0, int(entity.offset))
            end = min(total_length, start + max(0, int(entity.length)))
            if end > start:
                excluded.append((start, end))

    excluded = _merge_ranges(excluded)
    bold_entities: list[MessageEntityBold] = []
    cursor = 0
    for start, end in excluded:
        if start > cursor:
            bold_entities.append(MessageEntityBold(offset=cursor, length=start - cursor))
        cursor = max(cursor, end)
    if cursor < total_length:
        bold_entities.append(MessageEntityBold(offset=cursor, length=total_length - cursor))
    return [entity for entity in bold_entities if entity.length > 0]


def _prepare_styled_payload(raw_text: str | None, kwargs: dict):
    if not isinstance(raw_text, str):
        return raw_text, kwargs

    parse_mode = kwargs.pop("parse_mode", None)
    base_entities = kwargs.pop("formatting_entities", None) or kwargs.pop("entities", None)
    parsed_text, combined_entities = emoji_utils.apply_premium_emojis(raw_text, base_entities, parse_mode)
    combined_entities = list(combined_entities or [])
    combined_entities.extend(_build_auto_bold_entities(parsed_text or "", combined_entities))
    kwargs["formatting_entities"] = combined_entities
    return parsed_text, kwargs


def _install_global_message_patches():
    if getattr(TelegramClient, "_ryhavean_global_style_patch", False):
        return

    base_send_message = TelegramClient.send_message
    base_send_file = TelegramClient.send_file
    base_edit_message = TelegramClient.edit_message
    base_message_edit = Message.edit
    base_message_reply = Message.reply
    base_message_respond = Message.respond

    async def _patched_send_message(self, entity, message="", *args, **kwargs):
        message, kwargs = _prepare_styled_payload(message, kwargs)
        return await base_send_message(self, entity, message, *args, **kwargs)

    async def _patched_send_file(self, entity, file, *args, **kwargs):
        caption = kwargs.get("caption")
        caption, kwargs = _prepare_styled_payload(caption, kwargs)
        kwargs["caption"] = caption
        return await base_send_file(self, entity, file, *args, **kwargs)

    async def _patched_edit_message(self, entity, message=None, text=None, *args, **kwargs):
        if isinstance(text, str):
            text, kwargs = _prepare_styled_payload(text, kwargs)
        elif isinstance(message, str):
            message, kwargs = _prepare_styled_payload(message, kwargs)
        return await base_edit_message(self, entity, message, text=text, *args, **kwargs)

    async def _patched_message_edit(self, text=None, *args, **kwargs):
        text, kwargs = _prepare_styled_payload(text, kwargs)
        return await base_message_edit(self, text, *args, **kwargs)

    async def _patched_message_reply(self, message=None, *args, **kwargs):
        message, kwargs = _prepare_styled_payload(message, kwargs)
        return await base_message_reply(self, message, *args, **kwargs)

    async def _patched_message_respond(self, message=None, *args, **kwargs):
        message, kwargs = _prepare_styled_payload(message, kwargs)
        return await base_message_respond(self, message, *args, **kwargs)

    TelegramClient.send_message = _patched_send_message
    TelegramClient.send_file = _patched_send_file
    TelegramClient.edit_message = _patched_edit_message
    Message.edit = _patched_message_edit
    Message.reply = _patched_message_reply
    Message.respond = _patched_message_respond
    TelegramClient._ryhavean_global_style_patch = True


_install_global_message_patches()


def get_session_string(raw_value: str | None = None) -> str:
    raw = _clean_text(raw_value or os.getenv("SESSION_STRING") or Config.SESSION_STRING)
    if not raw:
        log.error("SESSION_STRING tapılmadı")
        return ""
    if raw.startswith("enc:"):
        try:
            return security.decrypt(raw[4:])
        except Exception as exc:
            log.exception("Session deşifrə xətası: %s", exc)
            return ""
    return raw


def _resolve_keepalive_url() -> str:
    if Config.UPTIME_URL:
        return Config.UPTIME_URL
    if Config.APP_BASE_URL:
        return f"{Config.APP_BASE_URL}/uptime"
    return ""


async def _keepalive_loop(url: str):
    headers = {"User-Agent": Config.UPTIME_USER_AGENT}
    timeout = httpx.Timeout(20.0)
    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        while True:
            try:
                response = await client.get(url)
                log.info("Keepalive ping -> %s [%s]", url, response.status_code)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Keepalive ping xətası (%s): %s", url, exc)
            await asyncio.sleep(Config.UPTIME_INTERVAL_SECONDS)


def start_keepalive_task() -> asyncio.Task | None:
    global keepalive_task
    if not Config.UPTIME_ENABLED:
        log.info("ℹ️ Keepalive söndürülüb")
        return None

    url = _resolve_keepalive_url()
    if not url:
        log.info("ℹ️ Keepalive üçün APP_BASE_URL və ya UPTIME_URL təyin edilməyib")
        return None

    if keepalive_task and not keepalive_task.done():
        return keepalive_task

    log.info("🌐 Keepalive aktivdir: %s", url)
    keepalive_task = asyncio.create_task(_keepalive_loop(url), name="raven-keepalive")
    return keepalive_task


async def stop_keepalive_task():
    global keepalive_task
    if keepalive_task and not keepalive_task.done():
        keepalive_task.cancel()
        with suppress(asyncio.CancelledError):
            await keepalive_task
    keepalive_task = None


async def post_restart_notice(client):
    chat = os.getenv("RESTART_CHAT")
    mid = os.getenv("RESTART_MSG")
    if not chat or not mid:
        return
    try:
        await client.edit_message(int(chat), int(mid), "✅ <b>Restart tamamlandı</b>", parse_mode="html")
    except Exception:
        pass
    os.environ.pop("RESTART_CHAT", None)
    os.environ.pop("RESTART_MSG", None)


def _snapshot_runtime_config() -> dict[str, object]:
    return {
        "api_id": _safe_int(os.getenv("API_ID", str(Config.API_ID or 0)), 0),
        "api_hash": _clean_text(os.getenv("API_HASH", Config.API_HASH)),
        "session_string": _clean_text(os.getenv("SESSION_STRING", Config.SESSION_STRING)),
        "mongodb_uri": _clean_text(os.getenv("MONGODB_URI", Config.MONGODB_URI)),
        "mongodb_db": _clean_text(os.getenv("MONGODB_DB", Config.MONGODB_DB)) or "ryhavean_userbot",
        "plugin_mongodb_uri": _clean_text(os.getenv("PLUGIN_MONGODB_URI", Config.PLUGIN_MONGODB_URI)),
        "plugin_mongodb_db": _clean_text(os.getenv("PLUGIN_MONGODB_DB", Config.PLUGIN_MONGODB_DB)) or "ryhavean_shared_plugins",
        "owner_id": _safe_int(os.getenv("OWNER_ID", str(Config.OWNER_ID or 0)), 0),
        "cmd_prefix": _clean_text(os.getenv("CMD_PREFIX", Config.CMD_PREFIX)) or ".",
    }


def _apply_runtime_config(config_map: dict[str, object]) -> None:
    api_id = _safe_int(config_map.get("api_id"), 0)
    api_hash = _clean_text(config_map.get("api_hash"))
    session_string = _clean_text(config_map.get("session_string"))
    mongodb_uri = _clean_text(config_map.get("mongodb_uri"))
    mongodb_db = _clean_text(config_map.get("mongodb_db")) or "ryhavean_userbot"
    plugin_mongodb_uri = _clean_text(config_map.get("plugin_mongodb_uri")) or mongodb_uri
    plugin_mongodb_db = _clean_text(config_map.get("plugin_mongodb_db")) or "ryhavean_shared_plugins"
    owner_id = _safe_int(config_map.get("owner_id"), 0)
    cmd_prefix = _clean_text(config_map.get("cmd_prefix")) or "."

    if api_id > 0:
        os.environ["API_ID"] = str(api_id)
    if api_hash:
        os.environ["API_HASH"] = api_hash
    if session_string:
        os.environ["SESSION_STRING"] = session_string
    if mongodb_uri:
        os.environ["MONGODB_URI"] = mongodb_uri
    os.environ["MONGODB_DB"] = mongodb_db
    if plugin_mongodb_uri:
        os.environ["PLUGIN_MONGODB_URI"] = plugin_mongodb_uri
    os.environ["PLUGIN_MONGODB_DB"] = plugin_mongodb_db
    if owner_id > 0:
        os.environ["OWNER_ID"] = str(owner_id)
    os.environ["CMD_PREFIX"] = cmd_prefix

    Config.API_ID = api_id
    Config.API_HASH = api_hash
    Config.SESSION_STRING = session_string
    Config.MONGODB_URI = mongodb_uri
    Config.MONGODB_DB = mongodb_db
    Config.PLUGIN_MONGODB_URI = plugin_mongodb_uri
    Config.PLUGIN_MONGODB_DB = plugin_mongodb_db
    Config.OWNER_ID = owner_id
    Config.CMD_PREFIX = cmd_prefix


async def _resolve_runtime_config() -> tuple[dict[str, object], list[str], bool]:
    config_map = _snapshot_runtime_config()
    _apply_runtime_config(config_map)

    db_ready = await db.init_db()
    bootstrap = {}
    try:
        bootstrap = await db.get_bootstrap_config()
    except Exception as exc:
        log.debug("Bootstrap fallback oxunmadı: %s", exc)

    if bootstrap:
        if not _safe_int(config_map.get("api_id"), 0):
            config_map["api_id"] = _safe_int(bootstrap.get("api_id"), 0)
        if not _clean_text(config_map.get("api_hash")):
            config_map["api_hash"] = _clean_text(bootstrap.get("api_hash"))
        if not _clean_text(config_map.get("session_string")):
            config_map["session_string"] = _clean_text(bootstrap.get("session_string"))
        if not _clean_text(config_map.get("mongodb_uri")):
            config_map["mongodb_uri"] = _clean_text(bootstrap.get("mongodb_uri"))
        if not _safe_int(config_map.get("owner_id"), 0):
            config_map["owner_id"] = _safe_int(bootstrap.get("owner_id"), 0)
        if not _clean_text(config_map.get("cmd_prefix")):
            config_map["cmd_prefix"] = _clean_text(bootstrap.get("cmd_prefix")) or "."
        if not _clean_text(config_map.get("mongodb_db")):
            config_map["mongodb_db"] = _clean_text(bootstrap.get("mongodb_db")) or "ryhavean_userbot"

    _apply_runtime_config(config_map)

    missing = []
    if _safe_int(config_map.get("api_id"), 0) <= 0:
        missing.append("API_ID")
    if not _clean_text(config_map.get("api_hash")):
        missing.append("API_HASH")
    if not _clean_text(config_map.get("session_string")):
        missing.append("SESSION_STRING")
    if not _clean_text(config_map.get("mongodb_uri")):
        missing.append("MONGODB_URI")

    if not missing:
        try:
            await db.save_bootstrap_config(config_map)
        except Exception as exc:
            log.debug("Bootstrap config saxlanmadı: %s", exc)

    return config_map, missing, db_ready


async def start_userbot() -> bool:
    global tg_client

    max_attempts = max(1, Config.STARTUP_MAX_RETRIES)
    delay_seconds = max(2, Config.STARTUP_RETRY_DELAY_SECONDS)
    last_summary = ""

    for attempt in range(1, max_attempts + 1):
        config_map, missing, db_ready = await _resolve_runtime_config()
        session_string = get_session_string(_clean_text(config_map.get("session_string")))
        if not session_string and "SESSION_STRING" not in missing:
            missing.append("SESSION_STRING")

        if missing:
            last_summary = f"Çatışmayan konfiqurasiya: {', '.join(missing)}"
            log.error("%s", last_summary)
            if not db_ready:
                log.warning("DB fallback hazır deyil; cəhd %s/%s", attempt, max_attempts)
            await _set_runtime_state("missing_env", last_summary)
            if attempt < max_attempts:
                await asyncio.sleep(delay_seconds)
                continue
            log.warning("Userbot graceful stop: startup konfiqurasiyası tamamlanmadı")
            return False

        try:
            await _set_runtime_state("starting", f"Userbot başladılır ({attempt}/{max_attempts})")
            tg_client = TelegramClient(
                StringSession(session_string),
                _safe_int(config_map.get("api_id"), 0),
                _clean_text(config_map.get("api_hash")),
                device_model="Ryhavean Userbot",
                system_version="render",
                app_version="2.0.0",
            )
            await tg_client.start()
            me = await tg_client.get_me()
            log.info("✅ Daxil oldu: %s (@%s) id=%s", me.first_name, me.username, me.id)

            commands.register(tg_client)
            quotly.register_quotly(tg_client, CMD_PREFIX=Config.CMD_PREFIX)
            await plugin_loader.load_all(tg_client)
            await plugin_loader.start_background_sync(tg_client)
            await post_restart_notice(tg_client)

            if Config.LOG_TO_SAVED:
                try:
                    await tg_client.send_message(
                        "me",
                        "✨ <b>Ryhavean Userbot Come Back</b>",
                        parse_mode="html",
                    )
                except Exception:
                    pass

            await _set_runtime_state("live", "Userbot aktivdir")
            await tg_client.run_until_disconnected()
            await _set_runtime_state("stopped", "Userbot dayandırıldı")
            return True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            last_summary = f"Userbot start xətası: {exc}"
            log.exception("Userbot start alınmadı (%s/%s)", attempt, max_attempts)
            await _set_runtime_state("startup_error", last_summary)
            if tg_client and tg_client.is_connected():
                with suppress(Exception):
                    await tg_client.disconnect()
            tg_client = None
            if attempt < max_attempts:
                await asyncio.sleep(delay_seconds)
                continue

    await _set_runtime_state("startup_error", last_summary or "Userbot start alınmadı")
    log.warning("Userbot graceful stop: maksimum startup cəhdləri bitdi")
    return False


async def _userbot_runner():
    try:
        started = await start_userbot()
        if not started:
            log.warning("Userbot prosesindən təhlükəsiz çıxış edildi")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.exception("Userbot kritik xəta")
        await _set_runtime_state("startup_error", f"Kritik xəta: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    userbot_task = asyncio.create_task(_userbot_runner(), name="raven-userbot")
    start_keepalive_task()
    try:
        yield
    finally:
        plugin_loader.stop_background_sync()
        await stop_keepalive_task()
        userbot_task.cancel()
        with suppress(asyncio.CancelledError):
            await userbot_task
        if tg_client and tg_client.is_connected():
            await tg_client.disconnect()
        await db.close_db()


app = FastAPI(title="Ryhavean Userbot", version="2.4.0", lifespan=lifespan)


@app.api_route("/uptime", methods=["GET", "HEAD"], response_class=PlainTextResponse)
def uptime():
    return PlainTextResponse("ok", headers=HEALTH_HEADERS)


@app.api_route("/health", methods=["GET", "HEAD"], response_class=PlainTextResponse)
def health():
    return PlainTextResponse(runtime_state.get("status", "ok"), headers=HEALTH_HEADERS)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
