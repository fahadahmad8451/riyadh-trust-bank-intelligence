# Production — Riyadh Trust Bank Enterprise Intelligence Platform (v0.8)

**Status: Production DONE & verified on this VM (2026-11-06).**
It is the step after Staging v0.6 (docs/STAGING.md). Fahad said "Yes,
start Production".

## What Production is here — and what it is NOT

**Is:** the same code as in dev/staging, but in production mode —
production hardening (see §1 below), separate data (`data-prod/`), DEBUG off,
fresh JWT secret, **demo accounts OFF**, backup/restore, runbook.
It will run on Fahad's PC on localhost (API :8000, web :3000), $0.

**Is NOT:**
- No cloud deployment, no public URL — everything is on `localhost`.
- No real customer data — the same 8 synthetic PDFs.
- No "deployed to the internet" claim — do not call something deployed that is not on the internet.
  For a portfolio demo, this is local production.
- The Monitoring phase is still remaining (Langfuse dashboards, scheduled
  healthcheck) — see §6.

## Port map (dev vs staging vs production)

| Item | Dev | Staging | **Production** |
|---|---|---|---|
| API | http://127.0.0.1:8000 | http://127.0.0.1:8001 | **http://127.0.0.1:8000** |
| Web | http://localhost:3000 | http://localhost:3001 | **http://localhost:3000** |
| Data dir | `data/` | `data-staging/` | **`data-prod/`** |
| JWT secret | dev default (`.env`) | fresh (`.env.staging`) | **fresh (`.env.production`)** |
| Demo accounts | ON | ON | **OFF** |
| Frontend build | `frontend/dist/` (dev) | `frontend/dist-staging/` | **`frontend/dist/` (prod build)** |

**Dev and production ports SHARE (:8000/:3000) — deliberately.**
Production is this machine's live instance; dev and production
cannot run together. Stop dev before starting production,
otherwise the bind will fail ("address already in use" — runbook §5).
Staging (:8001/:3001) can run alongside production.

## 1. Production hardening (what changed in v0.8, vs v0.7)

| # | Item | Where | Status |
|---|---|---|---|
| 1 | Demo accounts OFF in prod | `RTB_DEMO_ACCOUNTS=0` (`.env.production.example`); even if the flag is forgotten in production, `validate_production_settings()` turns demo off (only an explicit `=1` turns it back on) | ✅ DONE + live proof (demo login → 401) |
| 2 | Seed demo users are not created | `app/core/users.py seed_users()` — if the flag is off it writes nothing, returns `[]` | ✅ DONE (no users.json existed in data-prod at first) |
| 3 | Login with a demo email is blocked | `app/api/v1/auth.py` — if the flag is off, 401 on a demo email, even if a demo user was copied into users.json | ✅ DONE + pytest |
| 4 | How to create the first admin | `scripts/create_admin.py --email you@bank.local` (bcrypt hash, role ADMIN; a demo email is refused, a duplicate is refused) | ✅ DONE + live proof |
| 5 | Weak JWT secret = server does NOT start | `app/core/config.py validate_production_settings()` — if the secret is < 32 chars or a placeholder (`CHANGE-ME`/`REPLACE-ME`), `RuntimeError` on import, with a clear message | ✅ DONE + pytest (subprocess) |
| 6 | CORS wildcard is refused | If production has `CORS_ORIGINS="*"` then also `RuntimeError`; the prod default is only `http://localhost:3000` | ✅ DONE + pytest (subprocess) |
| 7 | DEBUG forced off | Even if production has `DEBUG=1`, `settings.debug = False` | ✅ DONE (code + config) |
| 8 | Security headers | On every response: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`; the `Server` header is disabled via uvicorn `--no-server-header` | ✅ DONE + live curl proof |
| 9 | Rate limiting (in-memory) | Login: 5 FAILED attempts / 60 s per (IP, email) — only failures are counted, a successful login clears the counter. Register: 3 attempts / 60 s per (IP, email). On the limit, **429 + `Retry-After` header**. `app/core/rate_limit.py` — no new dependency | ✅ DONE + pytest + live proof (6th wrong login → 429) |
| 10 | Upload limit 10 MB | `POST /documents/upload` — counts while streaming, if over 10 MB then **413** and the partial file is deleted | ✅ DONE + pytest + live proof (11 MB → 413) |
| 11 | Extended `/health` | `env, version, uptime_seconds, demo_accounts_enabled, reranker, embeddings, vector_store {status, documents, chunks}, generation_mode, database` — only file reads, no model load, no Ollama probe | ✅ DONE + live proof |
| 12 | Reranker off flag | `RTB_RERANKER=off` — rerank scores without trying the cross-encoder (for the latency test, §4) | ✅ DONE + pytest |
| 13 | Backup / restore | `scripts/backup.py` (timestamped zip, keeps the last 7) + `scripts/restore.py` (first a pre-restore backup, then restore) | ✅ DONE + live proof |
| 14 | Healthcheck script | `scripts/healthcheck.py` — exit 0/1, the probe for the Monitoring phase | ✅ DONE + live proof |
| 15 | Login page demo section | `frontend/src/pages/Login.tsx` — reads `demo_accounts_enabled` from `/health` and hides the demo section (not shown in prod) | ✅ DONE (verified in the bundle) |
| 16 | Version 0.8.0 | `config.py` + `test_health.py` + README | ✅ DONE |

## 2. Promotion checklist — Staging to Production (final status)

The final accounting of the Staging checklist (STAGING.md) items:

| # | Item | Status |
|---|---|---|
| 1 | Demo passwords changed | ✅ SUPERSEDED — there are no demo accounts in production at all (OFF). There is no need to change demo passwords, because demo login is not possible at all. |
| 2 | JWT secret set (Production, separate, long random) | ✅ DONE — fresh 64-char secret in `.env.production` (created by the setup script); the server does not start at all on a weak secret. |
| 3 | Ollama running + llama3.1:8b (real LLM answers) | ⏳ **PC-PENDING** — no Ollama on this VM; answers are in extractive-fallback mode (the mode is written in the response). Steps in §4. |
| 4 | PgVector tested on Fahad's PC (port 5432) | ⏳ **PC-PENDING** — no Postgres on this VM. Steps in §4. |
| 5 | English latency decision (re-measure on PC; if > 3 s then cross-encoder fix) | ⏳ **PC-PENDING** — re-measured on this VM: staging 7.26 / 4.51 / 8.38 s (median 7.26 s), target < 3 s still missed. The `RTB_RERANKER=off` flag is ready (§4). |
| 6 | Arabic garbling + relevancy 0.42 — accept or fix decision | ⏳ **PENDING (Fahad's decision)** — the fix is recreating the PDFs with logical-order Arabic + BGE-M3; neither has happened yet. |
| 7 | Full 20-question eval on the production env | ⏳ **PC-PENDING** — limit=3 ran in staging (faithfulness 1.00, recall 1.00, relevancy 0.6118). The full 20-question eval will run on the PC via the §4 steps. |
| 8 | Tokens localStorage → httpOnly cookie | ⏳ **PENDING — the risk must be accepted or it must be built.** Tokens are still in localStorage (since Sprint 3). The risk is low for a localhost-only demo (no public URL, no third-party script), but this is production's largest remaining weakness — it should be done before or with the Monitoring phase. |
| 9 | Staging smoke 22/22 PASS | ✅ DONE (run again — §7) |
| 10 | Fresh venv bcrypt 4.0.1 + pytest 81/81 | ✅ DONE (§7) |

**Items 3–8 are pending on the PC or on Fahad's decision — do not treat them as DONE.**
Production is "local production" for this reason: hardening is
complete, but the real LLM, PgVector and the full eval remain on the PC.

## 3. Running on a Windows PC (PowerShell) — step by step

**Requirements:** Python 3.12+, Node.js 20+, PostgreSQL (optional —
for the PgVector test). Docker **not** required.

```powershell
# 1. Open the project folder
cd riyadh-trust-bank-intelligence

# 2. Stop dev/staging (ports :8000/:3000 belong to production)
.\scripts\production_stop.ps1   # stops anything running

# 3. Production setup (first time; 5-10 minutes — venv + packages + index + build)
#    If Activate.ps1 gives an error, run this first:
#    Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
.\scripts\production_setup.ps1

# 4. Create the first admin (demo users are NOT created — this is mandatory)
python scripts\create_admin.py --email you@bank.local
#    It will ask for a password (min 8 chars, 1 letter + 1 digit). A demo email
#    (admin@rtb.local) is refused — it will never log in in production.

# 5. Start the production API — Terminal 1 (foreground, stop with Ctrl+C)
.\scripts\production_start.ps1
# Check: http://127.0.0.1:8000/api/v1/health
#   -> {"success": true, "data": {"status": "ok", "environment": "production", ...}}

# 6. Start the web UI — Terminal 2
.\scripts\production_start_web.ps1
# Open: http://localhost:3000  (Sign In page — demo accounts will NOT be shown)

# 7. Smoke test — Terminal 3 (while the API is running)
python scripts\production_smoke.py
#   -> 18/18 PASS expected

# 8. Backup (first time + before every upgrade)
python scripts\backup.py
```

To set up again (fresh data): `.\scripts\production_setup.ps1 -Fresh`
Setup + start together: `.\scripts\production_setup.ps1 -Start`
Linux (like this VM): `./scripts/production_setup.sh` / `./scripts/production_start.sh` /
`./scripts/production_start_web.sh` / `python scripts/production_smoke.py` — same steps.
The venv is created in `~/rtb-prod-venv` (not inside the project).

**Admin login:** the same email/password created in step 4.
New users are created via Sign Up (always the Customer Service role);
higher access is granted by changing the role in the Admin panel.

## 4. Steps to do on Fahad's PC (PC-only — NOT done on this VM)

This checklist must be completed on the PC. Each item includes its command:

- [ ] **Install Ollama + llama3.1:8b (Windows):**
  1. Run the Ollama Windows installer from https://ollama.com/download.
  2. `ollama pull llama3.1:8b` (first time ~4.7 GB download — it will take time).
  3. Uncomment this line in `.env.production`: `OLLAMA_HOST=http://127.0.0.1:11434`
  4. Restart the API. Then chat — the answer's `generation_mode` should
     show `ollama` (instead of extractive-fallback).
  5. Check: `curl http://127.0.0.1:11434/api/tags` — `llama3.1:8b` should
     appear in the model list.
- [ ] **PgVector test (PostgreSQL port 5432):**
  1. If PostgreSQL is running: `createdb rtb_intelligence_prod`
  2. Comment the SQLite line in `.env.production`, uncomment this:
     `DATABASE_URL=postgresql://postgres:<password>@localhost:5432/rtb_intelligence_prod`
  3. `python scripts\seed_users.py --postgres` — only a mirror, the real store
     is still JSON (the Postgres users table in the Design is for a future deployment).
     Turn the PgVector store on with `RTB_USE_PGVECTOR=1`, run
     `python scripts\index_chunks.py` again, then the search test:
     `python scripts\search_test.py` — 3/3 PASS expected.
  4. If Postgres does not run, the SQLite setup is production —
     the app runs without Postgres (health reports `database`).
- [ ] **Re-measure English latency + cross-encoder decision:**
  1. First ask 3 English questions in normal mode, measure the time
     (the smoke test also gives 3 timed chats).
  2. Then set `RTB_RERANKER=off` in `.env.production`, restart the API,
     ask the same 3 questions again.
  3. Decision: if latency is < 3 s with `off` and the answers still arrive with correct
     citations, keep `off` in production (check the impact on relevancy — via eval).
     If the answers are poor with `off`, return to `auto` and accept 4–8 s (write in the
     portfolio demo that it is due to the cross-encoder).
- [ ] **Full 20-question eval on production data:**
  `python scripts\run_eval.py` (an Admin token is required — ~2 minutes).
  Targets: faithfulness ≥ 0.85, context_recall ≥ 0.80,
  answer_relevancy ≥ 0.85 (0.42–0.61 is expected due to MiniLM —
  this will only be fixed with BGE-M3 + a real LLM; write it that way in the eval report).
- [ ] **Arabic garbling decision:** in Arabic answers, numbers/clauses appear in the wrong
  order (known since Sprint 1). The fix is recreating the source PDFs with
  logical-order Arabic (`scripts/generate_docs.py`).
  Or accept it and write it in the portfolio as a limitation.
- [ ] **httpOnly cookies (checklist item 8):** tokens are still in localStorage.
  For the fix, the backend must provide the token via `Set-Cookie: HttpOnly`
  and the frontend must send it with `credentials: 'include'` — this is
  work before the Monitoring phase. The risk is low in a localhost-only demo,
  but it remains for a "production-ready" claim.
- [ ] **Backup schedule:** run `python scripts\backup.py` once a week
  (or via Task Scheduler). Backups remain in `backups/`
  (last 7). Keep a backup of `.env.production` SEPARATELY (it does not go into
  the zip — to avoid a secret leak) — keep a copy in a safe place,
  otherwise if the secret is lost all tokens will become invalid
  (if you create the secret again, the old logins will need to be done again).

## 5. Backup & restore + rollback + runbook

### Backup
```powershell
python scripts\backup.py            # backups\rtb-prod-backup-YYYYMMDD-HHMMSS.zip
```
The zip contains: `users.json`, `audit.jsonl`, conversations, feedback,
refresh tokens, docs manifest, chunks, vector store. **`.env` files
never go into the zip** (keep the secret separately).

### Restore
```powershell
.\scripts\production_stop.ps1
python scripts\restore.py --backup backups\rtb-prod-backup-20261106-120000.zip --force
.\scripts\production_start.ps1
```
Restore is refused without `--force` (data-prod/ already exists).
A pre-restore backup is always created before restore
(`backups\rtb-pre-restore-<stamp>.zip`) — even a wrong restore can be reversed.

### Rollback (back from production to staging/dev)
1. Stop production: `.\scripts\production_stop.ps1`
2. Run staging: `.\scripts\staging_start.ps1` (API :8001) +
   staging web `:3001` — staging data (`data-staging/`) never mixes with production,
   it remains as it was.
3. Code rollback: restore from the previous version zip
   `Project-1-Frontend-v0.7.zip` (v0.7 code is the one whose live smoke passed 13/13).
   The production-only additions (hardening/scripts) are not in that zip — after rollback
   the v0.8 setup will need to be run again.
4. If a secret leaks: delete `.env.production`, run setup again — a new random secret
   will be generated. **Old tokens will immediately become invalid**
   (all users will log in again) — this is correct behavior. `.env.production` never goes into git or zip.

### Runbook — what to do if there is a problem
| Problem | What to do |
|---|---|
| API does not start: "PRODUCTION REFUSED TO START" | Read the message — either SECRET_KEY is weak/placeholder (run setup again or create a new one with `python -c "import secrets; print(secrets.token_urlsafe(64))"`), or CORS contains `*` (keep only `http://localhost:3000`). |
| Port 8000 busy ("address already in use") | Dev or the old production is still running. Run `.\scripts\production_stop.ps1`, then start again. |
| "Demo accounts" shown on the login page | The production API is not running — the browser is talking to the staging/dev API. Check that the environment on `:8000` is `production` (`/api/v1/health`). |
| Login 429 "Too many attempts" | 5 wrong passwords in one minute — wait 60 seconds, then try again. (Admin is not exempt from this — it is to stop brute-force.) |
| Chat is slow (English 4–8 s) | Known — cross-encoder + RAM. Try the `RTB_RERANKER=off` test in §4. |
| Server stopped (crash) | See the error in the terminal, then run it again with `.\scripts\production_start.ps1`. Data is safe in `data-prod/` — a restart deletes nothing. If the data looks corrupt, restore from a backup (above). |
| Users forgot their password | There is no password reset flow yet (FRONTEND.md §11). Admin can recreate a user with `scripts/create_admin.py --email <same-email> --force` (the old role will be lost — then set the role again from the Admin panel). |
| Need to check health | `python scripts\healthcheck.py` — exit 0 = healthy, 1 = there is a problem. |

### Monitoring hooks (ready for the Monitoring phase)
- `/api/v1/health` is extended (§1 item 11) — it reports uptime, vector store,
  embeddings, generation mode.
- `scripts/healthcheck.py` gives exit 0/1 — run it every 5 minutes via Windows Task Scheduler
  or cron and alert on failure.
- Logs: uvicorn writes to the console (in the terminal). File logging /
  rotation is not there yet — in the Monitoring phase `logs/` + rotation
  will arrive. Until then do not close the API terminal (it contains the logs).
- No external monitoring service (budget $0).

## 6. What changed in v0.8 (vs v0.7)

- `backend/app/core/config.py`: version **0.8.0**; `demo_accounts_enabled`
  (`RTB_DEMO_ACCOUNTS`), `debug`, `reranker_mode` (`RTB_RERANKER`);
  `validate_production_settings()` — production fail-fast.
- `backend/app/core/rate_limit.py` (NEW): in-memory sliding window
  (login 5 failed/min, register 3/min, per IP+email, 429 + Retry-After).
- `backend/app/core/users.py`: `seed_users()` does nothing if the demo flag is off; `DEMO_EMAILS` set.
- `backend/app/api/v1/auth.py`: demo login block + rate limiting
  (login/register), 429 envelope.
- `backend/app/api/v1/documents.py`: 10 MB upload limit (streaming,
  413 + partial delete).
- `backend/app/main.py`: security headers middleware; extended `/health`
  (`_health_extras()` — file reads only).
- `backend/app/services/retrieval.py`: `RTB_RERANKER=off` support.
- `frontend/src/pages/Login.tsx`: demo section gated from `/health`;
  `frontend/src/api/client.ts`: `HealthResponse` extended type.
- `frontend/.env.production` (NEW): prod build API URL.
- `.env.production.example` (NEW), `scripts/create_admin.py`,
  `scripts/healthcheck.py`, `scripts/backup.py`, `scripts/restore.py`,
  `scripts/production_setup.{sh,ps1}`, `scripts/production_start.{sh,ps1}`,
  `scripts/production_start_web.{sh,ps1}`, `scripts/production_stop.{sh,ps1}`,
  `scripts/production_smoke.py` (NEW, 18 checks).
- `tests/test_production.py` (NEW, 12 tests); `tests/test_health.py`
  version 0.8.0; `scripts/staging_smoke.py` version pin 0.6.0 → 0.8.0.
- README.md: status + Production section; `.gitignore`:
  `.env.production`, `data-prod/`, `backups/`.

## 7. Live verification on this VM (2026-11-06, actual output)

### Fresh prod venv
- `~/rtb-prod-venv` — created from `backend/requirements.txt`.
- **bcrypt 4.0.1** ✓ (TESTING BUG-1 pin), fastapi 0.115.0, torch 2.15.0+cpu.
- Note: the first setup attempt failed on one line of `.env.production` —
  `DATABASE_URL=<redacted>` (unquoted `<`/`>`) gives a syntax error in shell sourcing.
  Fix: the value was put in quotes
  (`DATABASE_URL="sqlite:///./rtb_intelligence_prod.db"`); PowerShell
  loaders also strip quotes. When setup ran again it was **DONE**.

### Production setup
- `.env.production` created, fresh 64-char SECRET_KEY generated (gitignored).
- `data-prod/`: 8 PDFs copied → ingestion **15 chunks** → index
  (all-MiniLM-L6-v2, 384-dim — BGE-M3, the same honest fallback).
- **Demo users were NOT seeded** — after setup `data-prod/users.json`
  did not exist at all (checked before creating the first admin).
- Frontend prod build **PASS** (vite 5.4.21, 47 modules, 2.47 s,
  `dist/` — the bundle has `127.0.0.1:8000` baked in, verified).

### create_admin
- `prod-admin@rtb.local` → ADMIN created ✓.
- Demo email `admin@rtb.local` → **refused** ("demo account address") ✓.
- Duplicate email → **refused** ("already exists — use --force") ✓.

### Pytest (staging venv, dev defaults)
- **81 passed, 0 failed** (69 old + 12 new `tests/test_production.py`).
  Rate limiting did not break the old tests (the limiter is per IP+email,
  it counts only failed logins).

### Live production API (:8000, ENV=production)
Health (actual output):
```json
{"status": "ok", "service": "Riyadh Trust Bank — Enterprise Intelligence Platform",
 "version": "0.8.0", "environment": "production", "uptime_seconds": 6.24,
 "demo_accounts_enabled": false, "reranker": "auto",
 "embeddings": {"model": "sentence-transformers/all-MiniLM-L6-v2", "dim": 384, "backend": "st"},
 "vector_store": {"status": "ok", "documents": 8, "chunks": 15},
 "generation_mode": "extractive-fallback", "database": "sqlite (local file)"}
```
Headers (curl): `x-content-type-options: nosniff`,
`x-frame-options: DENY`, `referrer-policy: no-referrer` ✓ —
**no `server` header** (uvicorn `--no-server-header`) ✓.
`scripts/healthcheck.py` → `HEALTHY ... env=production version=0.8.0` **exit 0** ✓.

### Production smoke — `scripts/production_smoke.py` → **18/18 PASS, 0 FAIL**

| # | Check | Result |
|---|---|---|
| 1–5 | health 200, env=production, v0.8.0, demo off, vector store ok | PASS |
| 6–9 | security headers (3) + no Server header | PASS |
| 10 | demo login admin@rtb.local → 401 | PASS |
| 11–12 | register 201 (CUSTOMER_SERVICE) + login 200 | PASS |
| 13 | EN chat answered + cited | PASS (5 citations) |
| 14 | RBAC: service AML → refused, 0 citations | PASS (refused=True, mode=rbac-refusal) |
| 15–16 | rate limit: 6th wrong login → 429, Retry-After=60 | PASS ([401×5, 429]) |
| 17 | metrics 200 + env=production | PASS |
| 18 | smoke user cleanup (deleted from data-prod) | PASS |

The first smoke run was 17/18 — **one FAIL in the RBAC check was my smoke
script's error, not the app's**: the script read `data.mode`, a field that does not exist
(the correct field is `generation_mode`), and asked a different question from staging
("AML policy for high-risk customers?").
On that question the actual answer seen was: **5 citations, all RETAIL**
(KYC/Loan/Account Opening) — **no COMPLIANCE citation, no leak**.
Reason: the KYC Policy mentions high-risk customers, so the allowed retrieval was strong
and the RBAC-blocked detector did not trigger. The staging question ("What is the AML reporting
threshold?") is also **refused** in production (smoke run again:
18/18 PASS). This is the detector's pre-existing, question-dependent
behavior (Sprint 4) — not a production regression. But note:
**RBAC refusal is not guaranteed on every AML-like phrasing**
— a question that overlaps RETAIL content (such as high-risk
customers) receives a grounded RETAIL-only answer, not a refusal.
A disallowed document never appears in citations — this security
property held in every test (23 RBAC unit tests + journeys +
smoke).

### Upload limit (live, curl)
- With an admin token, an 11 MB PDF upload → **HTTP 413** ("File too large —
  maximum upload size is 10 MB"), the file was **not** saved to disk,
  the admin still sees 8 documents ✓.

### Backup / restore (live)
- `python scripts/backup.py` → `backups/rtb-prod-backup-20261105-215752.zip`
  (**17 files, 0.34 MB**) ✓.
- Restore test (in a separate dir `/tmp/rtb-restore-test`, without touching data-prod):
  **17 files restored**, users contained only
  `prod-admin@rtb.local` ✓. The test dir was then deleted.

### Frontend preview (:3000)
- `npx vite preview --port 3000` → `http://localhost:3000/` **HTTP 200** ✓.
- The bundle was verified for `demo_accounts_enabled` gating + `127.0.0.1:8000` ✓.

### Regression — staging smoke run again
- Staging API :8001 + `scripts/staging_smoke.py` → **22/22 PASS**
  (the first run was 21/22 — only the hardcoded version pin 0.6.0 failed,
  the version is now 0.8.0; after updating the pin and running again,
  22/22). English latency re-measured: **7.26 / 4.51 / 8.38 s,
  median 7.26 s** — target < 3 s still missed (on this VM).
  Dev `data/audit.jsonl` untouched by staging smoke ✓.

## 8. Honest limits of Production (all the same as before)

1. **English latency 4–8 s** — target < 3 s missed (on this VM).
2. **Generation extractive-fallback** — no Ollama on this VM.
3. **Embeddings MiniLM (384-dim)** — BGE-M3 fallback.
4. **Arabic visual-order garbling** and **relevancy 0.42–0.61**.
5. **Tokens in localStorage** — the httpOnly cookie is still remaining (item 8).
6. **SQLite file is inert** — the real stores are JSONL files; the PgVector
   test remains on the PC.
7. **Rate limiter is in-memory, per-process** — production runs a single
   worker, so the limit holds. Do not run `--workers > 1`
   (there is no shared store).
8. **RBAC-blocked refusal is question-dependent** (§7 — never a leak,
   but refusal is not given on every AML-like phrasing).
9. **No file logging / rotation** — logs are on the API terminal.
10. **No HTTPS** — a localhost-only demo; before running on a public URL,
    a reverse proxy + TLS + httpOnly cookies are mandatory.
