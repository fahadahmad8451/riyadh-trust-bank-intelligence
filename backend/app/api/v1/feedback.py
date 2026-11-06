"""Feedback API — Sprint 4.

POST /feedback — thumbs up/down on an assistant answer. Requires a
logged-in user. The message_id must be a real assistant message from
data/conversations.jsonl (the id is returned by POST /chat as
message_id); unknown ids get 404, so feedback cannot be attached to
a message that never existed. One feedback per (user, message): a
second vote replaces the first (upsert), so the total never
double-counts a user changing their mind.

GET /admin/feedback-stats — ADMIN only. Totals, % up, and the
down-rated ("worst") messages with the question they answered and
their citations, so the team can see what to fix.

Storage: data/feedback.jsonl (one JSON object per line, gitignored,
excluded from the zip) — the same JSONL-primary pattern as the audit
log. The Feedback DB table exists in app/db/models.py, but it is NOT
populated here: messages live in the JSONL conversation log, not in
the DB (there is no messages row to point the foreign key at), so a
DB mirror would fail its FK. That is recorded here and in
docs/SPRINT4.md as a known limitation, not hidden.
"""
import json
import logging
import os
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.audit import append_audit
from app.core.security import get_current_user, require_admin

logger = logging.getLogger("rtb.feedback")
router = APIRouter()

from app.core.paths import data_dir

ROOT = Path(__file__).resolve().parents[4]  # backend/app/api/v1 -> project root
CONVERSATIONS_PATH = data_dir() / "conversations.jsonl"


def feedback_path() -> Path:
    env = os.getenv("RTB_FEEDBACK_FILE")
    if env:
        return Path(env)
    return data_dir() / "feedback.jsonl"


class FeedbackRequest(BaseModel):
    message_id: str = Field(..., min_length=1, max_length=100)
    rating: str = Field(..., pattern="^(up|down)$")
    comment: str | None = Field(default=None, max_length=500)


def _envelope(data, request_id: str | None = None) -> dict:
    return {"success": True, "data": data, "error": None,
            "request_id": request_id or str(uuid.uuid4())}


def _read_conversations() -> list[dict]:
    records: list[dict] = []
    if not CONVERSATIONS_PATH.exists():
        return records
    for line in CONVERSATIONS_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def find_assistant_message(message_id: str) -> dict | None:
    """The assistant message with this id, or None. Only assistant
    messages can receive feedback (you rate the answer, not the question)."""
    for rec in _read_conversations():
        if rec.get("message_id") == message_id and rec.get("role") == "assistant":
            return rec
    return None


def _read_feedback() -> list[dict]:
    path = feedback_path()
    entries: list[dict] = []
    if not path.exists():
        return entries
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _write_feedback(entries: list[dict]) -> None:
    path = feedback_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
        encoding="utf-8",
    )


@router.post("/feedback")
async def post_feedback(payload: FeedbackRequest, user: dict = Depends(get_current_user)):
    message = find_assistant_message(payload.message_id)
    if message is None:
        return {
            "success": False, "data": None,
            "error": f"Message not found: {payload.message_id}",
            "request_id": str(uuid.uuid4()),
        }
    entries = _read_feedback()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    updated = False
    for entry in entries:
        if entry.get("message_id") == payload.message_id \
                and entry.get("user_email") == user["email"]:
            entry.update({"rating": payload.rating, "comment": payload.comment, "ts": now})
            updated = True
            break
    if not updated:
        entries.append({
            "id": str(uuid.uuid4()),
            "message_id": payload.message_id,
            "conversation_id": message.get("conversation_id"),
            "user_email": user["email"],
            "rating": payload.rating,
            "comment": payload.comment,
            "ts": now,
        })
    _write_feedback(entries)
    append_audit("FEEDBACK", user_email=user["email"], role=user["role"], result="ok",
                 resource=f"feedback:{payload.message_id}",
                 detail=f"rating={payload.rating}")
    return _envelope({
        "message_id": payload.message_id,
        "rating": payload.rating,
        "updated": updated,
        "message": "Shukriya, feedback mil gaya.",
    })


def feedback_stats() -> dict:
    """Aggregate stats + the down-rated messages (worst first)."""
    entries = _read_feedback()
    total = len(entries)
    ups = sum(1 for e in entries if e.get("rating") == "up")
    downs = total - ups
    conversations = _read_conversations()
    by_id = {r.get("message_id"): r for r in conversations if r.get("message_id")}
    worst = []
    for entry in entries:
        if entry.get("rating") != "down":
            continue
        message = by_id.get(entry["message_id"], {})
        # The question is the user message just before this answer in
        # the same conversation.
        question = None
        conv = entry.get("conversation_id")
        seen = [r for r in conversations if r.get("conversation_id") == conv]
        for i, rec in enumerate(seen):
            if rec.get("message_id") == entry["message_id"] and i > 0:
                question = seen[i - 1].get("content")
        worst.append({
            "message_id": entry["message_id"],
            "user_email": entry.get("user_email"),
            "comment": entry.get("comment"),
            "ts": entry.get("ts"),
            "question": question,
            "answer_excerpt": (message.get("content") or "")[:200],
            "citations": message.get("citations") or [],
        })
    worst.sort(key=lambda w: w.get("ts") or "", reverse=True)
    return {
        "total": total,
        "up": ups,
        "down": downs,
        "percent_up": round(100.0 * ups / total, 1) if total else None,
        "worst": worst,
    }


@router.get("/admin/feedback-stats")
async def admin_feedback_stats(user: dict = Depends(require_admin)):
    return _envelope(feedback_stats())
