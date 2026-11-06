"""v0.10 tests — password reset (admin reset + forgot-password request).

Run (from backend/):  python -m pytest ../tests/test_password_reset.py -v

Design (no email/SMTP exists, so no token is ever emailed or shown):
  * POST /api/v1/auth/forgot-password — records a pending request
    for the admin; the response never reveals whether the email
    exists (same 200 either way).
  * GET /api/v1/admin/password-reset-requests — admin lists them.
  * POST /api/v1/admin/users/{email}/reset-password — admin sets a
    new password (validated like register); the user's old sessions
    are revoked and any pending request for that email is resolved.
  * POST /api/v1/admin/password-reset-requests/{id}/dismiss — admin
    dismisses a request without changing any password.

Isolation: same tmp-file pattern as test_rbac.py, plus
RTB_PASSWORD_RESETS_FILE for the request store.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

ADMIN = ("admin@rtb.local", "Admin123!")
SERVICE = ("service@rtb.local", "Service123!")
USER_EMAIL = "resetme@rtb.local"
USER_PASSWORD = "OldPass123"


@pytest.fixture(scope="module")
def isolated_env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("password_reset")
    os.environ["RTB_USERS_FILE"] = str(tmp / "users.json")
    os.environ["RTB_AUDIT_FILE"] = str(tmp / "audit.jsonl")
    os.environ["RTB_REFRESH_FILE"] = str(tmp / "refresh.json")
    os.environ["RTB_DENYLIST_FILE"] = str(tmp / "denylist.json")
    os.environ["RTB_PASSWORD_RESETS_FILE"] = str(tmp / "reset_requests.json")
    from app.core.users import create_user, seed_users

    seed_users(force=True)
    create_user(USER_EMAIL, "Reset Me", USER_PASSWORD)
    yield tmp


@pytest.fixture(scope="module")
def client(isolated_env):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def login(client, creds):
    email, password = creds
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    # v0.10: token comes from the httpOnly cookie jar.
    return {"Authorization": f"Bearer {client.cookies.get('rtb_access')}"}


def try_login(client, email, password):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


# ---------------------------------------------------------------------------
# Forgot-password request
# ---------------------------------------------------------------------------
def test_forgot_password_records_request_for_existing_user(client):
    res = client.post("/api/v1/auth/forgot-password", json={"email": USER_EMAIL})
    assert res.status_code == 200, res.text
    assert res.json()["data"]["message"]
    from app.core.password_reset import list_requests

    pending = [r for r in list_requests("pending") if r["email"] == USER_EMAIL]
    assert len(pending) == 1, "exactly one pending request expected"
    assert pending[0]["status"] == "pending"


def test_forgot_password_same_response_for_unknown_email(client):
    # No email-existence leak: same 200 + same message shape.
    res = client.post("/api/v1/auth/forgot-password",
                      json={"email": "nobody@rtb.local"})
    assert res.status_code == 200, res.text
    assert res.json()["data"]["message"]
    from app.core.password_reset import list_requests

    assert not [r for r in list_requests("pending") if r["email"] == "nobody@rtb.local"]


def test_forgot_password_second_request_does_not_duplicate(client):
    client.post("/api/v1/auth/forgot-password", json={"email": USER_EMAIL})
    client.post("/api/v1/auth/forgot-password", json={"email": USER_EMAIL})
    from app.core.password_reset import list_requests

    pending = [r for r in list_requests("pending") if r["email"] == USER_EMAIL]
    assert len(pending) == 1, "a second request must not duplicate the pending one"


def test_forgot_password_audit_entry(client):
    from app.core.audit import read_audit

    entries, _ = read_audit(limit=500)
    assert [e for e in entries if e.get("action") == "PASSWORD_RESET_REQUESTED"
            and e.get("user") == USER_EMAIL], "PASSWORD_RESET_REQUESTED audit missing"


# ---------------------------------------------------------------------------
# Admin list + dismiss
# ---------------------------------------------------------------------------
def test_admin_lists_pending_requests(client):
    headers = login(client, ADMIN)
    res = client.get("/api/v1/admin/password-reset-requests", headers=headers)
    assert res.status_code == 200, res.text
    emails = [r["email"] for r in res.json()["data"]["requests"]]
    assert USER_EMAIL in emails


def test_non_admin_cannot_list_requests(client):
    headers = login(client, SERVICE)
    res = client.get("/api/v1/admin/password-reset-requests", headers=headers)
    assert res.status_code == 403, res.text


def test_admin_dismiss_request(client):
    headers = login(client, ADMIN)
    from app.core.password_reset import list_requests

    req = next(r for r in list_requests("pending") if r["email"] == USER_EMAIL)
    res = client.post(f"/api/v1/admin/password-reset-requests/{req['id']}/dismiss",
                      headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["data"]["request"]["status"] == "dismissed"
    assert not [r for r in list_requests("pending") if r["email"] == USER_EMAIL]


# ---------------------------------------------------------------------------
# Admin reset (sets a new password)
# ---------------------------------------------------------------------------
def test_admin_reset_password_works_and_old_password_fails(client):
    # A fresh pending request first (the previous one was dismissed).
    client.post("/api/v1/auth/forgot-password", json={"email": USER_EMAIL})
    headers = login(client, ADMIN)
    res = client.post(f"/api/v1/admin/users/{USER_EMAIL}/reset-password",
                      json={"new_password": "NewPass456", "confirm_password": "NewPass456"},
                      headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["data"]["user"]["email"] == USER_EMAIL
    # New password logs in; old one does not.
    assert try_login(client, USER_EMAIL, "NewPass456").status_code == 200
    assert try_login(client, USER_EMAIL, USER_PASSWORD).status_code == 401
    # The pending request was resolved by the reset.
    from app.core.password_reset import list_requests

    assert not [r for r in list_requests("pending") if r["email"] == USER_EMAIL]


def test_admin_reset_revokes_old_sessions(client):
    # Log in as the user, then reset the password: the old refresh
    # token must stop working.
    headers = login(client, (USER_EMAIL, "NewPass456"))
    old_refresh = client.cookies.get("rtb_refresh")
    assert old_refresh
    admin_headers = login(client, ADMIN)
    res = client.post(f"/api/v1/admin/users/{USER_EMAIL}/reset-password",
                      json={"new_password": "NewerPass789",
                            "confirm_password": "NewerPass789"},
                      headers=admin_headers)
    assert res.status_code == 200, res.text
    # Present ONLY the old refresh token: clear the jar first, or
    # the admin's refresh cookie (from the reset login above) would
    # authenticate this call on its own.
    client.cookies.clear()
    res = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert res.status_code == 401, "revoked refresh token must not work after reset"


def test_admin_reset_weak_password_is_400(client):
    headers = login(client, ADMIN)
    res = client.post(f"/api/v1/admin/users/{USER_EMAIL}/reset-password",
                      json={"new_password": "short", "confirm_password": "short"},
                      headers=headers)
    assert res.status_code == 400, res.text


def test_admin_reset_mismatched_passwords_is_400(client):
    headers = login(client, ADMIN)
    res = client.post(f"/api/v1/admin/users/{USER_EMAIL}/reset-password",
                      json={"new_password": "NewPass456", "confirm_password": "OtherPass456"},
                      headers=headers)
    assert res.status_code == 400, res.text


def test_admin_reset_unknown_user_is_404(client):
    headers = login(client, ADMIN)
    res = client.post("/api/v1/admin/users/ghost@rtb.local/reset-password",
                      json={"new_password": "NewPass456", "confirm_password": "NewPass456"},
                      headers=headers)
    assert res.status_code == 404, res.text


def test_non_admin_reset_is_403(client):
    headers = login(client, SERVICE)
    res = client.post(f"/api/v1/admin/users/{USER_EMAIL}/reset-password",
                      json={"new_password": "NewPass456", "confirm_password": "NewPass456"},
                      headers=headers)
    assert res.status_code == 403, res.text


def test_admin_reset_audit_entry(client):
    from app.core.audit import read_audit

    entries, _ = read_audit(limit=500)
    assert [e for e in entries if e.get("action") == "PASSWORD_RESET_BY_ADMIN"
            and USER_EMAIL in (e.get("detail") or "")], \
        "PASSWORD_RESET_BY_ADMIN audit entry missing"
