# Riyadh Trust Bank — Enterprise Intelligence Platform

![Python](https://img.shields.io/badge/Python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)
![React](https://img.shields.io/badge/React-18-61DAFB)
![TypeScript](https://img.shields.io/badge/TypeScript-5.5-3178C6)
![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-3.4-06B6D4)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791)
![License: Portfolio Demo](https://img.shields.io/badge/License-Portfolio_Demo-lightgrey)

> **Enterprise Intelligence Platform for a fictional Saudi bank** — ask policy questions and get grounded answers with a citation for every claim, with access controlled by your role. **Project 1 of an 11-project Saudi enterprise AI portfolio.**

## What it is

Employees at a bank waste hours hunting for the right policy, contract, or compliance memo. This platform indexes the bank's own documents (KYC, AML, SAMA compliance, loans, HR, PDPL) and answers questions **only from those documents** — every answer carries citations (document + page + relevance score), and role-based access control is enforced in the backend **before** any document is retrieved, so a Customer Service user never sees Compliance or HR documents, not even in a citation.

- **Fictional bank, synthetic data only.** "Riyadh Trust Bank" is not a real bank. All 8 documents (24 pages) are fictional, created for this demo. **No real customer data, ever.**
- **Local-first, $0.** Runs on a laptop without Docker or any cloud service: Python venv + Node + local PostgreSQL. No paid APIs, no paid LLM — answers run in extractive-fallback mode until Ollama is installed (see Honest limitations).
- **Full process, one project at a time:** Requirements → Estimate → Design → Setup → Development (4 sprints) → Testing → Staging → Production → Monitoring. This repo is the finished Project 1 (v0.9.1).

## Features

- **RAG chat with citations** — hybrid retrieval (vector top-20 + BM25 top-20 → RRF → cross-encoder rerank top-5); every answer cites document, page, and score; out-of-scope questions get a clear refusal instead of an invented answer.
- **Sign in / Sign up** — real registration (new accounts default to the lowest-privilege `CUSTOMER_SERVICE` role); JWT access (15 min) + refresh (24 h) tokens with rotation and logout revoke.
- **Role-based access (RBAC)** — Customer Service sees RETAIL only (4 docs), Compliance Officer RETAIL + COMPLIANCE (6 docs), Admin all 8 docs incl. HR/PDPL. Enforced in the backend before retrieval. Admins can change user roles.
- **Audit trail** — every login, question, upload, and denied access is logged (user, role, time, result); Admin can review it in the dashboard.
- **Documents** — upload (PDF/Word/Excel, OCR fallback), list, search, delete; ingestion with section-aware chunking (8 docs → 15 chunks).
- **Evaluation** — local RAGAS-style eval (faithfulness, context recall, answer relevancy) on a 20-question set, plus user feedback (thumbs up/down) on every answer.
- **Monitoring** — every request recorded (endpoint, status, latency, role); 6 alert rules (brute force, error rate, p95 latency, RBAC spike, API down, disk usage); Admin `/monitoring` dashboard with live cards, hourly chart, alerts + acknowledge; daily report generator; log rotation.
- **Production hardening** — demo accounts OFF in production, fail-fast on weak JWT secret / wildcard CORS, security headers, login/register rate limiting (429), 10 MB upload limit, backup/restore scripts, extended `/health`.
- **Professional frontend** — React 18 + TypeScript + Tailwind: landing page, Sign In/Sign Up (password strength meter), sidebar app shell, chat with citation cards, documents table, audit log, admin panel, monitoring dashboard. Arabic + English.

## Tech stack

| Layer | Tech |
|---|---|
| Backend | FastAPI, Python 3.12, Pydantic, LangGraph (design) |
| Retrieval | pgvector (HNSW) + BM25 + BGE-M3 embeddings (fallback: all-MiniLM-L6-v2, 384-dim — see limitations) + cross-encoder reranker |
| Database | PostgreSQL 16 + pgvector (local file store default; pgvector path included, tested on PC) |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, React Router |
| OCR | PaddleOCR (fallback, never faked) |
| Auth | JWT + bcrypt, refresh-token rotation |
| Monitoring | JSONL metrics/alerts, `monitor_check.py`, daily reports |
| Tests | pytest (backend), `tsc` + Vite build (frontend) |

## Screenshots

![Landing page](docs/screenshots/01-landing.png)
![Sign in](docs/screenshots/02-signin.png)
![Sign up](docs/screenshots/03-signup.png)
![Chat with citations](docs/screenshots/04-chat.png)
![Monitoring dashboard](docs/screenshots/05-monitoring.png)
![Landing page — fixed](docs/screenshots/06-landing-fixed.png)

## Quick start

**You need:** Python 3.12+, Node.js 20+, PostgreSQL (local, port 5432). Docker, Redis, Ollama are **not** required.

### Development (Windows PowerShell)

```powershell
# 1. Copy the example env and set a secret
copy .env.example .env

# 2. Backend — Terminal 1
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python ..\scripts\seed_users.py   # demo users (DEMO ONLY — see below)
uvicorn app.main:app --reload --port 8000
# Health: http://127.0.0.1:8000/api/v1/health
# API docs: http://127.0.0.1:8000/docs

# 3. Frontend — Terminal 2
cd frontend
npm install
npm run dev
# Open: http://localhost:3000
```

Linux: same steps with `./scripts/production_setup.sh` / `staging_setup.sh` — see `docs/SETUP.md`, `docs/STAGING.md`, `docs/PRODUCTION.md`.

### Production (local, $0 — no cloud)

```powershell
.\scripts\production_setup.ps1        # venv + secret + data-prod + index + frontend build
python scripts\create_admin.py --email you@bank.local   # first admin (demo users are NOT seeded)
.\scripts\production_start.ps1         # API :8000
.\scripts\production_start_web.ps1     # Web :3000
python scripts\production_smoke.py     # smoke test
python scripts\backup.py               # backup data-prod/
```

### Demo accounts (demo only)

| Role | Email | Password |
|---|---|---|
| Admin | admin@rtb.local | Admin123! |
| Compliance Officer | compliance@rtb.local | Compliance123! |
| Customer Service | service@rtb.local | Service123! |

**These are public demo credentials. Change them before any real use, and never enable them in production** (`RTB_DEMO_ACCOUNTS=0` in production; the app refuses to start with a weak secret or wildcard CORS).

## Verified results

All numbers below were measured live on the test VM and recorded in `docs/` — nothing here is estimated.

- **pytest: 99 passed, 0 failed** (health, ingestion, RAG, RBAC incl. 12+ negative tests, feedback/eval, production, monitoring).
- **End-to-end journeys: 25/25 PASS** (Customer Service, Compliance Officer, Admin, attacker, refusals) — `docs/TESTING.md`.
- **Staging smoke: 22/22 PASS** (API :8001, web :3001) — `docs/STAGING.md`.
- **Production smoke: 18/18 PASS** (demo login 401, rate-limit 429, security headers, RBAC) — `docs/PRODUCTION.md`.
- **Frontend smoke: 13/13 PASS** (register → login → chat → role change) — `docs/FRONTEND.md`.
- **RAG: 10/10 questions correct** (6 English + 4 Arabic) + refusal PASS.
- **Eval (20 questions, Admin, extractive mode):** faithfulness **1.00**, context recall **1.00**, answer relevancy **0.42** (see limitations), top-doc 19/20.

## Project structure

```
frontend/   React 18 + TypeScript + Vite + Tailwind (Landing, Login/Register, Chat, Documents, Audit, Admin, Monitoring)
backend/    FastAPI (app/main.py, app/core, app/db, app/api/v1, app/services, app/monitoring)
scripts/    setup/start/smoke/backup/restore/monitor/daily-report/rotate-logs (PowerShell + bash)
tests/      pytest suite (health, ingestion, RAG, RBAC, auth, feedback/eval, production, monitoring)
data/       synthetic docs (data/docs/*.pdf + sources in data/docs_src/*.md), chunks, eval results
docs/       SETUP, SPRINT1–4, TESTING, STAGING, FRONTEND, PRODUCTION, MONITORING, LANDING-FIX
infra/      docker-compose.optional.yml (OPTIONAL only — Docker is not required)
```

## Honest limitations

Nothing hidden — these are real, recorded limits of v0.9.1:

- **Extractive-fallback generation until Ollama runs.** No LLM is bundled; answers are composed only from retrieved chunks (the response says which mode was used). Install Ollama + `llama3.1:8b` on the PC for real LLM answers.
- **English latency 4–8 s** (target < 3 s) on the RAM-starved test VM — cross-encoder reranker + RBAC probe. Arabic is ~0.2–0.3 s. The reranker can be disabled with `RTB_RERANKER=off` to re-measure on a stronger PC.
- **Answer relevancy 0.42** (target 0.85) — the MiniLM embedder is English-only; Arabic scores ~0.24. The real fix needs BGE-M3 + a real LLM.
- **Arabic text has a logical-order display defect** in the generated PDFs (visual order, not logical order).
- **Tokens are stored in localStorage** (httpOnly cookies are still pending — the biggest remaining production weakness).
- **RBAC refusal is not guaranteed on every AML-like phrasing** — e.g. "AML policy for high-risk customers?" returned 5 RETAIL citations (no COMPLIANCE leak, but no refusal either). This is question-dependent behaviour present since Sprint 4.
- **PgVector path is code-complete but was not live-tested on the VM** (no Postgres there) — test it against local PostgreSQL on port 5432.
- **No password reset yet** — the login page honestly says to contact an admin.

## Docs

- `docs/SETUP.md` — detailed setup · `docs/SPRINT1.md` — ingestion + vector DB · `docs/SPRINT2.md` — RAG + citations · `docs/SPRINT3.md` — login, RBAC, audit, admin UI · `docs/SPRINT4.md` — evaluation + polish · `docs/TESTING.md` — test report (CONDITIONAL GO) · `docs/STAGING.md` — staging environment · `docs/FRONTEND.md` — professional redesign + auth · `docs/PRODUCTION.md` — production hardening + runbook · `docs/MONITORING.md` — metrics, alerts, dashboard · `docs/LANDING-FIX.md` — landing page fix (v0.9.1)

---

## Build history (v0.1 → v0.9.1)

> Neeche wala hissa chronological build log hai — har version ke waqt likha gaya. Kuch purani lines us waqt ki hain jab wo feature abhi nahi bana tha; aaj ki haalat upar "What it is" / "Honest limitations" me hai. Koi fact delete nahi kiya gaya.

> **DOCKER NAHI CHAHIYE — ye setup bina Docker ke chalega.**
> Fahad ke laptop par Docker nahi chalta (BIOS password-locked, VT-x Disabled).
> Is liye primary setup **local Windows** hai: Python venv + Node + local PostgreSQL.
> Docker sirf optional hai (`infra/docker-compose.optional.yml`) — un ke liye jin ke PC par Docker chalta ho.

Fictional Saudi bank (Riyadh Trust Bank) ke liye Enterprise Intelligence Platform — portfolio project, koi asal company nahi, koi asal customer data nahi.

Status: **Landing Fix v0.9.1 DONE — Project 1 COMPLETE.** Landing page Fahad ke PC par blank/faint dikh rahi thi (white-on-white) — plain-CSS fallback classes (`.hero-bg`, `.hero-gold-btn`, `.footer-bg`, `.dark-btn`) + version badge v0.9.1. VM par build sahi tha — wajah stale build/cache thi; real headless-Chrome screenshot + computed-style probe se verify. Details `docs/LANDING-FIX.md`, screenshot `docs/screenshots/06-landing-fixed.png`. Pytest **99 passed**.
Monitoring (v0.9): request metrics (`metrics.jsonl`, har request record hoti hai), 6 alert rules (brute force, error rate, p95 latency, RBAC spike, API down, disk), `scripts/monitor_check.py` (har 5 min, exit 0/1/2), `scripts/daily_report.py`, `scripts/rotate_logs.py`, Admin Monitoring dashboard (`/monitoring`, live cards + hourly chart + alerts + acknowledge). Pytest **99 passed** (81 purane + 18 naye), live verify: brute-force HIGH + p95 MEDIUM alerts asal traffic par bane. Details `docs/MONITORING.md`. PC-only pending list (Ollama, PgVector, latency, eval, httpOnly cookies) — `docs/MONITORING.md` §8.
Production hardening: demo accounts OFF (`RTB_DEMO_ACCOUNTS=0`, fail-fast on weak JWT secret / wildcard CORS), security headers,
login/register rate limiting (429), 10 MB upload limit, extended `/health`, `scripts/create_admin.py`, backup/restore, production
runbook. Details `docs/PRODUCTION.md`. "Production" yahan local production hai (Fahad ke PC par, $0, no cloud) — koi fake
cloud deployment nahi. Agla step: Monitoring.
Professional frontend redesign (landing, Sign In/Sign Up, sidebar app shell, chat, documents, audit log,
admin + evaluation) + real register endpoint (auto-login, CUSTOMER_SERVICE default) + Admin role change.
Pytest **69 passed** (57 purane + 12 naye), live smoke staging par **13/13 PASS**. Details `docs/FRONTEND.md`.
Testing: **CONDITIONAL GO** (docs/TESTING.md) — 57 tests + 25/25 journeys pass, RBAC airtight; English latency 4–8 s
(target < 3 s) aur Arabic garbling / relevancy 0.42 known limitations hain.
Evaluation (local RAGAS-style, no LLM judge) aur feedback ban gaye hain — details `docs/SPRINT4.md` me.
Eval results (20 sawal, ADMIN): faithfulness **1.00** ✅, context recall **1.00** ✅, answer relevancy **0.42** ❌ (target 0.85 —
MiniLM English-only hai, Arabic judge nahi kar sakta; asal LLM + BGE-M3 se theek hoga). Agla step: Production → Monitoring.

## Monitoring (v0.9, NEW)
Local-first, $0, no external service: har request `metrics.jsonl` me record hoti hai; alerts `alerts.jsonl` me; Admin dashboard `/monitoring` par. Details: `docs/MONITORING.md`.
```powershell
python scripts\monitor_check.py --port 8000 --data-dir data-prod   # har 5 min (Task Scheduler) — exit 0 ok / 1 alert / 2 critical-down
python scripts\daily_report.py --data-dir data-prod                 # rozana — data-prod/reports/daily-YYYY-MM-DD.md
python scripts\rotate_logs.py --data-dir data-prod                  # haftawar — 10k lines se zyada hon to archive (7 archives max)
```

## Production (v0.8)
Local production on this machine ($0, no cloud): API **:8000**, web **:3000**, data **data-prod/** (dev + staging data untouched),
DEBUG off, fresh JWT secret, demo accounts OFF. Details: `docs/PRODUCTION.md`.
```powershell
.\scripts\production_setup.ps1        # Windows: venv + secret + data-prod + index + frontend build
python scripts\create_admin.py --email you@bank.local   # first admin (demo users are NOT seeded)
.\scripts\production_start.ps1         # API :8000 start karo
.\scripts\production_start_web.ps1     # Web :3000 start karo
python scripts\production_smoke.py     # smoke test (health, headers, demo 401, register, chat, RBAC, 429)
python scripts\backup.py               # data-prod/ ka backup
```
Linux: `./scripts/production_setup.sh` / `./scripts/production_start.sh` / `./scripts/production_start_web.sh` — same steps.

## Staging (v0.6)
Same code, alag environment: API **:8001**, web **:3001**, data **data-staging/** (dev data/ untouched), DEBUG off,
fresh JWT secret. Details: `docs/STAGING.md`.
```powershell
.\scripts\staging_setup.ps1        # Windows: venv + secret + data-staging + index
.\scripts\staging_start.ps1        # API :8001 start karo
python scripts\staging_smoke.py    # smoke test (health, 3 roles, EN/AR chat, RBAC, feedback)
```
Linux: `./scripts/staging_setup.sh` / `./scripts/staging_start.sh` — same steps.

## Kya ban gaya hai (v0.4 — Sprint 3; Sprint 2 neeche)
- **Login + JWT (Sprint 3, NEW):** `POST /api/v1/auth/login` (access 15 min
  + refresh 24 h, rotation + logout revoke), `POST /api/v1/auth/refresh`,
  `POST /api/v1/auth/logout`, `GET /api/v1/auth/me`. Demo users seed karo:
  `python scripts/seed_users.py` — admin@rtb.local / Admin123! (ADMIN),
  compliance@rtb.local / Compliance123! (COMPLIANCE_OFFICER),
  service@rtb.local / Service123! (CUSTOMER_SERVICE). **DEMO ONLY — asal
  istemal se pehle passwords badlo.**
- **RBAC (Sprint 3, NEW):** Backend me enforce — chat, documents list,
  upload, admin. Service sirf RETAIL (4 docs), Compliance RETAIL +
  COMPLIANCE (6 docs), Admin sab (8 docs). HR docs (HR Leave + PDPL)
  sirf ADMIN. Galat role ko disallowed document ki citation kabhi nahi
  milti — service ko AML sawal par refusal milta hai.
- **Audit log (Sprint 3, NEW):** Har LOGIN / QUERY / UPLOAD /
  ACCESS_DENIED `data/audit.jsonl` me (Postgres ho to `audit_logs`
  table me bhi). Admin dashboard me dekho: `GET /api/v1/admin/audit-logs`.
- **Admin UI (Sprint 3, NEW):** Users, documents aur audit-log tables —
  sab real API se, koi fake rows nahi. Login page par 3 clickable DEMO
  account buttons hain; Chat page user + role badge dikhata hai.
- **Tests:** `tests/test_health.py` + `tests/test_ingestion.py` +
  `tests/test_rag.py` + `tests/test_rbac.py` — **43 passed, 0 failed**.
- **Synthetic documents:** 8 PDFs (24 pages) — KYC, AML, SAMA Compliance,
  Personal Loan, Account Opening, HR Leave, Charges & Fees, PDPL. Sab fictional,
  English + Arabic summary. Sources: `data/docs_src/*.md`, regenerate with
  `python scripts/generate_docs.py`.
- **Ingestion:** `backend/app/services/ingestion.py` — PDF (PyMuPDF), Word,
  Excel; OCR fallback (PaddleOCR, warning if missing, never faked);
  section-aware chunking (~800 tokens, ~150 overlap). CLI:
  `python -m app.services.ingestion --docs ../data/docs --out ../data/chunks.jsonl`
  Result: 8 docs, 15 chunks, avg 528.1 tokens.
- **Embeddings + Vector DB:** embedding model recorded in
  `data/vector_store/embedding_config.json` (BGE-M3 tried first, fallback
  recorded honestly). Local file store in `data/vector_store/` (default,
  no Postgres needed) + Postgres/pgvector store code (`RTB_USE_PGVECTOR=1`).
  Index: `python scripts/index_chunks.py`. Search test: `python scripts/search_test.py`.
- **API (new):** `GET /api/v1/documents` (list) aur
  `POST /api/v1/documents/upload` (ingest + index). RBAC **not enforced yet**
  (Sprint 3) — response me saaf likha hai.
- **Frontend:** React 18 + TypeScript + Vite + Tailwind scaffold — Login / Chat / Admin pages, real routing, `/api/v1/health` ko real fetch kar ke API status dikhata hai. Koi fake chat answer nahi.
- **Backend:** FastAPI — `/api/v1/health`, `/api/v1/metrics`, documents endpoints
  real aur working. Baaki 10 endpoints honest 501 stubs hain.
- **RAG chat (Sprint 2, NEW):** `POST /api/v1/chat` — hybrid retrieval
  (vector + BM25 -> RRF -> rerank) + grounded answer with citations.
  `GET /api/v1/conversations` list karta hai, `GET /api/v1/conversations/{id}`
  saved messages deta hai. Generation modes: Ollama LLM (agar chal raha ho)
  ya extractive-fallback (is VM par yehi chala — jawab sirf retrieved
  chunks se banta hai, kuch invent nahi hota). Out-of-scope sawal par
  refusal: "Is document me ye maloomat nahi hai". Test: 10/10 questions
  correct + refusal OK. Detail: `docs/SPRINT2.md`.
- **Frontend Chat (Sprint 2, NEW):** Chat page ab real hai — sawal likho,
  `/api/v1/chat` se jawab aata hai, citations (title + page + score) aur
  generation-mode badge dikhte hain. Koi fake answer nahi.
- **Tests:** `tests/test_health.py` + `tests/test_ingestion.py` +
  `tests/test_rag.py` — **20 passed, 0 failed**.

## Kya abhi NAHI bana (v0.4 ke waqt ki note — ab sab ban gaya hai, upar dekho)
- Production deployment, Monitoring (Langfuse dashboards) — Staging ke baad ke steps hain.

Detail: `docs/SPRINT1.md`, `docs/SPRINT2.md`, `docs/SPRINT3.md`, `docs/SPRINT4.md`, `docs/TESTING.md`, `docs/STAGING.md`

## Quick Start — Windows (PowerShell), bina Docker

**Zaroorat:** Python 3.12+, Node.js 20+, PostgreSQL (local, port 5432 — pehle se hai). Docker, Redis, Ollama **zaroori nahi**.

```powershell
# 1. Project folder kholo
cd riyadh-trust-bank-intelligence

# 2. .env banao (copy, edit mat karo — secret badlo)
copy .env.example .env

# 3. Backend — Terminal 1
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python ..\scripts\seed_users.py   # demo users banao (admin/compliance/service)
uvicorn app.main:app --reload --port 8000
# Check: http://127.0.0.1:8000/api/v1/health  -> {"success": true, "data": {"status": "ok", ...}}
# API docs: http://127.0.0.1:8000/docs

# 4. Frontend — Terminal 2
cd frontend
npm install
npm run dev
# Open: http://localhost:3000  (header me "API online" dikhna chahiye)
```

**Database:** `.env` me `DATABASE_URL=postgresql://localhost:5432/rtb_intelligence` hai.
Database ek dafa banao: `createdb rtb_intelligence` (ya pgAdmin se).
Agar PostgreSQL na chal raha ho to bhi Setup chalega — DB wiring Sprint 1 me hai, aur skeleton SQLite file par fallback karta hai. pgvector extension Sprint 1 me lagayenge, Setup me zaroori nahi.

**Redis / Celery:** Optional. Bina Redis ke backend chalta hai (health OK). Worker Sprint 1 me.

**Ollama (LLM, local):** Windows installer se alag install hota hai, Docker nahi chahiye: https://ollama.com/download/windows — Setup me zaroori **nahi**; health check bina Ollama ke bhi OK hai. Models (`llama3.1:8b`, `qwen2.5:7b`) Sprint 2 me download karenge.

**Docker (optional, sirf doosron ke liye):** `infra/docker-compose.optional.yml` — Fahad ke laptop par **mat chalao**.

## Tests
```powershell
cd backend
.\venv\Scripts\Activate.ps1
python -m pytest ../tests/ -v
# 57 passed (health 3 + ingestion 10 + RAG 7 + RBAC 23 + feedback/eval 14)
```

## Structure
```
frontend/   React + TS + Vite + Tailwind
backend/    FastAPI (app/main.py, app/core, app/db, app/api/v1)
infra/      docker-compose.optional.yml (OPTIONAL only)
data/       empty — synthetic docs Sprint 1 me
tests/      test_health.py
docs/       SETUP.md (detail steps)
```
