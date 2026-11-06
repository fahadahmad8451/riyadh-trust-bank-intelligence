"""Evaluation — Sprint 4 (Design section 10).

Honest, local, RAGAS-STYLE metrics. This is NOT official RAGAS:
  * The `ragas` package is not installed here, and RAGAS needs an LLM
    judge (usually a paid OpenAI/Azure call). We do NOT have one, so
    we do not claim RAGAS scores. Every output labels the method as
    "local-ragas-style (no LLM judge)".
  * Instead, each metric is computed deterministically from the
    retrieved chunks and the answer, with the exact formula written
    below and in docs/SPRINT4.md. Nothing is tuned to pass: the
    aggregates are reported even when they miss the Design targets.

Formulas (per question; aggregates are the mean over questions):
  * faithfulness — the answer is split into sentences (claims). A
    sentence counts as SUPPORTED when at least 30% of its content
    tokens (retrieval.tokenize minus STOPWORDS) also appear in the
    concatenated text of the cited chunks. Sentences with fewer than
    3 content tokens (e.g. the "According to the bank documents:"
    intro, or a citation marker alone) are skipped, not counted.
    faithfulness = supported / counted. A refused answer scores 0.0
    (it made no supported claim). NOTE the known blind spot, written
    in SPRINT4.md: this proxy checks the answer against the CITED
    chunks, so it cannot catch a wrong number that is already wrong
    in the chunk itself (the visual-order Arabic in Sprint 1 PDFs
    scrambles some numbers — see the e16/e17 findings).
  * context_recall — 1.0 if any expected document appears in the
    top-5 citations, else 0.0. (Top-5, not top-1: retrieval is
    judged on whether the right document was found at all.)
  * answer_relevancy — cosine similarity between the MiniLM
    embeddings of the question and of the answer (same model as
    Sprint 1, all-MiniLM-L6-v2, 384-dim). This is a lexical/semantic
    proxy, NOT the RAGAS LLM-judged relevancy: MiniLM is
    English-trained, so Arabic question/answer pairs score lower
    than English ones, and extractive answers (which quote document
    sentences instead of directly answering) score lower than a
    fluent LLM answer would. The number is reported as-is.
  * phrase_present — whether the eval set's expected_phrase (from
    the source document, logical text) appears in the answer after
    Arabic normalisation + whitespace collapsing. Reported per
    question; it is a diagnostic, not part of the three aggregates.
  * top_doc_correct — whether the top (first) citation is one of
    the expected documents. Diagnostic, not an aggregate.

Targets (Design section 10): faithfulness >= 0.85,
context_recall >= 0.80, answer_relevancy >= 0.85. The run reports
pass/fail per metric against these targets — a miss is reported,
never hidden.
"""
import json
import logging
import re
import statistics
import time
from pathlib import Path

logger = logging.getLogger("rtb.evaluation")

try:
    import ragas  # noqa: F401  (only to record whether it exists)

    RAGAS_AVAILABLE = True
    RAGAS_NOTE = f"ragas {getattr(ragas, '__version__', '?')} is installed"
except Exception:  # noqa: BLE001 — ragas simply is not installed here
    RAGAS_AVAILABLE = False
    RAGAS_NOTE = ("ragas is NOT installed, and RAGAS needs a paid LLM judge "
                  "(OpenAI/Azure) — so this run uses local RAGAS-style "
                  "metrics instead, labelled as such everywhere.")

METHOD = "local-ragas-style (no LLM judge)"
TARGETS = {"faithfulness": 0.85, "context_recall": 0.80, "answer_relevancy": 0.85}
SUPPORT_THRESHOLD = 0.30  # min token overlap for a claim to count as supported

_CITATION_RE = re.compile(r"\[[^\]]*,\s*page\s*\d+\]")


def _content_tokens(text: str) -> set[str]:
    """Content tokens of a text: retrieval tokenisation minus stopwords."""
    from app.services.retrieval import STOPWORDS, tokenize

    return {t for t in tokenize(text or "") if t not in STOPWORDS}


def _sentences(text: str) -> list[str]:
    from app.services.generation import _sentences as split_sentences

    return split_sentences(text or "")


def faithfulness(answer: str, cited_chunk_texts: list[str]) -> float:
    """Share of answer sentences supported by the cited chunks."""
    if not answer:
        return 0.0
    chunk_tokens: set[str] = set()
    for chunk_text in cited_chunk_texts:
        chunk_tokens |= _content_tokens(chunk_text)
    if not chunk_tokens:
        return 0.0
    counted = 0
    supported = 0
    for sentence in _sentences(answer):
        clean = _CITATION_RE.sub(" ", sentence)
        tokens = _content_tokens(clean)
        if len(tokens) < 3:
            continue  # intro / fragment — not a claim, do not count
        counted += 1
        overlap = len(tokens & chunk_tokens) / len(tokens)
        if overlap >= SUPPORT_THRESHOLD:
            supported += 1
    if counted == 0:
        return 0.0
    return round(supported / counted, 4)


def answer_relevancy(question: str, answer: str) -> float:
    """Cosine similarity between MiniLM embeddings of Q and A."""
    import numpy as np

    from app.services.embeddings import encode_texts

    vectors = encode_texts([question, answer])
    q, a = vectors[0], vectors[1]
    denom = float(np.linalg.norm(q) * np.linalg.norm(a))
    if denom == 0:
        return 0.0
    return round(float(np.dot(q, a) / denom), 4)


def _normalised(text: str) -> str:
    from app.services.retrieval import normalize_arabic

    return re.sub(r"\s+", " ", normalize_arabic(text or "")).strip().lower()


def load_eval_set(path: Path | None = None) -> list[dict]:
    """The fixed 20-question set. Single source of truth for the eval
    script, the API and the tests — never edited at run time."""
    path = path or (Path(__file__).resolve().parents[3] / "tests" / "eval_set.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["questions"]


def eval_results_path() -> Path:
    from app.core.paths import data_dir

    return data_dir() / "eval_results.json"


def evaluate_question(question_item: dict, retriever=None,
                      allowed_departments: list[str] | None = None) -> dict:
    """Run one eval question through the real pipeline (as ADMIN: all
    departments visible) and score it. Returns the per-question row."""
    from app.services.generation import answer_question

    question = question_item["question"]
    expected_docs = set(question_item.get("expected_documents", []))
    departments = allowed_departments if allowed_departments is not None \
        else ["RETAIL", "COMPLIANCE", "HR"]
    result = answer_question(question, retriever=retriever,
                             allowed_departments=departments)
    citations = result.get("citations", [])
    cited_ids = [c.get("document_id") for c in citations]
    top_doc = cited_ids[0] if cited_ids else None

    if result.get("refused"):
        faith = 0.0
    else:
        # Cited chunk texts: look the cited chunks up in the store.
        # Citations carry (document_id, page_no) but NOT chunk_index
        # (see generation._citations) — so look up by page and take
        # every chunk of that page. (Bug found 2026-11-06: the first
        # eval run looked up by chunk_index, matched nothing, and
        # reported faithfulness 0.00 for all 20 questions.)
        chunk_texts: list[str] = []
        if retriever is not None:
            by_page: dict[tuple, list[str]] = {}
            for c in retriever._chunks:
                by_page.setdefault((c.get("document_id"), c.get("page_no")), []) \
                    .append(c.get("content", ""))
            for cit in citations:
                chunk_texts.extend(
                    by_page.get((cit.get("document_id"), cit.get("page_no")), []))
        faith = faithfulness(result["answer"], chunk_texts) if chunk_texts else 0.0

    recall = 1.0 if (expected_docs & set(cited_ids)) else 0.0
    relevancy = answer_relevancy(question, result["answer"]) \
        if result.get("answer") else 0.0
    phrase = question_item.get("expected_phrase", "")
    phrase_present = bool(phrase) and _normalised(phrase) in _normalised(result["answer"])

    return {
        "id": question_item.get("id"),
        "question": question,
        "language": question_item.get("language"),
        "expected_documents": sorted(expected_docs),
        "expected_page": question_item.get("expected_page"),
        "expected_phrase": phrase,
        "top_document": top_doc,
        "top_doc_correct": top_doc in expected_docs if top_doc else False,
        "context_recall": recall,
        "faithfulness": faith,
        "answer_relevancy": relevancy,
        "phrase_present": phrase_present,
        "refused": bool(result.get("refused")),
        "answer": result.get("answer"),
        "generation_mode": result.get("generation_mode"),
        "latency_ms": result.get("latency_ms"),
        "citations": [{"document_id": c.get("document_id"),
                       "page_no": c.get("page_no"),
                       "score": c.get("score")} for c in citations],
    }


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 1)
    idx = (len(ordered) - 1) * pct / 100.0
    lo, hi = int(idx), min(int(idx) + 1, len(ordered) - 1)
    frac = idx - lo
    return round(ordered[lo] * (1 - frac) + ordered[hi] * frac, 1)


def run_eval(limit: int | None = None, retriever=None) -> dict:
    """Run the whole eval set (ADMIN view) and store the results in
    data/eval_results.json. Returns the stored report. This takes
    minutes on this VM (cross-encoder + embedding loads) — the API
    runs it synchronously and says so in its docs."""
    from app.services.retrieval import get_retriever

    started = time.time()
    questions = load_eval_set()
    if limit is not None:
        questions = questions[: max(0, limit)]
    retriever = retriever or get_retriever()
    rows = [evaluate_question(q, retriever=retriever) for q in questions]

    def _mean(key: str) -> float:
        values = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        return round(sum(values) / len(values), 4) if values else 0.0

    latencies = [r["latency_ms"] for r in rows if isinstance(r.get("latency_ms"), (int, float))]
    aggregates = {
        "faithfulness": _mean("faithfulness"),
        "context_recall": _mean("context_recall"),
        "answer_relevancy": _mean("answer_relevancy"),
        "top_doc_accuracy": _mean("top_doc_correct"),
        "phrase_present_rate": _mean("phrase_present"),
        "refused_count": sum(1 for r in rows if r.get("refused")),
        "latency_ms_p50": _percentile(latencies, 50),
        "latency_ms_p95": _percentile(latencies, 95),
    }
    verdict = {name: aggregates[name] >= target for name, target in TARGETS.items()}
    report = {
        "method": METHOD,
        "ragas_used": False,
        "ragas_note": RAGAS_NOTE,
        "targets": TARGETS,
        "question_count": len(rows),
        "aggregates": aggregates,
        "verdict_vs_targets": verdict,
        "all_targets_met": all(verdict.values()),
        "run_seconds": round(time.time() - started, 1),
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "questions": rows,
    }
    path = eval_results_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Eval run stored: %s (faithfulness=%s recall=%s relevancy=%s)",
                path, aggregates["faithfulness"], aggregates["context_recall"],
                aggregates["answer_relevancy"])
    return report


def read_eval_results() -> dict | None:
    """The last stored eval report, or None if no run has happened."""
    path = eval_results_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
