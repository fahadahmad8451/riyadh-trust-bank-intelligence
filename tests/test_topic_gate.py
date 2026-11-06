"""v0.10 tests — deterministic RBAC topic gate.

Run (from backend/):  python -m pytest ../tests/test_topic_gate.py -v

The gate (app/services/topic_gate.py) runs BEFORE retrieval: a
question that matches a topic of a department the caller's role may
not see is refused immediately, with 0 citations and
generation_mode "rbac-refusal". The exact case that motivated it:
a Service user asking "AML policy for high-risk customers?" used
to get an answer stitched from RETAIL chunks; now it is refused.

Isolation: same tmp-file pattern as test_rbac.py.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

USERS = {
    "admin": ("admin@rtb.local", "Admin123!"),
    "compliance": ("compliance@rtb.local", "Compliance123!"),
    "service": ("service@rtb.local", "Service123!"),
}

# (question, expected blocked department for service, for compliance)
# None = the role may ask it (answer expected, not a refusal).
CASES = [
    # The reported case, verbatim.
    ("AML policy for high-risk customers?", "COMPLIANCE", None),
    ("What is the AML reporting threshold?", "COMPLIANCE", None),
    ("What is anti-money laundering policy?", "COMPLIANCE", None),
    ("How do I report a suspicious transaction?", "COMPLIANCE", None),
    ("What are the SAMA compliance requirements?", "COMPLIANCE", None),
    ("What is the bank's policy on terrorist financing?", "COMPLIANCE", None),
    ("How many days of annual leave do employees get?", "HR", "HR"),
    ("What is the salary structure for employees?", "HR", "HR"),
    ("What does the PDPL privacy summary say about personal data?", "HR", "HR"),
    ("What is the HR leave policy?", "HR", "HR"),
    # Allowed questions — a Service user MUST still get answers.
    ("What documents are needed for KYC account opening?", None, None),
    ("What is the maximum personal loan amount?", None, None),
    ("What are the charges for a personal loan?", None, None),
]
AR_CASES = [
    # Arabic AML question: service refused, compliance answered.
    ("ما هو حد الإبلاغ عن المعاملات النقدية؟", "COMPLIANCE", None),
    ("ما هي سياسة مكافحة غسل الأموال؟", "COMPLIANCE", None),
]


@pytest.fixture(scope="module")
def isolated_env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("topic_gate")
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
    # v0.10: token comes from the httpOnly cookie jar.
    return {"Authorization": f"Bearer {client.cookies.get('rtb_access')}"}


def chat(client, headers, question: str) -> dict:
    res = client.post("/api/v1/chat", json={"question": question}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["data"]


# ---------------------------------------------------------------------------
# Unit: the gate itself (no HTTP, no retrieval)
# ---------------------------------------------------------------------------
def test_gate_unit_service_blocked_topics():
    from app.services.topic_gate import gated_department

    assert gated_department("AML policy for high-risk customers?", ["RETAIL"]) == "COMPLIANCE"
    assert gated_department("How many days of annual leave do employees get?", ["RETAIL"]) == "HR"
    assert gated_department("What does the PDPL summary say?", ["RETAIL", "COMPLIANCE"]) == "HR"


def test_gate_unit_allowed_questions_not_gated():
    from app.services.topic_gate import gated_department

    assert gated_department("What documents are needed for KYC account opening?", ["RETAIL"]) is None
    assert gated_department("What is the maximum personal loan amount?", ["RETAIL"]) is None
    assert gated_department("What is the AML reporting threshold?",
                            ["RETAIL", "COMPLIANCE"]) is None  # compliance may ask
    assert gated_department("What is the AML reporting threshold?",
                            ["RETAIL", "COMPLIANCE", "HR"]) is None  # admin may ask
    assert gated_department("What is the AML reporting threshold?", None) is None


def test_gate_unit_no_false_positive_on_plain_words():
    from app.services.topic_gate import gated_department

    # "leave" without an HR context word is not gated.
    assert gated_department("Please leave a message for the branch manager.", ["RETAIL"]) is None
    assert gated_department("How do I open a savings account?", ["RETAIL"]) is None


# ---------------------------------------------------------------------------
# Integration: role x topic matrix over the real /chat endpoint
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("question,blocked_service,blocked_compliance", CASES)
def test_topic_matrix(client, question, blocked_service, blocked_compliance):
    for who, blocked in (("service", blocked_service),
                         ("compliance", blocked_compliance),
                         ("admin", None)):
        data = chat(client, login(client, who), question)
        if blocked is None:
            assert data["refused"] is False, f"{who} should be answered: {question!r} -> {data}"
            assert data["citations"], f"{who} should get citations: {question!r}"
        else:
            assert data["refused"] is True, f"{who} should be refused: {question!r} -> {data}"
            assert data["generation_mode"] == "rbac-refusal", data
            assert data["citations"] == [], f"{who} must get 0 citations: {question!r}"
            assert data["blocked_department"] == blocked, data
            assert "role" in data["answer"].lower() or "ijazat" in data["answer"] or \
                "صلاحية" in data["answer"], data["answer"]


@pytest.mark.parametrize("question,blocked_service,blocked_compliance", AR_CASES)
def test_topic_matrix_arabic(client, question, blocked_service, blocked_compliance):
    for who, blocked in (("service", blocked_service),
                         ("compliance", blocked_compliance),
                         ("admin", None)):
        data = chat(client, login(client, who), question)
        if blocked is None:
            assert data["refused"] is False, f"{who} should be answered: {question!r}"
            assert data["citations"], f"{who} should get citations: {question!r}"
        else:
            assert data["refused"] is True, f"{who} should be refused: {question!r} -> {data}"
            assert data["generation_mode"] == "rbac-refusal", data
            assert data["citations"] == [], f"{who} must get 0 citations: {question!r}"
            assert data["blocked_department"] == blocked, data


def test_gate_refusal_is_audit_logged(client):
    from app.core.audit import read_audit

    headers = login(client, "service")
    chat(client, headers, "AML policy for high-risk customers?")
    entries, _ = read_audit(limit=500)
    gated = [e for e in entries
             if e.get("action") == "RBAC_DENIED"
             and "AML policy for high-risk customers?" in (e.get("detail") or "")]
    assert gated, "RBAC_DENIED audit entry missing for the topic-gate refusal"
