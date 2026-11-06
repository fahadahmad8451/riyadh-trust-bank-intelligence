"""Refresh-token bookkeeping — Sprint 3.

Access tokens are stateless (15 min, cannot be revoked — that is why
they are short-lived). Refresh tokens carry a jti; issued jtis are
kept in data/refresh_tokens.json and revoked jtis in
data/token_denylist.json (both gitignored, excluded from the zip).
Logout revokes the refresh token; refresh rotates it (old jti revoked,
new jti issued). Expired jtis are pruned on read.
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("rtb.refresh_tokens")


def _path(name: str) -> Path:
    env = os.getenv("RTB_REFRESH_FILE" if name == "refresh" else "RTB_DENYLIST_FILE")
    if env:
        return Path(env)
    from app.core.paths import data_dir

    root = data_dir()
    return root / ("refresh_tokens.json" if name == "refresh" else "token_denylist.json")


def _read(name: str) -> dict:
    path = _path(name)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write(name: str, data: dict) -> None:
    path = _path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _prune(data: dict) -> dict:
    now = datetime.now(timezone.utc).timestamp()
    return {jti: rec for jti, rec in data.items() if rec.get("exp", 0) > now}


def issue_refresh_token(jti: str, email: str, exp_epoch: float) -> None:
    data = _prune(_read("refresh"))
    data[jti] = {"email": email, "exp": exp_epoch}
    _write("refresh", data)


def is_refresh_valid(jti: str) -> bool:
    data = _prune(_read("refresh"))
    return jti in data


def revoke_refresh_token(jti: str) -> None:
    data = _prune(_read("refresh"))
    rec = data.pop(jti, None)
    _write("refresh", data)
    denied = _read("denylist")
    denied[jti] = rec or {"exp": datetime.now(timezone.utc).timestamp() + 86400}
    _write("denylist", denied)


def revoke_user_refresh_tokens(email: str) -> int:
    """Revoke EVERY refresh token of one user (v0.10: called when an
    admin resets that user's password, so old sessions die with the
    old password). Returns the number revoked."""
    email = (email or "").strip().lower()
    data = _prune(_read("refresh"))
    doomed = [jti for jti, rec in data.items()
              if (rec.get("email") or "").lower() == email]
    if not doomed:
        return 0
    denied = _read("denylist")
    for jti in doomed:
        denied[jti] = data.pop(jti)
    _write("refresh", data)
    _write("denylist", denied)
    logger.info("Revoked %d refresh token(s) for %s", len(doomed), email)
    return len(doomed)


def is_denied(jti: str) -> bool:
    return jti in _read("denylist")
