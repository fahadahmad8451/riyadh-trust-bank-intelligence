"""v0.7 tests — Sign Up (POST /auth/register) and Admin role change.

Run (from backend/):  python -m pytest ../tests/test_auth_register.py -v

Isolation: user/audit/refresh files point at tmp files (same pattern
as tests/test_rbac.py) so these tests never touch real data/users.json.
The register endpoint auto-logs the new user in (tokens returned) and
every new account starts as CUSTOMER_SERVICE — the caller never
chooses a role.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

ADMIN = ("admin@rtb.local", "Admin123!")
SERVICE = ("service@rtb.local", "Service123!")


@pytest.fixture(scope="module")
def isolated_env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("auth_register")
    os.environ["RTB_USERS_FILE"] = str(tmp / "users.json")
    os.environ["RTB_AUDIT_FILE"] = str(tmp / "audit.jsonl")
    os.environ["RTB_REFRESH_FILE"] = str(tmp / "refresh.json")
    os.environ["RTB_DENYLIST_FILE"] = str(tmp / "denylist.json")
    from app.core.users import seed_users

    seed_users(force=True)
    yield tmp


@pytest.fixture(scope="module")
def client(isolated_env):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def login(client, creds) -> dict:
    email, password = creds
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    # v0.10: the token arrives as an httpOnly cookie — read it
    # from the TestClient cookie jar, not from the JSON body.
    return {"Authorization": f"Bearer {client.cookies.get('rtb_access')}"}


def register(client, email, password="Pass1234", name="Test User", confirm=None):
    return client.post("/api/v1/auth/register", json={
        "full_name": name,
        "email": email,
        "password": password,
        "confirm_password": password if confirm is None else confirm,
    })


# ---------------------------------------------------------------------------
# 1-6. Register: happy path + validation
# ---------------------------------------------------------------------------
def test_valid_register_returns_201_and_auto_login(client):
    res = register(client, "newuser@rtb.local")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["success"] is True
    data = body["data"]
    # v0.10: no tokens in the JSON body — they arrive as
    # httpOnly cookies (Set-Cookie), which the client jar holds.
    assert "access_token" not in data and "refresh_token" not in data
    assert client.cookies.get("rtb_access") and client.cookies.get("rtb_refresh")
    assert data["user"]["email"] == "newuser@rtb.local"
    assert data["user"]["name"] == "Test User"


def test_new_user_default_role_is_customer_service(client):
    res = register(client, "defaultrole@rtb.local")
    assert res.status_code == 201, res.text
    assert res.json()["data"]["user"]["role"] == "CUSTOMER_SERVICE"
    assert res.json()["data"]["user"]["departments"] == ["RETAIL"]


def test_duplicate_email_is_409(client):
    assert register(client, "dup@rtb.local").status_code == 201
    res = register(client, "dup@rtb.local")
    assert res.status_code == 409, res.text
    assert "already exists" in res.json()["error"]


def test_weak_password_is_400(client):
    # Too short
    res = register(client, "weak1@rtb.local", password="Ab1")
    assert res.status_code == 400, res.text
    # No digit
    res = register(client, "weak2@rtb.local", password="Password")
    assert res.status_code == 400, res.text
    assert "digit" in res.json()["error"]
    # No letter
    res = register(client, "weak3@rtb.local", password="12345678")
    assert res.status_code == 400, res.text


def test_bad_email_is_400(client):
    res = register(client, "not-an-email")
    assert res.status_code == 400, res.text
    res = register(client, "missing-at.rtb.local")
    assert res.status_code == 400, res.text


def test_password_mismatch_is_400(client):
    res = register(client, "mismatch@rtb.local", confirm="Different1")
    assert res.status_code == 400, res.text
    assert "match" in res.json()["error"]


def test_register_then_login_works(client):
    assert register(client, "loginlater@rtb.local", password="Secret99").status_code == 201
    res = client.post("/api/v1/auth/login",
                      json={"email": "loginlater@rtb.local", "password": "Secret99"})
    assert res.status_code == 200, res.text
    assert res.json()["data"]["user"]["role"] == "CUSTOMER_SERVICE"


def test_register_audit_entry_recorded(client):
    assert register(client, "audited@rtb.local").status_code == 201
    headers = login(client, ADMIN)
    logs = client.get("/api/v1/admin/audit-logs?limit=500", headers=headers).json()["data"]
    entries = [e for e in logs["audit_logs"]
               if e["action"] == "USER_REGISTERED" and e["user"] == "audited@rtb.local"]
    assert entries, "USER_REGISTERED audit entry missing"
    assert entries[0]["result"] == "ok"


# ---------------------------------------------------------------------------
# 9-12. Admin role change
# ---------------------------------------------------------------------------
def test_non_admin_role_change_is_403(client):
    assert register(client, "target1@rtb.local").status_code == 201
    headers = login(client, SERVICE)
    res = client.put("/api/v1/admin/users/target1@rtb.local/role",
                     json={"role": "COMPLIANCE_OFFICER"}, headers=headers)
    assert res.status_code == 403, res.text


def test_admin_role_change_works_and_audit_logged(client):
    assert register(client, "target2@rtb.local").status_code == 201
    headers = login(client, ADMIN)
    res = client.put("/api/v1/admin/users/target2@rtb.local/role",
                     json={"role": "COMPLIANCE_OFFICER"}, headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["data"]["user"]["role"] == "COMPLIANCE_OFFICER"
    # The new role takes effect on the next login.
    res = client.post("/api/v1/auth/login",
                      json={"email": "target2@rtb.local", "password": "Pass1234"})
    assert res.status_code == 200, res.text
    assert res.json()["data"]["user"]["role"] == "COMPLIANCE_OFFICER"
    assert res.json()["data"]["user"]["departments"] == ["COMPLIANCE", "RETAIL"]
    # Audit log has the ROLE_CHANGED entry. The target2 login above
    # replaced the cookie jar, so log back in as admin first.
    headers = login(client, ADMIN)
    logs = client.get("/api/v1/admin/audit-logs?limit=500", headers=headers).json()["data"]
    entries = [e for e in logs["audit_logs"]
               if e["action"] == "ROLE_CHANGED" and "target2@rtb.local" in (e["detail"] or "")]
    assert entries, "ROLE_CHANGED audit entry missing"


def test_admin_cannot_change_own_role(client):
    headers = login(client, ADMIN)
    res = client.put("/api/v1/admin/users/admin@rtb.local/role",
                     json={"role": "CUSTOMER_SERVICE"}, headers=headers)
    assert res.status_code == 400, res.text


def test_invalid_role_is_400_and_unknown_user_is_404(client):
    headers = login(client, ADMIN)
    res = client.put("/api/v1/admin/users/target2@rtb.local/role",
                     json={"role": "SUPERUSER"}, headers=headers)
    assert res.status_code == 400, res.text
    res = client.put("/api/v1/admin/users/nobody@rtb.local/role",
                     json={"role": "ADMIN"}, headers=headers)
    assert res.status_code == 404, res.text
