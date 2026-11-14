"""Best-effort SMTP notifications for human approval requests."""
from __future__ import annotations

import os
import imaplib
import smtplib
from dataclasses import dataclass
from datetime import datetime, timezone
from email import message_from_bytes
from email.message import EmailMessage
from email.policy import default
from email.utils import parseaddr, parsedate_to_datetime
from html import escape, unescape
import re


def is_enabled(value: str | None) -> bool:
    return (value or "false").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class EmailSettings:
    host: str
    port: int
    username: str
    password: str
    sender: str
    recipients: tuple[str, ...]
    use_tls: bool

    @classmethod
    def from_environment(cls) -> "EmailSettings | None":
        if not is_enabled(os.getenv("HITL_EMAIL")):
            return None
        # HITL_APPROVER_EMAILS supports multiple recipients; the legacy singular
        # key remains supported to avoid breaking existing .env files.
        raw = os.getenv("HITL_APPROVER_EMAILS") or os.getenv("HITL_APPROVER_EMAIL", "")
        recipients = tuple(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))
        host, sender = os.getenv("SMTP_HOST", ""), os.getenv("SMTP_FROM", "")
        if not host or not sender or not recipients:
            return None
        try:
            port = int(os.getenv("SMTP_PORT", "587"))
        except ValueError:
            return None
        return cls(host, port, os.getenv("SMTP_USERNAME", ""), os.getenv("SMTP_PASSWORD", ""), sender, recipients, is_enabled(os.getenv("SMTP_USE_TLS", "true")))

@dataclass(frozen=True)
class ImapSettings:
    host: str
    port: int
    username: str
    password: str
    folder: str

    @classmethod
    def from_environment(cls) -> "ImapSettings | None":
        if not is_enabled(os.getenv("HITL_EMAIL")):
            return None
        smtp_host = os.getenv("SMTP_HOST", "").strip().lower()
        host = os.getenv("IMAP_HOST", "").strip()
        if not host and smtp_host == "smtp.gmail.com":
            host = "imap.gmail.com"
        username = os.getenv("IMAP_USERNAME") or os.getenv("SMTP_USERNAME", "")
        password = os.getenv("IMAP_PASSWORD") or os.getenv("SMTP_PASSWORD", "")
        if not host or not username or not password:
            return None
        try:
            port = int(os.getenv("IMAP_PORT", "993"))
        except ValueError:
            return None
        return cls(host, port, username, password, os.getenv("IMAP_FOLDER", "INBOX"))


@dataclass(frozen=True)
class IncomingEmail:
    uid: int
    sender: str
    subject: str
    body: str
    received_at: datetime | None = None


def fetch_approval_emails(after_uid: int) -> tuple[int, list[IncomingEmail]]:
    """Fetch new inbox messages by UID; the caller filters and processes replies."""
    settings = ImapSettings.from_environment()
    if settings is None:
        return after_uid, []

    mailbox = imaplib.IMAP4_SSL(settings.host, settings.port, timeout=10)
    try:
        mailbox.login(settings.username, settings.password)
        status, _ = mailbox.select(settings.folder)
        if status != "OK":
            raise imaplib.IMAP4.error("Could not select the configured IMAP folder")
        status, data = mailbox.uid("search", None, f"UID {after_uid + 1}:*")
        if status != "OK":
            raise imaplib.IMAP4.error("Could not search the configured IMAP folder")

        uids = [int(value) for value in (data[0] or b"").split()]
        messages = []
        for uid in uids:
            status, fetched = mailbox.uid("fetch", str(uid), "(INTERNALDATE RFC822)")
            if status != "OK":
                raise imaplib.IMAP4.error("Could not fetch an IMAP message")
            response = next((item for item in fetched if isinstance(item, tuple)), None)
            if response is None or not response[1]:
                continue
            raw = response[1]
            internal_date = re.search(rb'INTERNALDATE "([^"]+)"', response[0])
            received_at = (
                parsedate_to_datetime(internal_date.group(1).decode("ascii"))
                if internal_date
                else None
            )
            if received_at and received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=timezone.utc)
            message = message_from_bytes(raw, policy=default)
            body = _email_body(message)
            messages.append(
                IncomingEmail(
                    uid=uid,
                    sender=parseaddr(str(message.get("From", "")))[1].lower(),
                    subject=str(message.get("Subject", "")),
                    body=body,
                    received_at=received_at,
                )
            )
        return (max(uids) if uids else after_uid), messages
    finally:
        mailbox.logout()


def _email_body(message) -> str:
    plain_parts = []
    html_parts = []
    parts = message.walk() if message.is_multipart() else (message,)
    for part in parts:
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        try:
            content = part.get_content()
        except (LookupError, UnicodeError):
            continue
        if not isinstance(content, str):
            continue
        if content_type == "text/plain":
            plain_parts.append(content)
        else:
            html_parts.append(content)
    if plain_parts:
        return "\n".join(plain_parts)
    html = "\n".join(html_parts)
    return re.sub(r"<[^>]+>", " ", unescape(html))


def send_approval_email(
    case_id: str,
    approval_id: str,
    action: str,
    risk: str,
    expires_at: str,
) -> tuple[bool, str]:
    """Send an approval request with an explicit, parseable reply format."""
    settings = EmailSettings.from_environment()
    if settings is None:
        return False, "Email notifications are disabled or incomplete"
    message = EmailMessage()
    message["Subject"] = f"[SAATHI {approval_id}] Approval required — {case_id}"
    message["From"] = settings.sender
    message["Reply-To"] = settings.username or settings.sender
    message["To"] = ", ".join(settings.recipients)
    message.set_content(
        f"Hello,\n\n"
        "A human decision is required for this Saathi support case.\n\n"
        f"Case: {case_id}\nApproval ID: {approval_id}\nRisk: {risk}\n"
        f"Proposed action: {action}\nReply deadline (UTC): {expires_at}\n\n"
        "To respond, reply to this email and put these lines above the quoted message:\n\n"
        "Decision: APPROVED\n"
        "Comments: [Optional]\n\n"
        "Or reject using:\n\n"
        "Decision: REJECTED\n"
        "Comments: [Optional]\n\n"
        "The decision is accepted only from a configured approver email address, "
        "with this approval ID and an explicit decision. Comments are optional. The request expires after "
        "20 minutes. No action is taken unless a valid APPROVED reply is received "
        "before the deadline."
    )
    message.add_alternative(
        f"""\
<!doctype html>
<html>
  <body style="margin:0;background:#f3f6fa;font-family:Arial,sans-serif;color:#17324d">
    <div style="max-width:620px;margin:28px auto;background:#ffffff;border:1px solid #dfe7ef;border-radius:12px;overflow:hidden">
      <div style="padding:22px 26px;background:#082f5f;color:#ffffff">
        <div style="font-size:12px;letter-spacing:1.5px;color:#b9e8f4">SAATHI · HUMAN REVIEW</div>
        <h1 style="font-size:22px;margin:10px 0 0">Approval requested</h1>
      </div>
      <div style="padding:24px 26px">
        <p style="margin-top:0">A support action is waiting for your decision.</p>
        <table style="width:100%;border-collapse:collapse;font-size:14px">
          <tr><td style="padding:9px;color:#657b90">Case</td><td style="padding:9px;font-weight:bold">{escape(case_id)}</td></tr>
          <tr><td style="padding:9px;color:#657b90">Approval ID</td><td style="padding:9px;font-weight:bold">{escape(approval_id)}</td></tr>
          <tr><td style="padding:9px;color:#657b90">Risk</td><td style="padding:9px">{escape(risk)}</td></tr>
          <tr><td style="padding:9px;color:#657b90">Proposed action</td><td style="padding:9px">{escape(action)}</td></tr>
          <tr><td style="padding:9px;color:#657b90">Reply deadline (UTC)</td><td style="padding:9px">{escape(expires_at)}</td></tr>
        </table>
        <div style="margin-top:20px;padding:16px;background:#f1f8fc;border-left:4px solid #1aa9c5">
          <strong>Reply to this email with one of these formats:</strong>
          <pre style="white-space:pre-wrap;background:#ffffff;padding:12px;border:1px solid #dfe7ef;border-radius:6px">Decision: APPROVED
Comments: [Optional]</pre>
          <p style="margin:12px 0 5px">Or reject the request:</p>
          <pre style="white-space:pre-wrap;background:#ffffff;padding:12px;border:1px solid #dfe7ef;border-radius:6px">Decision: REJECTED
Comments: [Optional]</pre>
        </div>
        <p style="font-size:13px;color:#526b80">Only a configured approver address can decide. Keep the approval ID in the subject. Comments are optional. This request expires after 20 minutes. No action will be taken without a valid APPROVED reply before then.</p>
      </div>
      <div style="padding:14px 26px;background:#f7f9fb;color:#72869a;font-size:12px">This is an automated Saathi approval request. Replies are processed only for this pending case.</div>
    </div>
  </body>
</html>""",
        subtype="html",
    )
    try:
        with smtplib.SMTP(settings.host, settings.port, timeout=10) as smtp:
            if settings.use_tls:
                smtp.starttls()
            if settings.username:
                smtp.login(settings.username, settings.password)
            refused = smtp.send_message(message)
        if refused:
            return False, f"Email server refused delivery to {len(refused)} recipient(s)"
        return True, f"Approval email sent to {len(settings.recipients)} reviewer(s)"
    except (OSError, smtplib.SMTPException) as error:
        return False, f"Email delivery failed: {type(error).__name__}"
