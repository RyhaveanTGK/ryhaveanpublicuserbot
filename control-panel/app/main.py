from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from telethon import TelegramClient
from telethon.errors import PhoneCodeExpiredError, PhoneCodeInvalidError, SessionPasswordNeededError
from telethon.sessions import StringSession

import db
from bot import start_bot_polling, stop_bot_polling
from deployment import DEPLOYMENTS, ensure_service, get_state
from schemas import (
    CredentialPayload,
    DeployRequest,
    InitDataRequest,
    ProfileResponse,
    TelegramCodeRequest,
    TelegramVerifyCodeRequest,
)
from telegram_auth import TelegramAuthError, validate_init_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("ryhavean.panel")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
PHONE_RE = re.compile(r"^\+[1-9]\d{6,14}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await db.connect_db()
    except Exception as e:
        log.error(f"DB error: {e}")

    try:
        await start_bot_polling()
    except Exception as e:
        log.error(f"Bot error: {e}")

    yield

    try:
        await stop_bot_polling()
        await db.close_db()
    except Exception:
        pass


app = FastAPI(title="Ryhavean Control Panel", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.api_route("/health", methods=["GET", "HEAD"], response_class=PlainTextResponse)
def health():
    return PlainTextResponse("ok", headers={"Cache-Control": "no-store"})



def _extract_user(init_data: str) -> dict:
    try:
        auth = validate_init_data(init_data)
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return auth["user"]



def _normalize_phone_number(phone_number: str) -> str:
    phone = re.sub(r"[^\d+]", "", (phone_number or "").strip())
    if phone.startswith("00"):
        phone = f"+{phone[2:]}"
    if not PHONE_RE.fullmatch(phone):
        raise HTTPException(status_code=400, detail="Telefon nömrəsini ölkə kodu ilə daxil et. Nümunə: +994501234567")
    return phone



def _build_auth_client(api_id: int, api_hash: str, session_string: str = "") -> TelegramClient:
    return TelegramClient(
        StringSession(session_string),
        api_id,
        api_hash,
        device_model="Ryhavean Panel Auth",
        system_version="webapp",
        app_version="2.0.0",
    )


def _normalize_telegram_code(code: str) -> str:
    normalized = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(normalized) < 3:
        raise HTTPException(status_code=400, detail="Telegram kodunu düzgün daxil et")
    return normalized


@app.post("/api/profile", response_model=ProfileResponse)
async def api_profile(payload: InitDataRequest):
    user = _extract_user(payload.init_data)
    await db.upsert_user_identity(user)
    doc = await db.get_user(int(user["id"])) or {}
    return ProfileResponse(
        telegram_id=int(user["id"]),
        first_name=doc.get("first_name", user.get("first_name", "")),
        username=doc.get("username", user.get("username", "")),
        has_credentials=bool(doc.get("credentials")),
        service_id=doc.get("service_id", ""),
        service_name=doc.get("service_name", ""),
        service_url=doc.get("service_url", ""),
        deploy_status=doc.get("deploy_status", "idle"),
    )


@app.post("/api/telegram/send-code")
async def api_send_telegram_code(payload: TelegramCodeRequest):
    user = _extract_user(payload.init_data)
    telegram_id = int(user["id"])
    await db.upsert_user_identity(user)

    phone_number = _normalize_phone_number(payload.phone_number)
    client = _build_auth_client(payload.api_id, payload.api_hash)
    try:
        await client.connect()
        sent = await client.send_code_request(phone_number)
        await db.save_phone_login_session(
            telegram_id,
            api_id=payload.api_id,
            api_hash=payload.api_hash,
            phone_number=phone_number,
            phone_code_hash=sent.phone_code_hash,
            auth_session=client.session.save(),
        )
        return {"ok": True, "message": "Telegram kodu göndərildi"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Kod göndərilmədi: {exc}") from exc
    finally:
        await client.disconnect()


@app.post("/api/telegram/verify-code")
async def api_verify_telegram_code(payload: TelegramVerifyCodeRequest):
    user = _extract_user(payload.init_data)
    telegram_id = int(user["id"])
    await db.upsert_user_identity(user)

    auth_state = await db.get_phone_login_session(telegram_id)
    if not auth_state:
        raise HTTPException(status_code=400, detail="Əvvəlcə kod göndərilməlidir")

    client = _build_auth_client(auth_state["api_id"], auth_state["api_hash"], auth_state.get("auth_session", ""))
    try:
        await client.connect()
        try:
            await client.sign_in(
                phone=auth_state["phone_number"],
                code=_normalize_telegram_code(payload.code),
                phone_code_hash=auth_state["phone_code_hash"],
            )
        except SessionPasswordNeededError:
            if not payload.password:
                return JSONResponse(
                    status_code=409,
                    content={
                        "ok": False,
                        "password_required": True,
                        "message": "Bu hesab üçün 2 mərhələli şifrə tələb olunur",
                    },
                )
            await client.sign_in(password=payload.password)
        except PhoneCodeInvalidError as exc:
            raise HTTPException(status_code=400, detail="Daxil edilən kod yanlışdır") from exc
        except PhoneCodeExpiredError as exc:
            raise HTTPException(status_code=400, detail="Kodun vaxtı bitib, yenidən kod göndər") from exc

        me = await client.get_me()
        session_string = client.session.save()
        await db.clear_phone_login_session(telegram_id)
        return {
            "ok": True,
            "message": "StringSession uğurla yaradıldı",
            "session_string": session_string,
            "account": {
                "id": me.id,
                "first_name": me.first_name or "",
                "username": me.username or "",
                "phone": auth_state["phone_number"],
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"StringSession yaradılmadı: {exc}") from exc
    finally:
        await client.disconnect()


@app.post("/api/save-credentials")
async def api_save_credentials(payload: CredentialPayload):
    user = _extract_user(payload.init_data)
    await db.upsert_user_identity(user)
    await db.save_credentials(
        int(user["id"]),
        render_api_key=payload.render_api_key,
        api_id=payload.api_id,
        api_hash=payload.api_hash,
        session_string=payload.session_string,
        mongodb_uri=payload.mongodb_uri,
        cmd_prefix=payload.cmd_prefix,
        app_base_url=payload.app_base_url,
    )
    await db.add_deployment_event(int(user["id"]), "success", "Məlumatlar MongoDB-də ayrıca saxlanıldı")
    return {"ok": True, "message": "Məlumatlar uğurla yadda saxlandı"}


@app.post("/api/deploy")
async def api_deploy(payload: DeployRequest):
    user = _extract_user(payload.init_data)
    telegram_id = int(user["id"])
    profile = await db.get_user(telegram_id)
    if not profile or not profile.get("credentials"):
        raise HTTPException(status_code=400, detail="Əvvəlcə məlumatları yadda saxla")

    state = DEPLOYMENTS.get(telegram_id)
    if state and state.status in {"starting", "deploying"}:
        return {"ok": True, "message": "Deploy artıq davam edir"}

    async def runner() -> None:
        try:
            await ensure_service(telegram_id, payload.service_name)
        except Exception as exc:
            await db.save_deploy_state(telegram_id, "failed", str(exc))
            await db.add_deployment_event(telegram_id, "error", f"Deploy xətası: {exc}")
            current = DEPLOYMENTS.get(telegram_id)
            if current:
                current.status = "failed"
                current.summary = str(exc)
                current.add("error", f"Deploy xətası: {exc}")
            log.exception("Deploy alınmadı user=%s", telegram_id)

    asyncio.create_task(runner(), name=f"deploy-{telegram_id}")
    return {"ok": True, "message": "Deploy başladıldı"}


@app.post("/api/deploy-status")
async def api_deploy_status(payload: InitDataRequest):
    user = _extract_user(payload.init_data)
    await db.upsert_user_identity(user)
    return await get_state(int(user["id"]))
