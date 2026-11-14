import os
os.environ["HITL_EMAIL"] = "false"  # Never send real messages during unit tests.
os.environ["HITL_TELEGRAM"] = "false"  # Never send real messages during unit tests.
import json
import sqlite3
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend.src.database import database

_TEST_DATABASE_DIRECTORY = tempfile.TemporaryDirectory(prefix="saathi-tests-")
database.path = Path(_TEST_DATABASE_DIRECTORY.name) / "saathi.db"

from backend.src.main import app
from backend.src.email_service import EmailSettings
from backend.src import api as api_module
from backend.src import openai_responses
from backend.src import telegram_service
from backend.src import email_service
from backend.src import approval_poller as approval_poller_module
from backend.src.approval_replies import parse_email_reply, parse_telegram_reply
from backend.src.approval_service import apply_channel_decision, expire_pending_approvals
from backend.src.approval_poller import ApprovalReplyPoller
from backend.src.email_service import ImapSettings, IncomingEmail

client = TestClient(app)

@pytest.fixture(autouse=True)
def isolate_database_and_avoid_live_openai_requests(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "path", tmp_path / "saathi.db")
    database.initialise()
    monkeypatch.setattr(
        api_module.response_agent,
        "respond",
        lambda customer_message, outcome, playbooks=(): outcome["reply"],
    )

def test_failed_debit_uses_local_markdown_rag_and_resolves():
    response = client.post("/api/chat/message", json={"message": "My ₹799 payment failed but I was debited"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "Resolved"
    assert body["approval"] is None
    assert "payment_playbooks.md" in body["rag_sources"]
    assert "reversal is already pending" in body["message"].lower()

def test_duplicate_charge_waits_for_channel_reply_not_dashboard_decision():
    created = client.post("/api/chat/message", json={"message": "I was charged twice ₹5,000"}).json()
    assert created["status"] == "Awaiting approval"
    approval_id = created["approval"]["id"]
    assert created["approval"]["expires_at"]
    assert client.post(f"/api/approvals/{approval_id}/approve", json={"comments": "Duplicate debit confirmed"}).status_code == 404
    assert client.post(f"/api/approvals/{approval_id}/reject", json={"comments": "Not approved"}).status_code == 404

    decided = apply_channel_decision(
        approval_id,
        "APPROVED",
        "Duplicate debit verified by reviewer",
        "email:approver@example.test",
    )
    assert decided is not None
    assert decided["status"] == "Resolved"
    assert apply_channel_decision(
        approval_id,
        "APPROVED",
        "Duplicate attempt",
        "email:approver@example.test",
    ) is None

def test_ambiguous_message_requests_transaction_details():
    response = client.post("/api/chat/message", json={"message": "My payment is missing"})
    assert response.status_code == 200
    assert response.json()["status"] == "More details needed"

def test_multiple_email_recipients_are_parsed(monkeypatch):
    monkeypatch.setenv("HITL_EMAIL", "true")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_FROM", "saathi@example.test")
    monkeypatch.setenv("HITL_APPROVER_EMAILS", "lead@example.test, finance@example.test,lead@example.test")
    settings = EmailSettings.from_environment()
    assert settings is not None
    assert settings.recipients == ("lead@example.test", "finance@example.test")

def test_gmail_imap_defaults_to_inbox_endpoint(monkeypatch):
    monkeypatch.setenv("HITL_EMAIL", "true")
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_USERNAME", "mailbox@example.test")
    monkeypatch.setenv("SMTP_PASSWORD", "test-password")
    monkeypatch.delenv("IMAP_HOST", raising=False)
    monkeypatch.delenv("IMAP_USERNAME", raising=False)
    monkeypatch.delenv("IMAP_PASSWORD", raising=False)

    settings = ImapSettings.from_environment()

    assert settings is not None
    assert settings.host == "imap.gmail.com"
    assert settings.port == 993
    assert settings.username == "mailbox@example.test"

def test_email_request_contains_reply_template_and_html(monkeypatch):
    monkeypatch.setenv("HITL_EMAIL", "true")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_FROM", "saathi@example.test")
    monkeypatch.setenv("SMTP_USERNAME", "mailbox@example.test")
    monkeypatch.setenv("HITL_APPROVER_EMAIL", "approver@example.test")
    captured = {}

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def starttls(self):
            pass

        def login(self, *args):
            pass

        def send_message(self, message):
            captured["message"] = message
            return {}

    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)
    sent, _ = email_service.send_approval_email(
        "CASE-TEST",
        "APR-TEST",
        "Simulated refund",
        "HIGH",
        "2026-01-01T00:20:00+00:00",
    )

    assert sent is True
    message = captured["message"]
    assert message["Reply-To"] == "mailbox@example.test"
    assert "APR-TEST" in message["Subject"]
    assert "Decision: APPROVED" in message.get_body(preferencelist=("plain",)).get_content()
    assert message.get_body(preferencelist=("html",)).get_content_subtype() == "html"

def test_telegram_notification_posts_approval_to_configured_chat(monkeypatch):
    monkeypatch.setenv("HITL_TELEGRAM", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "test-chat")
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"ok":true}'

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(telegram_service, "urlopen", fake_urlopen)
    sent, detail = telegram_service.send_approval_telegram(
        "CASE-TEST",
        "APR-TEST",
        "Simulated refund",
        "HIGH",
        "2026-01-01T00:20:00+00:00",
    )

    assert sent is True
    assert "sent" in detail
    assert captured["timeout"] == 10
    assert captured["request"].get_method() == "POST"
    payload = json.loads(captured["request"].data)
    assert payload["chat_id"] == "test-chat"
    assert "APR-TEST" in payload["text"]
    assert "No action is taken" in payload["text"]

def test_approval_response_reports_email_and_telegram_delivery(monkeypatch):
    monkeypatch.setattr(
        api_module,
        "send_approval_email",
        lambda *args: (True, "Email accepted"),
    )
    monkeypatch.setattr(
        api_module,
        "send_approval_telegram",
        lambda *args: (False, "Telegram rejected the notification"),
    )

    response = client.post(
        "/api/chat/message",
        json={"message": "I was charged twice ₹5,000"},
    )

    assert response.status_code == 200
    approval = response.json()["approval"]
    assert approval["notification_sent"] is True
    assert approval["email_notification_sent"] is True
    assert approval["telegram_notification_sent"] is False

def test_email_approval_reply_requires_id_decision_and_comments():
    reply = parse_email_reply(
        "Re: [SAATHI APR-AB12CD34] Approval required — CASE-TEST",
        "Decision: APPROVED\nComments: Duplicate payment verified.\n\n"
        "On Tue, approver wrote:\n> Decision: REJECTED",
    )
    assert reply is not None
    assert reply.approval_id == "APR-AB12CD34"
    assert reply.decision == "APPROVED"
    assert reply.comments == "Duplicate payment verified."
    placeholder_reply = parse_email_reply(
        "[SAATHI APR-AB12CD34] Approval required",
        "Decision: APPROVED\nComments: [reason]",
    )
    assert placeholder_reply is not None
    assert placeholder_reply.comments == ""
    natural_reply = parse_email_reply(
        "Re: [SAATHI APR-AB12CD34] Approval required",
        "Approved with comments: duplicate was verified.",
    )
    assert natural_reply is not None
    assert natural_reply.comments == "duplicate was verified."
    assert parse_email_reply(
        "[SAATHI APR-AB12CD34] Approval required",
        "Looks good.\n\nOn Tue, approver wrote:\n"
        "Decision: APPROVED\nComments: Verified.",
    ) is None

def test_telegram_reply_requires_approval_id_and_comments():
    reply = parse_telegram_reply("APPROVED APR-AB12CD34 Verified duplicate charge")
    assert reply is not None
    assert reply.approval_id == "APR-AB12CD34"
    assert reply.decision == "APPROVED"
    assert reply.comments == "Verified duplicate charge"
    no_comment_reply = parse_telegram_reply("REJECTED APR-AB12CD34")
    assert no_comment_reply is not None
    assert no_comment_reply.comments == ""

def test_authorized_email_reply_is_processed_by_poller(monkeypatch):
    monkeypatch.setenv("HITL_EMAIL", "true")
    monkeypatch.setenv("HITL_APPROVER_EMAIL", "approver@example.test")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_FROM", "saathi@example.test")
    monkeypatch.setenv("SMTP_USERNAME", "mailbox@example.test")
    monkeypatch.setenv("SMTP_PASSWORD", "test-password")
    monkeypatch.setenv("IMAP_HOST", "imap.example.test")
    monkeypatch.setattr(api_module, "send_approval_email", lambda *args: (True, "sent"))
    monkeypatch.setattr(api_module, "send_approval_telegram", lambda *args: (False, "disabled"))
    created = client.post(
        "/api/chat/message",
        json={"message": "I was charged twice ₹5,000"},
    ).json()
    approval_id = created["approval"]["id"]
    monkeypatch.setattr(
        "backend.src.approval_poller.fetch_approval_emails",
        lambda uid: (
            1,
            [
                IncomingEmail(
                    1,
                    "approver@example.test",
                    f"Re: [SAATHI {approval_id}] Approval required",
                    "Decision: APPROVED\nComments: Duplicate payment verified.",
                )
            ],
        ),
    )

    ApprovalReplyPoller(threading.Event())._poll_email()

    with sqlite3.connect(database.path) as conn:
        status = conn.execute(
            "SELECT status FROM approval_requests WHERE id=?",
            (approval_id,),
        ).fetchone()[0]
    assert status == "APPROVED"

def test_authorized_private_telegram_reply_is_processed_by_poller(monkeypatch):
    monkeypatch.setenv("HITL_TELEGRAM", "true")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setattr(api_module, "send_approval_email", lambda *args: (False, "disabled"))
    monkeypatch.setattr(api_module, "send_approval_telegram", lambda *args: (True, "sent"))
    created = client.post(
        "/api/chat/message",
        json={"message": "I was charged twice ₹5,000"},
    ).json()
    approval_id = created["approval"]["id"]
    monkeypatch.setattr(
        "backend.src.approval_poller.get_telegram_updates",
        lambda offset: (
            [
                {
                    "update_id": 25,
                    "message": {
                        "chat": {"id": 12345, "type": "private"},
                        "from": {"id": 12345},
                        "text": f"REJECTED {approval_id} Duplicate was not confirmed",
                    },
                }
            ],
            26,
        ),
    )

    ApprovalReplyPoller(threading.Event())._poll_telegram()

    with sqlite3.connect(database.path) as conn:
        status = conn.execute(
            "SELECT status FROM approval_requests WHERE id=?",
            (approval_id,),
        ).fetchone()[0]
    assert status == "REJECTED"


def test_email_received_before_deadline_is_accepted_when_polled_late(monkeypatch):
    monkeypatch.setenv("HITL_EMAIL", "true")
    monkeypatch.setenv("HITL_TELEGRAM", "false")
    monkeypatch.setenv("HITL_APPROVER_EMAIL", "approver@example.test")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_FROM", "saathi@example.test")
    monkeypatch.setenv("SMTP_USERNAME", "mailbox@example.test")
    monkeypatch.setenv("SMTP_PASSWORD", "test-password")
    monkeypatch.setenv("IMAP_HOST", "imap.example.test")
    monkeypatch.setattr(api_module, "send_approval_email", lambda *args: (True, "sent"))
    monkeypatch.setattr(api_module, "send_approval_telegram", lambda *args: (False, "disabled"))
    created = client.post(
        "/api/chat/message",
        json={"message": "I was charged twice ₹5,000"},
    ).json()
    approval_id = created["approval"]["id"]
    deadline = datetime.now(timezone.utc) - timedelta(seconds=1)
    received_at = deadline - timedelta(seconds=1)
    requested_at = deadline - timedelta(minutes=20)
    with database.connection() as conn:
        conn.execute(
            "UPDATE approval_requests SET requested_at=?,expires_at=? WHERE id=?",
            (requested_at.isoformat(), deadline.isoformat(), approval_id),
        )
    monkeypatch.setattr(
        approval_poller_module,
        "fetch_approval_emails",
        lambda uid: (
            1,
            [
                IncomingEmail(
                    1,
                    "approver@example.test",
                    f"Re: [SAATHI {approval_id}] Approval required",
                    "Decision: APPROVED\nComments: Verified before deadline.",
                    received_at,
                )
            ],
        ),
    )

    ApprovalReplyPoller(threading.Event()).poll_once()

    with database.connection() as conn:
        approval = conn.execute(
            "SELECT status,decision_at FROM approval_requests WHERE id=?",
            (approval_id,),
        ).fetchone()
    assert approval["status"] == "APPROVED"
    assert approval["decision_at"] == received_at.isoformat()

def test_approval_is_committed_before_notification_delivery(monkeypatch):
    observed = {}

    def reply_during_send(case_id, approval_id, action, risk, expires_at):
        observed["decision"] = apply_channel_decision(
            approval_id,
            "APPROVED",
            "Verified before notification completed",
            "email:approver@example.test",
        )
        return True, "sent"

    monkeypatch.setattr(api_module, "send_approval_email", reply_during_send)
    monkeypatch.setattr(api_module, "send_approval_telegram", lambda *args: (False, "disabled"))

    response = client.post(
        "/api/chat/message",
        json={"message": "I was charged twice ₹5,000"},
    )

    assert response.status_code == 200
    assert observed["decision"]["status"] == "Resolved"

def test_unanswered_approval_expires_without_executing():
    created = client.post(
        "/api/chat/message",
        json={"message": "I was charged twice ₹5,000"},
    ).json()
    approval_id = created["approval"]["id"]
    deadline = datetime.fromisoformat(created["approval"]["expires_at"])
    assert expire_pending_approvals(deadline - timedelta(seconds=1)) == 0
    with sqlite3.connect(database.path) as conn:
        status = conn.execute(
            "SELECT status FROM approval_requests WHERE id=?",
            (approval_id,),
        ).fetchone()[0]
    assert status == "PENDING"
    assert expire_pending_approvals(deadline) == 1

    with sqlite3.connect(database.path) as conn:
        status = conn.execute(
            "SELECT status FROM approval_requests WHERE id=?",
            (approval_id,),
        ).fetchone()[0]
        executions = conn.execute(
            "SELECT COUNT(*) FROM execution_records WHERE approval_id=?",
            (approval_id,),
        ).fetchone()[0]
    assert status == "EXPIRED"
    assert executions == 0
    assert apply_channel_decision(
        approval_id,
        "APPROVED",
        "Late approval after timeout",
        "telegram:123",
    ) is None

def test_openai_response_agent_uses_configured_model_and_grounded_draft(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    requests = []

    from langchain_core.runnables import RunnableLambda

    def fake_chat_openai(**kwargs):
        requests.append(kwargs)
        return RunnableLambda(
            lambda prompt_value: (
                requests.append({"prompt": prompt_value.to_string()})
                or "Your payment reversal is pending."
            )
        )

    monkeypatch.setattr(openai_responses, "ChatOpenAI", fake_chat_openai)
    outcome = {
        "reply": "The reversal is pending.",
        "status": "Resolved",
        "approval_required": False,
    }

    reply = openai_responses.OpenAIResponseAgent().respond(
        "Where is my payment?",
        outcome,
        [{"source": "payment_playbooks.md", "content": "Reversal pending."}],
    )

    assert reply == "Your payment reversal is pending."
    assert requests[0]["model"] == "test-model"
    assert requests[0]["api_key"] == "test-key"
    assert "Reversal pending." in requests[1]["prompt"]

def test_openai_response_agent_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(HTTPException) as error:
        openai_responses.OpenAIResponseAgent().respond(
            "Where is my payment?",
            {"reply": "Please share more details.", "status": "More details needed", "approval_required": False},
        )

    assert error.value.status_code == 503

def test_api_lifespan_starts_approval_poller_without_network_when_disabled(monkeypatch):
    monkeypatch.setenv("HITL_EMAIL", "false")
    monkeypatch.setenv("HITL_TELEGRAM", "false")

    with TestClient(app) as running_client:
        response = running_client.get("/api/health")

    assert response.status_code == 200
