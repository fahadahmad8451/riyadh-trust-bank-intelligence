# SETUP — Riyadh Trust Bank Enterprise Intelligence Platform v0.1

## DOCKER NAHI CHAHIYE — ye setup bina Docker ke chalega

Fahad ke laptop par Docker Desktop nahi chalta: BIOS password-locked hai aur
VT-x Disabled hai, is liye Docker / VirtualBox dono nahi chal sakte.
Ye setup is liye **local Windows, bina Docker** ke banaya gaya hai.
`infra/docker-compose.optional.yml` sirf un logon ke liye hai jin ke PC par
Docker chalta ho — Fahad use **na** chalaye.

## 1. Kya chahiye (Prerequisites)

| Cheez | Version | Check command (PowerShell) |
|---|---|---|
| Python | 3.12+ | `python --version` |
| Node.js | 20+ | `node --version` |
| PostgreSQL | 16 (local) | `psql --version` — port 5432 pehle se open hai |
| Git | any | `git --version` |

**Nahi chahiye:** Docker, Redis, Ollama — ye sab optional hain.

## 2. Backend — PowerShell steps

```powershell
cd riyadh-trust-bank-intelligence
copy .env.example .env
# .env kholo, SECRET_KEY badlo (koi bhi lambi random string)

cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Verify (browser ya PowerShell):
```powershell
curl.exe http://127.0.0.1:8000/api/v1/health
# Expected: {"success":true,"data":{"status":"ok","service":"Riyadh Trust Bank — Enterprise Intelligence Platform","version":"0.1.0","environment":"development"},...}
curl.exe http://127.0.0.1:8000/api/v1/metrics
```
API docs: http://127.0.0.1:8000/docs

**Agar `Activate.ps1` error de** (execution policy):
```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```
phir dobara activate karo.

## 3. Database — local PostgreSQL

```powershell
# Database ek dafa banao (psql ya pgAdmin se):
createdb rtb_intelligence
# .env me yehi hai: DATABASE_URL=postgresql://localhost:5432/rtb_intelligence
```

- Tables **abhi create nahi hoti** — Sprint 1 me `Base.metadata.create_all` + pgvector aayega.
- **SQLite fallback:** agar PostgreSQL band ho, to bhi backend start hoga — config default SQLite file (`rtb_intelligence.db`) par girta hai. Ye sirf skeleton ke liye hai; asal data Sprint 1 me PostgreSQL par jayega.
- **pgvector:** Setup me install karne ki zaroorat nahi. Sprint 1 me `CREATE EXTENSION vector;` + `pip install pgvector` karenge.

## 4. Frontend — PowerShell steps (doosri terminal)

```powershell
cd riyadh-trust-bank-intelligence\frontend
npm install
npm run dev
```
Open http://localhost:3000 — header me **"API online"** dikhna chahiye jab backend chal raha ho, warna **"API offline"**. Chat input Setup me disabled hai (Sprint 2).

## 5. Redis / Celery — OPTIONAL

- Bina Redis ke backend bilkul theek chalta hai, health OK rehta hai.
- Celery worker Sprint 1 me aayega (document ingestion background me).
- Agar Redis install karna ho (baad me): Windows par WSL ya Memurai use hota hai — Setup me mat karo.

## 6. Ollama — OPTIONAL (Windows installer, Docker nahi)

- Download: https://ollama.com/download/windows — normal Windows installer hai.
- Setup me **zaroori nahi** — health check bina Ollama ke bhi OK hai.
- Models Sprint 2 me: `ollama pull llama3.1:8b` aur `ollama pull qwen2.5:7b`.

## 7. Docker — OPTIONAL ONLY (Fahad ke liye nahi)

```powershell
# SIRF tab chalao jab tumhare PC par Docker chalta ho:
docker compose -f infra/docker-compose.optional.yml up -d
```
Fahad ke laptop par ye **nahi chalega** (VT-x off) — is liye upar wale local steps hi primary hain.

## 8. Tests

```powershell
cd backend
.\venv\Scripts\Activate.ps1
python -m pytest ../tests/test_health.py -v
# 3 tests pass hone chahiye: health 200, metrics, 501 stub
```

## 9. Masle (Troubleshooting)

| Masla | Hal |
|---|---|
| Port 8000 busy | `uvicorn app.main:app --reload --port 8001` — frontend proxy tab bhi 8001 par badlo |
| `pip install` slow/fail | `pip install --upgrade pip` phir dobara |
| Frontend "API offline" | Pehle backend Terminal 1 me chal raha ho, phir page refresh karo |
| PostgreSQL connect nahi | Sprint 1 tak DB zaroori nahi — backend phir bhi chalega (SQLite fallback) |
| PowerShell venv activate nahi | Execution policy wala step upar dekho |
