# SETUP — Riyadh Trust Bank Enterprise Intelligence Platform v0.1

## DOCKER NOT REQUIRED — this setup runs without Docker

Docker Desktop does not run on Fahad's laptop: the BIOS is password-locked and
VT-x is Disabled, so neither Docker nor VirtualBox can run.
This setup is therefore built for **local Windows, without Docker**.
`infra/docker-compose.optional.yml` is only for people whose PCs can run
Docker — Fahad should **not** run it.

## 1. Requirements (Prerequisites)

| Item | Version | Check command (PowerShell) |
|---|---|---|
| Python | 3.12+ | `python --version` |
| Node.js | 20+ | `node --version` |
| PostgreSQL | 16 (local) | `psql --version` — port 5432 is already open |
| Git | any | `git --version` |

**Not required:** Docker, Redis, Ollama — all of these are optional.

## 2. Backend — PowerShell steps

```powershell
cd riyadh-trust-bank-intelligence
copy .env.example .env
# Open .env and change SECRET_KEY (any long random string)

cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Verify (browser or PowerShell):
```powershell
curl.exe http://127.0.0.1:8000/api/v1/health
# Expected: {"success":true,"data":{"status":"ok","service":"Riyadh Trust Bank — Enterprise Intelligence Platform","version":"0.1.0","environment":"development"},...}
curl.exe http://127.0.0.1:8000/api/v1/metrics
```
API docs: http://127.0.0.1:8000/docs

**If `Activate.ps1` gives an error** (execution policy):
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```
Then activate again.

## 3. Database — local PostgreSQL

```powershell
# Create the database once (via psql or pgAdmin):
createdb rtb_intelligence
# This is what is in .env: DATABASE_URL=postgresql://localhost:5432/rtb_intelligence
```

- Tables **are not created yet** — in Sprint 1 `Base.metadata.create_all` + pgvector will arrive.
- **SQLite fallback:** if PostgreSQL is stopped, the backend will still start — the config defaults to the SQLite file (`rtb_intelligence.db`). This is only for the skeleton; the real data will go to PostgreSQL in Sprint 1.
- **pgvector:** there is no need to install it during Setup. In Sprint 1 we will run `CREATE EXTENSION vector;` + `pip install pgvector`.

## 4. Frontend — PowerShell steps (second terminal)

```powershell
cd riyadh-trust-bank-intelligence\frontend
npm install
npm run dev
```
Open http://localhost:3000 — the header should show **"API online"** when the backend is running, otherwise **"API offline"**. Chat input is disabled in Setup (Sprint 2).

## 5. Redis / Celery — OPTIONAL

- The backend runs perfectly without Redis, and health remains OK.
- The Celery worker will arrive in Sprint 1 (document ingestion in the background).
- If Redis needs to be installed (later): on Windows, WSL or Memurai is used — do not do it in Setup.

## 6. Ollama — OPTIONAL (Windows installer, not Docker)

- Download: https://ollama.com/download/windows — a normal Windows installer.
- It is **not required** in Setup — the health check is OK even without Ollama.
- Models in Sprint 2: `ollama pull llama3.1:8b` and `ollama pull qwen2.5:7b`.

## 7. Docker — OPTIONAL ONLY (not for Fahad)

```powershell
# ONLY run this if Docker runs on your PC:
docker compose -f infra/docker-compose.optional.yml up -d
```
This will **not run** on Fahad's laptop (VT-x off) — so the local steps above are the primary ones.

## 8. Tests

```powershell
cd backend
.\venv\Scripts\Activate.ps1
python -m pytest ../tests/test_health.py -v
# 3 tests should pass: health 200, metrics, 501 stub
```

## 9. Issues (Troubleshooting)

| Issue | Solution |
|---|---|
| Port 8000 busy | `uvicorn app.main:app --reload --port 8001` — also change the frontend proxy to 8001 |
| `pip install` slow/fail | `pip install --upgrade pip` then try again |
| Frontend "API offline" | First make sure the backend is running in Terminal 1, then refresh the page |
| PostgreSQL will not connect | The DB is not required until Sprint 1 — the backend will still run (SQLite fallback) |
| PowerShell venv will not activate | See the execution policy step above |
