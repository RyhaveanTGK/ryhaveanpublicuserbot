"""MongoDB əsaslı persistent state manager."""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from config import Config

log = logging.getLogger("db")


@dataclass(slots=True)
class CloneSnapshot:
    user_id: int
    original_first: str
    original_last: str
    original_bio: str
    original_photo: bytes


_client: AsyncIOMotorClient | None = None
_database: AsyncIOMotorDatabase | None = None

_settings: dict[str, str] = {}
_welcomes: dict[tuple[int, int], str] = {}
_clones: dict[int, CloneSnapshot] = {}
_blocks: set[int] = set()


def _owner_scope() -> int:
    return Config.OWNER_ID or 0


def _mongo_enabled() -> bool:
    return _database is not None


def _photo_to_text(photo: bytes) -> str:
    if not photo:
        return ""
    return base64.b64encode(photo).decode("ascii")


def _photo_from_text(photo_text: str | None) -> bytes:
    if not photo_text:
        return b""
    try:
        return base64.b64decode(photo_text.encode("ascii"))
    except Exception:
        return b""


async def _ensure_indexes() -> None:
    # FIX: proper None check (NO truth value testing)
    if _database is None:
        return

    await _database.settings.create_index(
        [("owner_scope", 1), ("key", 1)],
        unique=True,
    )

    await _database.welcomes.create_index(
        [("owner_scope", 1), ("chat_id", 1)],
        unique=True,
    )

    await _database.clones.create_index(
        [("owner_scope", 1), ("user_id", 1)],
        unique=True,
    )

    await _database.blocks.create_index(
        [("owner_scope", 1), ("user_id", 1)],
        unique=True,
    )


async def init_db():
    global _client, _database

    if _database is not None:
        return True

    if not Config.MONGODB_URI:
        log.warning("MONGODB_URI env tapılmadı, in-memory mode aktivdir")
        return True

    try:
        _client = AsyncIOMotorClient(
            Config.MONGODB_URI,
            serverSelectionTimeoutMS=10000,
            connectTimeoutMS=10000,
            socketTimeoutMS=10000,
            retryWrites=True,
        )

        await _client.admin.command("ping")

        _database = _client[Config.MONGODB_DB]

        await _ensure_indexes()

        log.info("✅ MongoDB qoşuldu: db=%s", Config.MONGODB_DB)
        return True

    except Exception as exc:
        log.exception("MongoDB bağlantı xətası")

        _database = None

        if _client is not None:
            _client.close()

        _client = None

        raise RuntimeError(f"MongoDB bağlantısı alınmadı: {exc}") from exc


async def close_db():
    global _client, _database

    if _client is not None:
        _client.close()

    _client = None
    _database = None


def pool():
    if not _mongo_enabled():
        raise RuntimeError("MongoDB aktiv deyil")
    return _database


async def set_setting(key: str, value: str):
    owner_scope = _owner_scope()

    if _mongo_enabled():
        await _database.settings.update_one(
            {"owner_scope": owner_scope, "key": key},
            {"$set": {"value": value}},
            upsert=True,
        )
        return

    _settings[key] = value


async def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    owner_scope = _owner_scope()

    if _mongo_enabled():
        row = await _database.settings.find_one(
            {"owner_scope": owner_scope, "key": key}
        )
        if row is None:
            return default
        return row.get("value", default)

    return _settings.get(key, default)


async def save_welcome(chat_id: int, message: str):
    owner_scope = _owner_scope()

    if _mongo_enabled():
        await _database.welcomes.update_one(
            {"owner_scope": owner_scope, "chat_id": chat_id},
            {"$set": {"message": message}},
            upsert=True,
        )
        return

    _welcomes[(owner_scope, chat_id)] = message


async def get_welcome(chat_id: int) -> Optional[str]:
    owner_scope = _owner_scope()

    if _mongo_enabled():
        row = await _database.welcomes.find_one(
            {"owner_scope": owner_scope, "chat_id": chat_id}
        )
        return row.get("message") if row else None

    return _welcomes.get((owner_scope, chat_id))


async def save_clone(
    user_id: int,
    original_first: str,
    original_last: str,
    original_bio: str,
    original_photo: bytes,
):
    owner_scope = _owner_scope()

    snapshot = CloneSnapshot(
        user_id=user_id,
        original_first=original_first,
        original_last=original_last,
        original_bio=original_bio,
        original_photo=original_photo,
    )

    if _mongo_enabled():
        await _database.clones.update_one(
            {"owner_scope": owner_scope, "user_id": user_id},
            {
                "$set": {
                    "original_first": original_first,
                    "original_last": original_last,
                    "original_bio": original_bio,
                    "original_photo": _photo_to_text(original_photo),
                }
            },
            upsert=True,
        )
        return

    _clones[user_id] = snapshot


async def get_clone(user_id: int) -> Optional[CloneSnapshot]:
    owner_scope = _owner_scope()

    if _mongo_enabled():
        row = await _database.clones.find_one(
            {"owner_scope": owner_scope, "user_id": user_id}
        )
        if row is None:
            return None

        return CloneSnapshot(
            user_id=user_id,
            original_first=str(row.get("original_first", "")),
            original_last=str(row.get("original_last", "")),
            original_bio=str(row.get("original_bio", "")),
            original_photo=_photo_from_text(row.get("original_photo")),
        )

    return _clones.get(user_id)


async def delete_clone(user_id: int):
    owner_scope = _owner_scope()

    if _mongo_enabled():
        await _database.clones.delete_one(
            {"owner_scope": owner_scope, "user_id": user_id}
        )
        return

    _clones.pop(user_id, None)


async def add_block(user_id: int):
    owner_scope = _owner_scope()

    if _mongo_enabled():
        await _database.blocks.update_one(
            {"owner_scope": owner_scope, "user_id": user_id},
            {"$set": {"active": True}},
            upsert=True,
        )
        return

    _blocks.add(user_id)


async def remove_block(user_id: int):
    owner_scope = _owner_scope()

    if _mongo_enabled():
        await _database.blocks.delete_one(
            {"owner_scope": owner_scope, "user_id": user_id}
        )
        return

    _blocks.discard(user_id)


async def is_blocked(user_id: int) -> bool:
    owner_scope = _owner_scope()

    if _mongo_enabled():
        row = await _database.blocks.find_one(
            {"owner_scope": owner_scope, "user_id": user_id}
        )
        return row is not None

    return user_id in _blocks
