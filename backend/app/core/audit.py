"""Audit log — Sprint 3 (Design sections 4, 9).

Every LOGIN (success/fail), QUERY, UPLOAD and ACCESS_DENIED is logged
with timestamp + user + action + result. Two stores:

  * data/audit.jsonl — ALWAYS written (works with no Postgres, no
    Docker). One JSON object per line. This is the primary store here.
  * audit_logs table (Design) — written as well, but ONLY when the
    configured database is PostgreSQL and reachable. With the default
    SQLite fallback the table is not used (the pgvector Vector column
    in the shared models cannot be created on SQLite), and the JSONL
    file is the record.

What is logged for a QUERY: the question truncated to 80 characters
(the full question is NOT stored here — it lives in the conversation
log) and the top cited document. Never log passwords, tokens, or full
PII: 10-digit ID-like numbers are masked before writing.
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("rtb.audit")

_PII_RE = re.compile(r"\b\d{10}\b")

_db_attempted = False
_db_ok = False


def audit_path() -> Path:
    env = os.getenv("RTB_AUDIT_FILE")
    if env:
        return Path(env)
    from app.core.paths import data_dir

    return data_dir() / "audit.jsonl"


def mask_pii(text: str | None) -> str | None:
    if text is None:
        return None
    return _PII_RE.sub("**********", str(text))


def append_audit(
    action: str,
    user_email: str | None = None,
    role: str | None = None,
    result: str = "ok",
    resource: str | None = None,
    detail: str | None = None,
    ip: str | None = None,
) -> dict:
    """Append one audit entry to the JSONL file (and to the DB table
    when Postgres is available). Returns the entry. Never raises."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "user": user_email,
        "role": role,
        "action": action,
        "resource": mask_pii(resource),
        "result": result,
        "detail": mask_pii(detail[:200]) if detail else None,
        "ip": ip,
    }
    try:
        path = audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001 — audit must never break the request
        logger.warning("Could not write audit log: %s", exc)
    _try_db_audit(entry)
    return entry


def _try_db_audit(entry: dict) -> None:
    """Best-effort mirror into the audit_logs table (Postgres only)."""
    global _db_attempted, _db_ok
    if _db_attempted and not _db_ok:
        return
    try:
        from app.db.session import get_session, init_db, is_postgres

        if not is_postgres():
            _db_attempted = True
            _db_ok = False
            return
        if not _db_attempted:
            init_db()
        _db_attempted = True
        from app.db.models import AuditLog, User

        session = get_session()
        try:
            user_id = None
            if entry.get("user"):
                user = session.query(User).filter_by(email=entry["user"]).first()
                user_id = user.id if user else None
            session.add(AuditLog(
                user_id=user_id,
                action=entry["action"],
                resource=entry.get("resource"),
                result=entry.get("result", "ok"),
                ip=entry.get("ip"),
            ))
            session.commit()
            _db_ok = True
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001 — JSONL is the record; DB is a mirror
        logger.warning("DB audit mirror failed (%s) — JSONL remains the record", exc)
        _db_attempted = True
        _db_ok = False


def read_audit(limit: int = 100, offset: int = 0) -> tuple[list[dict], int]:
    """Read audit entries, newest first. Returns (entries, total)."""
    path = audit_path()
    entries: list[dict] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    entries.sort(key=lambda e: e.get("ts", ""), reverse=True)
    total = len(entries)
    return entries[offset:offset + limit], total
