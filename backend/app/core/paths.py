"""Shared filesystem paths — Staging (v0.6).

Dev and staging must never share runtime data (users, audit log,
conversations, vector store, refresh tokens). All runtime data lives
under one data directory:

    <project root>/data/            (dev — the default)
    <project root>/data-staging/    (staging)

The directory is chosen by the RTB_DATA_DIR environment variable.
It may be an absolute path or a path relative to the project root.
When it is not set, everything behaves exactly as in v0.5 (data/).

Modules that already had their own env override (RTB_USERS_FILE,
RTB_AUDIT_FILE, RTB_REFRESH_FILE / RTB_DENYLIST_FILE,
RTB_FEEDBACK_FILE) keep that precedence — those specific files win
over RTB_DATA_DIR. Nothing here reads secrets; the JWT secret stays
in .env / SECRET_KEY (see app/core/config.py).
"""
import os
from pathlib import Path


def project_root() -> Path:
    """backend/app/core/ -> project root (three levels up)."""
    return Path(__file__).resolve().parents[3]


def data_dir() -> Path:
    """Runtime data directory for this instance (dev or staging)."""
    env = os.getenv("RTB_DATA_DIR")
    if env:
        path = Path(env)
        if not path.is_absolute():
            path = project_root() / path
        return path
    return project_root() / "data"
