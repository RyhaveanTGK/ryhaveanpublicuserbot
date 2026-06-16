from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class Settings:
    app_name: str = os.getenv("APP_NAME", "Ryhavean")
    app_base_url: str = os.getenv("APP_BASE_URL", "http://localhost:10000").rstrip("/")
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_bot_username: str = os.getenv("TELEGRAM_BOT_USERNAME", "")
    webapp_url: str = os.getenv("WEBAPP_URL", os.getenv("APP_BASE_URL", "http://localhost:10000")).rstrip("/")

    mongodb_uri: str = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    mongodb_db: str = os.getenv("MONGODB_DB", "ryhavean_control_panel")

    master_key: str = os.getenv("MASTER_KEY", "")

    render_api_base: str = os.getenv("RENDER_API_BASE", "https://api.render.com/v1").rstrip("/")
    render_default_region: str = os.getenv("RENDER_DEFAULT_REGION", "oregon")
    render_default_plan: str = os.getenv("RENDER_DEFAULT_PLAN", "free")
    render_template_repo: str = os.getenv("RENDER_TEMPLATE_REPO", "https://github.com/yourname/Ryhavean.git")
    render_template_branch: str = os.getenv("RENDER_TEMPLATE_BRANCH", "main")
    render_template_root_dir: str = os.getenv("RENDER_TEMPLATE_ROOT_DIR", "userbot-template/userbot")
    render_workspace_hint: str = os.getenv("RENDER_WORKSPACE_HINT", "")

    userbot_env_prefix: str = os.getenv("USERBOT_ENV_PREFIX", "ryhavean")
    service_name_prefix: str = os.getenv("SERVICE_NAME_PREFIX", "ryhavean-userbot")
    poll_interval_seconds: int = int(os.getenv("POLL_INTERVAL_SECONDS", "4"))

    start_message: str = os.getenv(
        "START_MESSAGE",
        "Salam, Ryhavean panelinə xoş gəldin. Aşağıdakı düymə ilə mini web app-i açıb öz hazır String Session məlumatlarınla deploy edə bilərsən.",
    )


settings = Settings()
