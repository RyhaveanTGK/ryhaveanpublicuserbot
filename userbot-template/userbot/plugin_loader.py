"""MongoDB-backed dynamic plugin loader."""
from __future__ import annotations

import asyncio
import logging
import re
import sys
import traceback
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from telethon import events

import db
from security import analyze_plugin

log = logging.getLogger("plugins")


@dataclass(slots=True)
class PluginRecord:
    name: str
    sha: str
    source_url: str
    module: types.ModuleType
    handlers: list[tuple[Any, Any]]


@dataclass(slots=True)
class SyncSummary:
    source: str
    loaded_names: list[str]
    failed_names: list[str]
    remote_attempted: bool = False
    remote_error: str = ""


loaded: dict[str, types.ModuleType] = {}
_loaded_records: dict[str, PluginRecord] = {}
_sync_lock = asyncio.Lock()
_sync_task: asyncio.Task | None = None


class PluginLoaderError(RuntimeError):
    pass


def preprocess_code(code: str) -> str:
    code = re.sub(r"from userbot\..* import .*\n", "", code)
    code = re.sub(r"from userbot import .*\n", "", code)
    code = re.sub(r"Help\s*=\s*CmdHelp\(.*\)", "", code)
    code = re.sub(r"Help\..*", "", code)
    code = re.sub(r"@register\(.*pattern=(.*)\)", r"@client.on(events.NewMessage(pattern=\1))", code)
    return code.replace("brend", "event")


def extract_commands(code: str) -> str:
    patterns = [
        r'pattern=r"\^\\\.([\w]+)"',
        r'pattern="\^\.([\w]+)"',
        r'pattern=r"\.([\w]+)"',
        r'pattern="\.([\w]+)"',
    ]
    matches: list[str] = []
    for pattern in patterns:
        matches.extend(re.findall(pattern, code))
    unique_matches = sorted(set(matches))
    if not unique_matches:
        return "<i>Komanda tapılmadı</i>"
    return ", ".join(f"<code>.{cmd}</code>" for cmd in unique_matches)


def normalize_plugin_name(name: str) -> str:
    stem = Path(str(name or "plugin")).stem.strip().lower()
    stem = re.sub(r"[^a-z0-9_]+", "_", stem).strip("_")
    if not stem:
        raise PluginLoaderError("Plugin adı boşdur")
    return stem


def _snapshot_handlers(client) -> list[tuple[Any, Any]]:
    try:
        return list(client.list_event_handlers())
    except Exception:
        return []


def _diff_handlers(before: list[tuple[Any, Any]], after: list[tuple[Any, Any]]) -> list[tuple[Any, Any]]:
    before_ids = {(id(cb), repr(ev)) for cb, ev in before}
    return [(cb, ev) for cb, ev in after if (id(cb), repr(ev)) not in before_ids]


async def _load_plugin(name: str, sha: str, source_url: str, code: str, client) -> PluginRecord:
    processed = preprocess_code(code)
    safe, reason = analyze_plugin(processed)
    if not safe:
        raise PluginLoaderError(f"Təhlükəsizlik xətası: {reason}")

    module_name = f"plugins.{name}"
    before = _snapshot_handlers(client)
    mod = types.ModuleType(module_name)
    mod.__file__ = source_url
    mod.__package__ = "plugins"
    mod.client = client
    mod.events = events
    mod.__dict__["__builtins__"] = __builtins__
    sys.modules[module_name] = mod

    try:
        exec(compile(processed, source_url, "exec"), mod.__dict__)
        if hasattr(mod, "register"):
            maybe = mod.register(client)
            if asyncio.iscoroutine(maybe):
                await maybe
        after = _snapshot_handlers(client)
        handlers = _diff_handlers(before, after)
        record = PluginRecord(name=name, sha=sha, source_url=source_url, module=mod, handlers=handlers)
        loaded[name] = mod
        _loaded_records[name] = record
        log.info("✅ Plugin yükləndi: %s", name)
        return record
    except Exception as exc:
        sys.modules.pop(module_name, None)
        err = traceback.format_exc()
        log.error("Plugin xətası %s: %s", name, err)
        raise PluginLoaderError(str(exc)) from exc


async def _unload_plugin(name: str, client) -> None:
    record = _loaded_records.pop(name, None)
    loaded.pop(name, None)
    if not record:
        return
    for callback, event_builder in reversed(record.handlers):
        try:
            client.remove_event_handler(callback, event_builder)
        except Exception:
            pass
    sys.modules.pop(record.module.__name__, None)
    log.info("🗑 Plugin unload edildi: %s", name)


async def _plugin_docs():
    docs = await db.list_plugins()
    normalized_docs = []
    for item in docs:
        name = normalize_plugin_name(item.get("name", ""))
        code = str(item.get("code", ""))
        if not code.strip():
            continue
        sha = str(item.get("code_hash") or "") or f"db:{hash(code)}"
        normalized_docs.append({
            "name": name,
            "code": code,
            "sha": sha,
            "source_name": str(item.get("source_name", f"{name}.py")),
        })
    return normalized_docs


async def sync_plugins(client, *, force_remote: bool = False) -> SyncSummary:
    async with _sync_lock:
        desired_docs = await _plugin_docs()
        desired = {item["name"]: item for item in desired_docs}
        loaded_names: list[str] = []
        failed_names: list[str] = []

        for name in list(_loaded_records):
            if name not in desired:
                await _unload_plugin(name, client)

        for name, item in desired.items():
            current = _loaded_records.get(name)
            if current and current.sha == item["sha"]:
                loaded_names.append(name)
                continue
            if current:
                await _unload_plugin(name, client)
            try:
                await _load_plugin(name, item["sha"], item["source_name"], item["code"], client)
                loaded_names.append(name)
            except Exception as exc:
                failed_names.append(name)
                log.error("Plugin yüklənmədi %s (db): %s", name, exc)

        return SyncSummary(source=db.plugin_store_label(), loaded_names=sorted(loaded_names), failed_names=sorted(failed_names))


async def load_all(client):
    return await sync_plugins(client, force_remote=False)


async def manual_update(client):
    return await sync_plugins(client, force_remote=False)


async def install_plugin(client, name: str, code: str, *, source_name: str = "", installed_by: int = 0) -> PluginRecord:
    plugin_name = normalize_plugin_name(name)
    source_label = source_name or f"{plugin_name}.py"
    safe, reason = analyze_plugin(preprocess_code(code))
    if not safe:
        raise PluginLoaderError(f"Təhlükəsizlik xətası: {reason}")
    await db.upsert_plugin(plugin_name, code, source_name=source_label, installed_by=installed_by)
    current = _loaded_records.get(plugin_name)
    if current:
        await _unload_plugin(plugin_name, client)
    doc = await db.get_plugin(plugin_name)
    if not doc:
        raise PluginLoaderError("Plugin MongoDB-yə yazılmadı")
    return await _load_plugin(plugin_name, str(doc.get("code_hash") or f"db:{hash(code)}"), source_label, code, client)


async def uninstall_plugin(client, name: str) -> bool:
    plugin_name = normalize_plugin_name(name)
    await _unload_plugin(plugin_name, client)
    return await db.remove_plugin(plugin_name)


async def start_background_sync(client):
    return None


def stop_background_sync():
    global _sync_task
    if _sync_task and not _sync_task.done():
        _sync_task.cancel()
    _sync_task = None
