"""Seed the 3 demo users — Sprint 3.

Usage (from the project root):
    python scripts/seed_users.py            # create if missing
    python scripts/seed_users.py --force    # overwrite existing users
    python scripts/seed_users.py --postgres # also mirror into the
                                            # PostgreSQL users table
                                            # (only if reachable)

Demo accounts (DEMO ONLY — change before any real use):
    admin@rtb.local      / Admin123!       ADMIN
    compliance@rtb.local / Compliance123!  COMPLIANCE_OFFICER
    service@rtb.local    / Service123!     CUSTOMER_SERVICE

Users are stored in data/users.json (bcrypt hashes, never plaintext).
No Docker needed.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.users import DEMO_USERS, load_users, seed_users


def seed_postgres() -> None:
    """Best-effort mirror into the Postgres users table. Logs and
    returns if Postgres is not reachable — the JSON file is the store
    this sprint actually reads."""
    try:
        from app.db.session import get_session, init_db, is_postgres

        if not is_postgres():
            print("Postgres not configured (DATABASE_URL is not postgresql) — skipping DB mirror.")
            return
        init_db()
        from app.core.security import hash_password
        from app.db.models import User

        session = get_session()
        try:
            for demo in DEMO_USERS:
                existing = session.query(User).filter_by(email=demo["email"]).first()
                if existing:
                    continue
                session.add(User(
                    email=demo["email"], name=demo["name"], role=demo["role"],
                    department="ALL" if demo["role"] == "ADMIN" else demo["role"],
                    password_hash=hash_password(demo["password"]),
                ))
            session.commit()
            print(f"Mirrored {len(DEMO_USERS)} demo users into the Postgres users table.")
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001
        print(f"Postgres mirror failed ({exc}) — JSON file remains the user store.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Sprint 3 demo users.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing users.json")
    parser.add_argument("--postgres", action="store_true", help="Also mirror into Postgres users table")
    args = parser.parse_args()

    before = load_users()
    users = seed_users(force=args.force)
    if before and not args.force:
        print(f"users.json already exists ({len(before)} users) — use --force to overwrite.")
    else:
        print(f"Seeded {len(users)} demo users:")
        for user in users:
            print(f"  {user['email']:24s} {user['role']}")
        print("DEMO ONLY — change these passwords before any real use.")
    if args.postgres:
        seed_postgres()


if __name__ == "__main__":
    main()
