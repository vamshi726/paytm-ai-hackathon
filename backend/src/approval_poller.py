"""Background polling for authorized email and Telegram approval replies."""
from __future__ import annotations

import imaplib
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone

from .approval_replies import APPROVAL_ID, parse_email_reply, parse_telegram_reply
from .approval_service import apply_channel_decision, expire_pending_approvals
from .database import database
from .email_service import EmailSettings, ImapSettings, fetch_approval_emails
from .telegram_service import (
    TelegramPollingError,
    TelegramSettings,
    get_telegram_updates,
)

logger = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 10


class ApprovalReplyPoller:
    def __init__(self, stop_event: threading.Event):
        self.stop_event = stop_event

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                self.poll_once()
            except imaplib.IMAP4.error as error:
                logger.error("Email reply polling failed (%s)", type(error).__name__)
            except TelegramPollingError as error:
                logger.error("Telegram reply polling failed (%s)", str(error))
            except (sqlite3.Error, OSError, ValueError) as error:
                logger.error("Approval reply polling failed (%s)", type(error).__name__)
            self.stop_event.wait(POLL_INTERVAL_SECONDS)

    def poll_once(self) -> None:
        with database.connection() as conn:
            has_pending = conn.execute(
                "SELECT 1 FROM approval_requests WHERE status='PENDING' LIMIT 1"
            ).fetchone()
        if has_pending:
            pollers = []
            if os.getenv("HITL_EMAIL", "").strip().lower() in {"1", "true", "yes", "on"}:
                pollers.append(("Email", self._poll_email))
            if os.getenv("HITL_TELEGRAM", "").strip().lower() in {"1", "true", "yes", "on"}:
                pollers.append(("Telegram", self._poll_telegram))
            for channel, poll in pollers:
                try:
                    poll()
                except imaplib.IMAP4.error as error:
                    logger.error("%s reply polling failed (%s)", channel, type(error).__name__)
                except TelegramPollingError as error:
                    logger.error("%s reply polling failed (%s)", channel, str(error))
                except (sqlite3.Error, OSError, ValueError) as error:
                    logger.error("%s reply polling failed (%s)", channel, type(error).__name__)
        expire_pending_approvals()

    def _poll_email(self) -> None:
        settings = ImapSettings.from_environment()
        if settings is None:
            logger.error("Email reply polling enabled but IMAP settings are incomplete")
            return

        last_uid = self._get_state("email_uid", "0")
        next_uid, messages = fetch_approval_emails(int(last_uid))
        email_settings = EmailSettings.from_environment()
        allowed_senders = (
            {address.lower() for address in email_settings.recipients}
            if email_settings
            else set()
        )
        for message in messages:
            if message.sender not in allowed_senders:
                self._log_ignored_email(
                    message.subject,
                    message.body,
                    "sender not authorized",
                )
                continue
            reply = parse_email_reply(message.subject, message.body)
            if reply is None:
                approval_ids = set(
                    item.upper()
                    for item in APPROVAL_ID.findall(f"{message.subject}\n{message.body}")
                )
                reason = (
                    "missing or ambiguous approval ID"
                    if len(approval_ids) != 1
                    else "reply must start with APPROVED or REJECTED"
                )
                self._log_ignored_email(
                    message.subject,
                    message.body,
                    reason,
                )
                continue
            result = apply_channel_decision(
                reply.approval_id,
                reply.decision,
                reply.comments,
                f"email:{message.sender}",
                now=message.received_at or datetime.now(timezone.utc),
            )
            if result is None:
                self._log_ignored_email(
                    message.subject,
                    message.body,
                    "approval is not pending",
                )
        self._set_state("email_uid", str(next_uid))

    def _poll_telegram(self) -> None:
        settings = TelegramSettings.from_environment()
        if settings is None:
            logger.error("Telegram reply polling enabled but bot settings are incomplete")
            return

        offset = int(self._get_state("telegram_offset", "0"))
        updates, next_offset = get_telegram_updates(offset)
        for update in updates:
            message = update.get("message")
            if not isinstance(message, dict) or not self._authorized_private_chat(
                message, settings.chat_id
            ):
                continue
            text = message.get("text")
            reply = parse_telegram_reply(text) if isinstance(text, str) else None
            if reply is None:
                self._log_ignored_telegram(message, "missing approval ID, decision, or comments")
                continue
            sender_id = message["from"]["id"]
            result = apply_channel_decision(
                reply.approval_id,
                reply.decision,
                reply.comments,
                f"telegram:{sender_id}",
                now=self._telegram_received_at(message),
            )
            if result is None:
                self._log_ignored_telegram(message, "approval is not pending")
        self._set_state("telegram_offset", str(next_offset))

    @staticmethod
    def _authorized_private_chat(message: dict, configured_chat_id: str) -> bool:
        chat = message.get("chat")
        sender = message.get("from")
        return (
            isinstance(chat, dict)
            and isinstance(sender, dict)
            and chat.get("type") == "private"
            and str(chat.get("id")) == str(configured_chat_id)
            and str(sender.get("id")) == str(configured_chat_id)
        )

    @staticmethod
    def _telegram_received_at(message: dict) -> datetime:
        timestamp = message.get("date")
        if isinstance(timestamp, int) and not isinstance(timestamp, bool):
            return datetime.fromtimestamp(timestamp, timezone.utc)
        return datetime.now(timezone.utc)

    def _log_ignored_email(self, subject: str, body: str, reason: str) -> None:
        self._log_ignored_reply(
            APPROVAL_ID.findall(f"{subject}\n{body}"),
            "email",
            reason,
        )

    def _log_ignored_telegram(self, message: dict, reason: str) -> None:
        self._log_ignored_reply(
            APPROVAL_ID.findall(str(message.get("text", ""))),
            "telegram",
            reason,
        )

    @staticmethod
    def _log_ignored_reply(approval_ids: list[str], channel: str, reason: str) -> None:
        for approval_id in set(item.upper() for item in approval_ids):
            with database.connection() as conn:
                approval = conn.execute(
                    "SELECT case_id FROM approval_requests WHERE id=? AND status='PENDING'",
                    (approval_id,),
                ).fetchone()
                if approval:
                    database.log_activity(
                        conn,
                        approval["case_id"],
                        "APPROVAL_REPLY_IGNORED",
                        f"Ignored {channel} reply: {reason}",
                        "Saathi system",
                    )

    @staticmethod
    def _get_state(key: str, default: str) -> str:
        with database.connection() as conn:
            row = conn.execute(
                "SELECT value FROM notification_state WHERE key=?",
                (key,),
            ).fetchone()
        return row["value"] if row else default

    @staticmethod
    def _set_state(key: str, value: str) -> None:
        with database.connection() as conn:
            conn.execute(
                "INSERT INTO notification_state(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
