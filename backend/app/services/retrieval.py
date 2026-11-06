"""Hybrid retrieval — Sprint 2.

Real, working pipeline (no fake scores anywhere):
  1. Language detect: Arabic characters present -> "ar", else "en".
  2. Vector search top-20 (cosine, Sprint 1 LocalVectorStore + MiniLM
     embeddings) — English queries score well here.
  3. BM25 top-20 (pure-Python BM25Okapi-style implementation over the
     indexed chunk texts) — this is what carries Arabic queries, because
     the MiniLM embedding model is English-trained and the Arabic
     summaries match Arabic questions token-for-token.
  4. Reciprocal Rank Fusion (k=60) merges the two ranked lists.
  5. Rerank top-5. Reranker, in order:
       a. Cross-encoder "cross-encoder/ms-marco-MiniLM-L-6-v2" — for
          ENGLISH queries only, and ONLY when it is already cached or
          RTB_TRY_RERANKER=1 is set (same rule as BGE-M3 in Sprint 1:
          the VM has ~400 MB free RAM and the download is ~90 MB, so
          we never hang a run on it).
       b. Score-based rerank (RRF score + small title boost) — used for
          ARABIC queries always, and for English when the cross-encoder
          is unavailable. Reason, measured 2026-11-06: the cross-encoder
          is trained on English MS MARCO; on the Arabic AML question it
          re-ranked the correct BM25 top chunk below an unrelated one
          (9/10 with cross-encoder on Arabic vs 10/10 with score
          rerank), so Arabic keeps the BM25-driven score rerank. A
          multilingual reranker (BGE reranker) is the proper fix for a
          later sprint. The actual reranker used per query is recorded
          on every reranked chunk ('reranker' field) and in SPRINT2.md
          — the code never claims the cross-encoder ran if it did not.

RBAC filtering (Sprint 3): HybridRetriever.retrieve() takes
allowed_departments and filters chunks BEFORE vector/BM25 ranking.
"""
import logging
import math
import os
import re
from collections import Counter

logger = logging.getLogger("rtb.retrieval")

VECTOR_TOP_K = 20
BM25_TOP_K = 20
RRF_K = 60
RERANK_TOP_K = 5
REFUSAL_THRESHOLD = 0.25  # min top cosine score, else "not in the documents"
# Vector noise floor for RRF fusion: MiniLM cosine scores for unrelated
# text sit at ~0.10-0.30 (Arabic queries score ~0.20-0.30 because the
# model is English-trained), so below 0.30 a vector rank is noise and
# would dilute the BM25 signal in the fusion. Chunks below the floor
# are excluded from the RRF lists only — the raw top score is still
# reported, and BM25 alone can still rank the chunk first.
VECTOR_FLOOR = 0.30

CROSS_ENCODER = "cross-encoder/ms-marco-MiniLM-L-6-v2"

_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
_TOKEN_RE = re.compile(r"[a-z0-9\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]+")

# Arabic diacritics (tashkeel) + tatweel — stripped so queries and
# documents match regardless of vowel marks.
_ARABIC_DIACRITICS = re.compile(r"[\u064B-\u0652\u0670\u0640]")


def normalize_arabic(text: str) -> str:
    """Normalise Arabic so a query and a document match even when the
    document text came out of a PDF in visual order (Arabic Presentation
    Forms, U+FB50-U+FEFF — that is how our synthetic PDFs store the
    Arabic summaries) and/or with diacritics. NFKD decomposes the
    presentation forms back to standard letters; alef variants and
    teh-marbuta / alef-maqsura are unified the same way on both sides."""
    import unicodedata

    text = unicodedata.normalize("NFKD", text or "")
    text = _ARABIC_DIACRITICS.sub("", text)
    return (
        text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ٱ", "ا")
        .replace("ة", "ه").replace("ى", "ي")
    )

_reranker = None  # singleton: ("cross-encoder", model) | ("score", None)
_reranker_tried = False


# ---------------------------------------------------------------------------
# Language + tokenisation
# ---------------------------------------------------------------------------
def detect_language(text: str) -> str:
    """'ar' if any Arabic-script character is present, else 'en'."""
    return "ar" if _ARABIC_RE.search(text or "") else "en"


def _stem(token: str) -> str:
    """Very light English stemming (fees -> fee, accounts -> account)
    so a query and a document match on plurals. Arabic tokens are
    untouched — only ASCII words are stemmed."""
    if token.isascii() and len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    tokens = _TOKEN_RE.findall(normalize_arabic(text or "").lower())
    return [_stem(t) for t in tokens]


# ---------------------------------------------------------------------------
# Stopwords — removed ONLY for BM25 scoring. Without them, a question
# like "What is the weather in Jeddah tomorrow?" scores 2.36 on pure
# filler words (what/is/the/in) that occur in every chunk, which made
# the out-of-scope guardrail fail. Content words are what BM25 must see.
# ---------------------------------------------------------------------------
STOPWORDS = {
    # English question/function words
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "what", "how", "why", "when", "where", "who", "which", "whom", "whose",
    "in", "on", "at", "of", "to", "for", "and", "or", "do", "does", "did",
    "can", "could", "would", "should", "it", "its", "this", "that", "there",
    "here", "with", "by", "from", "as", "if", "then", "than", "so", "such",
    "no", "not", "only", "own", "same", "too", "very", "just", "about",
    "into", "over", "after", "before", "between", "through", "during",
    "under", "again", "further", "once", "all", "any", "both", "each",
    "few", "more", "most", "other", "some", "nor", "but", "up", "out",
    "i", "you", "he", "she", "we", "they", "me", "my", "your", "our",
    "their", "his", "her", "am", "have", "has", "had", "will", "shall",
    # Arabic question/function words (normalised forms — see normalize_arabic)
    "ما", "هي", "هو", "هم", "هن", "في", "من", "الي", "علي", "عن", "مع",
    "و", "او", "هل", "كان", "يكون", "التي", "الذي", "الذين", "هذا",
    "هذه", "ذلك", "تلك", "لا", "لم", "لن", "ان", "ثم", "بعد", "قبل",
    "بين", "تحت", "فوق", "عند", "لدي", "دون", "غير", "كل", "بعض",
    "اي", "اذا", "لو", "حتي", "لكن", "بل", "كما", "نحو", "حول", "منذ",
}


# ---------------------------------------------------------------------------
# BM25 (pure Python, BM25Okapi-style: k1=1.5, b=0.75)
# ---------------------------------------------------------------------------
class BM25Index:
    """Built over the chunk texts in the vector store. Scores are real
    BM25 scores computed from term frequencies — never invented."""

    def __init__(self, docs: list[dict]):
        self.docs = docs
        self.tokenized = [tokenize(d.get("content", "")) for d in docs]
        self.doc_len = [len(t) for t in self.tokenized]
        self.avg_len = sum(self.doc_len) / max(len(self.doc_len), 1)
        self.n_docs = len(docs)
        df = Counter()
        for tokens in self.tokenized:
            for term in set(tokens):
                df[term] += 1
        self.df = df

    def _idf(self, term: str) -> float:
        df = self.df.get(term, 0)
        return math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))

    def score(self, query_tokens: list[str]) -> list[tuple[int, float]]:
        k1, b = 1.5, 0.75
        qf = Counter(query_tokens)
        results: list[tuple[int, float]] = []
        for i, tokens in enumerate(self.tokenized):
            tf = Counter(tokens)
            s = 0.0
            for term, _ in qf.items():
                if tf.get(term, 0) == 0:
                    continue
                denom = tf[term] + k1 * (1 - b + b * self.doc_len[i] / max(self.avg_len, 1))
                s += self._idf(term) * (tf[term] * (k1 + 1)) / denom
            results.append((i, s))
        results.sort(key=lambda x: -x[1])
        return results

    def search(self, query: str, top_k: int = BM25_TOP_K) -> list[dict]:
        tokens = [t for t in tokenize(query) if t not in STOPWORDS]
        if not tokens:
            return []
        ranked = self.score(tokens)
        out = []
        for idx, score in ranked[:top_k]:
            if score <= 0:
                continue
            doc = dict(self.docs[idx])
            doc["bm25_score"] = round(score, 4)
            out.append(doc)
        return out


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion
# ---------------------------------------------------------------------------
def reciprocal_rank_fusion(ranked_lists: list[list[dict]], k: int = RRF_K) -> list[dict]:
    """Merge ranked lists by RRF. Each list is ordered best-first; a chunk
    is identified by (document_id, chunk_index). Returns chunks ordered
    by fused score, each with an 'rrf_score' field."""
    fused: dict[tuple, dict] = {}
    scores: dict[tuple, float] = {}
    for ranked in ranked_lists:
        for rank, doc in enumerate(ranked, start=1):
            key = (doc.get("document_id"), doc.get("chunk_index"))
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            if key not in fused:
                fused[key] = dict(doc)
    for key, doc in fused.items():
        doc["rrf_score"] = round(scores[key], 6)
    return sorted(fused.values(), key=lambda d: -d["rrf_score"])


# ---------------------------------------------------------------------------
# Reranker
# ---------------------------------------------------------------------------
def _cross_encoder_cached() -> bool:
    if os.getenv("RTB_TRY_RERANKER") == "1":
        return True
    try:
        from huggingface_hub import scan_cache_dir

        for repo in scan_cache_dir().repos:
            if repo.repo_id == CROSS_ENCODER and repo.size_on_disk > 10_000_000:
                return True
    except Exception:
        pass
    return False


def get_reranker():
    """Return (kind, model). 'cross-encoder' only if cached/requested and
    the load succeeds; otherwise the honest ('score', None) fallback.
    The load is attempted at most once per process.

    Production (v0.8): RTB_RERANKER=off forces the score reranker
    without even trying the cross-encoder — the one-command latency
    test for Fahad's PC (see docs/PRODUCTION.md). RTB_RERANKER=auto
    (default) keeps the Sprint 2 behaviour."""
    global _reranker, _reranker_tried
    if os.getenv("RTB_RERANKER", "auto").strip().lower() == "off":
        _reranker = ("score", None)
        _reranker_tried = True
        logger.info("Reranker disabled by RTB_RERANKER=off — using score rerank")
        return _reranker
    if _reranker is not None or _reranker_tried:
        return _reranker if _reranker is not None else ("score", None)
    _reranker_tried = True
    if _cross_encoder_cached():
        try:
            from sentence_transformers import CrossEncoder

            model = CrossEncoder(CROSS_ENCODER)
            _reranker = ("cross-encoder", model)
            logger.info("Reranker loaded: cross-encoder %s", CROSS_ENCODER)
            return _reranker
        except Exception as exc:  # noqa: BLE001 — fall back, do not crash
            logger.warning("Cross-encoder reranker failed (%s) — using score rerank", exc)
    else:
        logger.warning(
            "Cross-encoder %s is not cached and RTB_TRY_RERANKER is not set — "
            "using score-based rerank. Set RTB_TRY_RERANKER=1 on a machine "
            "with good internet to use the cross-encoder.",
            CROSS_ENCODER,
        )
    _reranker = ("score", None)
    return _reranker


def reranker_info() -> dict:
    kind, _ = get_reranker()
    return {"reranker": "cross-encoder/ms-marco-MiniLM-L-6-v2" if kind == "cross-encoder"
            else "score-based (RRF + title boost)", "kind": kind}


def _score_rerank(query: str, candidates: list[dict]) -> list[dict]:
    """Fallback rerank: RRF score, plus a small boost when a query
    keyword appears in the chunk title (titles are short and topical)."""
    q_tokens = set(tokenize(query))
    scored = []
    for doc in candidates:
        boost = 0.0
        title_tokens = set(tokenize(doc.get("title", "")))
        overlap = q_tokens & title_tokens
        if overlap:
            # Small on purpose: RRF scores here are ~0.01-0.03, so a
            # 0.05 boost used to swamp the retrieval signal entirely.
            boost = 0.002 * len(overlap)
        scored.append((doc.get("rrf_score", 0.0) + boost, doc))
    scored.sort(key=lambda x: -x[0])
    out = []
    for score, doc in scored:
        d = dict(doc)
        d["rerank_score"] = round(score, 6)
        out.append(d)
    return out


def rerank(query: str, candidates: list[dict], top_k: int = RERANK_TOP_K,
           force_score: bool = False) -> list[dict]:
    """Rerank fused candidates down to top_k. Returns chunks with a
    'rerank_score' field and a 'reranker' field naming the method used.
    Arabic queries always use the score reranker (see module docstring:
    the English MS MARCO cross-encoder mis-ranks Arabic). The RBAC
    probe (v0.10) passes force_score=True: it only needs a top-1
    comparison, and a cross-encoder predict costs ~3s on this
    RAM-starved VM — the probe runs on every chat, so it uses the
    score reranker and leaves the cross-encoder for the real answer."""
    if not candidates:
        return []
    if detect_language(query) == "ar" or force_score:
        out = _score_rerank(query, candidates)[:top_k]
        for d in out:
            d["reranker"] = "score"
        return out
    kind, model = get_reranker()
    if kind == "cross-encoder":
        pairs = [(query, c.get("content", "")[:2000]) for c in candidates]
        try:
            scores = model.predict(pairs)
            scored = sorted(zip(scores, candidates), key=lambda x: -x[0])
            out = []
            for score, doc in scored[:top_k]:
                d = dict(doc)
                d["rerank_score"] = round(float(score), 4)
                d["reranker"] = "cross-encoder"
                out.append(d)
            return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cross-encoder predict failed (%s) — score rerank", exc)
    out = _score_rerank(query, candidates)[:top_k]
    for d in out:
        d["reranker"] = "score"
    return out


# ---------------------------------------------------------------------------
# Hybrid retrieval entry point
# ---------------------------------------------------------------------------
class HybridRetriever:
    """Vector + BM25 -> RRF -> rerank. Holds the store and the BM25 index
    (built once from the store's chunk texts)."""

    def __init__(self, store=None):
        from app.db.vector_store import get_vector_store

        self.store = store or get_vector_store()
        if not self.store.load():
            raise RuntimeError(
                "No vector store found — run scripts/index_chunks.py first "
                "(Sprint 1). The local store lives in data/vector_store/."
            )
        self._bm25 = BM25Index(self.store._meta)
        self._chunks = list(self.store._meta)

    def retrieve(self, question: str, top_k: int = RERANK_TOP_K,
                 allowed_departments: list[str] | None = None,
                 rerank_mode: str | None = None) -> dict:
        """Returns {language, vector_results, bm25_results, fused, reranked,
        top_score, reranker}. top_score is the best vector cosine score —
        the guardrail threshold is applied to it in generation.py.

        rerank_mode="score" (v0.10) forces the score reranker even for
        English — used by the RBAC probe, which only needs a top-1
        comparison and must not pay a ~3s cross-encoder predict on
        every chat. The real answer always uses the cross-encoder
        (unless RTB_RERANKER=off or the model is unavailable).

        RBAC (Sprint 3): when allowed_departments is given, ONLY chunks
        from those departments are searched — the filter is applied
        BEFORE vector search and BEFORE the BM25 index is built, so a
        disallowed chunk can never be retrieved, reranked, cited, or
        fed to the generator. allowed_departments=None means "no
        restriction" (used only by the direct answer_question() tests
        that run without a logged-in user; the /chat API always passes
        the caller's departments)."""
        from app.services import embeddings as emb

        language = detect_language(question)
        qvec = emb.encode_query(question)
        if allowed_departments is None:
            allowed_chunks = list(self._chunks)
            vector_results = self.store.search(qvec, top_k=VECTOR_TOP_K)
            bm25_results = self._bm25.search(question, top_k=BM25_TOP_K)
        else:
            allowed_set = set(allowed_departments)
            allowed_chunks = [c for c in self._chunks if c.get("department") in allowed_set]
            if not allowed_chunks:
                return {
                    "language": language,
                    "vector_results": [],
                    "bm25_results": [],
                    "fused": [],
                    "reranked": [],
                    "top_score": 0.0,
                    "bm25_top_score": 0.0,
                    "reranker": "score-based (RRF + title boost)",
                    "allowed_departments": sorted(allowed_set),
                }
            # Vector search restricted to allowed chunks: the local
            # store filters by department; PgVectorStore filters by
            # document department. Both take a departments list.
            try:
                vector_results = self.store.search(
                    qvec, top_k=VECTOR_TOP_K, departments=sorted(allowed_set))
            except TypeError:
                vector_results = self.store.search(qvec, top_k=VECTOR_TOP_K)
                vector_results = [r for r in vector_results
                                  if r.get("department") in allowed_set]
            # BM25 is rebuilt over allowed chunks only — a disallowed
            # chunk is not even in the index for this query.
            bm25_results = BM25Index(allowed_chunks).search(question, top_k=BM25_TOP_K)
        # Fuse only the vector hits above the noise floor — see VECTOR_FLOOR.
        fused = reciprocal_rank_fusion([
            [r for r in vector_results if r["score"] >= VECTOR_FLOOR],
            bm25_results,
        ])
        reranked = rerank(question, fused, top_k=top_k,
                          force_score=(rerank_mode == "score"))
        top_score = vector_results[0]["score"] if vector_results else 0.0
        bm25_top_score = bm25_results[0]["bm25_score"] if bm25_results else 0.0
        # The reranker actually used for THIS query (Arabic queries use
        # the score reranker even when the cross-encoder is loaded).
        used = reranked[0].get("reranker") if reranked else reranker_info()["kind"]
        return {
            "language": language,
            "vector_results": vector_results,
            "bm25_results": bm25_results,
            "fused": fused,
            "reranked": reranked,
            "top_score": top_score,
            "bm25_top_score": bm25_top_score,
            "reranker": ("cross-encoder/ms-marco-MiniLM-L-6-v2" if used == "cross-encoder"
                         else "score-based (RRF + title boost)"),
            "allowed_departments": (sorted(set(allowed_departments))
                                    if allowed_departments is not None else None),
        }


def get_retriever() -> HybridRetriever:
    return HybridRetriever()
