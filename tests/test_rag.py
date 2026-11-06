"""Sprint 2 tests — hybrid retrieval + grounded generation + /chat API.

Run (from backend/):  python -m pytest ../tests/test_rag.py -v
The 10-question set (6 EN, 4 AR) is the Sprint 2 acceptance test:
at least 8/10 must cite the correct document, and the out-of-scope
question must be refused with empty citations. The embedding model
loads once (module-scoped retriever); Ollama is probed per answer and
is expected to be absent on this VM, so generation_mode is
"extractive-fallback" here — the test asserts the mode is honest
(ollama or extractive-fallback), never a claimed LLM answer.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.generation import REFUSAL_EN, answer_question
from app.services.retrieval import BM25Index, detect_language, get_retriever

# (question, expected document_id(s), language)
# The KYC question accepts either 01 or 05: BOTH documents hold the
# authoritative "Documents Needed for Account Opening" list (Sprint 1
# note), so either top citation is a correct answer for this question.
QUESTIONS = [
    ("What documents are needed for KYC account opening?",
     {"01-kyc-policy.pdf", "05-account-opening-policy.pdf"}, "en"),
    ("What is the AML reporting threshold?", "02-aml-policy.pdf", "en"),
    ("How long does it take to open an account at a branch?", "05-account-opening-policy.pdf", "en"),
    ("What is the maximum personal loan amount?", "04-personal-loan-policy.pdf", "en"),
    ("How many days of annual leave do employees get?", "06-hr-leave-policy.pdf", "en"),
    ("What is the monthly account fee if the average balance falls below SAR 1,000?",
     "07-charges-fees-schedule.pdf", "en"),
    # Same as the English KYC question: both Arabic summaries list the
    # required documents, so either document is a correct top citation.
    ("ما هي المستندات المطلوبة لفتح حساب؟",
     {"01-kyc-policy.pdf", "05-account-opening-policy.pdf"}, "ar"),
    ("ما هو حد الإبلاغ عن المعاملات النقدية؟", "02-aml-policy.pdf", "ar"),
    ("ما هي شروط القرض الشخصي؟", "04-personal-loan-policy.pdf", "ar"),
    ("كم عدد أيام الإجازة السنوية؟", "06-hr-leave-policy.pdf", "ar"),
]

OUT_OF_SCOPE = "What is the weather in Jeddah tomorrow?"


@pytest.fixture(scope="module")
def retriever():
    return get_retriever()


def test_detect_language_ar_and_en():
    assert detect_language("ما هي المستندات؟") == "ar"
    assert detect_language("What is the AML threshold?") == "en"
    assert detect_language("ما هو حد 60,000 SAR؟") == "ar"


def test_bm25_finds_aml_threshold(retriever):
    index = BM25Index(retriever._chunks)
    results = index.search("What is the AML reporting threshold?", top_k=3)
    assert results, "BM25 returned nothing"
    assert results[0]["document_id"] == "02-aml-policy.pdf"


def test_rag_questions_cite_correct_document(retriever):
    correct = 0
    failures = []
    for question, expected_docs, _lang in QUESTIONS:
        if isinstance(expected_docs, str):
            expected_docs = {expected_docs}
        result = answer_question(question, retriever=retriever)
        assert result["refused"] is False, f"refused a valid question: {question}"
        assert result["citations"], f"no citations for: {question}"
        top_doc = result["citations"][0]["document_id"]
        # Every citation must point at a chunk that exists in the store.
        store_docs = {m["document_id"] for m in retriever._chunks}
        for cit in result["citations"]:
            assert cit["document_id"] in store_docs
        if top_doc in expected_docs:
            correct += 1
        else:
            failures.append((question, top_doc, expected_docs))
    assert correct >= 8, f"only {correct}/10 correct: {failures}"


def test_out_of_scope_is_refused(retriever):
    result = answer_question(OUT_OF_SCOPE, retriever=retriever)
    assert result["refused"] is True
    assert result["citations"] == []
    assert result["answer"] == REFUSAL_EN
    assert result["generation_mode"] == "refusal"


def test_generation_mode_is_honest(retriever):
    result = answer_question(QUESTIONS[0][0], retriever=retriever)
    assert result["generation_mode"] in ("ollama", "extractive-fallback")
    # On this VM Ollama is not running, so the honest mode is the fallback.
    assert result["ollama"]["available"] is False
    assert result["generation_mode"] == "extractive-fallback"
    assert "[KYC Policy" in result["answer"] or "KYC" in result["answer"]


def _admin_headers(client):
    """Sprint 3: /chat needs a JWT. Seed the demo users if needed and
    log in as admin (sees all departments, so Sprint 2 expectations
    still hold)."""
    from app.core.users import load_users, seed_users

    if not load_users():
        seed_users()
    res = client.post("/api/v1/auth/login",
                      json={"email": "admin@rtb.local", "password": "Admin123!"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['data']['access_token']}"}


def test_chat_api_returns_citations_and_saves_conversation():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    headers = _admin_headers(client)
    res = client.post("/api/v1/chat", json={"question": QUESTIONS[0][0]}, headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    data = body["data"]
    assert data["citations"], "chat response has no citations"
    assert data["citations"][0]["document_id"] in QUESTIONS[0][1]
    assert data["generation_mode"] in ("ollama", "extractive-fallback")
    assert data["rbac_enforced"] is True
    cid = data["conversation_id"]
    res2 = client.get(f"/api/v1/conversations/{cid}", headers=headers)
    assert res2.status_code == 200
    assert res2.json()["data"]["message_count"] == 2  # user + assistant


def test_chat_api_refuses_out_of_scope():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    headers = _admin_headers(client)
    res = client.post("/api/v1/chat", json={"question": OUT_OF_SCOPE}, headers=headers)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["refused"] is True
    assert data["citations"] == []
