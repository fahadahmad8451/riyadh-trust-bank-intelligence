"""Create the FIRST admin account — Production (v0.8).

Production never seeds demo users, so the first admin must be created
explicitly with this script. Usage (from the project root, prod venv
active, production env loaded — see scripts/production_setup.*):

    python scripts/create_admin.py --email admin@rtb.local --password 'StrongPass123'
    python scripts/create_admin.py --email admin@rtb.local   # prompts for the password

Rules:
- Email must be valid, password min 8 chars + 1 letter + 1 digit
  (same rule as POST /auth/register).
- The email must NOT be a demo account (admin@rtb.local etc. are
  reserved — demo accounts are disabled in production; recreating
  one with a new password would defeat the point).
- Refuses if the email already exists (use --force to overwrite the
  existing user with a new admin record — prints a warning first).
- The user is stored in data-prod/users.json (bcrypt hash, never
  plaintext) — the RTB_DATA_DIR / RTB_USERS_FILE env vars decide
  where, exactly like the app itself.
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.api.v1.auth import _password_error  # noqa: E402 — same rule as /auth/register
from app.core.users import DEMO_EMAILS, create_user, get_user  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the first production admin.")
    parser.add_argument("--email", required=True, help="Admin email (e.g. admin@bank.local)")
    parser.add_argument("--password", default=None, help="Admin password (prompted if omitted)")
    parser.add_argument("--name", default="Administrator", help="Display name")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite the existing user with this email")
    args = parser.parse_args()

    email = (args.email or "").strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        print("ERROR: please enter a valid email address.")
        return 2
    if email in DEMO_EMAILS:
        print(f"ERROR: {email} is a demo account address — demo accounts are disabled "
              "in production. Use a different email (e.g. admin@bank.local).")
        return 2
    password = args.password or getpass.getpass("Admin password: ")
    pw_error = _password_error(password or "")
    if pw_error:
        print(f"ERROR: {pw_error}")
        return 2
    existing = get_user(email)
    if existing is not None and not args.force:
        print(f"ERROR: a user with email {email} already exists — use --force to overwrite.")
        return 2
    if existing is not None and args.force:
        from app.core.users import load_users, save_users

        save_users([u for u in load_users() if u.get("email", "").lower() != email])
        print(f"WARNING: overwrote the existing user {email}.")
    user = create_user(email, args.name, password, role="ADMIN")
    print(f"Admin created: {user['email']} (role ADMIN)")
    print("Log in at http://localhost:3000 with this email and password.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
