"""Strict, auditable parsing for email approval replies."""
from __future__ import annotations

import re
from dataclasses import dataclass


APPROVAL_ID = re.compile(r"\bAPR-[A-Z0-9-]+\b", re.IGNORECASE)
DECISION_LINE = re.compile(
    r"^\s*(?:decision\s*:\s*|i\s+)?(approved|approve|rejected|reject)\b\s*(.*)$",
    re.IGNORECASE,
)
COMMENTS_LINE = re.compile(r"^\s*comments\s*:\s*(.*)$", re.IGNORECASE)
QUOTED_REPLY = re.compile(
    r"^\s*(?:>{1,}|-{2,}\s*original message|on .+wrote:|from:\s)",
    re.IGNORECASE,
)
@dataclass(frozen=True)
class ApprovalReply:
    approval_id: str
    decision: str
    comments: str


def _clean_comments(value: str) -> str | None:
    comments = value.strip()
    if not comments:
        return ""
    if len(comments) < 3 or len(comments) > 1000:
        return None
    if (
        (comments.startswith("[") and comments.endswith("]"))
        or (comments.startswith("<") and comments.endswith(">"))
        or comments.casefold().startswith("explain the evidence or reason for your decision")
    ):
        return ""
    return comments


def _reply_text(body: str) -> str:
    lines = []
    for line in body.splitlines():
        if QUOTED_REPLY.match(line):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def parse_email_reply(subject: str, body: str) -> ApprovalReply | None:
    text = _reply_text(body)
    ids = {value.upper() for value in APPROVAL_ID.findall(f"{subject}\n{body}")}
    if len(ids) != 1:
        return None

    lines = text.splitlines()
    decision_index = next((index for index, line in enumerate(lines) if line.strip()), None)
    if decision_index is None:
        return None
    decision_match = DECISION_LINE.match(lines[decision_index])
    if not decision_match:
        return None
    decision = (
        "APPROVED"
        if decision_match.group(1).lower() in {"approve", "approved"}
        else "REJECTED"
    )
    inline_comments = re.sub(
        r"^(?:with\s+comments?\s*:?\s*|comments?\s*:?\s*|because\s+)",
        "",
        decision_match.group(2),
        flags=re.IGNORECASE,
    ).lstrip(" \t:;,.—–-")
    remaining = [line for line in lines[decision_index + 1 :] if line.strip()]
    if remaining:
        labeled = COMMENTS_LINE.match(remaining[0])
        if labeled:
            remaining[0] = labeled.group(1)
    comments = "\n".join(
        part for part in [inline_comments, *remaining] if part.strip()
    ).strip()

    cleaned = _clean_comments(comments)
    if cleaned is None:
        return None
    return ApprovalReply(ids.pop(), decision, cleaned)
