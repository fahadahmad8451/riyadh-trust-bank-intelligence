# Limitations Fix — v0.10.0

Date: 2026-11-06. Fahad's order: complete every limitation that can be fully
covered, and do not write limitations in the README. This document is the
record: what was closed, what stays PC-only, and the proof for each item.

## Status table

| # | Limitation (v0.9.1 README) | Status | What happened |
|---|---|---|---|
| 1 | Tokens stored in localStorage (biggest production weakness) | **DONE** | httpOnly cookie auth — see §1 |
| 2 | No password reset | **DONE** | Admin reset + forgot-password request flow — see §2 |
| 3 | Arabic PDF logical-order defect | **DONE** | PDFs regenerated in logical order — see §3 |
| 4 | RBAC refusal not guaranteed on AML-like phrasing | **DONE** | Deterministic topic gate before retrieval — see §4 |
| 5 | English latency 4–8 s (target < 3 s) | **IMPROVED, PC-only for < 3 s** | 7.13 s → 3.53 s median on this VM — see §5 |
| 6 | PgVector path not live-tested | **DONE (live, with a caveat)** | Live test PASS on local PostgreSQL 16 + pgvector 0.6.0 — see §6 |
| 7a | Extractive-fallback generation (no Ollama / real LLM) | **PC-ONLY** | Ollama + llama3.1:8b cannot run on this VM — see §7 |
| 7b | Answer relevancy 0.42 (target 0.85) | **PC-ONLY** | Needs BGE-M3 + a real LLM; measured unchanged at 0.4172 — see §7 |

## 1. httpOnly cookies — DONE

- Backend sets `rtb_access` (15 min, path `/`) and `rtb_refresh` (24 h, path
  `/api/v1/auth`) as **HttpOnly + SameSite=Lax** cookies on login / register /
  refresh; logout clears both. `Secure` is set only when the request
  actually arrived over HTTPS (`request.url.scheme`, or
  `X-Forwarded-Proto` behind a proxy) — NOT from the environment name.
  The first version used `ENVIRONMENT=production` as the rule, and the
  production smoke caught it live: **16/18 PASS** — login succeeded but
  the next chat returned 401, because an httpx/curl client never sends a
  Secure cookie back over plain HTTP. Local production on Fahad's PC *is*
  plain HTTP, so the environment rule was wrong; the transport rule fixed
  it (production smoke re-run: **18/18 PASS**). Regression test in
  `tests/test_cookies.py`: production env + HTTP → no Secure flag; HTTPS
  → Secure flag present and the cookie is sent back.
- `backend/app/core/cookies.py`: `set_auth_cookies`, `clear_auth_cookies`,
  `read_access_token` (cookie first, then `Authorization: Bearer` fallback for
  API clients/scripts), `read_refresh_token` (cookie first, then JSON body).
- `get_current_user` now reads the cookie-first token; `HTTPBearer` removed.
- Login/register/refresh/logout responses contain **no tokens** — only user +
  metadata (`token_type` is now `"cookie"`).
- CSRF defence-in-depth: `csrf_origin_check` middleware in `main.py` — for
  non-GET/HEAD/OPTIONS requests carrying the `rtb_access` cookie with an
  Origin header not in `cors_origins` → 403. SameSite=Lax is the first layer;
  clients without an Origin header (curl) are allowed.
- Frontend (`frontend/src/api/client.ts`): all fetches use
  `credentials: 'include'`; **all localStorage token code removed**
  (`rtb_access_token`, `rtb_refresh_token` gone — only `rtb_user` display info
  remains); `App.tsx` verifies the cookie session against `api.me()` on
  mount, and only an `UNAUTHORIZED` error clears the session (a network
  error / API offline must not log the user out).
- Smoke scripts use one `httpx.Client` per role (each keeps its own cookie
  jar) — no Bearer headers.
- **Proof:** new `tests/test_cookies.py` — 8 tests (Set-Cookie httpOnly +
  SameSite=Lax, no tokens in body, chat with cookie only, refresh with cookie
  only + empty body, logout clears cookies, no-cookie-no-token 401, CSRF
  wrong-Origin 403 / no-Origin works / allowed-Origin works, GETs not
  CSRF-blocked). Live curl check on staging: login shows
  `Set-Cookie: rtb_access... HttpOnly`, subsequent chat works with the cookie
  only. Full suite: see §8.

## 2. Password reset — DONE (no fake email — there is no SMTP)

Honest design for a local/demo system: no reset token is emailed anywhere.

- **(a) Admin reset:** `POST /api/v1/admin/users/{email}/reset-password`
  (Admin only) — new password validated like register, sets the password,
  revokes **all** old refresh tokens for the user, resolves any pending
  requests for that email, audit `PASSWORD_RESET_BY_ADMIN`.
- **(b) Forgot-password request:** `POST /api/v1/auth/forgot-password`
  records a request (`data/password_reset_requests.json`, single pending per
  email) + audit `PASSWORD_RESET_REQUESTED` only if the user exists; the
  response is identical for unknown emails (no existence leak). The Admin
  panel lists pending requests with a **"Set new password"** action
  (`GET /admin/password-reset-requests`, `POST .../{id}/dismiss`).
- Frontend: Login "Forgot password?" opens a real request form (the old "not
  available yet" note is gone); Admin panel has a "Password reset requests"
  section + a per-user "Reset password" action and dialog.
- **Proof:** new `tests/test_password_reset.py` — both paths covered
  (request + admin reset + dismiss + revoked refresh token can no longer be
  used + unknown-email response identical). Run together with the topic-gate
  tests: **33 passed, 0 failed**.

## 3. Arabic PDF logical-order defect — DONE

- **Approach:** ReportLab + uharfbuzz manual typesetter. `fpdf2` stored
  Arabic in visual order (Presentation Forms) — the old
  `arabic_reshaper + python-bidi` path in `generate_docs.py` did not fix
  extraction. The rewrite splits each Arabic paragraph into directional runs
  (RTL Arabic, LTR numbers, parentheses) and shapes them with HarfBuzz, so
  the text stream in the PDF is in logical order.
- `scripts/generate_docs.py` rewritten (same CLI, same 8 filenames, A4, same
  footer). New dependencies: `reportlab`, `uharfbuzz` (+ a font that covers
  Arabic — see `backend/requirements.txt` / `scripts/generate_docs.py`).
- All 8 PDFs regenerated; ingestion + re-index re-run: **still 15 chunks /
  8 docs** (same counts).
- **Proof:** new `scripts/verify_arabic_pdfs.py` — **8/8 PASS** (one PASS line
  per PDF, non-zero exit on failure). Independent PyMuPDF check of
  `02-aml-policy.pdf`: the logical-order phrase `مكافحة غسل الأموال` is
  present in the extracted text and **zero** Presentation Forms characters
  (U+FB50–U+FEFF) remain in any PDF. Both vector stores
  (`data/vector_store/`, `data-staging/vector_store/`) re-indexed: 15 chunks,
  0 with presentation-forms, 3 with logical-order Arabic. Ingestion + RAG +
  RBAC tests with the new PDFs: **40 passed, 0 failed**.
- Note: `data-staging/` was re-synced the same way (copy PDFs → re-run
  ingestion → force re-index). The indexer deduplicates by
  (document_id, chunk_index), so a plain re-index adds 0 new chunks — the
  staging vector store had to be wiped first (`rm data-staging/vector_store/*`)
  or it would have kept the old chunk text.

## 4. RBAC topic gate — DONE

- New `backend/app/services/topic_gate.py`: a deterministic topic→department
  map, checked **before any retrieval**. COMPLIANCE phrases (EN: aml,
  anti-money laundering, money laundering, terrorist financing, terrorism
  financing, sama, suspicious transaction/activity, cash transaction
  reporting, reporting threshold, sanctions, sanction screening, compliance
  policy/department; AR: غسل الأموال, مكافحة غسل الأموال, تمويل الإرهاب,
  ساما, المعاملات المشبوهة, الإبلاغ عن المعاملات, عتبة الإبلاغ, الامتثال).
  HR phrases (EN: annual leave, leave policy, sick/maternity/paternity
  leave, salary, payroll, hr policy, human resources, employee benefits,
  working hours, overtime, performance review, resignation, probation, pdpl,
  data privacy, personal data protection, privacy policy/summary; AR: إجازة,
  الإجازة, الراتب, الموارد البشرية, ساعات العمل, حماية البيانات, البيانات
  الشخصية, الخصوصية). Plus a bare-word "leave" rule that needs an HR context
  word (employee/employees/days/policy/annual/sick). KYC and loans are
  RETAIL, so they are never gated.
- Matching: normalized question (lowercase, NFKD, punctuation→spaces);
  Latin phrases match on whole words (`\b`), Arabic as substrings.
- Wired into `answer_question` after language detection and the
  empty-departments check, before `get_retriever()`/retrieve: a gated
  question returns the standard RBAC refusal
  (`generation_mode="rbac-refusal"`, `rbac_blocked=True`,
  `topic_gate=True`, `blocked_department`, **0 citations, no retrieval**).
  `chat.py` adds an explicit `RBAC_DENIED` audit entry for gate refusals.
  The score-based probe stays as a fallback for phrasings the map misses.
- **Proof:** the exact reported case — service role asking
  **"AML policy for high-risk customers?" → refused, 0 citations**. New
  `tests/test_topic_gate.py`: unit tests + a role×topic matrix over real
  `/chat` (13 EN cases + 2 AR cases + audit test). Run together with the
  password-reset tests: **33 passed, 0 failed**. Allowed questions still
  answer (service asking KYC/loan) — regression suite green.
- **Bug found while testing:** NFKD decomposes Arabic hamza letters
  (أ → ا + combining hamza), so composed phrases never matched decomposed
  question text — fixed by normalizing the phrase with the same `_normalize`
  inside `_phrase_matches`. Verified directly: "ما هي سياسة مكافحة غسل
  الأموال؟" → COMPLIANCE, "ما هو حد الإبلاغ عن المعاملات النقدية؟" →
  COMPLIANCE (and None for the compliance role), Arabic leave question → HR,
  "AML policy for high-risk customers?" → COMPLIANCE, KYC question → None.

## 5. English latency — IMPROVED, < 3 s stays PC-only

- **Profiling (in-process, staging data, staging venv):** the real cost is
  the **cross-encoder rerank predict, ~3.2–4.7 s per call** on this
  RAM-starved VM. The model IS cached (HF cache 176 MB total, MiniLM +
  cross-encoder ~90 MB each); the earlier "968K" dir size was symlinks not
  followed by `du`. Everything else is ~0.01 s warm (encode_query 0.01 s,
  vector search, BM25 build/search, RRF fuse, score rerank all 0.00 s).
  First encode is 13.8–15.4 s (model load). Each EN chat paid **two**
  cross-encoder predicts (main retrieval + RBAC probe); AR pays zero (score
  rerank) → AR 0.21–0.30 s.
- **Optimizations (no quality drop):**
  (a) The RBAC probe now uses score rerank only — new
  `rerank_mode="score"` parameter on `HybridRetriever.retrieve()` →
  `rerank(..., force_score=True)`. The probe thresholds already had a
  score-based branch (strong ≥ 0.015, weak = allowed < 0.5×unrestricted),
  so this is a supported mode; the real answer still uses the cross-encoder.
  (b) Ollama availability cached 10 s (`_OLLAMA_CACHE`,
  `OLLAMA_CACHE_TTL_S=10.0`) — `ollama_available()` was called on every chat.
- **Measured on staging (`scripts/staging_smoke.py`, 3 warm EN chats):**

  | | Before | After |
  |---|---|---|
  | Warm-up | 29.4 s | 17.9 s |
  | EN chat 1 / 2 / 3 | 7.13 s / 4.61 s / 9.69 s | 3.53 s / 2.32 s / 5.28 s |
  | Median | **7.13 s** | **3.53 s** |

  One chat (2.32 s) is under 3 s; median 3.53 s is still a MISS. The
  remaining cost is the single cross-encoder predict (~2.5–3 s) under swap
  pressure on this VM. A second staging measurement after the v0.10.0
  fixes (new code, new PDFs) gave 4.17 s / 2.38 s / 5.23 s, median
  **4.17 s** — the improvement over 7.13 s holds, but the number moves
  run to run on this VM (swap pressure); < 3 s is not reliably reachable
  here.
- **Quality check after the probe change:** 20-question eval re-run on
  staging data — faithfulness 1.0000 PASS, context_recall 1.0000 PASS,
  answer_relevancy 0.4172 (unchanged, MISS), top_doc_accuracy 0.9500
  (19/20, unchanged), phrase_present 0.6000, refused 0/20, latency
  p50/p95 756/5696 ms (run took 60.6 s).
- **Decision recorded:** do NOT cap rerank candidates and do NOT enable
  `RTB_RERANKER=off` by default — that would hit ~0.2 s but silently lower
  ranking quality. **PC step:** on a PC with real RAM the same predict
  should be ~0.2–0.5 s; re-measure there and decide the < 3 s target then.

## 6. PgVector live test — DONE (live, with a caveat)

- PostgreSQL was NOT installed on the VM. Installed via apt:
  `postgresql-16` (16.15) + `postgresql-16-pgvector` (0.6.0). Cluster
  started with `sudo pg_ctlcluster 16 main start` (auto-start blocked by
  policy-rc.d); PostgreSQL 16.15 online on port 5432. Test DB `rtb_pgtest`
  + user `rtb` (VM-local test only, password passed via env, never written
  to a committed file) + `CREATE EXTENSION vector` (0.6.0).
- **Live test:** `~/workspace/pgvector_live_test.py` (throwaway, not in the
  repo): `RTB_USE_PGVECTOR=1` +
  `DATABASE_URL=postgresql://rtb:...@127.0.0.1:5432/rtb_pgtest` →
  PgVectorStore indexed the 15 real chunks (MiniLM 384-dim).
  **Result: PASS** — EN (KYC), EN (loan), AR (AML), and RBAC-filtered
  (RETAIL only, AML question) searches agree **exactly** with the local store
  (identical top-3 titles and scores, e.g. KYC 0.663 / Account Opening
  0.5966). Verified via psql: documents 8, chunks 15, extension vector 0.6.0.
- **Caveat (honest):** the DB plumbing (extension, tables, index, search,
  RBAC filter) is proven live, but **TRUE pgvector vector-column search needs
  1024-dim BGE-M3 embeddings** — the `vector(1024)` column has 0 populated
  rows; 15/15 chunks store 384-dim embeddings as JSON in `metadata` (the
  code logs 15× "pgvector column is 1024-dim but embeddings are 384-dim —
  storing as JSON instead"). That step is PC-only (BGE-M3, §7).
- **Driver bug found and fixed:** SQLAlchemy 2.1.8 (in the venvs;
  requirements.txt pins 2.0.35) resolves plain `postgresql://` URLs with the
  **psycopg (v3)** driver, but only `psycopg2-binary` was installed →
  "No module named 'psycopg'" and silent fallback to LocalVectorStore.
  Fix: added `psycopg[binary]==3.3.8` to `backend/requirements.txt` with a
  comment, installed into all three venvs.
- **Tests:** new `tests/test_pgvector.py` — fallback test (unreachable
  Postgres → LocalVectorStore) always runs; live test skips unless
  `RTB_LIVE_PGVECTOR=1` + DATABASE_URL. Final run with live DB: **2 passed**.
- **Apt gotcha (for next time):** `apt-get update` stalled ~8 min because
  `/etc/apt/sources.list.d/ubuntu.sources` lists two mirrors and
  `mirror.cogentco.com` is unreachable (apt cycles on it with Ign); fix was
  to temporarily remove the cogentco URI from that file (backup at
  `/tmp/ubuntu.sources.bak` — restored after this task) and re-run; update
  then took 9 s and the install was fast (~25–30 MB).

## 7. Ollama / BGE-M3 / answer relevancy — PC-ONLY

- **Evidence:** `answer_relevancy` is cosine between **MiniLM embeddings**
  of question and answer (`backend/app/services/evaluation.py`, uses
  `app.services.embeddings.encode_texts`) — swapping the retrieval model
  would change the scorer too, so any "improvement" number would be an
  invalid yardstick comparison. Ollama is not installed (`which ollama`
  empty) and llama3.1:8b (~4.7 GB) cannot run with ~450 MB–945 MB available
  RAM; BGE-M3 (2.2 GB) already proved stalled on this VM in Sprint 1; a
  smaller multilingual model (paraphrase-multilingual-MiniLM-L12-v2,
  ~470 MB) would change the metric's yardstick and risks OOM alongside
  MiniLM + cross-encoder.
- Measured relevancy after all other changes: **0.4172, unchanged** (same
  as Sprint 4). Keep PC-only.
- **PC steps:** install Ollama + `llama3.1:8b` on Fahad's PC; test BGE-M3
  there; re-run the full 20-question eval with the real LLM; then decide
  the relevancy target.

## 8. Verification summary (v0.10.0)

- Full pytest suite (dev venv): **141 passed, 1 skipped, 0 failed** (236.72 s; the 1 skip is the pgvector live test, which only runs with `RTB_LIVE_PGVECTOR=1`).
- Focused re-runs: ingestion + RAG + RBAC (new PDFs) **40 passed**;
  topic-gate + password-reset **33 passed**; pgvector live **2 passed**;
  cookie/RBAC/monitoring/feedback focused re-run **63 passed**.
- Frontend builds: dev `npm run build` PASS (tsc + vite, 48 modules,
  `dist/assets/index-DlUIGlRB.js` 243.07 kB, 3.12 s); staging
  `npm run build -- --mode staging --config vite.config.staging.ts` PASS
  (`dist-staging/assets/index-DbuORQXF.js` 243.07 kB, 2.85 s).
- Staging smoke (API :8001 / web :3001, after the v0.10.0 fixes):
  **22/22 PASS** — register, login (cookie check), chat EN + AR, RBAC
  topic-gate case, admin password reset path covered by the suite, plus
  the live curl proof in §1. Production smoke (API :8000):
  **18/18 PASS** after the Secure-flag fix (first run 16/18 — see §1).
- Version: `0.10.0` (`backend/app/core/config.py`, `tests/test_health.py`,
  both smoke scripts, landing-page badge, CI comment).
- README: the entire "Honest limitations" section was deleted; no
  "limitation" section remains (scan: `grep -i limitation README.md` shows
  only the `docs/LIMITATIONS-FIX.md` doc link and the historical build-log
  line, which now points at this document). README stays 100% professional
  English.
- Zip: `~/workspace/your_files/Project-1-Fixes-v0.10.zip` (verified with
  `unzip -l`).
- GitHub: commit **b8dcbbf** "v0.10.0 — close fixable limitations: httpOnly
  cookie auth, admin password reset, Arabic PDF logical order,
  deterministic RBAC topic gate" pushed to `main` (50 files, public repo
  fahadahmad8451/riyadh-trust-bank-intelligence); CI run 42184059698
  triggered on push (in progress at push time — not waited on, per the
  task). This hash line itself was recorded in a follow-up docs commit.

## Gotchas found during this task (keep for next time)

- **Cookie-jar precedence:** cookie-first auth means any test that presents
  BOTH a Bearer header and a jar cookie authenticates as the cookie's user;
  clear the jar (`client.cookies.clear()`) before presenting a token alone.
  Two JWT access tokens minted in the same second are identical (no jti) —
  refresh-rotation assertions must check the refresh cookie, not the access
  token.
- **Settings singleton:** `app.core.config.settings` is created at FIRST
  import, reading DATABASE_URL from the environment at that moment — never
  `monkeypatch.setenv("DATABASE_URL", ...)` before that first import, or the
  singleton is born with the patched value and no restore can fix it. Patch
  only the attribute after import; reset the cached
  `app.db.session._engine`/`_Session` globals in tests that switch stores.
- **Retrieval docstring edit trap:** a docstring edit in `retrieval.py`
  once broke the file (premature closing `"""` left the original docstring
  continuation as code → SyntaxError, HTTP 500 on staging) — keep the
  continuation inside the docstring; verify imports + syntax after any edit.
- **Staging server restarts:** kill by PID via `ss -ltnp` (never
  `pkill -f "uvicorn..."` — it matches the caller's own command line and
  kills the shell); start detached with
  `setsid nohup ./scripts/staging_start.sh > log 2>&1 < /dev/null &`
  (plain `&` inside exec dies with SIGHUP when the exec session ends).
- **Vector-store re-index dedup:** re-indexing the same chunks adds 0 new
  ones and keeps old chunk text — wipe the store dir first when chunk
  content changed (§3).
- **/tmp is 79% full** — use `~/workspace` scratch, not /tmp, for big
  downloads.
