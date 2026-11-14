"""Persist and execute channel-confirmed approval decisions."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from .database import database

APPROVAL_WINDOW = timedelta(minutes=20)


def _deadline(approval) -> datetime:
    value = approval["expires_at"]
    if value:
        deadline = datetime.fromisoformat(value)
    else:
        deadline = datetime.fromisoformat(approval["requested_at"]) + APPROVAL_WINDOW
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return deadline.astimezone(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _expire(conn, approval, decision_time: str) -> None:
    message = (
        "The approval window expired without a valid email or Telegram response. "
        "No action was taken; please contact support if you still need help."
    )
    updated = conn.execute(
        "UPDATE approval_requests SET status='EXPIRED',reviewer_id=?,decision_at=?,"
        "reviewer_comments=? WHERE id=? AND status='PENDING'",
        ("system:timeout", decision_time, "No valid response received within 20 minutes", approval["id"]),
    )
    if updated.rowcount != 1:
        return
    conn.execute(
        "UPDATE support_tickets SET status='Escalated',resolution=?,updated_at=? WHERE id=?",
        (message, decision_time, approval["case_id"]),
    )
    conn.execute(
        "INSERT INTO chat_messages VALUES(?,?,?,?,?)",
        (str(uuid.uuid4()), approval["case_id"], "assistant", message, decision_time),
    )
    database.log_activity(
        conn,
        approval["case_id"],
        "APPROVAL_EXPIRED",
        "Approval expired without a valid channel response",
        "Saathi system",
    )


def expire_pending_approvals(now: datetime | None = None) -> int:
    now = _as_utc(now or datetime.now(timezone.utc))
    now_text = now.isoformat()
    expired = 0
    with database.connection() as conn:
        pending = conn.execute(
            "SELECT id,case_id,requested_at,expires_at FROM approval_requests WHERE status='PENDING'"
        ).fetchall()
        for approval in pending:
            if _deadline(approval) <= now:
                _expire(conn, approval, now_text)
                expired += 1
    return expired


def apply_channel_decision(
    approval_id: str,
    decision: str,
    comments: str,
    reviewer: str,
    now: datetime | None = None,
) -> dict | None:
    if decision not in {"APPROVED", "REJECTED"} or len(comments.strip()) > 1000:
        return None

    now = _as_utc(now or datetime.now(timezone.utc))
    decision_time = now.isoformat()
    with database.connection() as conn:
        approval = conn.execute(
            "SELECT * FROM approval_requests WHERE id=?",
            (approval_id,),
        ).fetchone()
        if not approval or approval["status"] != "PENDING":
            return None
        requested_at = _as_utc(datetime.fromisoformat(approval["requested_at"]))
        if now < requested_at:
            return None
        if _deadline(approval) <= now:
            _expire(conn, approval, decision_time)
            return {"status": "EXPIRED", "case_id": approval["case_id"]}

        status = "APPROVED" if decision == "APPROVED" else "REJECTED"
        updated = conn.execute(
            "UPDATE approval_requests SET status=?,reviewer_id=?,decision_at=?,"
            "reviewer_comments=? WHERE id=? AND status='PENDING'",
            (status, reviewer, decision_time, comments.strip(), approval_id),
        )
        if updated.rowcount != 1:
            return None

        case_id = approval["case_id"]
        if decision == "APPROVED":
            reference = f"REF-{uuid.uuid4().hex[:6].upper()}"
            conn.execute(
                "INSERT INTO execution_records VALUES(?,?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    case_id,
                    approval_id,
                    approval["proposed_action"],
                    approval_id,
                    "EXECUTED",
                    reference,
                    decision_time,
                ),
            )
            reply = (
                "Your request was reviewed and the simulated action has been initiated. "
                f"Reference: {reference}."
            )
            ticket_status = "Resolved"
        else:
            reply = (
                "Your request was reviewed and was not approved. Our support team will "
                "continue investigating and update this case."
            )
            ticket_status = "Escalated"

        conn.execute(
            "UPDATE support_tickets SET status=?,resolution=?,updated_at=? WHERE id=?",
            (ticket_status, reply, decision_time, case_id),
        )
        conn.execute(
            "INSERT INTO chat_messages VALUES(?,?,?,?,?)",
            (str(uuid.uuid4()), case_id, "assistant", reply, decision_time),
        )
        description = f"Decision received via {reviewer}"
        if comments.strip():
            description += f": {comments.strip()}"
        database.log_activity(
            conn,
            case_id,
            f"APPROVAL_{decision}",
            description,
            reviewer,
        )
        return {"status": ticket_status, "case_id": case_id, "message": reply}
