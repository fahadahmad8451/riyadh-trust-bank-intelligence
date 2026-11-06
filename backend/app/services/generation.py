"""Grounded generation — Sprint 2.

Explicit pipeline (retrieve -> rerank -> generate -> verify). This is
NOT LangGraph — no LangGraph import is used, and the code does not
claim otherwise. The pipeline is a plain, inspectable sequence of
functions, which is the honest description of what runs.

Generation modes (the actual mode is always returned in the response):
  * "ollama" — a real local LLM (llama3.1:8b, temperature 0.1) answered
    via the Ollama HTTP API. Only used when Ollama is reachable and a
    model is present.
  * "extractive-fallback" — Ollama is NOT reachable / has no model
    (the case on this VM). The answer is composed ONLY from the top
    retrieved chunks: relevant sentences are quoted, each with its
    [Doc, page] citation. Nothing is invented, and the response says
    so. This is a real grounded answer, not an LLM answer, and it is
    never presented as one.

Guardrail: if the best vector score is below REFUSAL_THRESHOLD, or
retrieval returns nothing, the answer is the refusal
"Is document me ye maloomat nahi hai" (EN) / "هذه المعلومات غير موجودة
في المستندات" (AR), with empty citations. PII-like 10-digit numbers
are masked in answers.
"""
import json
import logging
import re
import time

import httpx

from app.core.config import settings
from app.services.retrieval import REFUSAL_THRESHOLD, detect_language
from app.services.topic_gate import gated_department

logger = logging.getLogger("rtb.generation")

SYSTEM_PROMPT = (
    "Sirf diye gaye context se jawab do. Agar jawab context me nahi, to "
    "'Is document me ye maloomat nahi hai' kaho. Har claim ke sath "
    "[Doc, Page] citation do."
)
OLLAMA_MODEL = "llama3.1:8b"
OLLAMA_TIMEOUT = 120.0
REFUSAL_EN = "Is document me ye maloomat nahi hai."
REFUSAL_AR = "هذه المعلومات غير موجودة في المستندات."
# Sprint 4 — RBAC-blocked topic refusal (clean, instead of stitching an
# answer from allowed chunks that merely share words with the question).
RBAC_REFUSAL_EN = ("Aap ke role ko is topic ke documents dekhne ki ijazat "
                   "nahi hai. Please ask your administrator or the "
                   "Compliance Department.")
RBAC_REFUSAL_AR = ("ليس لديك صلاحية للاطلاع على مستندات هذا الموضوع. "
                   "يرجى التواصل مع المسؤول أو قسم الامتثال.")

_PII_RE = re.compile(r"\b\d{10}\b")  # Saudi National ID / Iqama shape


def ollama_host() -> str:
    return (settings.ollama_host or "http://localhost:11434").rstrip("/")


# v0.10: Ollama availability is cached for 10 s — answer_question()
# calls ollama_available() on every chat, and an HTTP probe per chat
# is pure overhead when Ollama is not there (or is there). The cache
# is per-process and only affects WHICH generation mode is picked;
# a stale 10 s entry cannot leak or invent anything.
_OLLAMA_CACHE: dict = {"at": 0.0, "result": {"available": False, "models": []}}
OLLAMA_CACHE_TTL_S = 10.0


def ollama_available() -> dict:
    """Probe Ollama. Returns {available, models}. Never raises.
    Result is cached for OLLAMA_CACHE_TTL_S (see above)."""
    now = time.time()
    if now - _OLLAMA_CACHE["at"] < OLLAMA_CACHE_TTL_S:
        return _OLLAMA_CACHE["result"]
    try:
        res = httpx.get(f"{ollama_host()}/api/tags", timeout=3.0)
        if res.status_code != 200:
            result = {"available": False, "models": []}
        else:
            models = [m.get("name") for m in res.json().get("models", [])]
            result = {"available": True, "models": models}
    except Exception as exc:  # noqa: BLE001 — Ollama simply not there
        logger.info("Ollama not reachable (%s) — extractive fallback will be used", exc)
        result = {"available": False, "models": []}
    _OLLAMA_CACHE["at"] = now
    _OLLAMA_CACHE["result"] = result
    return result


def mask_pii(text: str) -> str:
    return _PII_RE.sub("**********", text)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?؟])\s+", (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def _extractive_answer(question: str, chunks: list[dict], language: str) -> str:
    """Compose an answer ONLY from retrieved chunks. For each of the top
    chunks, pick the sentences that share the most words with the
    question (at least one shared word, else the chunk's first sentence),
    and quote them with a citation marker. No sentence is invented."""
    from app.services.retrieval import tokenize

    q_tokens = set(tokenize(question))
    lines: list[str] = []
    for chunk in chunks[:3]:
        best = []
        for sentence in _sentences(chunk.get("content", "")):
            # Skip heading-only fragments (short lines with no real
            # sentence in them) — they quote a title, not an answer.
            if len(sentence) < 50:
                continue
            overlap = len(q_tokens & set(tokenize(sentence)))
            best.append((overlap, sentence))
        best.sort(key=lambda x: -x[0])
        picked = [s for _, s in best[:2] if s]
        if not picked:
            continue
        title = chunk.get("title", "?")
        page = chunk.get("page_no", "?")
        for sentence in picked:
            lines.append(f"{mask_pii(sentence)} [{title}, page {page}]")
    if not lines:
        return REFUSAL_AR if language == "ar" else REFUSAL_EN
    if language == "ar":
        intro = "وفقًا للمستندات المتوفرة:"
    else:
        intro = "According to the bank documents:"
    return intro + "\n" + "\n".join(f"- {line}" for line in lines)


def _ollama_answer(question: str, chunks: list[dict], language: str) -> str | None:
    """Ask the local Ollama model. Returns the answer text, or None if
    Ollama fails for any reason (caller falls back honestly)."""
    context = "\n\n".join(
        f"[{c.get('title', '?')}, page {c.get('page_no', '?')}]\n{c.get('content', '')}"
        for c in chunks[:5]
    )
    prompt = (
        f"{SYSTEM_PROMPT}\n\nContext:\n{context}\n\n"
        f"Question ({language}): {question}\nAnswer:"
    )
    try:
        res = httpx.post(
            f"{ollama_host()}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": 800},
            },
            timeout=OLLAMA_TIMEOUT,
        )
        if res.status_code != 200:
            logger.warning("Ollama returned HTTP %s", res.status_code)
            return None
        return mask_pii(res.json().get("response", "").strip()) or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ollama generate failed (%s)", exc)
        return None


def _citations(chunks: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for chunk in chunks:
        key = (chunk.get("document_id"), chunk.get("chunk_index"))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "document_id": chunk.get("document_id"),
            "document_title": chunk.get("title"),
            "page_no": chunk.get("page_no"),
            "department": chunk.get("department"),
            "score": chunk.get("rerank_score", chunk.get("score")),
        })
    return out


def _rbac_blocked_department(question: str, retriever, allowed_departments: list[str],
                             allowed_result: dict) -> str | None:
    """Return the blocked department a question is really about, or None.

    Compares the unrestricted best chunk with the allowed retrieval:
    blocked = the unrestricted best chunk is in a department the caller
    cannot see, it matches strongly, and the allowed retrieval is
    clearly weaker. The comparison uses the RERANKER scores — the
    cross-encoder is the best relevance judge we have (measured
    2026-11-06: compliance asking about HR leave scored -5.5 on the
    best allowed chunk vs +4.0 on the HR chunk; PDPL -10.4 vs +6.8;
    a genuine allowed question scores +6.5 on both sides). Thresholds
    are mode-aware because the two rerankers score on different
    scales: cross-encoder logits (strong >= 1.0, weak = allowed more
    than 3.0 below unrestricted) vs score-based RRF sums (strong
    >= 0.015 — one top-ranked list — weak = allowed below half of
    unrestricted). A weak unrestricted match (out-of-scope questions
    such as the weather) never triggers this — those fall through to
    the normal "not in the documents" refusal. Returns the department
    name, or None. Never raises — on any error it returns None (fail
    open to the normal refusal/answer path, never to a leak).
    """
    try:
        # v0.10: the probe uses the SCORE reranker (rerank_mode="score")
        # — it only needs a top-1 comparison, and a cross-encoder
        # predict costs ~3s on this RAM-starved VM (profiled 2026-11-06:
        # rerank 3.2-4.7s of a 4.6-9.7s EN chat). The probe thresholds
        # already have a score-based branch (strong >= 0.015, weak =
        # allowed below half of unrestricted), so this is a supported
        # mode, not a shortcut. The real answer still uses the
        # cross-encoder.
        unrestricted = retriever.retrieve(question, top_k=1,
                                         allowed_departments=None,
                                         rerank_mode="score")
    except Exception as exc:  # noqa: BLE001 — probe is best-effort
        logger.info("Unrestricted RBAC probe failed (%s) — skipping", exc)
        return None
    top = unrestricted.get("reranked") or []
    if not top:
        return None
    department = top[0].get("department")
    if not department or department in allowed_departments:
        return None
    if not (unrestricted.get("top_score", 0.0) >= 0.35
            or unrestricted.get("bm25_top_score", 0.0) > 0):
        return None  # unrestricted match itself is weak: not a blocked topic
    u_score = top[0].get("rerank_score")
    if u_score is None:
        return None
    allowed_top = (allowed_result.get("reranked") or [None])[0]
    a_score = allowed_top.get("rerank_score") if allowed_top else None
    cross_encoder = "cross-encoder" in str(unrestricted.get("reranker", ""))
    if cross_encoder:
        strong = u_score >= 1.0
        weak = a_score is None or a_score < u_score - 3.0
    else:
        strong = u_score >= 0.015
        weak = a_score is None or a_score < 0.5 * u_score
    return department if (strong and weak) else None


def answer_question(question: str, retriever=None, top_k: int = 5,
                    allowed_departments: list[str] | None = None) -> dict:
    """Full pipeline: retrieve -> rerank -> generate -> verify.

    Returns a dict ready for the /chat API response:
      answer, citations, retrieval_scores, latency_ms, generation_mode,
      language, retrieved_count, refused, ollama (probe result).
    Every citation points at a chunk that really exists in the store.

    RBAC (Sprint 3): allowed_departments is the caller's department
    list (from app.core.rbac). It is passed to the retriever BEFORE
    ranking, so disallowed chunks never reach the answer. None means
    "no restriction" (direct calls without a logged-in user, e.g. the
    Sprint 2 tests); the /chat API always passes the caller's list.
    An empty list means the user may see no documents at all.
    """
    from app.services.retrieval import get_retriever

    started = time.time()
    question = (question or "").strip()
    if not question:
        return {
            "answer": REFUSAL_EN, "citations": [], "retrieval_scores": {},
            "latency_ms": 0, "generation_mode": "refusal",
            "language": "en", "retrieved_count": 0, "refused": True,
            "ollama": {"available": False, "models": []},
        }
    language = detect_language(question)
    if allowed_departments is not None and not allowed_departments:
        return {
            "answer": ("You do not have access to any documents. "
                       "Please ask your administrator to grant you access."),
            "citations": [],
            "retrieval_scores": {"allowed_departments": []},
            "latency_ms": round((time.time() - started) * 1000, 1),
            "generation_mode": "refusal",
            "language": language,
            "retrieved_count": 0,
            "refused": True,
            "ollama": {"available": False, "models": []},
        }
    retriever = retriever or get_retriever()

    # v0.10 — deterministic topic gate (BEFORE any retrieval): if the
    # question is about a department this role may NOT see (AML for
    # Service, HR for Service/Compliance, PDPL for non-admin), refuse
    # immediately with no retrieval at all. The score-based probe
    # below stays as a fallback for phrasings the keyword map does
    # not cover — but the gate is what guarantees the reported case
    # ("AML policy for high-risk customers?" as Service) is refused
    # instead of answered from RETAIL chunks that share its words.
    if allowed_departments is not None:
        gated = gated_department(question, allowed_departments)
        if gated is not None:
            rbac_answer = RBAC_REFUSAL_AR if language == "ar" else RBAC_REFUSAL_EN
            return {
                "answer": rbac_answer,
                "citations": [],
                "retrieval_scores": {
                    "blocked_department": gated,
                    "topic_gate": True,
                },
                "latency_ms": round((time.time() - started) * 1000, 1),
                "generation_mode": "rbac-refusal",
                "language": language,
                "retrieved_count": 0,
                "refused": True,
                "rbac_blocked": True,
                "topic_gate": True,
                "blocked_department": gated,
                "ollama": {"available": False, "models": []},
            }

    result = retriever.retrieve(question, top_k=top_k,
                                allowed_departments=allowed_departments)
    reranked = result["reranked"]
    top_score = result["top_score"]
    ollama = ollama_available()

    # Sprint 4 — RBAC-blocked topic: if the question is really about a
    # department the caller may NOT see, and nothing the caller may see
    # matches it well, say so cleanly instead of stitching an answer
    # from allowed chunks that merely share words (the Sprint 3 quality
    # note). Detection: run the same query once WITHOUT the department
    # filter. If the unrestricted best chunk belongs to a blocked
    # department, matches strongly, and the allowed retrieval is weak,
    # the topic is blocked for this role. Out-of-scope questions (e.g.
    # the weather) do not trigger this: their unrestricted match is
    # weak too, so they fall through to the normal "not in the
    # documents" refusal below.
    if allowed_departments is not None:
        blocked = _rbac_blocked_department(question, retriever,
                                           allowed_departments, result)
        if blocked is not None:
            rbac_answer = RBAC_REFUSAL_AR if language == "ar" else RBAC_REFUSAL_EN
            return {
                "answer": rbac_answer,
                "citations": [],
                "retrieval_scores": {
                    "top_vector_score": round(top_score, 4),
                    "bm25_top_score": round(result.get("bm25_top_score", 0.0), 4),
                    "reranker": result["reranker"],
                    "blocked_department": blocked,
                },
                "latency_ms": round((time.time() - started) * 1000, 1),
                "generation_mode": "rbac-refusal",
                "language": language,
                "retrieved_count": 0,
                "refused": True,
                "rbac_blocked": True,
                "blocked_department": blocked,
                "ollama": ollama,
            }

    refusal = REFUSAL_AR if language == "ar" else REFUSAL_EN
    # Refuse only when NEITHER signal finds anything: the vector score
    # is below threshold AND BM25 found no matching term. BM25 matters
    # because the MiniLM embedding model is English-trained — an Arabic
    # question scores low on vectors even when its exact Arabic terms
    # are in the documents (BM25 top score > 0 proves a real match).
    bm25_top = result.get("bm25_top_score", 0.0)
    if not reranked or (top_score < REFUSAL_THRESHOLD and bm25_top <= 0):
        return {
            "answer": refusal,
            "citations": [],
            "retrieval_scores": {
                "top_vector_score": round(top_score, 4),
                "bm25_top_score": round(bm25_top, 4),
                "reranker": result["reranker"],
                "refusal_threshold": REFUSAL_THRESHOLD,
            },
            "latency_ms": round((time.time() - started) * 1000, 1),
            "generation_mode": "refusal",
            "language": language,
            "retrieved_count": len(reranked),
            "refused": True,
            "rbac_blocked": False,
            "ollama": ollama,
        }

    # Verify step: every citation must exist in the store — it does by
    # construction (citations are built from reranked chunks only).
    citations = _citations(reranked)
    generation_mode = "extractive-fallback"
    answer = None
    if ollama["available"] and OLLAMA_MODEL in ollama["models"]:
        answer = _ollama_answer(question, reranked, language)
        if answer:
            generation_mode = "ollama"
    if answer is None:
        answer = _extractive_answer(question, reranked, language)
        generation_mode = "extractive-fallback"
    return {
        "answer": answer,
        "citations": citations,
        "retrieval_scores": {
            "top_vector_score": round(top_score, 4),
            "bm25_top_score": round(bm25_top, 4),
            "reranker": result["reranker"],
            "reranked": [
                {
                    "document_title": c.get("title"),
                    "page_no": c.get("page_no"),
                    "rerank_score": c.get("rerank_score"),
                }
                for c in reranked
            ],
        },
        "latency_ms": round((time.time() - started) * 1000, 1),
        "generation_mode": generation_mode,
        "language": language,
        "retrieved_count": len(reranked),
        "refused": False,
        "rbac_blocked": False,
        "ollama": ollama,
    }
