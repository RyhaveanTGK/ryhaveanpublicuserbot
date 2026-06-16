"""Mərkəzi konfiqurasiya"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR.parent


def _getenv_str(key: str, default: str = "") -> str:
    value = os.getenv(key)
    if value is None:
        return default
    return str(value).strip()


def _getenv_int(key: str, default: int = 0) -> int:
    raw = _getenv_str(key, "")
    if not raw:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _detect_repo_from_git() -> str:
    candidates = [
        _getenv_str("PLUGIN_SOURCE_REPO"),
        _getenv_str("GITHUB_REPOSITORY"),
        _getenv_str("RENDER_GIT_REPOSITORY"),
    ]
    for candidate in candidates:
        if candidate:
            return candidate.replace("https://github.com/", "").replace(".git", "").strip("/")

    git_config = REPO_DIR / ".git" / "config"
    if git_config.exists():
        try:
            text = git_config.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("url = ") and "github.com" in line:
                    url = line.split("=", 1)[1].strip()
                    if url.startswith("git@github.com:"):
                        return url.split(":", 1)[1].replace(".git", "").strip("/")
                    if "github.com/" in url:
                        return url.split("github.com/", 1)[1].replace(".git", "").strip("/")
        except Exception:
            pass
    return ""


def _default_plugin_cache_dir() -> str:
    candidates = [
        _getenv_str("PLUGIN_CACHE_DIR"),
        _getenv_str("RENDER_DISK_PATH"),
        _getenv_str("RENDER_PERSISTENT_DIR"),
    ]
    for candidate in candidates:
        if candidate:
            base = Path(candidate).expanduser()
            if base.name == "ryhavean-plugin-cache":
                return str(base)
            return str(base / "ryhavean-plugin-cache")

    render_disk_fallback = Path("/var/data")
    if render_disk_fallback.exists() and render_disk_fallback.is_dir():
        return str(render_disk_fallback / "ryhavean-plugin-cache")

    return str((BASE_DIR / ".plugin_cache").resolve())


def _default_local_plugin_dir() -> str:
    explicit = _getenv_str("LOCAL_PLUGIN_DIR")
    if explicit:
        return str(Path(explicit).expanduser())
    return str((BASE_DIR / "plugins").resolve())


def _detect_public_base_url() -> str:
    candidates = [
        _getenv_str("APP_BASE_URL"),
        _getenv_str("RENDER_EXTERNAL_URL"),
        _getenv_str("RENDER_PUBLIC_URL"),
    ]
    for candidate in candidates:
        if candidate:
            return candidate.rstrip("/")
    return ""


class Config:
    API_ID = _getenv_int("API_ID", 0)
    API_HASH = _getenv_str("API_HASH")
    SESSION_STRING = _getenv_str("SESSION_STRING")
    ENCRYPTION_KEY = _getenv_str("ENCRYPTION_KEY")
    OWNER_ID = _getenv_int("OWNER_ID", 0)
    CMD_PREFIX = _getenv_str("CMD_PREFIX", ".") or "."
    LOG_TO_SAVED = _getenv_str("LOG_TO_SAVED", "1") == "1"

    PLUGIN_SOURCE_REPO = _detect_repo_from_git()
    PLUGIN_SOURCE_BRANCH = _getenv_str("PLUGIN_SOURCE_BRANCH", "main")
    PLUGIN_SOURCE_PATH = _getenv_str("PLUGIN_SOURCE_PATH", "plugins").strip("/")
    PLUGIN_SYNC_INTERVAL = max(60, _getenv_int("PLUGIN_SYNC_INTERVAL", 300))
    GITHUB_TOKEN = _getenv_str("GITHUB_TOKEN")
    PLUGIN_CACHE_DIR = _default_plugin_cache_dir()
    PLUGIN_AUTO_SYNC = _getenv_str("PLUGIN_AUTO_SYNC", "0") == "1"
    PLUGIN_ALLOWLIST = [
        item.strip() for item in _getenv_str("PLUGIN_ALLOWLIST", "").split(",") if item.strip()
    ]
    LOCAL_PLUGIN_DIR = _default_local_plugin_dir()

    MONGODB_URI = _getenv_str("MONGODB_URI")
    MONGODB_DB = _getenv_str("MONGODB_DB", "ryhavean_userbot") or "ryhavean_userbot"

    APP_BASE_URL = _detect_public_base_url()
    UPTIME_URL = _getenv_str("UPTIME_URL")
    UPTIME_ENABLED = _getenv_str("UPTIME_ENABLED", "1") == "1"
    UPTIME_INTERVAL_SECONDS = max(60, _getenv_int("UPTIME_INTERVAL_SECONDS", 240))
    UPTIME_USER_AGENT = _getenv_str("UPTIME_USER_AGENT", "RavenUserbotKeepAlive/1.0") or "RavenUserbotKeepAlive/1.0"

    STARTUP_MAX_RETRIES = max(1, _getenv_int("STARTUP_MAX_RETRIES", 3))
    STARTUP_RETRY_DELAY_SECONDS = max(2, _getenv_int("STARTUP_RETRY_DELAY_SECONDS", 5))
