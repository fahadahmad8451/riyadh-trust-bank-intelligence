"""Password-reset requests — v0.10.

There is NO email/SMTP in this system (local demo on Fahad's PC),
so a reset cannot be delivered by email. The honest design:

  * A user who forgot their password submits a REQUEST
    (POST /api/v1/auth/forgot-password). The request is recorded
    server-side with status "pending" and an audit entry
    (PASSWORD_RESET_REQUESTED). The response never reveals whether
    the email exists — the same message is returned either way.
  * An Admin sees the pending requests in the Admin panel
    (GET /admin/password-reset-requests) and approves one by
    setting a new temporary password
    (POST /api/v1/admin/users/{email}/reset-password). The admin
    then gives that temporary password to the user out of band
    (in person / on the phone). The user's old sessions are revoked
    at reset time.
  * An Admin can also dismiss a request (no password is changed).

Requests live in data/password_reset_requests.json (a JSON list),
configurable with RTB_PASSWORD_RESETS_FILE so tests can point at a
temporary file. No reset TOKEN is ever issued or shown to anyone:
there is no email to send it to, and showing a token in the UI
would let anyone who can see the screen reset anyone's password.
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("rtb.password_reset")

STATUSES = ("pending", "resolved", "dismissed")


def requests_path() -> Path:
    env = os.getenv("RTB_PASSWORD_RESETS_FILE")
    if env:
        return Path(env)
    from app.core.paths import data_dir

    return data_dir() / "password_reset_requests.json"


def load_requests() -> list[dict]:
    path = requests_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("requests", []) if isinstance(data, dict) else []
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read password-reset requests %s: %s", path, exc)
        return []


def save_requests(requests: list[dict]) -> None:
    path = requests_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"requests": requests}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def create_request(email: str) -> dict:
    """Record a reset request. If one is already pending for this
    email, return the existing one (no duplicate queue entries)."""
    email = (email or "").strip().lower()
    requests = load_requests()
    for req in requests:
        if req.get("email") == email and req.get("status") == "pending":
            return req
    req = {
        "id": uuid.uuid4().hex[:12],
        "email": email,
        "status": "pending",
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "resolved_by": None,
        "resolved_at": None,
    }
    requests.append(req)
    save_requests(requests)
    logger.info("Password-reset request %s for %s", req["id"], email)
    return req


def list_requests(status: str | None = None) -> list[dict]:
    requests = load_requests()
    if status:
        requests = [r for r in requests if r.get("status") == status]
    return sorted(requests, key=lambda r: r.get("requested_at", ""), reverse=True)


def resolve_request(request_id: str, status: str, resolved_by: str) -> dict | None:
    """Mark a request resolved/dismissed. Returns it, or None."""
    if status not in ("resolved", "dismissed"):
        raise ValueError(f"bad status: {status}")
    requests = load_requests()
    for req in requests:
        if req.get("id") == request_id:
            req["status"] = status
            req["resolved_by"] = resolved_by
            req["resolved_at"] = datetime.now(timezone.utc).isoformat()
            save_requests(requests)
            return req
    return None


def resolve_pending_for_email(email: str, resolved_by: str) -> int:
    """Mark every pending request for an email resolved (called when
    an admin resets that user's password). Returns the count."""
    email = (email or "").strip().lower()
    requests = load_requests()
    count = 0
    for req in requests:
        if req.get("email") == email and req.get("status") == "pending":
            req["status"] = "resolved"
            req["resolved_by"] = resolved_by
            req["resolved_at"] = datetime.now(timezone.utc).isoformat()
            count += 1
    if count:
        save_requests(requests)
    return count
