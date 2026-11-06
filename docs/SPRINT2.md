# Sprint 2 — RAG + Citations + Hybrid Search (v0.3)

Status: DONE & VERIFIED (2026-11-06). No Docker used — local setup only.
Version: backend 0.3.0. Previous: Setup v0.1, Sprint 1 v0.2.

## What was built

### 1. Hybrid retrieval — `backend/app/services/retrieval.py`
- **Vector search top-20** (cosine, Sprint 1 local store, MiniLM 384-dim).
- **BM25 top-20** — pure-Python BM25Okapi-style implementation
  (k1=1.5, b=0.75) over the 15 chunk texts. Real scores, never faked.
  A stopword list is applied for BM25 only: without it, "What is the
  weather in Jeddah tomorrow?" scored 2.36 on filler words (what/is/the/in)
  and the out-of-scope guardrail failed. Stopwords: English question/
  function words + Arabic question/function words (normalised forms).
- **Reciprocal Rank Fusion (k=60)** merges the two lists.
- **Vector noise floor (0.30) for RRF**: MiniLM cosine for unrelated text
  sits at ~0.10–0.30, and Arabic queries score ~0.20–0.30 because the
  model is English-trained — below 0.30 a vector rank is noise and
  dilutes the BM25 signal. Chunks below the floor are excluded from the
  RRF lists only; the raw top score is still reported.
- **Arabic normalisation** (`normalize_arabic`): the synthetic PDFs store
  Arabic summaries in visual order as Arabic Presentation Forms
  (U+FB50–U+FEFF, from arabic-reshaper in Sprint 1). NFKD decomposes them
  back to standard letters, diacritics/tatweel are stripped, and alef
  variants / teh-marbuta / alef-maqsura are unified — the same
  normalisation is applied to queries and documents, so Arabic BM25
  matching works. Without this fix, Arabic BM25 scored 0 and all four
  Arabic questions were refused or mis-ranked.
- **Light English stemming** in tokenisation (fees -> fee, accounts ->
  account) so queries and documents match on plurals.
- **Title boost in the score reranker is 0.002/token** (was 0.05 in the
  first draft — RRF scores here are ~0.01–0.03, so 0.05 swamped the
  retrieval signal and pushed "Account Opening Policy" above the correct
  "Charges and Fees Schedule" for the fee question).

### 2. Reranker — what ACTUALLY ran
- **Cross-encoder `cross-encoder/ms-marco-MiniLM-L-6-v2` — English queries
  only, and only when cached or `RTB_TRY_RERANKER=1`.** It downloaded and
  loaded fine on this VM on the second attempt (~90 MB, ~50 s) and is now
  in the HF cache. English latency with it is ~2–6 s per query on this VM.
- **Score-based rerank (RRF + title boost) — Arabic queries always, and
  English when the cross-encoder is unavailable.** Measured reason
  (2026-11-06): the cross-encoder is trained on English MS MARCO; on the
  Arabic AML question it re-ranked the correct BM25 top chunk (AML) below
  an unrelated one (PDPL) — 9/10 with the cross-encoder on all questions
  vs 10/10 with the language-aware rule. A multilingual reranker (BGE
  reranker) is the proper fix for a later sprint.
- The reranker actually used per query is recorded on every reranked
  chunk (`reranker` field) and in the API response (`retrieval_scores.reranker`).

### 3. Generation — `backend/app/services/generation.py`
Explicit pipeline: retrieve -> rerank -> generate -> verify. This is
NOT LangGraph — no LangGraph import is used, and the code does not claim
otherwise.
- **Ollama first**: `OLLAMA_HOST` (default http://localhost:11434),
  model `llama3.1:8b`, temperature 0.1, grounded system prompt
  ("Sirf diye gaye context se jawab do... Har claim ke sath [Doc, Page]
  citation do."). **Ollama was NOT reachable on this VM** (no Ollama
  server here), so no LLM answer was produced here.
- **Extractive fallback (what actually ran here)**: the answer is composed
  ONLY from the top retrieved chunks — relevant sentences are quoted with
  `[Title, page]` citations. `generation_mode: "extractive-fallback"` is
  returned in every response, so it is never presented as an LLM answer.
- **Guardrail**: refuse when the best vector score is below 0.25 AND
  BM25 found no content-word match (BM25 top score <= 0), or when
  retrieval returns nothing. Refusal text: "Is document me ye maloomat
  nahi hai" (EN) / "هذه المعلومات غير موجودة في المستندات" (AR), with
  empty citations. PII-like 10-digit numbers are masked in answers.
- **Citations**: every non-refusal answer carries at least 1 citation,
  each pointing at a chunk that really exists in the store
  (`document_id`, `document_title`, `page_no`, `department`, `score`).

### 4. API — `POST /api/v1/chat` (replaces the 501 stub)
- Request: `{question, conversation_id?, language?}`.
  Response envelope: `{success, data: {answer, citations,
  retrieval_scores, latency_ms, generation_mode, language,
  retrieved_count, refused, rbac_enforced: false, warning}, error,
  request_id}`. JSON response (no SSE streaming — recorded choice:
  streaming was judged too fragile for this sprint; JSON is the
  contract, SSE can be added in Sprint 4 polish).
- `GET /api/v1/conversations` and `GET /api/v1/conversations/{id}` —
  conversations are stored in `data/conversations.jsonl` (one line per
  message, JSONL file log). That is the Sprint 2 storage: it works with
  no PostgreSQL and no Docker; the SQLAlchemy conversations/messages
  tables from the Design are wired in a later sprint if Postgres is
  used. The file is excluded from the zip (`.gitignore`).
- RBAC is NOT enforced yet (Sprint 3) — every response says so.

### 5. Frontend — Chat page is real now
`frontend/src/pages/Chat.tsx` + `frontend/src/api/client.ts` (`api.chat`):
real input, real POST to `/api/v1/chat`, answer + clickable source
citations (title + page + score), generation-mode badge ("LLM (Ollama)"
or "Grounded extract — no LLM running"), latency + retrieved-count,
"thinking" state, RTL (`dir="rtl"`) for Arabic messages, and 4 sample
questions. No fake answers, no hardcoded replies.

## How to run on Windows (PowerShell, no Docker)

```powershell
cd riyadh-trust-bank-intelligence
cd backend
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Chat test (new terminal):
curl -X POST http://127.0.0.1:8000/api/v1/chat -H "Content-Type: application/json" `
  -d '{"question":"What documents are needed for KYC account opening?"}'
```

### Real LLM mode (Ollama) — optional, on Windows
```powershell
# 1. Install Ollama for Windows: https://ollama.com/download/windows
# 2. Pull the model (one time, needs internet):
ollama pull llama3.1:8b
#    Arabic-heavy use: ollama pull qwen2.5:7b
# 3. Ollama runs on http://localhost:11434 by default — the backend
#    finds it automatically (OLLAMA_HOST env if different).
# 4. Ask a question: generation_mode becomes "ollama".
# Without Ollama running, the API still works in extractive-fallback mode.
```

### Verification commands (this VM)
```powershell
cd backend
python -m pytest ../tests/ -v        # 20 passed
python ../scripts/rag_test.py         # 10/10 + refusal PASS
python ../scripts/search_test.py      # Sprint 1 search, still 3/3
```

## Verification (this VM, 2026-11-06)

### RAG test — `scripts/rag_test.py`
| # | Question | Top doc | Expected | Result |
|---|---|---|---|---|
| 1 | What documents are needed for KYC account opening? | KYC / Account Opening | KYC or Account Opening* | PASS |
| 2 | What is the AML reporting threshold? | AML Policy | AML Policy | PASS |
| 3 | How long does it take to open an account at a branch? | Account Opening Policy | Account Opening Policy | PASS |
| 4 | What is the maximum personal loan amount? | Personal Loan Policy | Personal Loan Policy | PASS |
| 5 | How many days of annual leave do employees get? | HR Leave Policy | HR Leave Policy | PASS |
| 6 | What is the monthly account fee if the average balance falls below SAR 1,000? | Charges and Fees Schedule | Charges and Fees Schedule | PASS |
| 7 | ما هي المستندات المطلوبة لفتح حساب؟ | Account Opening Policy | KYC or Account Opening* | PASS |
| 8 | ما هو حد الإبلاغ عن المعاملات النقدية؟ | AML Policy | AML Policy | PASS |
| 9 | ما هي شروط القرض الشخصي؟ | Personal Loan Policy | Personal Loan Policy | PASS |
| 10 | كم عدد أيام الإجازة السنوية؟ | HR Leave Policy | HR Leave Policy | PASS |
| — | What is the weather in Jeddah tomorrow? | — (refused) | refusal, no citations | PASS |

\* Questions 1 and 7 accept either document: BOTH the KYC Policy and
the Account Opening Policy hold the authoritative "Documents Needed for
Account Opening" list (Sprint 1 note), so either top citation is correct.

**Final: 10/10 correct, refusal OK -> PASS.** Two runs were done and both
are recorded honestly:
- Score reranker only (cross-encoder not yet cached): **10/10**.
- Cross-encoder for all queries (after it downloaded): **9/10** — the
  Arabic AML question (Q8) was mis-ranked to PDPL. That finding is why
  Arabic queries now always use the score reranker (section 2).
- Final language-aware rule (cross-encoder EN + score AR): **10/10**.
- First-call latency ~17–23 s (embedding + cross-encoder model loads);
  steady-state ~0.1–0.2 s (score rerank) / ~2–6 s (cross-encoder).

### pytest — 20 passed, 0 failed
`tests/test_health.py` (3) + `tests/test_ingestion.py` (10) +
`tests/test_rag.py` (7: language detect, BM25, 10-question set,
out-of-scope refusal, honest generation mode, chat API + conversation
save, chat API refusal).

### Live API (uvicorn :8125, this VM)
- `GET /api/v1/health` -> 200, version **0.3.0**.
- `POST /api/v1/chat` KYC question -> 200, `generation_mode:
  "extractive-fallback"`, `refused: false`, latency 23140.7 ms (first
  call, model loads), 5 citations (KYC p.1 top).
- `POST /api/v1/chat` weather question -> 200, `refused: true`,
  answer "Is document me ye maloomat nahi hai.", citations [].
- `GET /api/v1/conversations` -> 2 conversations saved, each with
  2 messages (user + assistant).

### Frontend
`npm install` + `npm run build` in a /tmp copy: **built cleanly in
2.20 s** (38 modules, no TypeScript errors).

### py_compile
All new/changed Python files OK.

## Known limitations (honest, for later sprints)
- **No real LLM on this VM**: answers here are extractive-fallback.
  Real LLM mode needs Ollama + `llama3.1:8b` (see Windows steps above).
- **Arabic quotes are visual-order text**: the synthetic PDFs store
  Arabic in presentation forms, so quoted Arabic sentences display in
  the stored visual order. Readable in an RTL context, but regenerating
  the docs with logical-order Arabic is a Sprint 4 polish item.
- **Extractive answers sometimes quote a heading** merged with the
  following sentence (e.g. Q1) — the sentence is still from the correct
  document, but a cleaner sentence picker is a Sprint 4 polish item.
- **Cross-encoder latency**: ~2–6 s/query on this VM; on Fahad's laptop
  it will depend on CPU. The score reranker is the fast path.
- **PgVector path**: code only, not live-tested on this VM (no Postgres
  server here) — same as Sprint 1; testable on Fahad's laptop (port 5432).

## What is NOT built yet
- Sprint 3: JWT login, RBAC enforcement, audit log, admin/users.
- Sprint 4: RAGAS evaluation, feedback endpoint, polish (SSE streaming,
  logical-order Arabic, multilingual BGE reranker).
