"""Mərkəzi konfiqurasiya"""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


BASE_DIR = Path(__file__).resolve().parent
REPO_DIR = BASE_DIR.parent


def _detect_repo_from_git() -> str:
    candidates = [
        os.getenv("PLUGIN_SOURCE_REPO", "").strip(),
        os.getenv("GITHUB_REPOSITORY", "").strip(),
        os.getenv("RENDER_GIT_REPOSITORY", "").strip(),
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
        os.getenv("PLUGIN_CACHE_DIR", "").strip(),
        os.getenv("RENDER_DISK_PATH", "").strip(),
        os.getenv("RENDER_PERSISTENT_DIR", "").strip(),
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
    explicit = os.getenv("LOCAL_PLUGIN_DIR", "").strip()
    if explicit:
        return str(Path(explicit).expanduser())
    return str((BASE_DIR / "plugins").resolve())


def _detect_public_base_url() -> str:
    candidates = [
        os.getenv("APP_BASE_URL", "").strip(),
        os.getenv("RENDER_EXTERNAL_URL", "").strip(),
        os.getenv("RENDER_PUBLIC_URL", "").strip(),
    ]
    for candidate in candidates:
        if candidate:
            return candidate.rstrip("/")
    return ""


class Config:
    API_ID = int(os.getenv("API_ID", "0"))
    API_HASH = os.getenv("API_HASH", "")
    SESSION_STRING = os.getenv("SESSION_STRING", "")
    ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")
    OWNER_ID = int(os.getenv("OWNER_ID", "0"))
    CMD_PREFIX = os.getenv("CMD_PREFIX", ".")
    LOG_TO_SAVED = os.getenv("LOG_TO_SAVED", "1") == "1"

    PLUGIN_SOURCE_REPO = _detect_repo_from_git()
    PLUGIN_SOURCE_BRANCH = os.getenv("PLUGIN_SOURCE_BRANCH", "main")
    PLUGIN_SOURCE_PATH = os.getenv("PLUGIN_SOURCE_PATH", "plugins").strip("/")
    PLUGIN_SYNC_INTERVAL = max(60, int(os.getenv("PLUGIN_SYNC_INTERVAL", "300")))
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
    PLUGIN_CACHE_DIR = _default_plugin_cache_dir()
    PLUGIN_AUTO_SYNC = os.getenv("PLUGIN_AUTO_SYNC", "0") == "1"
    PLUGIN_ALLOWLIST = [
        item.strip() for item in os.getenv("PLUGIN_ALLOWLIST", "").split(",") if item.strip()
    ]
    LOCAL_PLUGIN_DIR = _default_local_plugin_dir()

    MONGODB_URI = os.getenv("MONGODB_URI", "").strip()
    MONGODB_DB = os.getenv("MONGODB_DB", "ryhavean_userbot").strip() or "ryhavean_userbot"

    APP_BASE_URL = _detect_public_base_url()
    UPTIME_URL = os.getenv("UPTIME_URL", "").strip()
    UPTIME_ENABLED = os.getenv("UPTIME_ENABLED", "1") == "1"
    UPTIME_INTERVAL_SECONDS = max(60, int(os.getenv("UPTIME_INTERVAL_SECONDS", "240")))
    UPTIME_USER_AGENT = os.getenv("UPTIME_USER_AGENT", "RavenUserbotKeepAlive/1.0").strip() or "RavenUserbotKeepAlive/1.0"
