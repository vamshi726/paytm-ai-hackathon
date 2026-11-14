"""Telegram notifications for human approval requests."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlencode


def is_enabled(value: str | None) -> bool:
    return (value or "false").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class TelegramSettings:
    bot_token: str
    chat_id: str

    @classmethod
    def from_environment(cls) -> "TelegramSettings | None":
        if not is_enabled(os.getenv("HITL_TELEGRAM")):
            return None
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat_id:
            return None
        return cls(token, chat_id)


def _http_error_detail(error: HTTPError) -> str:
    try:
        body = json.loads(error.read().decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        body = None
    description = body.get("description") if isinstance(body, dict) else None
    if description:
        return f"HTTP {error.code}: {str(description)[:140]}"
    return f"HTTP {error.code}"


def send_approval_telegram(
    case_id: str,
    approval_id: str,
    action: str,
    risk: str,
    expires_at: str,
) -> tuple[bool, str]:
    """Send an approval card and precise reply instructions to the approver chat."""
    settings = TelegramSettings.from_environment()
    if settings is None:
        return False, "Telegram notifications are disabled or incomplete"

    request = Request(
        f"https://api.telegram.org/bot{settings.bot_token}/sendMessage",
        data=json.dumps(
            {
                "chat_id": settings.chat_id,
                "text": (
                    "Saathi human approval required\n\n"
                    f"Case: {case_id}\n"
                    f"Approval: {approval_id}\n"
                    f"Risk: {risk}\n"
                    f"Proposed action: {action}\n\n"
                    f"Reply deadline (UTC): {expires_at}\n\n"
                    f"To approve, send: APPROVED {approval_id} [optional comments]\n"
                    f"To reject, send: REJECTED {approval_id} [optional comments]\n\n"
                    "Only replies from this private bot chat are accepted. "
                    "Comments are optional. No action is taken without a valid "
                    "APPROVED reply before the 20-minute deadline."
                ),
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return False, f"Telegram delivery failed ({_http_error_detail(error)})"
    except (OSError, URLError, json.JSONDecodeError) as error:
        return False, f"Telegram delivery failed: {type(error).__name__}"

    if not isinstance(result, dict) or result.get("ok") is not True:
        return False, "Telegram rejected the approval notification"
    return True, "Approval notification sent to Telegram"


class TelegramPollingError(Exception):
    """A safe, non-secret error while receiving bot updates."""


def get_telegram_updates(offset: int) -> tuple[list[dict], int]:
    settings = TelegramSettings.from_environment()
    if settings is None:
        return [], offset

    url = (
        f"https://api.telegram.org/bot{settings.bot_token}/getUpdates?"
        + urlencode({"offset": offset, "timeout": 5, "allowed_updates": '["message"]'})
    )
    try:
        with urlopen(url, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise TelegramPollingError(
            f"Telegram polling failed ({_http_error_detail(error)})"
        ) from error
    except (OSError, URLError, json.JSONDecodeError) as error:
        raise TelegramPollingError(type(error).__name__) from error

    if not isinstance(result, dict) or result.get("ok") is not True:
        description = result.get("description") if isinstance(result, dict) else None
        message = str(description or "Telegram getUpdates was rejected")
        raise TelegramPollingError(message[:160])
    updates = result.get("result")
    if not isinstance(updates, list):
        raise TelegramPollingError("Telegram returned an invalid update list")
    next_offset = max(
        (int(update["update_id"]) + 1 for update in updates if "update_id" in update),
        default=offset,
    )
    return updates, next_offset
