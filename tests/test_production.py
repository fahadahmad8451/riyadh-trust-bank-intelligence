"""v0.8 tests — Production hardening.

Run (from backend/):  python -m pytest ../tests/test_production.py -v

Covers: demo accounts disabled (seed refused + login blocked),
production fail-fast (weak JWT secret / wildcard CORS refuse to start,
strong secret starts), security headers, login/register rate limiting
(429 + Retry-After), 10 MB upload limit, extended /health fields, and
the RTB_RERANKER=off flag.

Isolation: user/audit/refresh files point at tmp files (same pattern
as tests/test_auth_register.py) so these tests never touch real
data/users.json. The fail-fast tests run in a SUBPROCESS with
ENVIRONMENT=production — they never change this process's settings.
Rate-limit tests use a unique email each, because the limiter is
in-memory and shared across the whole pytest process.
"""
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

ROOT = Path(__file__).resolve().parents[1]
ADMIN = ("admin@rtb.local", "Admin123!")
STRONG_SECRET = "x" * 64  # 64 chars, no placeholder markers — valid for prod


@pytest.fixture(scope="module")
def isolated_env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("production")
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


def login(client, email, password):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def _prod_import(env_extra: dict) -> subprocess.CompletedProcess:
    """Import app.main in a fresh interpreter with production env.
    Returns the completed process (returncode 0 = app started)."""
    env = dict(os.environ)
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, 'backend'); import app.main"],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120,
    )


# ---------------------------------------------------------------------------
# 1-3. Demo accounts
# ---------------------------------------------------------------------------
def test_demo_seed_refused_when_disabled(isolated_env, monkeypatch):
    from app.core.config import settings
    from app.core.users import seed_users

    monkeypatch.setattr(settings, "demo_accounts_enabled", False)
    users_file = Path(os.environ["RTB_USERS_FILE"])
    backup = users_file.read_bytes() if users_file.exists() else None
    try:
        result = seed_users(force=True)
        assert result == [], "seed_users must return [] when demo accounts are disabled"
    finally:
        if backup is not None:
            users_file.write_bytes(backup)


def test_demo_login_blocked_when_disabled(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "demo_accounts_enabled", False)
    res = login(client, ADMIN[0], ADMIN[1])
    assert res.status_code == 401, res.text
    res = login(client, "service@rtb.local", "Service123!")
    assert res.status_code == 401, res.text


def test_demo_login_works_when_enabled(client):
    # Control test: with demo accounts on (dev default) the demo
    # login must still work — the flag must not break normal login.
    res = login(client, ADMIN[0], ADMIN[1])
    assert res.status_code == 200, res.text


# ---------------------------------------------------------------------------
# 4-6. Production fail-fast (subprocess — real process start)
# ---------------------------------------------------------------------------
def test_weak_secret_refuses_production_start():
    proc = _prod_import({"ENVIRONMENT": "production", "SECRET_KEY": "change-me"})
    assert proc.returncode != 0, "app must refuse to start with a weak secret"
    assert "SECRET_KEY" in proc.stderr, proc.stderr[-500:]


def test_wildcard_cors_refuses_production_start():
    proc = _prod_import({
        "ENVIRONMENT": "production", "SECRET_KEY": STRONG_SECRET,
        "CORS_ORIGINS": "*",
    })
    assert proc.returncode != 0, "app must refuse to start with wildcard CORS"
    assert "CORS" in proc.stderr, proc.stderr[-500:]


def test_strong_secret_production_imports_ok():
    proc = _prod_import({"ENVIRONMENT": "production", "SECRET_KEY": STRONG_SECRET})
    assert proc.returncode == 0, proc.stderr[-1000:]


# ---------------------------------------------------------------------------
# 7. Security headers
# ---------------------------------------------------------------------------
def test_security_headers_present(client):
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.headers.get("x-content-type-options") == "nosniff"
    assert res.headers.get("x-frame-options") == "DENY"
    assert res.headers.get("referrer-policy") == "no-referrer"


# ---------------------------------------------------------------------------
# 8-9. Rate limiting (429 + Retry-After)
# ---------------------------------------------------------------------------
def test_login_rate_limit_429(client):
    email = "ratelimit-login@rtb.local"
    codes = [login(client, email, "Wrong1234").status_code for _ in range(6)]
    assert codes[:5] == [401] * 5, codes
    assert codes[5] == 429, codes
    res = login(client, email, "Wrong1234")
    assert res.status_code == 429
    assert "retry-after" in res.headers
    assert "Too many attempts" in res.json()["error"]


def test_register_rate_limit_429(client):
    email = "ratelimit-register@rtb.local"
    payload = {"full_name": "Rate Test", "email": email,
               "password": "Pass1234", "confirm_password": "Pass1234"}
    codes = [client.post("/api/v1/auth/register", json=payload).status_code
             for _ in range(4)]
    # 1st: 201 created; 2nd/3rd: 409 duplicate; 4th: 429 rate-limited.
    assert codes == [201, 409, 409, 429], codes


# ---------------------------------------------------------------------------
# 10. Upload size limit
# ---------------------------------------------------------------------------
def test_upload_over_10mb_is_413(client):
    res = login(client, ADMIN[0], ADMIN[1])
    assert res.status_code == 200, res.text
    headers = {"Authorization": f"Bearer {client.cookies.get('rtb_access')}"}
    big = io.BytesIO(b"x" * (11 * 1024 * 1024))
    res = client.post("/api/v1/documents/upload",
                      files={"file": ("big.pdf", big, "application/pdf")},
                      data={"department": "RETAIL"}, headers=headers)
    assert res.status_code == 413, res.text
    assert "10 MB" in res.json()["error"]


# ---------------------------------------------------------------------------
# 11. Extended /health
# ---------------------------------------------------------------------------
def test_health_extended_fields(client):
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["status"] == "ok"
    assert data["uptime_seconds"] >= 0
    assert "demo_accounts_enabled" in data
    assert data["reranker"] in ("auto", "off")
    assert "embeddings" in data and "model" in data["embeddings"]
    vs = data["vector_store"]
    assert vs["status"] in ("ok", "not indexed")
    assert "documents" in vs and "chunks" in vs
    assert data["generation_mode"] in ("extractive-fallback", "ollama-configured")
    assert data["database"] in ("sqlite (local file)", "postgresql")


# ---------------------------------------------------------------------------
# 12. RTB_RERANKER=off
# ---------------------------------------------------------------------------
def test_reranker_off_flag(monkeypatch):
    import app.services.retrieval as ret

    monkeypatch.setenv("RTB_RERANKER", "off")
    ret._reranker = None
    ret._reranker_tried = False
    try:
        kind, _ = ret.get_reranker()
        assert kind == "score", "RTB_RERANKER=off must force the score reranker"
        candidates = [
            {"document_id": "d1", "chunk_index": 0, "title": "KYC Policy",
             "content": "open account documents", "rrf_score": 0.02},
            {"document_id": "d2", "chunk_index": 0, "title": "Loan",
             "content": "personal loan rates", "rrf_score": 0.01},
        ]
        out = ret.rerank("What documents open an account?", candidates, top_k=2)
        assert all(d.get("reranker") == "score" for d in out)
    finally:
        ret._reranker = None
        ret._reranker_tried = False
