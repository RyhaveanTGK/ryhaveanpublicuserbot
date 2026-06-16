from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import db
from bot import start_bot_polling, stop_bot_polling
from deployment import DEPLOYMENTS, ensure_service, get_state
from schemas import CredentialPayload, DeployRequest, InitDataRequest, ProfileResponse
from telegram_auth import TelegramAuthError, validate_init_data

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("ryhavean.panel")

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"


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


app = FastAPI(title="Ryhavean Control Panel", version="1.0.0", lifespan=lifespan)
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


@app.get("/health")
async def health():
    return {"status": "ok"}


def _extract_user(init_data: str) -> dict:
    try:
        auth = validate_init_data(init_data)
    except TelegramAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return auth["user"]


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
