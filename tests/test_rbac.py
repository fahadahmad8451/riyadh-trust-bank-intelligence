"""Sprint 3 tests — JWT auth, RBAC enforcement, audit log.

Run (from backend/):  python -m pytest ../tests/test_rbac.py -v

Isolation: the user store, audit log and refresh-token files are
pointed at tmp files (RTB_USERS_FILE / RTB_AUDIT_FILE /
RTB_REFRESH_FILE / RTB_DENYLIST_FILE) so these tests never touch the
real data/users.json or data/audit.jsonl. The vector store and the
retriever are the real Sprint 1/2 ones (models are cached).

The core RBAC rule under test: a disallowed chunk must NEVER be
retrieved, cited, or fed to the generator. Tests assert on the
citations actually returned by POST /api/v1/chat, not on UI hiding.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

AML_Q = "What is the AML reporting threshold?"
HR_Q = "How many days of annual leave do employees get?"
PDPL_Q = "What does the PDPL privacy summary say about personal data?"
KYC_Q = "What documents are needed for KYC account opening?"

USERS = {
    "admin": ("admin@rtb.local", "Admin123!"),
    "compliance": ("compliance@rtb.local", "Compliance123!"),
    "service": ("service@rtb.local", "Service123!"),
}


@pytest.fixture(scope="module")
def isolated_env(tmp_path_factory):
    """Point user/audit/refresh files at tmp files and seed demo users."""
    tmp = tmp_path_factory.mktemp("rbac")
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


def login(client, who: str) -> dict:
    email, password = USERS[who]
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    token = client.cookies.get("rtb_access")  # v0.10: httpOnly cookie
    return {"Authorization": f"Bearer {token}"}


def chat(client, headers, question: str) -> dict:
    res = client.post("/api/v1/chat", json={"question": question}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["data"]


def cited_departments(data: dict) -> set:
    return {c["department"] for c in data["citations"]}


# ---------------------------------------------------------------------------
# 1-4. Authentication: 401s
# ---------------------------------------------------------------------------
def test_unauthenticated_chat_is_401(client):
    client.cookies.clear()
    res = client.post("/api/v1/chat", json={"question": KYC_Q})
    assert res.status_code == 401


def test_unauthenticated_documents_is_401(client):
    client.cookies.clear()
    assert client.get("/api/v1/documents").status_code == 401


def test_unauthenticated_admin_is_401(client):
    client.cookies.clear()
    assert client.get("/api/v1/admin/users").status_code == 401
    assert client.get("/api/v1/admin/audit-logs").status_code == 401


def test_wrong_password_is_401(client):
    res = client.post("/api/v1/auth/login",
                      json={"email": "admin@rtb.local", "password": "wrong-password"})
    assert res.status_code == 401
    assert res.json()["success"] is False


def test_unknown_email_is_401(client):
    res = client.post("/api/v1/auth/login",
                      json={"email": "nobody@rtb.local", "password": "whatever"})
    assert res.status_code == 401


def test_expired_token_is_401(client):
    from app.core.security import create_access_token

    client.cookies.clear()  # present ONLY the expired Bearer token

    expired = create_access_token("admin@rtb.local", "ADMIN", expires_minutes=-1)
    res = client.post("/api/v1/chat", json={"question": KYC_Q},
                      headers={"Authorization": f"Bearer {expired}"})
    assert res.status_code == 401


def test_refresh_token_cannot_be_used_as_access_token(client):
    res = client.post("/api/v1/auth/login",
                      json={"email": USERS["admin"][0], "password": USERS["admin"][1]})
    refresh = client.cookies.get("rtb_refresh")  # v0.10: httpOnly cookie
    # Clear the jar: the chat call must present ONLY the refresh
    # token as a Bearer token (otherwise the login's access cookie
    # in the jar would authenticate the request on its own).
    client.cookies.clear()
    res = client.post("/api/v1/chat", json={"question": KYC_Q},
                      headers={"Authorization": f"Bearer {refresh}"})
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# 5-6. Login works and returns the right role/departments
# ---------------------------------------------------------------------------
def test_login_returns_user_with_departments(client):
    res = client.post("/api/v1/auth/login",
                      json={"email": USERS["compliance"][0], "password": USERS["compliance"][1]})
    assert res.status_code == 200
    user = res.json()["data"]["user"]
    assert user["role"] == "COMPLIANCE_OFFICER"
    assert user["departments"] == ["COMPLIANCE", "RETAIL"]


def test_refresh_and_logout_flow(client):
    res = client.post("/api/v1/auth/login",
                      json={"email": USERS["admin"][0], "password": USERS["admin"][1]})
    refresh = client.cookies.get("rtb_refresh")  # v0.10: httpOnly cookie
    res = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert res.status_code == 200
    new_refresh = client.cookies.get("rtb_refresh")  # v0.10: rotated cookie
    assert new_refresh != refresh  # rotation: a fresh refresh token is issued
    assert client.post("/api/v1/auth/logout", json={"refresh_token": new_refresh}).status_code == 200
    # The revoked refresh token no longer works.
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh}).status_code == 401


# ---------------------------------------------------------------------------
# 7-10. RBAC in chat: citations must never leak a disallowed department
# ---------------------------------------------------------------------------
def test_service_asking_aml_gets_refusal_no_aml_citation(client):
    data = chat(client, login(client, "service"), AML_Q)
    assert data["rbac_enforced"] is True
    assert data["role"] == "CUSTOMER_SERVICE"
    assert "COMPLIANCE" not in cited_departments(data)
    assert data["refused"] is True
    assert data["citations"] == []


def test_compliance_asking_aml_gets_aml_citation(client):
    data = chat(client, login(client, "compliance"), AML_Q)
    assert data["refused"] is False
    assert data["citations"], "compliance should get AML citations"
    assert data["citations"][0]["document_id"] == "02-aml-policy.pdf"
    assert "HR" not in cited_departments(data)


def test_admin_asking_aml_gets_aml_citation(client):
    data = chat(client, login(client, "admin"), AML_Q)
    assert data["refused"] is False
    assert data["citations"][0]["document_id"] == "02-aml-policy.pdf"


def test_compliance_asking_hr_gets_no_hr_citation(client):
    data = chat(client, login(client, "compliance"), HR_Q)
    assert "HR" not in cited_departments(data)
    assert all(c["document_id"] != "06-hr-leave-policy.pdf" for c in data["citations"])
    assert all(c["document_id"] != "08-pdpl-privacy-summary.pdf" for c in data["citations"])


def test_admin_asking_hr_gets_hr_citation(client):
    data = chat(client, login(client, "admin"), HR_Q)
    assert data["refused"] is False
    assert data["citations"][0]["document_id"] == "06-hr-leave-policy.pdf"


def test_service_asking_hr_gets_no_hr_citation(client):
    data = chat(client, login(client, "service"), HR_Q)
    assert "HR" not in cited_departments(data)
    assert "COMPLIANCE" not in cited_departments(data)


def test_compliance_asking_pdpl_gets_no_pdpl_citation(client):
    # PDPL is an HR document in Sprint 3 (corrected from COMPLIANCE) —
    # a Compliance Officer must never see it.
    data = chat(client, login(client, "compliance"), PDPL_Q)
    assert all(c["document_id"] != "08-pdpl-privacy-summary.pdf" for c in data["citations"])
    assert "HR" not in cited_departments(data)


def test_service_can_still_answer_retail_questions(client):
    data = chat(client, login(client, "service"), KYC_Q)
    assert data["refused"] is False
    assert data["citations"]
    assert cited_departments(data) == {"RETAIL"}


# ---------------------------------------------------------------------------
# 11-13. RBAC in documents / upload / admin
# ---------------------------------------------------------------------------
def test_documents_list_is_filtered_by_role(client):
    admin_docs = client.get("/api/v1/documents", headers=login(client, "admin")).json()["data"]
    assert admin_docs["count"] == 8
    service_docs = client.get("/api/v1/documents", headers=login(client, "service")).json()["data"]
    assert service_docs["count"] == 4  # RETAIL only
    assert {d["department"] for d in service_docs["documents"]} == {"RETAIL"}
    compliance_docs = client.get("/api/v1/documents", headers=login(client, "compliance")).json()["data"]
    assert compliance_docs["count"] == 6  # RETAIL + COMPLIANCE
    assert {d["department"] for d in compliance_docs["documents"]} == {"RETAIL", "COMPLIANCE"}


def test_service_cannot_fetch_compliance_document_by_id(client):
    res = client.get("/api/v1/documents/02-aml-policy.pdf", headers=login(client, "service"))
    assert res.status_code == 404  # 404, not 403 — existence is not leaked
    res = client.get("/api/v1/documents/02-aml-policy.pdf", headers=login(client, "compliance"))
    assert res.status_code == 200
    assert res.json()["data"]["document"]["title"].startswith("Anti-Money Laundering")


def test_service_upload_is_403_and_compliance_upload_is_403(client):
    for who in ("service", "compliance"):
        res = client.post(
            "/api/v1/documents/upload", headers=login(client, who),
            files={"file": ("x.pdf", b"junk", "application/pdf")},
        )
        assert res.status_code == 403, f"{who} upload should be 403, got {res.status_code}"


def test_non_admin_cannot_read_audit_logs_or_users(client):
    for who in ("service", "compliance"):
        headers = login(client, who)
        assert client.get("/api/v1/admin/audit-logs", headers=headers).status_code == 403
        assert client.get("/api/v1/admin/users", headers=headers).status_code == 403


def test_admin_can_read_users_and_audit_logs(client):
    headers = login(client, "admin")
    users = client.get("/api/v1/admin/users", headers=headers)
    assert users.status_code == 200
    assert users.json()["data"]["count"] == 3
    assert all("password_hash" not in u for u in users.json()["data"]["users"])
    logs = client.get("/api/v1/admin/audit-logs", headers=headers)
    assert logs.status_code == 200
    assert logs.json()["data"]["total"] >= 1


# ---------------------------------------------------------------------------
# 14. Audit log actually records the calls above
# ---------------------------------------------------------------------------
def test_audit_log_records_login_query_and_denials(client):
    headers = login(client, "admin")
    # Make a query and a denied call, then check the log contains them.
    chat(client, headers, KYC_Q)
    client.get("/api/v1/admin/users", headers=login(client, "service"))
    # The service login replaced the cookie jar — log back in as admin
    # so the audit-log read is authenticated as admin.
    headers = login(client, "admin")
    logs = client.get("/api/v1/admin/audit-logs?limit=500", headers=headers).json()["data"]
    actions = [e["action"] for e in logs["audit_logs"]]
    assert "LOGIN" in actions
    assert "QUERY" in actions
    assert "ACCESS_DENIED" in actions
    # Query entries must record who asked (the audit log is shared by
    # the whole module, so earlier tests' service queries are in here
    # too — assert the admin query we just made is recorded).
    query_entries = [e for e in logs["audit_logs"] if e["action"] == "QUERY"]
    assert query_entries
    assert any(e["user"] == "admin@rtb.local" for e in query_entries)
    for entry in query_entries:
        assert entry["user"] in ("admin@rtb.local", "compliance@rtb.local",
                                 "service@rtb.local")
