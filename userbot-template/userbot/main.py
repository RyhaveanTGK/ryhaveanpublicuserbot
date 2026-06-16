"""Ryhavean Userbot - Render üçün yüngül web service entrypoint."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager, suppress

import emoji_utils  # noqa: F401
import httpx
import uvicorn
from fastapi import FastAPI
from telethon import TelegramClient
from telethon.sessions import StringSession

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


def _install_extra_emoji_patches():
    if getattr(TelegramClient, "_raven_extra_emoji_patch", False):
        return

    injector = getattr(emoji_utils, "_inject_entities", None)
    if injector is None:
        return

    base_send_message = getattr(emoji_utils, "_orig_send_message", TelegramClient.send_message)
    base_send_file = TelegramClient.send_file
    base_edit_message = TelegramClient.edit_message

    def _prepare_text_payload(raw_text: str | None, kwargs: dict):
        if not isinstance(raw_text, str):
            return raw_text, kwargs
        parse_mode = kwargs.pop("parse_mode", None)
        base_entities = kwargs.pop("formatting_entities", None) or kwargs.pop("entities", None)
        text, entities = injector(raw_text, base_entities, parse_mode)
        kwargs["formatting_entities"] = entities
        return text, kwargs

    async def _patched_send_message(self, entity, message="", *args, **kwargs):
        message, kwargs = _prepare_text_payload(message, kwargs)
        return await base_send_message(self, entity, message, *args, **kwargs)

    async def _patched_send_file(self, entity, file, *args, **kwargs):
        caption = kwargs.get("caption")
        caption, kwargs = _prepare_text_payload(caption, kwargs)
        kwargs["caption"] = caption
        return await base_send_file(self, entity, file, *args, **kwargs)

    async def _patched_edit_message(self, entity, message=None, text=None, *args, **kwargs):
        if isinstance(text, str):
            text, kwargs = _prepare_text_payload(text, kwargs)
        return await base_edit_message(self, entity, message, text=text, *args, **kwargs)

    TelegramClient.send_message = _patched_send_message
    TelegramClient.send_file = _patched_send_file
    TelegramClient.edit_message = _patched_edit_message
    TelegramClient._raven_extra_emoji_patch = True


_install_extra_emoji_patches()


def get_session_string() -> str:
    raw = Config.SESSION_STRING
    if not raw:
        log.critical("SESSION_STRING env yoxdur")
        sys.exit(1)
    if raw.startswith("enc:"):
        try:
            return security.decrypt(raw[4:])
        except Exception as exc:
            log.critical("Session deşifrə xətası: %s", exc)
            sys.exit(1)
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


async def start_userbot():
    global tg_client
    if not Config.API_ID or not Config.API_HASH:
        raise RuntimeError("API_ID və API_HASH env-ləri tələb olunur")

    await db.init_db()
    tg_client = TelegramClient(
        StringSession(get_session_string()),
        Config.API_ID,
        Config.API_HASH,
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

    await tg_client.run_until_disconnected()


async def _userbot_runner():
    try:
        await start_userbot()
    except Exception:
        log.exception("Userbot kritik xəta")
        os._exit(1)


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


app = FastAPI(title="Ryhavean Userbot", version="2.2.0", lifespan=lifespan)
from fastapi.responses import PlainTextResponse



@app.api_route("/uptime", methods=["GET", "HEAD"])
async def uptime():
    return PlainTextResponse("ok")





@app.get("/health")
async def health():
    return {"status": "healthy" if tg_client and tg_client.is_connected() else "starting"}





if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
