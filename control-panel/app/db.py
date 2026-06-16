from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from config import settings
from crypto import decrypt_text, encrypt_text

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None
_LOGIN_SESSION_TTL_MINUTES = 15



def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def connect_db() -> None:
    global _client, _db
    if _db is not None:
        return
    _client = AsyncIOMotorClient(settings.mongodb_uri)
    _db = _client[settings.mongodb_db]
    await _db.users.create_index("telegram_id", unique=True)
    await _db.users.create_index("service_id")
    await _db.deployment_events.create_index([("telegram_id", 1), ("created_at", -1)])
    await _db.telegram_auth_sessions.create_index("telegram_id", unique=True)
    await _db.telegram_auth_sessions.create_index("expires_at", expireAfterSeconds=0)


async def close_db() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None



def database() -> AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("MongoDB connection hazır deyil")
    return _db


async def get_user(telegram_id: int) -> dict[str, Any] | None:
    return await database().users.find_one({"telegram_id": telegram_id})


async def upsert_user_identity(user: dict[str, Any]) -> None:
    await database().users.update_one(
        {"telegram_id": int(user["id"])},
        {
            "$set": {
                "telegram_id": int(user["id"]),
                "first_name": user.get("first_name", ""),
                "last_name": user.get("last_name", ""),
                "username": user.get("username", ""),
                "language_code": user.get("language_code", ""),
                "is_premium": bool(user.get("is_premium", False)),
                "updated_at": utcnow(),
            },
            "$setOnInsert": {"created_at": utcnow()},
        },
        upsert=True,
    )


async def save_credentials(
    telegram_id: int,
    *,
    render_api_key: str,
    api_id: int,
    api_hash: str,
    session_string: str,
    mongodb_uri: str | None,
    cmd_prefix: str,
    app_base_url: str | None,
) -> None:
    await database().users.update_one(
        {"telegram_id": telegram_id},
        {
            "$set": {
                "credentials": {
                    "render_api_key": encrypt_text(render_api_key),
                    "api_id": int(api_id),
                    "api_hash": encrypt_text(api_hash),
                    "session_string": encrypt_text(session_string),
                    "mongodb_uri": encrypt_text(mongodb_uri or settings.mongodb_uri),
                    "cmd_prefix": cmd_prefix,
                    "app_base_url": app_base_url or "",
                    "saved_at": utcnow(),
                },
                "updated_at": utcnow(),
            }
        },
        upsert=True,
    )


async def get_decrypted_credentials(telegram_id: int) -> dict[str, Any] | None:
    user = await get_user(telegram_id)
    if not user or "credentials" not in user:
        return None
    credentials = user["credentials"]
    return {
        "render_api_key": decrypt_text(credentials.get("render_api_key")),
        "api_id": int(credentials.get("api_id", 0)),
        "api_hash": decrypt_text(credentials.get("api_hash")),
        "session_string": decrypt_text(credentials.get("session_string")),
        "mongodb_uri": decrypt_text(credentials.get("mongodb_uri")) if credentials.get("mongodb_uri") else settings.mongodb_uri,
        "cmd_prefix": credentials.get("cmd_prefix", "."),
        "app_base_url": credentials.get("app_base_url", ""),
    }


async def save_phone_login_session(
    telegram_id: int,
    *,
    api_id: int,
    api_hash: str,
    phone_number: str,
    phone_code_hash: str,
    auth_session: str,
) -> None:
    await database().telegram_auth_sessions.update_one(
        {"telegram_id": telegram_id},
        {
            "$set": {
                "telegram_id": telegram_id,
                "api_id": int(api_id),
                "api_hash": encrypt_text(api_hash),
                "phone_number": phone_number,
                "phone_code_hash": phone_code_hash,
                "auth_session": encrypt_text(auth_session),
                "created_at": utcnow(),
                "expires_at": utcnow() + timedelta(minutes=_LOGIN_SESSION_TTL_MINUTES),
            }
        },
        upsert=True,
    )


async def get_phone_login_session(telegram_id: int) -> dict[str, Any] | None:
    row = await database().telegram_auth_sessions.find_one({"telegram_id": telegram_id})
    if not row:
        return None
    return {
        "telegram_id": telegram_id,
        "api_id": int(row.get("api_id", 0)),
        "api_hash": decrypt_text(row.get("api_hash")),
        "phone_number": row.get("phone_number", ""),
        "phone_code_hash": row.get("phone_code_hash", ""),
        "auth_session": decrypt_text(row.get("auth_session")) if row.get("auth_session") else "",
        "expires_at": row.get("expires_at"),
    }


async def clear_phone_login_session(telegram_id: int) -> None:
    await database().telegram_auth_sessions.delete_one({"telegram_id": telegram_id})


async def save_service_info(
    telegram_id: int,
    *,
    service_id: str,
    service_name: str,
    service_url: str,
    owner_id: str,
    latest_deploy_id: str = "",
) -> None:
    await database().users.update_one(
        {"telegram_id": telegram_id},
        {
            "$set": {
                "service_id": service_id,
                "service_name": service_name,
                "service_url": service_url,
                "owner_id": owner_id,
                "latest_deploy_id": latest_deploy_id,
                "updated_at": utcnow(),
            }
        },
    )


async def save_deploy_state(telegram_id: int, state: str, summary: str = "") -> None:
    await database().users.update_one(
        {"telegram_id": telegram_id},
        {
            "$set": {
                "deploy_status": state,
                "deploy_summary": summary,
                "updated_at": utcnow(),
            }
        },
        upsert=True,
    )


async def add_deployment_event(telegram_id: int, level: str, message: str) -> None:
    await database().deployment_events.insert_one(
        {
            "telegram_id": telegram_id,
            "level": level,
            "message": message,
            "created_at": utcnow(),
        }
    )


async def list_recent_events(telegram_id: int, limit: int = 50) -> list[dict[str, Any]]:
    cursor = database().deployment_events.find({"telegram_id": telegram_id}).sort("created_at", -1).limit(limit)
    items = await cursor.to_list(length=limit)
    return list(reversed(items))
