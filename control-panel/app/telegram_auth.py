from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from urllib.parse import parse_qsl

from config import settings


class TelegramAuthError(ValueError):
    pass


def validate_init_data(init_data: str) -> dict[str, Any]:
    if not init_data:
        raise TelegramAuthError("Telegram initData boşdur")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", "")
    if not received_hash:
        raise TelegramAuthError("Telegram hash tapılmadı")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", settings.telegram_bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise TelegramAuthError("Telegram initData doğrulanmadı")

    user_raw = pairs.get("user")
    if not user_raw:
        raise TelegramAuthError("Telegram user payload yoxdur")

    user = json.loads(user_raw)
    return {
        "user": user,
        "chat_type": pairs.get("chat_type", ""),
        "chat_instance": pairs.get("chat_instance", ""),
        "start_param": pairs.get("start_param", ""),
        "auth_date": pairs.get("auth_date", ""),
        "query_id": pairs.get("query_id", ""),
        "raw": init_data,
    }
