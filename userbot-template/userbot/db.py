"""MongoDB əsaslı persistent state manager."""
from __future__ import annotations

import base64
import hashlib
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
_plugin_client: AsyncIOMotorClient | None = None
_plugin_database: AsyncIOMotorDatabase | None = None

_settings: dict[str, str] = {}
_welcomes: dict[tuple[int, int], str] = {}
_clones: dict[int, CloneSnapshot] = {}
_blocks: set[int] = set()
_filters: dict[tuple[int, int, str], str] = {}


def _owner_scope() -> int:
    return Config.OWNER_ID or 0


def _mongo_enabled() -> bool:
    return _database is not None


def _plugin_mongo_enabled() -> bool:
    return _plugin_database is not None


def _plugin_mongo_uri() -> str:
    return (Config.PLUGIN_MONGODB_URI or Config.MONGODB_URI or "").strip()


def _plugin_mongo_db_name() -> str:
    return (Config.PLUGIN_MONGODB_DB or "ryhavean_shared_plugins").strip() or "ryhavean_shared_plugins"


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


def _normalize_filter_text(text: str) -> str:
    return " ".join((text or "").split()).casefold()


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

    await _database.filters.create_index(
        [("owner_scope", 1), ("chat_id", 1), ("trigger", 1)],
        unique=True,
    )


async def _ensure_plugin_indexes() -> None:
    if _plugin_database is None:
        return

    await _plugin_database.plugins.create_index(
        [("name", 1)],
        unique=True,
    )


async def init_db():
    global _client, _database, _plugin_client, _plugin_database

    main_ready = _database is not None
    plugin_ready = _plugin_database is not None
    if main_ready and plugin_ready:
        return True

    if not Config.MONGODB_URI:
        log.warning("MONGODB_URI env tapılmadı, persistent DB fallback əlçatan deyil")
        return False

    try:
        if _client is None:
            _client = AsyncIOMotorClient(
                Config.MONGODB_URI,
                serverSelectionTimeoutMS=10000,
                connectTimeoutMS=10000,
                socketTimeoutMS=10000,
                retryWrites=True,
            )
            await _client.admin.command("ping")

        if _database is None:
            _database = _client[Config.MONGODB_DB]
            await _ensure_indexes()
            log.info("✅ MongoDB qoşuldu: db=%s", Config.MONGODB_DB)

        plugin_uri = _plugin_mongo_uri()
        plugin_db_name = _plugin_mongo_db_name()
        if plugin_uri:
            same_plugin_store = (
                plugin_uri == Config.MONGODB_URI
                and plugin_db_name == Config.MONGODB_DB
            )
            if same_plugin_store:
                _plugin_client = _client
                _plugin_database = _database
            elif _plugin_database is None:
                if _plugin_client is None:
                    _plugin_client = AsyncIOMotorClient(
                        plugin_uri,
                        serverSelectionTimeoutMS=10000,
                        connectTimeoutMS=10000,
                        socketTimeoutMS=10000,
                        retryWrites=True,
                    )
                    await _plugin_client.admin.command("ping")
                _plugin_database = _plugin_client[plugin_db_name]
            await _ensure_plugin_indexes()
            if _plugin_database is not None:
                log.info("✅ Plugin store qoşuldu: db=%s", plugin_db_name)

        return _database is not None

    except Exception:
        log.exception("MongoDB bağlantı xətası")

        _database = None
        _plugin_database = None

        if _plugin_client is not None and _plugin_client is not _client:
            _plugin_client.close()
        if _client is not None:
            _client.close()

        _plugin_client = None
        _client = None
        return False


async def close_db():
    global _client, _database, _plugin_client, _plugin_database

    if _plugin_client is not None and _plugin_client is not _client:
        _plugin_client.close()
    if _client is not None:
        _client.close()

    _plugin_client = None
    _plugin_database = None
    _client = None
    _database = None


def pool():
    if not _mongo_enabled():
        raise RuntimeError("MongoDB aktiv deyil")
    return _database


def plugin_pool():
    if not _plugin_mongo_enabled():
        raise RuntimeError("Plugin store aktiv deyil")
    return _plugin_database


def plugin_store_label() -> str:
    if not _plugin_mongo_enabled():
        return "local"
    plugin_db_name = _plugin_mongo_db_name()
    if _database is not None and _plugin_database is _database:
        return f"mongodb:{plugin_db_name}"
    return f"shared-mongodb:{plugin_db_name}"


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


async def save_bootstrap_config(config_map: dict[str, object]) -> None:
    payload = {
        "bootstrap_api_id": str(int(config_map.get("api_id", 0) or 0)),
        "bootstrap_api_hash": str(config_map.get("api_hash", "") or "").strip(),
        "bootstrap_session_string": str(config_map.get("session_string", "") or "").strip(),
        "bootstrap_mongodb_uri": str(config_map.get("mongodb_uri", "") or "").strip(),
        "bootstrap_mongodb_db": str(config_map.get("mongodb_db", "") or "").strip(),
        "bootstrap_owner_id": str(int(config_map.get("owner_id", 0) or 0)),
        "bootstrap_cmd_prefix": str(config_map.get("cmd_prefix", ".") or ".").strip() or ".",
    }
    for key, value in payload.items():
        if value:
            await set_setting(key, value)


async def get_bootstrap_config() -> dict[str, str]:
    return {
        "api_id": await get_setting("bootstrap_api_id", "0") or "0",
        "api_hash": await get_setting("bootstrap_api_hash", "") or "",
        "session_string": await get_setting("bootstrap_session_string", "") or "",
        "mongodb_uri": await get_setting("bootstrap_mongodb_uri", "") or "",
        "mongodb_db": await get_setting("bootstrap_mongodb_db", Config.MONGODB_DB) or Config.MONGODB_DB,
        "owner_id": await get_setting("bootstrap_owner_id", "0") or "0",
        "cmd_prefix": await get_setting("bootstrap_cmd_prefix", ".") or ".",
    }


async def set_runtime_status(status: str, summary: str = "") -> None:
    await set_setting("runtime_status", status)
    await set_setting("runtime_summary", summary)


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


async def upsert_plugin(name: str, code: str, *, source_name: str = "", installed_by: int = 0):
    payload = {
        "name": name,
        "code": code,
        "source_name": source_name or f"{name}.py",
        "installed_by": int(installed_by or 0),
        "code_hash": hashlib.sha1(code.encode("utf-8")).hexdigest(),
    }

    if _plugin_mongo_enabled():
        await _plugin_database.plugins.update_one(
            {"name": name},
            {
                "$set": {
                    **payload,
                },
                "$setOnInsert": {"created_at": __import__("datetime").datetime.utcnow()},
                "$currentDate": {"updated_at": True},
            },
            upsert=True,
        )
        return payload

    _settings[f"plugin:{name}"] = code
    _settings[f"plugin_meta:{name}"] = source_name or f"{name}.py"
    return payload


async def get_plugin(name: str):
    if _plugin_mongo_enabled():
        row = await _plugin_database.plugins.find_one({"name": name})
        if row is None:
            return None
        return {
            "name": str(row.get("name", name)),
            "code": str(row.get("code", "")),
            "source_name": str(row.get("source_name", f"{name}.py")),
            "installed_by": int(row.get("installed_by", 0) or 0),
            "code_hash": str(row.get("code_hash", "")),
        }

    code = _settings.get(f"plugin:{name}")
    if code is None:
        return None
    return {
        "name": name,
        "code": code,
        "source_name": _settings.get(f"plugin_meta:{name}", f"{name}.py"),
        "installed_by": 0,
        "code_hash": hashlib.sha1(code.encode("utf-8")).hexdigest(),
    }


async def list_plugins():
    if _plugin_mongo_enabled():
        rows = await _plugin_database.plugins.find({}).sort("name", 1).to_list(length=None)
        return [
            {
                "name": str(row.get("name", "")).strip(),
                "code": str(row.get("code", "")),
                "source_name": str(row.get("source_name", "")),
                "installed_by": int(row.get("installed_by", 0) or 0),
                "code_hash": str(row.get("code_hash", "")),
            }
            for row in rows
            if str(row.get("name", "")).strip()
        ]

    items = []
    for key, code in sorted(_settings.items()):
        if not key.startswith("plugin:") or key.startswith("plugin_meta:"):
            continue
        name = key.split(":", 1)[1]
        items.append({
            "name": name,
            "code": code,
            "source_name": _settings.get(f"plugin_meta:{name}", f"{name}.py"),
            "installed_by": 0,
            "code_hash": hashlib.sha1(code.encode("utf-8")).hexdigest(),
        })
    return items


async def remove_plugin(name: str) -> bool:
    if _plugin_mongo_enabled():
        result = await _plugin_database.plugins.delete_one({"name": name})
        return result.deleted_count > 0

    existed = f"plugin:{name}" in _settings
    _settings.pop(f"plugin:{name}", None)
    _settings.pop(f"plugin_meta:{name}", None)
    return existed


async def save_filter(chat_id: int, trigger: str, response: str):
    owner_scope = _owner_scope()
    normalized_trigger = _normalize_filter_text(trigger)
    if not normalized_trigger:
        raise ValueError("Filter trigger boş ola bilməz")

    if _mongo_enabled():
        await _database.filters.update_one(
            {"owner_scope": owner_scope, "chat_id": int(chat_id), "trigger": normalized_trigger},
            {"$set": {"response": response, "trigger_text": trigger.strip()}},
            upsert=True,
        )
        return

    _filters[(owner_scope, int(chat_id), normalized_trigger)] = response


async def get_filter(chat_id: int, trigger: str) -> Optional[str]:
    owner_scope = _owner_scope()
    normalized_trigger = _normalize_filter_text(trigger)
    if not normalized_trigger:
        return None

    if _mongo_enabled():
        row = await _database.filters.find_one(
            {"owner_scope": owner_scope, "chat_id": int(chat_id), "trigger": normalized_trigger}
        )
        return str(row.get("response", "")) if row else None

    return _filters.get((owner_scope, int(chat_id), normalized_trigger))


async def remove_filter(chat_id: int, trigger: str) -> bool:
    owner_scope = _owner_scope()
    normalized_trigger = _normalize_filter_text(trigger)
    if not normalized_trigger:
        return False

    if _mongo_enabled():
        result = await _database.filters.delete_one(
            {"owner_scope": owner_scope, "chat_id": int(chat_id), "trigger": normalized_trigger}
        )
        return result.deleted_count > 0

    return _filters.pop((owner_scope, int(chat_id), normalized_trigger), None) is not None
