from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import db
from config import settings
from render_api import RenderClient, RenderAPIError, slugify_service_name



def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class DeploymentState:
    telegram_id: int
    status: str = "idle"
    summary: str = ""
    started_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    service_id: str = ""
    service_url: str = ""
    logs: list[dict[str, str]] = field(default_factory=list)

    def add(self, level: str, message: str) -> None:
        self.updated_at = utcnow()
        self.logs.append(
            {
                "level": level,
                "message": message,
                "created_at": self.updated_at.isoformat(),
            }
        )
        self.logs = self.logs[-80:]


DEPLOYMENTS: dict[int, DeploymentState] = {}


async def _log(telegram_id: int, level: str, message: str) -> None:
    state = DEPLOYMENTS.setdefault(telegram_id, DeploymentState(telegram_id=telegram_id, status="queued"))
    state.add(level, message)
    await db.add_deployment_event(telegram_id, level, message)


async def get_state(telegram_id: int) -> dict[str, Any]:
    user = await db.get_user(telegram_id) or {}
    state = DEPLOYMENTS.get(telegram_id)
    recent_events = await db.list_recent_events(telegram_id, limit=30)
    logs = [
        {
            "level": item.get("level", "info"),
            "message": item.get("message", ""),
            "created_at": item.get("created_at").isoformat() if item.get("created_at") else "",
        }
        for item in recent_events
    ]
    return {
        "status": (state.status if state else user.get("deploy_status", "idle")) or "idle",
        "summary": (state.summary if state else user.get("deploy_summary", "")) or "",
        "service_id": (state.service_id if state else user.get("service_id", "")) or user.get("service_id", ""),
        "service_url": (state.service_url if state else user.get("service_url", "")) or user.get("service_url", ""),
        "logs": logs,
    }



def _extract_service_id(payload: dict[str, Any] | None) -> str:
    payload = payload or {}
    return str(
        payload.get("id")
        or payload.get("serviceId")
        or payload.get("service", {}).get("id")
        or payload.get("serviceDetails", {}).get("id")
        or ""
    ).strip()



def _resolve_service_id(user: dict[str, Any] | None, state: DeploymentState | None, fallback: str = "") -> str:
    state_service_id = str(getattr(state, "service_id", "") or "").strip()
    if state_service_id:
        return state_service_id
    user_service_id = str((user or {}).get("service_id", "") or "").strip()
    if user_service_id:
        return user_service_id
    return str(fallback or "").strip()



def build_env_vars(telegram_id: int, credentials: dict[str, Any], service_url: str = "") -> list[dict[str, str]]:
    app_base_url = credentials.get("app_base_url") or service_url
    values = {
        "API_ID": str(credentials["api_id"]),
        "API_HASH": credentials["api_hash"],
        "SESSION_STRING": credentials["session_string"],
        "MONGODB_URI": credentials.get("mongodb_uri") or settings.mongodb_uri,
        "MONGODB_DB": f"ryhavean_userbot_{telegram_id}",
        "OWNER_ID": str(telegram_id),
        "CMD_PREFIX": credentials.get("cmd_prefix", "."),
        "UPTIME_ENABLED": "1",
        "UPTIME_INTERVAL_SECONDS": "240",
        "APP_BASE_URL": app_base_url,
    }
    return [{"key": key, "value": value} for key, value in values.items() if value != ""]


async def _find_existing_service(
    client: RenderClient,
    *,
    owner_id: str,
    candidate_names: list[str],
) -> dict[str, Any] | None:
    normalized_names = {item.strip().lower() for item in candidate_names if item and item.strip()}
    if not normalized_names:
        return None

    for service_list in (await client.list_services(owner_id), await client.list_services()):
        for service in service_list:
            service_name = str(service.get("name", "")).strip().lower()
            if service_name and service_name in normalized_names:
                return service
    return None


async def ensure_service(telegram_id: int, requested_name: str | None = None) -> None:
    credentials = await db.get_decrypted_credentials(telegram_id)
    if not credentials:
        raise RuntimeError("Deploy üçün əvvəlcə məlumatlar saxlanmalıdır")

    user = await db.get_user(telegram_id)
    if not user:
        raise RuntimeError("İstifadəçi profili tapılmadı")

    state = DEPLOYMENTS[telegram_id] = DeploymentState(telegram_id=telegram_id, status="starting")
    await db.save_deploy_state(telegram_id, "starting", "Deploy başladıldı")
    await _log(telegram_id, "info", "Render workspace ID axtarılır")

    client = RenderClient(credentials["render_api_key"])
    owner_id = await client.resolve_owner_id(user.get("owner_id", ""))
    if not owner_id:
        raise RenderAPIError("Render workspace ID tapılmadı")

    base_name = requested_name or user.get("service_name") or f"{settings.service_name_prefix}-{telegram_id}"
    service_name = slugify_service_name(base_name, f"{settings.service_name_prefix}-{telegram_id}")
    env_vars = build_env_vars(telegram_id, credentials, user.get("service_url", ""))

    existing_service_id = str(user.get("service_id", "") or "").strip()
    existing_service: dict[str, Any] | None = None

    if existing_service_id:
        try:
            existing_service = await client.get_service(existing_service_id)
            await _log(telegram_id, "info", f"Mövcud service ID tapıldı: {existing_service_id}")
        except RenderAPIError:
            await _log(telegram_id, "warning", "Yadda qalan service ID işləmədi, ad ilə fallback axtarışı edilir")

    if existing_service is None:
        existing_service = await _find_existing_service(
            client,
            owner_id=owner_id,
            candidate_names=[service_name, user.get("service_name", "")],
        )
        if existing_service:
            existing_service_id = str(existing_service.get("id", "") or "").strip()
            await _log(telegram_id, "info", f"Service ad ilə tapıldı: {existing_service.get('name', service_name)}")

    service_payload: dict[str, Any]

    if existing_service_id:
        state.service_id = existing_service_id
        await _log(telegram_id, "info", "Service mövcuddur, env-lər yenilənir və deploy başladılır")
        await client.replace_env_vars(existing_service_id, env_vars)
        deploy = await client.trigger_deploy(existing_service_id)
        service_payload = await client.get_service(existing_service_id)
        service_url = service_payload.get("serviceDetails", {}).get("url", "") or user.get("service_url", "")
        state.service_url = service_url
        await db.save_service_info(
            telegram_id,
            service_id=existing_service_id,
            service_name=service_payload.get("name", service_name),
            service_url=service_url,
            owner_id=owner_id,
            latest_deploy_id=deploy.get("id", ""),
        )
        await _log(telegram_id, "success", "Service yeniləndi və deploy başladı")
    else:
        await _log(telegram_id, "info", f"Yeni Render service yaradılır: {service_name}")
        service_payload = await client.create_service(owner_id=owner_id, service_name=service_name, env_vars=env_vars)
        service_id = _extract_service_id(service_payload)
        service_url = service_payload.get("serviceDetails", {}).get("url", "") or service_payload.get("url", "") or ""
        state.service_id = service_id
        state.service_url = service_url
        await db.save_service_info(
            telegram_id,
            service_id=service_id,
            service_name=service_payload.get("name", service_name),
            service_url=service_url,
            owner_id=owner_id,
            latest_deploy_id=service_payload.get("suspendedDeploy", {}).get("id", "") or service_payload.get("deploy", {}).get("id", ""),
        )
        await _log(telegram_id, "success", "Service yaradıldı")

async def watch_service(telegram_id: int, client: RenderClient, service_id: str = "") -> None:
    user = await db.get_user(telegram_id) or {}

    state = DEPLOYMENTS.get(telegram_id)

    # SAFE fallback
    if not service_id:
        service_id = _resolve_service_id(user, state)

    if not service_id:
        raise RuntimeError("Service ID tapılmadı")

    owner_id = user.get("owner_id", "")
    max_rounds = 60
    last_status = ""

    state = DEPLOYMENTS.setdefault(
        telegram_id,
        DeploymentState(telegram_id=telegram_id, status="deploying")
    )

    state.service_id = service_id

    for _ in range(max_rounds):
        service = await client.get_service(service_id)

        state = DEPLOYMENTS.setdefault(
            telegram_id,
            DeploymentState(telegram_id=telegram_id, status="deploying")
        )

        state.service_id = service_id
        state.service_url = (
            service.get("serviceDetails", {}).get("url", "")
            or user.get("service_url", "")
            or ""
        )

        deploys = await client.list_deploys(service_id, limit=1)
        deploy = deploys[0] if deploys else {}

        status = (
            deploy.get("status")
            or service.get("serviceDetails", {}).get("buildStatus")
            or service.get("serviceDetails", {}).get("deployStatus")
            or service.get("suspended")
            or "unknown"
        )

        status_text = str(status)

        if status_text != last_status:
            last_status = status_text
            await _log(telegram_id, "info", f"Cari status: {status_text}")

        normalized = status_text.lower()

        if any(word in normalized for word in ("live", "running", "deployed", "success")):
            state.status = "live"
            state.summary = "Deploy uğurla tamamlandı"

            await db.save_deploy_state(telegram_id, "live", state.summary)

            await db.save_service_info(
                telegram_id,
                service_id=service_id,
                service_name=service.get("name", user.get("service_name", "")),
                service_url=state.service_url,
                owner_id=user.get("owner_id", "") or owner_id,
                latest_deploy_id=deploy.get("id", ""),
            )

            await _log(telegram_id, "success", "Userbot servis hazırdır")
            return

        if any(word in normalized for word in ("failed", "canceled", "cancelled")):
            state.status = "failed"
            state.summary = f"Deploy alınmadı: {status_text}"

            await db.save_deploy_state(telegram_id, "failed", state.summary)
            await _log(telegram_id, "error", state.summary)
            return

        state.status = "deploying"
        state.summary = f"Deploy davam edir: {status_text}"

        await db.save_deploy_state(telegram_id, "deploying", state.summary)

        await asyncio.sleep(settings.poll_interval_seconds)

    state = DEPLOYMENTS.setdefault(
        telegram_id,
        DeploymentState(telegram_id=telegram_id)
    )

    state.status = "pending"
    state.summary = "Render build hələ davam edir, sonra statusu yenilə"

    await db.save_deploy_state(telegram_id, "pending", state.summary)
    await _log(telegram_id, "warning", state.summary)
