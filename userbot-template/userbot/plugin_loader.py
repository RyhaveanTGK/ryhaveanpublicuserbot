"""GitHub plugin loader with local cache + fallback support."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import traceback
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from telethon import events

from config import Config
from security import analyze_plugin

log = logging.getLogger("plugins")


@dataclass(slots=True)
class PluginRecord:
    name: str
    sha: str
    source_url: str
    module: types.ModuleType
    handlers: list[tuple[Any, Any]]


loaded: dict[str, types.ModuleType] = {}
_loaded_records: dict[str, PluginRecord] = {}
_sync_lock = asyncio.Lock()
_sync_task: asyncio.Task | None = None

_CACHE_VERSION = 1
_CACHE_MANIFEST = "manifest.json"


class PluginLoaderError(RuntimeError):
    pass


@dataclass(slots=True)
class CachedPlugin:
    name: str
    sha: str
    source_url: str
    cache_path: Path


@dataclass(slots=True)
class SyncSummary:
    source: str
    loaded_names: list[str]
    failed_names: list[str]
    remote_attempted: bool = False
    remote_error: str = ""


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


def _headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "raven-userbot-plugin-loader",
    }
    if Config.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {Config.GITHUB_TOKEN}"
    return headers


def _cache_root() -> Path:
    path = Path(Config.PLUGIN_CACHE_DIR).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _plugins_cache_dir() -> Path:
    path = _cache_root() / "plugins"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _manifest_path() -> Path:
    return _cache_root() / _CACHE_MANIFEST


def _local_plugins_dir() -> Path:
    return Path(Config.LOCAL_PLUGIN_DIR).expanduser()


def _safe_stem(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", name).strip("_") or "plugin"


def _cache_file_path(name: str) -> Path:
    return _plugins_cache_dir() / f"{_safe_stem(name)}.py"


def cache_exists() -> bool:
    manifest = _manifest_path()
    if not manifest.exists():
        return False
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return False
    for item in data.get("plugins", []):
        name = item.get("name", "")
        if not name:
            continue
        if _cache_file_path(name).exists():
            return True
    return False


def local_plugins_available() -> bool:
    plugin_dir = _local_plugins_dir()
    if not plugin_dir.exists() or not plugin_dir.is_dir():
        return False
    return any(path.is_file() and path.suffix == ".py" and not path.name.startswith("_") for path in plugin_dir.iterdir())


def _read_manifest() -> dict[str, Any]:
    path = _manifest_path()
    if not path.exists():
        return {"version": _CACHE_VERSION, "plugins": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.warning("Plugin cache manifest oxunmadı: %s", exc)
        return {"version": _CACHE_VERSION, "plugins": []}
    if not isinstance(data, dict):
        return {"version": _CACHE_VERSION, "plugins": []}
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        data["plugins"] = []
    return data


def _write_manifest(data: dict[str, Any]) -> None:
    path = _manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": _CACHE_VERSION,
        "repo": Config.PLUGIN_SOURCE_REPO,
        "branch": Config.PLUGIN_SOURCE_BRANCH,
        "path": Config.PLUGIN_SOURCE_PATH,
        "plugins": data.get("plugins", []),
        "updated_at": data.get("updated_at"),
    }
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _load_cached_catalog() -> list[CachedPlugin]:
    manifest = _read_manifest()
    allowlist = {name.lower() for name in Config.PLUGIN_ALLOWLIST}
    cached: list[CachedPlugin] = []
    for item in manifest.get("plugins", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        if allowlist and name.lower() not in allowlist:
            continue
        cache_path = _cache_file_path(name)
        if not cache_path.exists():
            log.warning("Cache faylı tapılmadı, keçilir: %s", cache_path)
            continue
        cached.append(
            CachedPlugin(
                name=name,
                sha=str(item.get("sha", "cache")),
                source_url=str(item.get("source_url") or cache_path.as_uri()),
                cache_path=cache_path,
            )
        )
    return cached


def _load_local_catalog() -> list[CachedPlugin]:
    plugin_dir = _local_plugins_dir()
    allowlist = {name.lower() for name in Config.PLUGIN_ALLOWLIST}
    if not plugin_dir.exists() or not plugin_dir.is_dir():
        return []

    plugins: list[CachedPlugin] = []
    for path in sorted(plugin_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        name = path.stem
        if allowlist and name.lower() not in allowlist:
            continue
        stat = path.stat()
        plugins.append(
            CachedPlugin(
                name=name,
                sha=f"local:{stat.st_mtime_ns}",
                source_url=path.resolve().as_uri(),
                cache_path=path.resolve(),
            )
        )
    return plugins


def _persist_remote_catalog(plugins: list[dict[str, str]], plugin_code_map: dict[str, str]) -> list[CachedPlugin]:
    manifest_plugins: list[dict[str, str]] = []
    cached_plugins: list[CachedPlugin] = []
    desired_names = {item["name"] for item in plugins}

    for name, code in plugin_code_map.items():
        cache_path = _cache_file_path(name)
        cache_path.write_text(code, encoding="utf-8")

    for item in plugins:
        name = item["name"]
        cache_path = _cache_file_path(name)
        if not cache_path.exists():
            continue
        manifest_plugins.append(
            {
                "name": name,
                "sha": item.get("sha", ""),
                "source_url": item.get("download_url", "") or cache_path.as_uri(),
            }
        )
        cached_plugins.append(
            CachedPlugin(
                name=name,
                sha=item.get("sha", ""),
                source_url=item.get("download_url", "") or cache_path.as_uri(),
                cache_path=cache_path,
            )
        )

    for old_file in _plugins_cache_dir().glob("*.py"):
        if old_file.stem not in {_safe_stem(name) for name in desired_names}:
            try:
                old_file.unlink()
            except Exception:
                pass

    _write_manifest({"plugins": manifest_plugins})
    return cached_plugins


async def _fetch_catalog() -> list[dict[str, str]]:
    repo = Config.PLUGIN_SOURCE_REPO
    if not repo:
        log.warning("PLUGIN_SOURCE_REPO tapılmadı, GitHub plugin sync söndürülüb")
        return []

    api_url = (
        f"https://api.github.com/repos/{repo}/contents/"
        f"{Config.PLUGIN_SOURCE_PATH}?ref={Config.PLUGIN_SOURCE_BRANCH}"
    )
    async with httpx.AsyncClient(timeout=20.0, headers=_headers()) as client:
        response = await client.get(api_url)
        response.raise_for_status()
        items = response.json()

    allowlist = {name.lower() for name in Config.PLUGIN_ALLOWLIST}
    plugins: list[dict[str, str]] = []
    for item in items:
        if item.get("type") != "file":
            continue
        name = item.get("name", "")
        if not name.endswith(".py") or name.startswith("_"):
            continue
        stem = name[:-3]
        if allowlist and stem.lower() not in allowlist:
            continue
        plugins.append(
            {
                "name": stem,
                "sha": item.get("sha", ""),
                "download_url": item.get("download_url", ""),
            }
        )
    return plugins


async def _fetch_code(download_url: str) -> str:
    async with httpx.AsyncClient(timeout=20.0, headers=_headers()) as client:
        response = await client.get(download_url)
        response.raise_for_status()
        return response.text


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


async def _reconcile_cached_plugins(cached_plugins: list[CachedPlugin], client, source: str) -> SyncSummary:
    desired = {item.name: item for item in cached_plugins}
    loaded_names: list[str] = []
    failed_names: list[str] = []

    for name in list(_loaded_records):
        if name not in desired:
            await _unload_plugin(name, client)

    for name, item in desired.items():
        current = _loaded_records.get(name)
        if current and current.sha == item.sha:
            loaded_names.append(name)
            continue
        if current:
            await _unload_plugin(name, client)
        try:
            code = item.cache_path.read_text(encoding="utf-8")
            await _load_plugin(name, item.sha, item.source_url, code, client)
            loaded_names.append(name)
        except Exception as exc:
            failed_names.append(name)
            log.error("Plugin yüklənmədi %s (%s): %s", name, source, exc)

    log.info("🔌 Aktiv plugin sayı (%s): %s", source, len(_loaded_records))
    return SyncSummary(source=source, loaded_names=sorted(loaded_names), failed_names=sorted(failed_names))


async def _download_and_cache_from_github() -> list[CachedPlugin]:
    plugins = await _fetch_catalog()
    code_map: dict[str, str] = {}
    for item in plugins:
        download_url = item.get("download_url", "")
        if not download_url:
            raise PluginLoaderError(f"download_url boşdur: {item['name']}")
        code_map[item["name"]] = await _fetch_code(download_url)
    return _persist_remote_catalog(plugins, code_map)


async def sync_plugins(client, *, force_remote: bool = False) -> SyncSummary:
    async with _sync_lock:
        has_cache = cache_exists()
        has_local = local_plugins_available()
        has_repo = bool(Config.PLUGIN_SOURCE_REPO)

        if force_remote:
            if has_repo:
                try:
                    cached_plugins = await _download_and_cache_from_github()
                    summary = await _reconcile_cached_plugins(cached_plugins, client, "github")
                    summary.remote_attempted = True
                    return summary
                except Exception as exc:
                    remote_error = str(exc)
                    if has_cache:
                        log.warning("GitHub sync xətası, cache istifadə olunur: %s", remote_error)
                        cached_plugins = _load_cached_catalog()
                        summary = await _reconcile_cached_plugins(cached_plugins, client, "cache-fallback")
                    elif has_local:
                        log.warning("GitHub sync xətası, local pluginlər istifadə olunur: %s", remote_error)
                        cached_plugins = _load_local_catalog()
                        summary = await _reconcile_cached_plugins(cached_plugins, client, "local-fallback")
                    else:
                        summary = await _reconcile_cached_plugins([], client, "empty")
                    summary.remote_attempted = True
                    summary.remote_error = remote_error
                    return summary

            summary = await _reconcile_cached_plugins(_load_local_catalog() if has_local else _load_cached_catalog(), client, "local" if has_local else "cache")
            summary.remote_attempted = True
            summary.remote_error = "PLUGIN_SOURCE_REPO təyin edilməyib"
            return summary

        if has_cache:
            return await _reconcile_cached_plugins(_load_cached_catalog(), client, "cache")

        if has_local:
            return await _reconcile_cached_plugins(_load_local_catalog(), client, "local")

        if has_repo:
            try:
                cached_plugins = await _download_and_cache_from_github()
                summary = await _reconcile_cached_plugins(cached_plugins, client, "github")
                summary.remote_attempted = True
                return summary
            except Exception as exc:
                summary = await _reconcile_cached_plugins([], client, "empty")
                summary.remote_attempted = True
                summary.remote_error = str(exc)
                return summary

        return await _reconcile_cached_plugins([], client, "empty")


async def load_all(client):
    return await sync_plugins(client, force_remote=False)


async def manual_update(client):
    return await sync_plugins(client, force_remote=True)


async def _sync_loop(client):
    while True:
        await asyncio.sleep(Config.PLUGIN_SYNC_INTERVAL)
        try:
            await sync_plugins(client, force_remote=True)
        except Exception as exc:
            log.warning("Plugin sync xətası: %s", exc)


async def start_background_sync(client):
    global _sync_task
    if not Config.PLUGIN_AUTO_SYNC:
        log.info("ℹ️ Avtomatik GitHub plugin sync söndürülüb")
        return None
    if not Config.PLUGIN_SOURCE_REPO:
        log.info("ℹ️ PLUGIN_SOURCE_REPO yoxdur, background sync local/cache ilə davam edir")
        return None
    if _sync_task and not _sync_task.done():
        return _sync_task
    _sync_task = asyncio.create_task(_sync_loop(client))
    return _sync_task


def stop_background_sync():
    global _sync_task
    if _sync_task and not _sync_task.done():
        _sync_task.cancel()
    _sync_task = None
