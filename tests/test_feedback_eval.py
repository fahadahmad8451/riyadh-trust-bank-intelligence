"""Sprint 4 tests — feedback, local RAGAS-style evaluation, RBAC refusal.

Run (from backend/):  python -m pytest ../tests/test_feedback_eval.py -v

Feedback is isolated: RTB_FEEDBACK_FILE points at a tmp file, so the
tests never touch the real data/feedback.jsonl. Chat messages are
verified against the real data/conversations.jsonl (the same pattern
as the Sprint 2/3 tests — a feedback vote must point at a message
that really exists, so the test asks a real question first).

The eval tests use the fixed tests/eval_set.json (20 questions) and
the real pipeline. The full 20-question run is NOT executed inside
pytest (it takes minutes on this VM) — the script scripts/run_eval.py
does the full run; here run_eval(limit=2) proves the endpoint and
the scoring work end to end.
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

USERS = {
    "admin": ("admin@rtb.local", "Admin123!"),
    "service": ("service@rtb.local", "Service123!"),
}
AML_Q = "What is the AML reporting threshold?"
HR_Q = "How many days of annual leave do employees get?"
KYC_Q = "What documents are needed for KYC account opening?"


@pytest.fixture(scope="module")
def isolated_env(tmp_path_factory):
    """Feedback file -> tmp; users/audit/refresh -> tmp (Sprint 3 pattern)."""
    tmp = tmp_path_factory.mktemp("feedback_eval")
    os.environ["RTB_FEEDBACK_FILE"] = str(tmp / "feedback.jsonl")
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
    return {"Authorization": f"Bearer {client.cookies.get('rtb_access')}"}


def ask(client, headers: dict, question: str) -> dict:
    res = client.post("/api/v1/chat", headers=headers, json={"question": question})
    assert res.status_code == 200, res.text
    return res.json()["data"]


# ---------------------------------------------------------------------------
# 1. Eval set: fixed, 20 questions, every expected doc really exists
# ---------------------------------------------------------------------------
def test_eval_set_is_fixed_and_valid():
    path = Path(__file__).resolve().parents[1] / "tests" / "eval_set.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    questions = data["questions"]
    assert len(questions) == 20, f"eval set must have 20 questions, has {len(questions)}"
    assert sum(1 for q in questions if q["language"] == "en") == 10
    assert sum(1 for q in questions if q["language"] == "ar") == 10
    manifest = json.loads(
        (Path(__file__).resolve().parents[1] / "data" / "docs_manifest.json")
        .read_text(encoding="utf-8"))
    known_docs = {d["document_id"] for d in manifest["documents"]}
    for q in questions:
        assert q["expected_documents"], q["id"]
        assert set(q["expected_documents"]) <= known_docs, q["id"]
        assert q["expected_page"] in (1, 2), q["id"]
        assert q["expected_phrase"], q["id"]


# ---------------------------------------------------------------------------
# 2. Metric formulas: unit tests on known inputs (no model needed)
# ---------------------------------------------------------------------------
def test_faithfulness_supported_and_unsupported():
    from app.services.evaluation import faithfulness

    chunk = "The AML reporting threshold is SAR 60,000 or more. Cash transactions must be reported."
    supported = "The AML reporting threshold is SAR 60,000 or more. [AML Policy, page 1]"
    assert faithfulness(supported, [chunk]) == 1.0
    invented = "The bank gives every customer a free gold bar every Friday."
    assert faithfulness(invented, [chunk]) == 0.0
    assert faithfulness("", [chunk]) == 0.0


def test_relevancy_is_a_cosine_in_range():
    from app.services.evaluation import answer_relevancy

    score = answer_relevancy("What is the AML reporting threshold?",
                             "The AML reporting threshold is SAR 60,000 or more.")
    assert -1.0 <= score <= 1.0
    assert score > 0.3, f"related Q/A should score clearly above 0, got {score}"


def test_ragas_is_not_used():
    from app.services.evaluation import METHOD, RAGAS_AVAILABLE

    assert RAGAS_AVAILABLE is False  # ragas is not installed on this VM
    assert "no LLM judge" in METHOD


# ---------------------------------------------------------------------------
# 3. Feedback: auth, validation, upsert, stats
# ---------------------------------------------------------------------------
def test_feedback_requires_login(client):
    client.cookies.clear()
    res = client.post("/api/v1/feedback",
                      json={"message_id": "nope", "rating": "up"})
    assert res.status_code == 401


def test_feedback_rejects_unknown_message(client):
    headers = login(client, "admin")
    res = client.post("/api/v1/feedback", headers=headers,
                      json={"message_id": "does-not-exist", "rating": "up"})
    assert res.status_code == 200  # envelope: success False, like other 404s
    assert res.json()["success"] is False


def test_feedback_rejects_bad_rating(client):
    headers = login(client, "admin")
    data = ask(client, headers, KYC_Q)
    res = client.post("/api/v1/feedback", headers=headers,
                      json={"message_id": data["message_id"], "rating": "love"})
    assert res.status_code == 422


def test_feedback_up_then_down_upserts_and_stats(client):
    headers = login(client, "admin")
    data = ask(client, headers, KYC_Q)
    mid = data["message_id"]
    assert mid, "chat must return a message_id for feedback"
    res = client.post("/api/v1/feedback", headers=headers,
                      json={"message_id": mid, "rating": "up"})
    assert res.status_code == 200
    assert res.json()["data"]["message"] == "Shukriya, feedback mil gaya."
    assert res.json()["data"]["updated"] is False
    # Change the vote: same (user, message) is updated, not duplicated.
    res = client.post("/api/v1/feedback", headers=headers,
                      json={"message_id": mid, "rating": "down",
                            "comment": "jawab adhoora tha"})
    assert res.json()["data"]["updated"] is True
    stats = client.get("/api/v1/admin/feedback-stats", headers=headers)
    assert stats.status_code == 200
    body = stats.json()["data"]
    assert body["total"] == 1, body
    assert body["down"] == 1 and body["up"] == 0
    assert body["percent_up"] == 0.0
    assert len(body["worst"]) == 1
    assert body["worst"][0]["message_id"] == mid
    assert body["worst"][0]["question"] == KYC_Q
    assert body["worst"][0]["comment"] == "jawab adhoora tha"


def test_feedback_stats_is_admin_only(client):
    headers = login(client, "service")
    res = client.get("/api/v1/admin/feedback-stats", headers=headers)
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# 4. Sprint 4 RBAC refusal: blocked topic gets a clean refusal
# ---------------------------------------------------------------------------
def test_service_aml_gets_rbac_refusal(client):
    data = ask(client, login(client, "service"), AML_Q)
    assert data["refused"] is True
    assert data["citations"] == []
    assert data["generation_mode"] == "rbac-refusal"
    assert data.get("rbac_blocked") is True
    assert data.get("blocked_department") == "COMPLIANCE"
    assert "ijazat nahi hai" in data["answer"]


def test_compliance_hr_gets_rbac_refusal(client):
    data = ask(client, login(client, "service"), HR_Q)  # service cannot see HR either
    assert data["generation_mode"] == "rbac-refusal"
    assert data.get("blocked_department") == "HR"
    # And the Compliance Officer, who also cannot see HR:
    from app.services.generation import answer_question
    from app.services.retrieval import get_retriever

    result = answer_question(HR_Q, retriever=get_retriever(),
                             allowed_departments=["RETAIL", "COMPLIANCE"])
    assert result["generation_mode"] == "rbac-refusal"
    assert result.get("blocked_department") == "HR"


def test_allowed_question_still_answers(client):
    data = ask(client, login(client, "service"), KYC_Q)
    assert data["refused"] is False
    assert data["citations"]
    assert data["generation_mode"] in ("ollama", "extractive-fallback")


# ---------------------------------------------------------------------------
# 5. Eval run (small): endpoint works, report is honest
# ---------------------------------------------------------------------------
def test_eval_run_limit_two_and_results(client):
    headers = login(client, "admin")
    res = client.get("/api/v1/eval/run?limit=2", headers=headers)
    assert res.status_code == 200, res.text
    report = res.json()["data"]
    assert report["method"] == "local-ragas-style (no LLM judge)"
    assert report["ragas_used"] is False
    assert report["question_count"] == 2
    assert set(report["aggregates"]) >= {
        "faithfulness", "context_recall", "answer_relevancy",
        "latency_ms_p50", "latency_ms_p95"}
    assert 0.0 <= report["aggregates"]["faithfulness"] <= 1.0
    assert 0.0 <= report["aggregates"]["context_recall"] <= 1.0
    res2 = client.get("/api/v1/eval/results", headers=headers)
    assert res2.status_code == 200
    assert res2.json()["data"]["question_count"] == 2


def test_eval_endpoints_are_admin_only(client):
    headers = login(client, "service")
    assert client.get("/api/v1/eval/run?limit=1", headers=headers).status_code == 403
    assert client.get("/api/v1/eval/results", headers=headers).status_code == 403
