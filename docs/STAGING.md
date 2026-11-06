# Staging — Riyadh Trust Bank Enterprise Intelligence Platform (v0.6)

**Status: Staging DONE & verified on this VM (2026-11-06).**
Testing's decision was **CONDITIONAL GO** (docs/TESTING.md) — Staging is the next step after it.
No new feature was built; only environment, configuration and scripts.

## What Staging is — and what it is NOT

**Is:** the same code as in dev, but in a separate environment — separate ports, separate
data, DEBUG off, fresh JWT secret. An attempt to behave like Production,
without Docker and without paid cloud (budget $0).

**Is NOT:**
- No cloud deployment, no public URL — everything is on `localhost`.
- No real users — only 3 demo accounts (below).
- No real customer data — the same 8 synthetic PDFs.
- Not Production — the promotion checklist (below) must be fully satisfied for Production.

## Port map (dev vs staging)

| Item | Dev | Staging |
|---|---|---|
| API | http://127.0.0.1:8000 | **http://127.0.0.1:8001** |
| Web | http://localhost:3000 | **http://localhost:3001** |
| Data dir | `data/` | **`data-staging/`** |
| Database file | `rtb_intelligence.db` (SQLite, inert — see below) | `rtb_intelligence_staging.db` |
| JWT secret | dev default (`.env`) | fresh random (`.env.staging`, gitignored) |
| Frontend build | `frontend/dist/` | `frontend/dist-staging/` |

Dev and staging can run **together** — ports and data are separate.

## What changed in v0.6 (vs v0.5)

- `backend/app/core/paths.py` (NEW): `data_dir()` — the data directory comes from the
  `RTB_DATA_DIR` env var (default `data/`). Staging uses `data-staging/`.
- `backend/app/core/config.py`: version **0.6.0**; `cors_origins` setting
  (default `http://localhost:3000,http://localhost:3001`).
- `backend/app/main.py`: CORS middleware (required for direct API
  calls from the staging web :3001).
- `frontend/src/api/client.ts`: `VITE_API_URL` support — in the staging build the
  API base `http://127.0.0.1:8001` is baked into the bundle; in dev it remains
  empty, so calls go via the Vite proxy (`:8000`) as before.
- `frontend/src/vite-env.d.ts` (NEW): `vite/client` types — without it
  `tsc` errors on `import.meta.env` (the staging build would fail).
- `frontend/vite.config.staging.ts` (NEW): port 3001, proxy → :8001,
  output `dist-staging/` (dev `dist/` untouched).
- `frontend/.env.staging` (NEW): `VITE_API_URL=http://127.0.0.1:8001`.
- `.env.staging.example` (NEW): staging env template (secret placeholder).
- `scripts/staging_setup.sh` + `scripts/staging_setup.ps1` (NEW):
  fresh venv → pip install → fresh JWT secret → create `data-staging/`
  (copy PDFs + ingestion + seed users + index).
- `scripts/staging_start.sh` + `scripts/staging_start.ps1` (NEW):
  start the staging API :8001.
- `scripts/staging_smoke.py` (NEW): 22-check smoke test.
- `tests/test_health.py`: version assertion 0.5.0 → 0.6.0 (test updated
  with the version bump — no behavior change).
- README.md: status + Staging section.
- `.gitignore`: `.env.staging`, `data-staging/`, `frontend/dist-staging/`.

## Running on a Windows PC (PowerShell) — step by step

**Requirements:** Python 3.12+, Node.js 20+, PostgreSQL (optional — staging
also runs on the SQLite file; Postgres is required for the PgVector test).
Docker **not** required. Ollama **not** required (extractive mode runs without it).

```powershell
# 1. Open the project folder
cd riyadh-trust-bank-intelligence

# 2. Staging setup (first time; 5-10 minutes — venv + packages + index)
#    If Activate.ps1 gives an error, run this first:
#    Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
.\scripts\staging_setup.ps1

# 3. Start the staging API — Terminal 1 (foreground, stop with Ctrl+C)
.\scripts\staging_start.ps1
# Check: http://127.0.0.1:8001/api/v1/health
#   -> {"success": true, "data": {"status": "ok", "environment": "staging", "version": "0.6.0"}}

# 4. Smoke test — Terminal 2
python scripts\staging_smoke.py
#   -> 22/22 PASS expected

# 5. Staging frontend — Terminal 3
cd frontend
npm install
npm run build -- --mode staging --config vite.config.staging.ts
npx vite preview --port 3001 --config vite.config.staging.ts
# Open: http://localhost:3001  (login page; demo accounts below)
```

To set up again (fresh data): `.\scripts\staging_setup.ps1 -Fresh`
Setup + start together: `.\scripts\staging_setup.ps1 -Start`

Linux (like this VM): `./scripts/staging_setup.sh` / `./scripts/staging_start.sh` —
same steps. The venv is created in `~/rtb-staging-venv` (not inside the project).

**Demo accounts (DEMO ONLY — change passwords before Production):**
admin@rtb.local / Admin123! (ADMIN) · compliance@rtb.local / Compliance123!
(COMPLIANCE_OFFICER) · service@rtb.local / Service123! (CUSTOMER_SERVICE)

## Live verification on this VM (2026-11-06, actual output)

### Fresh venv
- `~/rtb-staging-venv` — created from `backend/requirements.txt`.
- **bcrypt 4.0.1** ✓ (TESTING BUG-1 pin — passlib breaks with bcrypt ≥ 4.1).
- fastapi 0.115.0, sentence-transformers 3.1.1, torch 2.15.0+cpu.
- Note: on the first attempt the torch wheel download from PyPI failed (network stall,
  165/539 MB) — setup scripts now install CPU-only torch from the PyTorch CPU index
  first, then the remaining requirements. `TMPDIR` is also set to home
  (this VM's /tmp is only 512 MB, the torch wheel is ~540 MB).

### Pytest (fresh staging venv, dev defaults)
- **57 passed, 0 failed.** The first run had 56 pass + 1 fail — the failure was only
  the hardcoded version "0.5.0" in `test_health`; with the 0.6.0 bump the test
  was updated, then 3/3 health tests pass. (The full suite was not run again —
  the remaining 56 had already passed and the cause of the failure was proven.)

### Staging setup
- `.env.staging` created, fresh random SECRET_KEY generated (gitignored).
- `data-staging/`: 8 PDFs copied → ingestion **15 chunks, avg 528.1 tokens**
  (same as dev) → 3 demo users seeded → vector store index (15 chunks,
  all-MiniLM-L6-v2, 384-dim — BGE-M3, the same honest fallback as Sprint 1).
- The staging setup did **not** touch dev `data/` (audit.jsonl mtime
  2026-11-05 20:19, before setup).

### Smoke test — `scripts/staging_smoke.py` → **22/22 PASS, 0 FAIL**

| # | Check | Result |
|---|---|---|
| 1 | health 200 + environment=staging | PASS (version 0.6.0) |
| 2 | health version 0.6.0 | PASS |
| 3 | metrics environment=staging | PASS |
| 4–6 | login admin / compliance / service | PASS (roles correct) |
| 7 | wrong password → 401 | PASS |
| 8 | no-token chat → 401 | PASS |
| 9 | EN chat (warm-up) answered + cited | PASS (top: KYC Policy, 25.7 s — first call, models loading) |
| 10–12 | EN chat timed ×3 (latency re-measurement) | PASS — **6.78 s / 4.50 s / 8.22 s**, median **6.78 s** |
| 13 | AR chat (compliance) AML cited | PASS (0.33 s, top: AML Policy) |
| 14 | RBAC: service AML → refused, 0 citations | PASS (mode: rbac-refusal) |
| 15–16 | documents list: service = 4, admin = 8 | PASS |
| 17–18 | feedback thumbs-up + feedback-stats | PASS ("Thank you, your feedback was received.", total=1) |
| 19 | eval/results 200 | PASS (no stored run at that time) |
| 20 | audit-logs contain LOGIN entries | PASS (13 entries) |
| 21 | staging data lives in data-staging/ | PASS (users.json + audit.jsonl) |
| 22 | dev data/audit.jsonl untouched by smoke | PASS (mtime + size before/after identical) |

### English latency re-measurement (Testing condition #1)
- **3 warm EN chats: 6.78 s, 4.50 s, 8.22 s — median 6.78 s.**
- Testing had 4.3–8.4 s steady-state — **no improvement, the same range.**
  Target < 3 s is still **missed** on this VM.
- The cause is the same as written in Testing: cross-encoder reranker + RBAC
  probe, RAM-starved VM (~1 GB free). AR chat is 0.33 s (score-based
  reranker, not cross-encoder) — this clearly shows that the cross-encoder is
  the bottleneck for English latency.
- **The real decision will be made on Fahad's PC** — RAM is higher there; if
  it remains > 3 s there, applying the cross-encoder only to top-k or disabling it
  will need to be decided before Production promotion.

### Eval (staging, limit=3, 21.8 s)
- faithfulness **1.00** ✓ (target ≥ 0.85), context_recall **1.00** ✓
  (target ≥ 0.80), answer_relevancy **0.6118** ✗ (target ≥ 0.85 —
  the same MiniLM English-only limit; in the Sprint 4 20-question eval it was 0.4172),
  top-doc accuracy **1.00** (3/3), latency p50 **8.31 s** / p95 **9.58 s**.
- The report was saved in `data-staging/eval_results.json`; `GET /eval/results`
  now returns the stored run. (The full 20-question eval was not run in staging —
  the 3-question run proves the pipeline; the full eval will run
  on Fahad's PC before Production.)

### Frontend staging build + preview + CORS
- `npm run build -- --mode staging` **PASS** (vite 5.4.21, 38 modules,
  `dist-staging/` — the JS bundle has `127.0.0.1:8001` baked in, verified).
- The dev build also **PASS** (the client.ts change did not break dev).
- Preview `http://localhost:3001/` **HTTP 200** — the staging bundle is served.
  (Note: the preview listens on `[::1]:3001` — curl from `127.0.0.1:3001` fails,
  it works from `localhost:3001`.)
- CORS: on both preflight + real GET,
  `access-control-allow-origin: http://localhost:3001` ✓.

## Honest limits of Staging (all the same as dev — staging changed nothing)

1. **English latency 4–8 s** — target < 3 s missed (see above). It must be
   re-measured on Fahad's PC.
2. **SQLite file is inert:** staging `DATABASE_URL` points to a different file
   (`rtb_intelligence_staging.db`), but at runtime
   **no .db file is created at all** — `init_db()` is only called from Postgres paths.
   In dev also no .db file exists. The real stores are JSONL
   files (`data-staging/`). The real PgVector test will be on Fahad's PC with
   Postgres (port 5432) — see the Promotion checklist.
3. **Embeddings MiniLM (384-dim)** — BGE-M3 (1024-dim) did not download
   on this VM (the same fallback since Sprint 1); it is recorded in the config.
4. **Generation extractive-fallback** — no Ollama on this VM; answers
   are built only from retrieved chunks (the mode is written in the response).
   A real LLM requires Ollama + llama3.1:8b on Windows.
5. **Arabic visual-order garbling** and **relevancy 0.42–0.61** — known limitations since Sprint 4,
   the same in staging.
6. **Tokens in localStorage** (demo) — Production requires an httpOnly cookie.
7. **Pytest touched dev data:** in this session the full pytest ran in a fresh venv
   on dev defaults (the same happens every sprint) — it updated
   `data/conversations.jsonl` and `data/eval_results.json`.
   **Staging traffic did not touch dev data** — the smoke test proved it by taking a
   before/after snapshot of audit.jsonl, and all staging files
   are in `data-staging/`.

## Promotion checklist — all of these must be TRUE before Production

| # | Item | Status |
|---|---|---|
| 1 | Demo passwords changed (3 accounts) | ⏳ PENDING — Fahad will do it on Production |
| 2 | JWT secret set (separate, long random, for Production) | ⏳ PENDING — the `.env.staging` one is only for staging |
| 3 | Ollama running + llama3.1:8b (real LLM answers) | ⏳ PENDING — via the Windows installer |
| 4 | PgVector tested on Fahad's PC (port 5432) | ⏳ PENDING — no Postgres on this VM |
| 5 | English latency decision (re-measure on Fahad's PC; if > 3 s then cross-encoder fix) | ⏳ PENDING — on this VM 4.5–8.2 s |
| 6 | Arabic garbling + relevancy 0.42 — accept or fix decision | ⏳ PENDING |
| 7 | Full 20-question eval on the staging/Production env | ⏳ PENDING — only limit=3 ran in staging |
| 8 | Tokens localStorage → httpOnly cookie (or accept the risk) | ⏳ PENDING |
| 9 | Staging smoke 22/22 PASS (on this VM) | ✅ DONE |
| 10 | Fresh venv bcrypt 4.0.1 + pytest 57/57 | ✅ DONE |

**Until 1–8 are pending, do not do Production.** Staging is only for demo and
verification.

## Rollback plan

- **Stop staging:** Ctrl+C in the API terminal; Ctrl+C in the preview terminal.
  Nothing needs to be uninstalled — staging is only processes + files.
- **Dev is completely untouched:** dev `data/`, the dev venv and dev ports (:8000/:3000)
  are separate from staging. After stopping staging, dev will run
  exactly as it ran before.
- **Wipe staging data:** `rm -rf data-staging/` (Linux) or
  `Remove-Item -Recurse data-staging\` (PowerShell), then
  recreate it with `./scripts/staging_setup.sh --fresh`.
- **Code rollback:** restore from the previous version zip
  `Project-1-Sprint4-v0.5.zip` (v0.5 code is the one that received CONDITIONAL GO in Testing).
- **If a secret leaks:** delete `.env.staging`, run setup again —
  a new random secret will be generated. `.env.staging` never goes into git or zip.
