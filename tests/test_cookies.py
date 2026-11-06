"""v0.10 tests — httpOnly cookie auth.

Run (from backend/):  python -m pytest ../tests/test_cookies.py -v

Isolation: user/audit/refresh files point at tmp files (same pattern
as tests/test_rbac.py) so these tests never touch real data.

What is proven here (the browser path, with NO Authorization header
anywhere):
  * login/register set httpOnly, SameSite=Lax cookies and put NO
    token in the JSON body;
  * a protected call works with the cookie alone;
  * refresh works with the cookie alone (empty body);
  * logout clears both cookies;
  * a cookie-authenticated POST from a foreign Origin is refused
    (CSRF check), while the same call without an Origin header works
    (curl/scripts) and a call from an allowed origin works;
  * no cookie and no token -> 401.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

ADMIN = ("admin@rtb.local", "Admin123!")
SERVICE = ("service@rtb.local", "Service123!")
KYC_Q = "What documents are needed for KYC account opening?"


@pytest.fixture(scope="module")
def isolated_env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("cookies")
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

    return TestClient(app, raise_server_exceptions=False)


def _login(client, creds):
    email, password = creds
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res


def _cookie_flags(res, name: str) -> str:
    """Raw Set-Cookie header value for one cookie name ('' if absent)."""
    for header in res.headers.get_list("set-cookie"):
        if header.startswith(name + "="):
            return header
    return ""


def test_login_sets_httponly_cookies_and_no_token_in_body(client):
    client.cookies.clear()
    res = _login(client, SERVICE)
    body = res.json()["data"]
    assert "access_token" not in body, "token must not be in the JSON body"
    assert "refresh_token" not in body, "token must not be in the JSON body"
    assert body["user"]["email"] == SERVICE[0]
    access_flags = _cookie_flags(res, "rtb_access")
    refresh_flags = _cookie_flags(res, "rtb_refresh")
    assert access_flags, "rtb_access cookie was not set"
    assert refresh_flags, "rtb_refresh cookie was not set"
    for flags in (access_flags, refresh_flags):
        assert "HttpOnly" in flags, flags
        assert "SameSite=lax" in flags, flags
    # The browser (TestClient jar) now holds both cookies.
    assert client.cookies.get("rtb_access")
    assert client.cookies.get("rtb_refresh")


def test_register_sets_cookies_and_no_token_in_body(client):
    client.cookies.clear()
    res = client.post("/api/v1/auth/register", json={
        "full_name": "Cookie User", "email": "cookieuser@rtb.local",
        "password": "Pass1234", "confirm_password": "Pass1234",
    })
    assert res.status_code == 201, res.text
    assert "access_token" not in res.json()["data"]
    assert client.cookies.get("rtb_access")


def test_protected_call_works_with_cookie_only(client):
    client.cookies.clear()
    _login(client, SERVICE)
    # No Authorization header at all — the cookie jar sends rtb_access.
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 200, res.text
    assert res.json()["data"]["user"]["email"] == SERVICE[0]
    res = client.post("/api/v1/chat", json={"question": KYC_Q})
    assert res.status_code == 200, res.text
    assert res.json()["data"]["citations"]


def test_refresh_with_cookie_only_and_no_body(client):
    client.cookies.clear()
    _login(client, ADMIN)
    old_refresh = client.cookies.get("rtb_refresh")
    # Empty body: the refresh token comes from the httpOnly cookie.
    res = client.post("/api/v1/auth/refresh")
    assert res.status_code == 200, res.text
    assert "access_token" not in res.json()["data"]
    assert client.cookies.get("rtb_access")
    # Rotation: the refresh token (which carries a unique id) changed.
    # (The access token itself is a plain JWT — two tokens minted in
    # the same second are identical, which is expected, not a bug.)
    assert client.cookies.get("rtb_refresh")
    assert client.cookies.get("rtb_refresh") != old_refresh
    # The rotated session still works.
    assert client.get("/api/v1/auth/me").status_code == 200


def test_logout_clears_both_cookies(client):
    client.cookies.clear()
    _login(client, ADMIN)
    assert client.cookies.get("rtb_access")
    res = client.post("/api/v1/auth/logout")
    assert res.status_code == 200, res.text
    assert not client.cookies.get("rtb_access")
    assert not client.cookies.get("rtb_refresh")
    assert client.get("/api/v1/auth/me").status_code == 401


def test_no_cookie_no_token_is_401(client):
    client.cookies.clear()
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.post("/api/v1/chat", json={"question": KYC_Q}).status_code == 401


def test_csrf_wrong_origin_refused_with_cookie(client):
    client.cookies.clear()
    _login(client, SERVICE)
    # Cookie present + foreign Origin -> 403 (CSRF check).
    res = client.post(
        "/api/v1/chat", json={"question": KYC_Q},
        headers={"Origin": "https://evil.example"},
    )
    assert res.status_code == 403, res.text
    assert "cross-site" in res.json()["error"]
    # Same call without an Origin header (curl/scripts) still works.
    res = client.post("/api/v1/chat", json={"question": KYC_Q})
    assert res.status_code == 200, res.text
    # And an allowed origin works too.
    res = client.post(
        "/api/v1/chat", json={"question": KYC_Q},
        headers={"Origin": "http://localhost:3000"},
    )
    assert res.status_code == 200, res.text


def test_csrf_check_does_not_block_get_requests(client):
    client.cookies.clear()
    _login(client, SERVICE)
    res = client.get("/api/v1/auth/me", headers={"Origin": "https://evil.example"})
    assert res.status_code == 200, res.text


def test_secure_flag_follows_transport_not_environment(client, monkeypatch):
    """Regression (v0.10 prod smoke 16/18): Secure followed the
    environment name, so local production over plain HTTP set Secure
    cookies that httpx/curl never send back -> chat 401. Secure must
    follow the actual transport instead: plain HTTP (even in a
    production environment) -> no Secure flag; HTTPS -> Secure."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "environment", "production")
    client.cookies.clear()
    res = _login(client, SERVICE)
    access = _cookie_flags(res, "rtb_access")
    assert "Secure" not in access, (
        "plain-HTTP login must not set a Secure cookie, even in production: "
        + access
    )
    # The same login over HTTPS must set Secure.
    from fastapi.testclient import TestClient

    from app.main import app

    https_client = TestClient(app, base_url="https://testserver",
                              raise_server_exceptions=False)
    https_client.cookies.clear()
    res = https_client.post("/api/v1/auth/login",
                            json={"email": SERVICE[0], "password": SERVICE[1]})
    assert res.status_code == 200, res.text
    access = _cookie_flags(res, "rtb_access")
    assert "Secure" in access, "HTTPS login must set a Secure cookie: " + access
    # And the Secure cookie is actually sent back over HTTPS.
    res = https_client.post("/api/v1/chat", json={"question": KYC_Q})
    assert res.status_code == 200, res.text
