"""Demo user store — Sprint 3.

Users live in data/users.json (bcrypt hashes, never plaintext).
The path is configurable with RTB_USERS_FILE so tests can point at a
temporary file. No PostgreSQL is needed: this works on Fahad's laptop
as-is. The SQLAlchemy `users` table (Design section 4) exists for a
future Postgres deployment; the seed script can also populate it when
Postgres is reachable (scripts/seed_users.py --postgres), but the JSON
file is the store this sprint actually reads.

Demo accounts (seeded by scripts/seed_users.py, DEMO ONLY — change
before any real use):
    admin@rtb.local      / Admin123!      — ADMIN
    compliance@rtb.local / Compliance123! — COMPLIANCE_OFFICER
    service@rtb.local    / Service123!    — CUSTOMER_SERVICE
"""
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("rtb.users")

DEMO_USERS = [
    {
        "email": "admin@rtb.local",
        "name": "Branch Manager (Admin)",
        "role": "ADMIN",
        "password": "Admin123!",
    },
    {
        "email": "compliance@rtb.local",
        "name": "Compliance Officer",
        "role": "COMPLIANCE_OFFICER",
        "password": "Compliance123!",
    },
    {
        "email": "service@rtb.local",
        "name": "Customer Service",
        "role": "CUSTOMER_SERVICE",
        "password": "Service123!",
    },
]


DEMO_EMAILS = {d["email"] for d in DEMO_USERS}


def users_path() -> Path:
    env = os.getenv("RTB_USERS_FILE")
    if env:
        return Path(env)
    from app.core.paths import data_dir

    return data_dir() / "users.json"


def load_users() -> list[dict]:
    path = users_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("users", []) if isinstance(data, dict) else []
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read users file %s: %s", path, exc)
        return []


def save_users(users: list[dict]) -> None:
    path = users_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"users": users}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_user(email: str) -> dict | None:
    email = (email or "").strip().lower()
    for user in load_users():
        if user.get("email", "").lower() == email:
            return user
    return None


def public_user(user: dict) -> dict:
    """User record safe to send to the frontend (no password hash)."""
    from app.core.rbac import allowed_departments

    out = {
        "email": user["email"],
        "name": user.get("name", ""),
        "role": user["role"],
        "departments": allowed_departments(user["role"]),
    }
    if user.get("created_at"):
        out["created_at"] = user["created_at"]
    if "is_active" in user:
        out["is_active"] = user["is_active"]
    return out


def create_user(email: str, name: str, password: str, role: str = "CUSTOMER_SERVICE") -> dict:
    """Create a user with a bcrypt-hashed password. Raises ValueError
    if the email already exists. New accounts are ALWAYS created with
    the lowest-privilege role (CUSTOMER_SERVICE) unless the caller
    explicitly passes another role — the register endpoint never does."""
    from datetime import datetime, timezone

    from app.core.security import hash_password

    email = (email or "").strip().lower()
    if get_user(email) is not None:
        raise ValueError("duplicate email")
    user = {
        "email": email,
        "name": (name or "").strip(),
        "role": role,
        "password_hash": hash_password(password),
        "is_active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    users = load_users()
    users.append(user)
    save_users(users)
    logger.info("Created user %s with role %s", email, role)
    return user


def update_user_role(email: str, new_role: str) -> dict | None:
    """Change a user's role. Returns the updated user, or None if the
    email does not exist."""
    email = (email or "").strip().lower()
    users = load_users()
    for user in users:
        if user.get("email", "").lower() == email:
            user["role"] = new_role
            save_users(users)
            logger.info("Changed role of %s to %s", email, new_role)
            return user
    return None


def update_password(email: str, new_password: str) -> dict | None:
    """Set a new (bcrypt-hashed) password for a user. Used by the
    admin password reset (v0.10). Returns the updated user, or None
    if the email does not exist."""
    from app.core.security import hash_password

    email = (email or "").strip().lower()
    users = load_users()
    for user in users:
        if user.get("email", "").lower() == email:
            user["password_hash"] = hash_password(new_password)
            save_users(users)
            logger.info("Password updated for %s (admin reset)", email)
            return user
    return None


def list_public_users() -> list[dict]:
    return [public_user(u) for u in load_users()]


def seed_users(force: bool = False) -> list[dict]:
    """Create the 3 demo users (bcrypt hashes). Returns the users.
    Refuses to overwrite an existing file unless force=True.

    Production (v0.8): when demo accounts are disabled
    (RTB_DEMO_ACCOUNTS=0, or ENVIRONMENT=production without an
    explicit opt-in) this does NOTHING and returns [] — production
    must never contain the well-known demo passwords. The first
    admin is created with scripts/create_admin.py instead."""
    from app.core.config import settings
    from app.core.security import hash_password

    if not settings.demo_accounts_enabled:
        logger.warning(
            "Demo accounts are disabled (RTB_DEMO_ACCOUNTS=0) — "
            "not seeding demo users. Create the first admin with "
            "scripts/create_admin.py."
        )
        return []
    existing = load_users()
    if existing and not force:
        return existing
    users = []
    for demo in DEMO_USERS:
        users.append({
            "email": demo["email"],
            "name": demo["name"],
            "role": demo["role"],
            "password_hash": hash_password(demo["password"]),
            "is_active": True,
            "created_at": "2026-11-06",
        })
    save_users(users)
    logger.info("Seeded %d demo users into %s", len(users), users_path())
    return users
