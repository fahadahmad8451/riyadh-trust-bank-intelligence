"""Chat API — Sprint 3 (real, working, RBAC-enforced).

POST /chat — grounded RAG answer with citations (see
app/services/generation.py). Requires a valid JWT: the caller's
allowed departments are passed to retrieval BEFORE ranking, so a
disallowed chunk can never be retrieved, cited, or fed to the
generator. Response includes rbac_enforced: true and the caller's
role. Every query is audit-logged (question truncated to 80 chars —
never full PII).

GET  /conversations — list conversation ids (own conversations only,
unless ADMIN).
GET  /conversations/{id} — saved messages of one conversation.

Conversations are stored in a JSONL file (data/conversations.jsonl) —
one line per message. The file is excluded from the zip via .gitignore.
"""
import json
import logging
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.audit import append_audit
from app.core.rbac import allowed_departments
from app.core.security import get_current_user

logger = logging.getLogger("rtb.chat")
router = APIRouter()

from app.core.paths import data_dir

ROOT = Path(__file__).resolve().parents[4]  # backend/app/api/v1 -> project root
LOG_PATH = data_dir() / "conversations.jsonl"


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    conversation_id: str | None = None
    language: str | None = None


def _envelope(data, request_id: str) -> dict:
    return {"success": True, "data": data, "error": None, "request_id": request_id}


def _append_message(conversation_id: str, role: str, content: str, extra: dict | None = None) -> str:
    """Append one message and return its id. Sprint 4: every message
    gets a stable message_id so POST /feedback can point at a real
    assistant answer (feedback on a made-up id is rejected with 404)."""
    message_id = str(uuid.uuid4())
    record = {
        "message_id": message_id,
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "ts": time.time(),
        **(extra or {}),
    }
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return message_id


def _read_conversations() -> dict[str, list[dict]]:
    convs: dict[str, list[dict]] = {}
    if not LOG_PATH.exists():
        return convs
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        convs.setdefault(rec.get("conversation_id", "unknown"), []).append(rec)
    return convs


@router.post("/chat")
async def chat(payload: ChatRequest, user: dict = Depends(get_current_user)):
    from app.services.generation import answer_question

    departments = allowed_departments(user["role"])
    conversation_id = payload.conversation_id or str(uuid.uuid4())
    result = answer_question(
        payload.question, allowed_departments=departments)
    _append_message(conversation_id, "user", payload.question,
                    {"user": user["email"]})
    assistant_message_id = _append_message(
        conversation_id, "assistant", result["answer"],
        {"citations": result["citations"], "generation_mode": result["generation_mode"],
         "user": user["email"]},
    )
    top_cited = result["citations"][0]["document_title"] if result["citations"] else None
    append_audit(
        "QUERY", user_email=user["email"], role=user["role"], result="ok",
        resource=f"chat:{conversation_id}",
        detail=f"q={payload.question[:80]!r} top_cited={top_cited} "
               f"refused={result['refused']}",
    )
    if result.get("topic_gate"):
        # v0.10: the deterministic topic gate refused this question —
        # log the denial explicitly (the audit log is how an admin
        # sees who was refused, and for which blocked department).
        append_audit(
            "RBAC_DENIED", user_email=user["email"], role=user["role"],
            result="denied", resource=f"chat:{conversation_id}",
            detail=f"q={payload.question[:80]!r} "
                   f"blocked_department={result.get('blocked_department')} "
                   f"(topic gate)",
        )
    return _envelope({
        "conversation_id": conversation_id,
        "message_id": assistant_message_id,
        "answer": result["answer"],
        "citations": result["citations"],
        "retrieval_scores": result["retrieval_scores"],
        "latency_ms": result["latency_ms"],
        "generation_mode": result["generation_mode"],
        "language": result["language"],
        "retrieved_count": result["retrieved_count"],
        "refused": result["refused"],
        "rbac_blocked": result.get("rbac_blocked", False),
        "blocked_department": result.get("blocked_department"),
        "rbac_enforced": True,
        "role": user["role"],
        "allowed_departments": departments,
    }, request_id=str(uuid.uuid4()))


@router.get("/conversations")
async def list_conversations(user: dict = Depends(get_current_user)):
    convs = _read_conversations()
    visible = []
    for cid, msgs in convs.items():
        # A user sees only their own conversations; ADMIN sees all.
        owners = {m.get("user") for m in msgs if m.get("user")}
        if user["role"] == "ADMIN" or user["email"] in owners or not owners:
            visible.append({
                "conversation_id": cid,
                "message_count": len(msgs),
                "first_question": next(
                    (m["content"] for m in msgs if m["role"] == "user"), None),
            })
    return _envelope({"conversations": visible, "count": len(visible)},
                     request_id=str(uuid.uuid4()))


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, user: dict = Depends(get_current_user)):
    convs = _read_conversations()
    messages = convs.get(conversation_id)
    if messages is None:
        return {
            "success": False, "data": None,
            "error": f"Conversation not found: {conversation_id}",
            "request_id": str(uuid.uuid4()),
        }
    owners = {m.get("user") for m in messages if m.get("user")}
    if user["role"] != "ADMIN" and owners and user["email"] not in owners:
        append_audit("ACCESS_DENIED", user_email=user["email"], role=user["role"],
                     result="denied", resource=f"conversations:{conversation_id}",
                     detail="conversation belongs to another user")
        return {
            "success": False, "data": None,
            "error": "Forbidden — this conversation belongs to another user.",
            "request_id": str(uuid.uuid4()),
        }
    return _envelope({
        "conversation_id": conversation_id,
        "messages": messages,
        "message_count": len(messages),
    }, request_id=str(uuid.uuid4()))
