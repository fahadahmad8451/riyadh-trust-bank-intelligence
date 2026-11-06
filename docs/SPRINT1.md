# Sprint 1 — Ingestion + Vector DB (v0.2)

Status: DONE & VERIFIED (2026-11-05). No Docker used — local setup only.

## What was built

### 1. Synthetic documents — 8 PDFs (data/docs/, sources in data/docs_src/)
All fictional, each marked "Riyadh Trust Bank — Synthetic Demo Document,
not a real bank". English main text + Arabic summary section in every doc.
Generated with `scripts/generate_docs.py` (fpdf2 + Noto Sans / Noto Sans
Arabic with arabic-reshaper + python-bidi).

| File | Title | Dept | Pages | Chunks |
|---|---|---|---|---|
| 01-kyc-policy.pdf | KYC Policy — Know Your Customer | RETAIL | 3 | 2 |
| 02-aml-policy.pdf | Anti-Money Laundering (AML) Policy | COMPLIANCE | 3 | 2 |
| 03-sama-compliance-summary.pdf | SAMA Compliance Summary | COMPLIANCE | 3 | 2 |
| 04-personal-loan-policy.pdf | Personal Loan Policy | RETAIL | 3 | 2 |
| 05-account-opening-policy.pdf | Account Opening Policy | RETAIL | 3 | 2 |
| 06-hr-leave-policy.pdf | HR Leave Policy | HR | 3 | 2 |
| 07-charges-fees-schedule.pdf | Charges and Fees Schedule | RETAIL | 3 | 1 |
| 08-pdpl-privacy-summary.pdf | PDPL Data Privacy Summary | COMPLIANCE | 3 | 2 |
| **Total** | | | **24** | **15** |

### 2. Ingestion service (backend/app/services/ingestion.py)
- PDF via PyMuPDF (per-page text), Word via python-docx, Excel via openpyxl.
- OCR fallback: tries PaddleOCR on image-only pages; if PaddleOCR is not
  installed it logs a warning and continues with the text layer — it never
  fakes OCR output. (Our 8 PDFs all have a text layer, so OCR was not used.)
- Cleaning: repeated header/footer lines removed.
- Chunking: section-aware, ~800 tokens max, ~150 tokens overlap, heading
  never split from its paragraph. Result: 15 chunks, avg 528.1 tokens,
  min 167, max 793.
- CLI: `python -m app.services.ingestion --docs data/docs --out data/chunks.jsonl --manifest data/docs_manifest.json`

### 3. Embeddings + vector store
- Embedding model actually used: **sentence-transformers/all-MiniLM-L6-v2,
  384-dim, backend "st"** (see data/vector_store/embedding_config.json —
  the code records the real model; it never claims BGE-M3 if a fallback
  was used).
- What happened with BGE-M3 (honest record): it WAS tried first, as
  designed. On this VM the 2.2 GB BGE-M3 download stalled at 0 bytes for
  4+ minutes (HF CDN, flaky network), and the VM has only ~350–475 MB
  free RAM while BGE-M3 needs ~2.3 GB in fp32 — so it would also likely
  OOM here. The torch CPU wheel itself needed a resumable download and
  a CPU-only install (the PyPI CUDA wheel needs NVIDIA libs that do not
  exist on this VM). Fallback used: all-MiniLM-L6-v2 (90 MB, 22M params).
  The code still supports BGE-M3: if it is already cached, or if
  RTB_TRY_BGE_M3=1 is set on a machine with good internet, BGE-M3
  (1024-dim) is tried first — the dimension is recorded either way.
- Attempt order in code: BGE-M3 (1024-dim, sentence-transformers, when
  cached or RTB_TRY_BGE_M3=1) → all-MiniLM-L6-v2 (384-dim,
  sentence-transformers) → MiniLM via ONNX Runtime (384-dim, no torch).
- Local vector store (default): `data/vector_store/` — vectors.npz +
  meta.jsonl, cosine search, same interface as the pgvector store.
  Works with NO Docker and NO Postgres server.
- Postgres + pgvector store: `backend/app/db/vector_store.py`
  (PgVectorStore). Activates only with `RTB_USE_PGVECTOR=1` and a
  reachable local Postgres; otherwise the local store is used. If the
  embedding dimension does not match the pgvector column (1024), the
  vectors are stored as JSON and searched with numpy cosine instead —
  logged, not hidden.

### 4. API (new in v0.2)
- `GET /api/v1/documents` — lists the 8 ingested documents (manifest).
- `POST /api/v1/documents/upload` — saves a .pdf/.docx/.xlsx, ingests it,
  embeds + indexes its chunks, updates the manifest. Response includes
  `rbac_enforced: false` and a warning: admin-only auth / RBAC is NOT
  enforced yet (Sprint 3). The other 13 endpoints are still honest 501s.

## How to run on Windows (PowerShell, no Docker)

```powershell
cd riyadh-trust-bank-intelligence
# 1. Regenerate the synthetic PDFs (optional — PDFs are already in the zip)
python scripts/generate_docs.py

# 2. Ingest (from backend/)
cd backend
.\venv\Scripts\Activate.ps1
python -m app.services.ingestion --docs ../data/docs --out ../data/chunks.jsonl --manifest ../data/docs_manifest.json

# 3. Index (downloads the embedding model on first run — needs internet once)
python ../scripts/index_chunks.py

# 4. Search test
python ../scripts/search_test.py

# 5. Tests
python -m pytest ../tests/ -v

# 6. API
uvicorn app.main:app --reload --port 8000
# GET http://127.0.0.1:8000/api/v1/documents
```

## Verification (this VM, 2026-11-05)

- Ingestion CLI: 8 documents, 24 pages, 15 chunks, avg 528.1 tokens
  (min 167, max 793). Chunk counts per doc: KYC 2, AML 2, SAMA 2, Loan 2,
  Account Opening 2, HR Leave 2, Charges 1, PDPL 2. Arabic text present
  in 8 of 15 chunks.
- Embeddings: 15 vectors, shape (15, 384), model
  sentence-transformers/all-MiniLM-L6-v2 (see section 3 for the BGE-M3
  story — it was tried and failed on this VM, honestly recorded).
- Search test (`scripts/search_test.py`): **3/3 PASS**
  - "What documents are needed for KYC account opening?" → KYC Policy
    p.1, score 0.6630 (2nd: Account Opening Policy, 0.5966)
  - "What is the AML reporting threshold?" → AML Policy p.1, 0.4753
    (2nd: AML Policy p.2, 0.4700)
  - "How long does it take to open an account at a branch?" →
    Account Opening Policy p.1, 0.4524
  - Note: the first query was first expected to hit the Account Opening
    Policy; the KYC Policy is actually the correct top result because
    it holds the authoritative "Documents Needed for Account Opening"
    list (section 3). The test expectation was corrected, not the
    search — see the comment in scripts/search_test.py.
- pytest: **13 passed, 0 failed** (`python -m pytest tests/ -v`).
- py_compile: all backend files OK.
- API live (uvicorn :8123/:8124): health 200 (version 0.2.0),
  GET /api/v1/documents returns 8 docs, POST /api/v1/documents/upload
  with the KYC PDF returns chunk_count 2, chunks_indexed 0 (dedupe —
  same doc re-uploaded), rbac_enforced false; POST /api/v1/chat still
  501 (Sprint 2).
- pgvector store: code only on this VM — no PostgreSQL server exists
  here, so the PgVectorStore path was not live-tested; the local file
  store is the default and is fully tested. On Fahad's laptop (local
  Postgres on port 5432) it can be tried with RTB_USE_PGVECTOR=1.

## What is NOT built yet

- Sprint 2: RAG chat, hybrid search, reranker, citations, LLM answers.
- Sprint 3: JWT login, RBAC enforcement, audit log, admin/users.
- Sprint 4: RAGAS evaluation, feedback, polish.
- PaddleOCR is NOT installed in this environment (OCR path is code-only
  and tested only via its warning path); scanned-PDF OCR will be verified
  when a scanned sample exists.
