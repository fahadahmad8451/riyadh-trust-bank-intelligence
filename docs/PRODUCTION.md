# Production — Riyadh Trust Bank Enterprise Intelligence Platform (v0.8)

**Status: Production DONE & verified on this VM (2026-11-06).**
Staging v0.6 ke baad ka step hai (docs/STAGING.md). Fahad ne "Haan,
Production shuru karo" kaha tha.

## Production yahan kya hai — aur kya NAHI hai

**Hai:** wahi code jo dev/staging me hai, lekin production mode me —
production hardening (neeche §1), alag data (`data-prod/`), DEBUG off,
fresh JWT secret, **demo accounts OFF**, backup/restore, runbook.
Fahad ke PC par localhost par chalega (API :8000, web :3000), $0.

**NAHI hai:**
- Koi cloud deployment nahi, koi public URL nahi — sab `localhost` par hai.
- Koi asal customer data nahi — wahi 8 synthetic PDFs.
- Koi "deployed to the internet" claim nahi — jo internet par nahi hai,
  usko deployed mat kaho. Portfolio demo ke liye ye local production hai.
- Monitoring phase abhi baqi hai (Langfuse dashboards, scheduled
  healthcheck) — §6 dekho.

## Port map (dev vs staging vs production)

| Cheez | Dev | Staging | **Production** |
|---|---|---|---|
| API | http://127.0.0.1:8000 | http://127.0.0.1:8001 | **http://127.0.0.1:8000** |
| Web | http://localhost:3000 | http://localhost:3001 | **http://localhost:3000** |
| Data dir | `data/` | `data-staging/` | **`data-prod/`** |
| JWT secret | dev default (`.env`) | fresh (`.env.staging`) | **fresh (`.env.production`)** |
| Demo accounts | ON | ON | **OFF** |
| Frontend build | `frontend/dist/` (dev) | `frontend/dist-staging/` | **`frontend/dist/` (prod build)** |

**Dev aur production ports SHARE karte hain (:8000/:3000) — jaan boojh
kar.** Production is machine ka live instance hai; dev aur production
ek saath nahi chal sakte. Production start karne se pehle dev band
karo, warna bind fail hoga ("address already in use" — runbook §5).
Staging (:8001/:3001) production ke saath chal sakta hai.

## 1. Production hardening (v0.8 me kya badla, vs v0.7)

| # | Cheez | Kahan | Status |
|---|---|---|---|
| 1 | Demo accounts OFF in prod | `RTB_DEMO_ACCOUNTS=0` (`.env.production.example`); production me flag bhool bhi jaye to `validate_production_settings()` demo off kar deta hai (sirf explicit `=1` wapas on karta hai) | ✅ DONE + live prove (demo login → 401) |
| 2 | Seed demo users nahi hote | `app/core/users.py seed_users()` — flag off ho to kuch nahi likhta, `[]` return karta hai | ✅ DONE (data-prod me pehle koi users.json hi nahi thi) |
| 3 | Demo email se login block | `app/api/v1/auth.py` — flag off ho to demo email par 401, chahe users.json me demo user copy bhi kar diya jaye | ✅ DONE + pytest |
| 4 | Pehla admin banane ka tareeqa | `scripts/create_admin.py --email you@bank.local` (bcrypt hash, role ADMIN; demo email mana hai, duplicate mana hai) | ✅ DONE + live prove |
| 5 | Weak JWT secret = server start NAHI hota | `app/core/config.py validate_production_settings()` — secret < 32 chars ya placeholder (`CHANGE-ME`/`REPLACE-ME`) ho to import par `RuntimeError`, saaf message ke sath | ✅ DONE + pytest (subprocess) |
| 6 | CORS wildcard mana hai | Production me `CORS_ORIGINS="*"` ho to bhi `RuntimeError`; prod default sirf `http://localhost:3000` | ✅ DONE + pytest (subprocess) |
| 7 | DEBUG forced off | Production me `DEBUG=1` bhi ho to `settings.debug = False` | ✅ DONE (code + config) |
| 8 | Security headers | Har response par: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`; `Server` header uvicorn `--no-server-header` se band | ✅ DONE + live curl prove |
| 9 | Rate limiting (in-memory) | Login: 5 FAILED attempts / 60 s per (IP, email) — sirf failures gini jati hain, kamyab login counter saaf kar deta hai. Register: 3 attempts / 60 s per (IP, email). Limit par **429 + `Retry-After` header**. `app/core/rate_limit.py` — koi nayi dependency nahi | ✅ DONE + pytest + live prove (6th wrong login → 429) |
| 10 | Upload limit 10 MB | `POST /documents/upload` — stream karte waqt ginta hai, 10 MB se zyada ho to **413** aur partial file delete | ✅ DONE + pytest + live prove (11 MB → 413) |
| 11 | Extended `/health` | `env, version, uptime_seconds, demo_accounts_enabled, reranker, embeddings, vector_store {status, documents, chunks}, generation_mode, database` — sirf file reads, koi model load nahi, koi Ollama probe nahi | ✅ DONE + live prove |
| 12 | Reranker off flag | `RTB_RERANKER=off` — cross-encoder try kiye baghair score rerank (latency test ke liye, §4) | ✅ DONE + pytest |
| 13 | Backup / restore | `scripts/backup.py` (timestamped zip, last 7 rakhta hai) + `scripts/restore.py` (pehle pre-restore backup, phir restore) | ✅ DONE + live prove |
| 14 | Healthcheck script | `scripts/healthcheck.py` — exit 0/1, Monitoring phase ka probe | ✅ DONE + live prove |
| 15 | Login page demo section | `frontend/src/pages/Login.tsx` — `/health` se `demo_accounts_enabled` parh kar demo section chhupata hai (prod me nahi dikhta) | ✅ DONE (bundle me verify) |
| 16 | Version 0.8.0 | `config.py` + `test_health.py` + README | ✅ DONE |

## 2. Promotion checklist — Staging se Production (final status)

Staging checklist (STAGING.md) ke items ka aakhri hisab:

| # | Item | Status |
|---|---|---|
| 1 | Demo passwords badle gaye | ✅ SUPERSEDED — production me demo accounts hain hi nahi (OFF). Demo passwords badalne ki zaroorat nahi, kyunke demo login hi nahi ho sakta. |
| 2 | JWT secret set (Production, alag, lamba random) | ✅ DONE — `.env.production` me fresh 64-char secret (setup script ne banaya); weak secret par server start hi nahi hota. |
| 3 | Ollama running + llama3.1:8b (asal LLM answers) | ⏳ **PC-PENDING** — is VM par Ollama nahi hai; answers extractive-fallback mode me hain (response me mode likha hota hai). Steps §4 me. |
| 4 | PgVector tested on Fahad's PC (port 5432) | ⏳ **PC-PENDING** — is VM par Postgres nahi tha. Steps §4 me. |
| 5 | English latency decision (PC par re-measure; agar > 3 s to cross-encoder fix) | ⏳ **PC-PENDING** — is VM par dobara napi: staging 7.26 / 4.51 / 8.38 s (median 7.26 s), target < 3 s abhi bhi miss. `RTB_RERANKER=off` flag taiyar hai (§4). |
| 6 | Arabic garbling + relevancy 0.42 — accept ya fix ka faisla | ⏳ **PENDING (Fahad ka faisla)** — fix = PDFs logical-order Arabic se dobara banana + BGE-M3; dono abhi nahi hue. |
| 7 | Full 20-question eval production env par | ⏳ **PC-PENDING** — staging me limit=3 chala tha (faithfulness 1.00, recall 1.00, relevancy 0.6118). Poora 20-sawal eval §4 ke steps se PC par chalega. |
| 8 | Tokens localStorage → httpOnly cookie | ⏳ **PENDING — risk accept karna hoga ya banana hoga.** Tokens abhi bhi localStorage me hain (Sprint 3 se). Localhost-only demo ke liye risk kam hai (koi public URL nahi, koi third-party script nahi), lekin ye production ki sab se bari baqi kamzori hai — Monitoring phase se pehle ya us ke sath karna chahiye. |
| 9 | Staging smoke 22/22 PASS | ✅ DONE (dobara chalaya — §7) |
| 10 | Fresh venv bcrypt 4.0.1 + pytest 81/81 | ✅ DONE (§7) |

**Items 3–8 PC par ya Fahad ke faisle par pending hain — unko DONE
mat samjho.** Production is liye "local production" hai: hardening
poori hai, lekin asal LLM, PgVector aur poora eval PC par baqi hai.

## 3. Windows PC par chalana (PowerShell) — step by step

**Zaroorat:** Python 3.12+, Node.js 20+, PostgreSQL (optional —
PgVector test ke liye). Docker **nahi** chahiye.

```powershell
# 1. Project folder kholo
cd riyadh-trust-bank-intelligence

# 2. Dev/staging band karo (ports :8000/:3000 production ke hain)
.\scripts\production_stop.ps1   # kuch chal raha ho to band karta hai

# 3. Production setup (pehli dafa; 5-10 minute — venv + packages + index + build)
#    Agar Activate.ps1 error de to pehle ye chalao:
#    Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
.\scripts\production_setup.ps1

# 4. Pehla admin banao (demo users NAHI bante — ye lazmi hai)
python scripts\create_admin.py --email you@bank.local
#    Password poochega (min 8 chars, 1 letter + 1 digit). Demo email
#    (admin@rtb.local) mana hai — woh production me kabhi login nahi karega.

# 5. Production API start karo — Terminal 1 (foreground, Ctrl+C se band)
.\scripts\production_start.ps1
# Check: http://127.0.0.1:8000/api/v1/health
#   -> {"success": true, "data": {"status": "ok", "environment": "production", ...}}

# 6. Web UI start karo — Terminal 2
.\scripts\production_start_web.ps1
# Open: http://localhost:3000  (Sign In page — demo accounts NAHI dikhenge)

# 7. Smoke test — Terminal 3 (API chalte hue)
python scripts\production_smoke.py
#   -> 18/18 PASS hona chahiye

# 8. Backup (pehli dafa + har upgrade se pehle)
python scripts\backup.py
```

Dobara setup karna ho (fresh data): `.\scripts\production_setup.ps1 -Fresh`
Setup + start ek saath: `.\scripts\production_setup.ps1 -Start`
Linux (is VM jaisa): `./scripts/production_setup.sh` / `./scripts/production_start.sh` /
`./scripts/production_start_web.sh` / `python scripts/production_smoke.py` — same steps.
Venv `~/rtb-prod-venv` me banta hai (project ke andar nahi).

**Admin login:** wohi email/password jo step 4 me banaya tha.
Naye users Sign Up se bante hain (hamesha Customer Service role);
zyada access Admin panel se role badal kar deta hai.

## 4. Fahad ke PC par karne wale steps (PC-only — is VM par NAHI hue)

Ye checklist PC par poori karni hai. Har item ke saath command di hai:

- [ ] **Ollama + llama3.1:8b install karo (Windows):**
  1. https://ollama.com/download se Ollama Windows installer chalao.
  2. `ollama pull llama3.1:8b` (pehli dafa ~4.7 GB download — waqt lagega).
  3. `.env.production` me line uncomment karo: `OLLAMA_HOST=http://127.0.0.1:11434`
  4. API restart karo. Phir chat karo — jawab ke `generation_mode` me
     `ollama` aana chahiye (extractive-fallback ki jagah).
  5. Check: `curl http://127.0.0.1:11434/api/tags` — model list me
     `llama3.1:8b` dikhna chahiye.
- [ ] **PgVector test (PostgreSQL port 5432):**
  1. PostgreSQL chal raha ho to: `createdb rtb_intelligence_prod`
  2. `.env.production` me SQLite line comment karo, ye uncomment karo:
     `DATABASE_URL=postgresql://postgres:<password>@localhost:5432/rtb_intelligence_prod`
  3. `python scripts\seed_users.py --postgres` — sirf mirror hai, asal store
     abhi bhi JSON hai (Design ka Postgres users table future deployment
     ke liye hai). PgVector store ko `RTB_USE_PGVECTOR=1` se on karke
     `python scripts\index_chunks.py` dobara chalao, phir search test:
     `python scripts\search_test.py` — 3/3 PASS hona chahiye.
  4. Agar Postgres na chale to SQLite wala setup hi production hai —
     app bina Postgres ke chalta hai (health me `database` batata hai).
- [ ] **English latency dobara napo + cross-encoder faisla:**
  1. Pehle normal mode me 3 English sawal poocho, waqt napo
     (smoke test bhi 3 timed chats deta hai).
  2. Phir `.env.production` me `RTB_RERANKER=off` set karo, API restart
     karo, wohi 3 sawal dobara poocho.
  3. Faisla: agar `off` par latency < 3 s ho aur jawab abhi bhi sahi
     citations ke sath aaye, to production me `off` hi rakho (relevancy
     par farq check karo — eval se). Agar `off` par jawab kharab ho,
     to `auto` wapas karo aur 4–8 s accept karo (portfolio demo me
     likh do ke cross-encoder ki wajah se hai).
- [ ] **Poora 20-sawal eval production data par:**
  `python scripts\run_eval.py` (Admin token chahiye — ~2 minute).
  Targets: faithfulness ≥ 0.85, context_recall ≥ 0.80,
  answer_relevancy ≥ 0.85 (MiniLM ki wajah se 0.42–0.61 expected hai —
  ye BGE-M3 + asal LLM se hi theek hoga; eval report me waisa hi likho).
- [ ] **Arabic garbling faisla:** Arabic jawab me numbers/clauses galat
  order me aate hain (Sprint 1 se known). Fix = source PDFs ko
  logical-order Arabic se dobara banana (`scripts/generate_docs.py`).
  Ya accept karo aur portfolio me limitation ke tor par likh do.
- [ ] **httpOnly cookies (checklist item 8):** tokens abhi localStorage
  me hain. Fix ke liye backend ko `Set-Cookie: HttpOnly` se token dena
  hoga aur frontend ko `credentials: 'include'` se bhejna hoga — ye
  Monitoring phase se pehle ka kaam hai. Localhost-only demo me risk
  kam hai, lekin "production-ready" ke daawe ke liye ye baqi hai.
- [ ] **Backup schedule:** hafte me ek dafa `python scripts\backup.py`
  chalao (ya Task Scheduler se). Backups `backups/` me rehte hain
  (last 7). `.env.production` ka backup ALAG se rakho (wo zip me
  nahi jata — secret leak se bachne ke liye) — ek safe jagah par
  copy kar ke rakho, warna secret kho gaya to saare tokens invalid
  ho jayenge (dobara secret banao to purane login dobara karne honge).

## 5. Backup & restore + rollback + runbook

### Backup
```powershell
python scripts\backup.py            # backups\rtb-prod-backup-YYYYMMDD-HHMMSS.zip
```
Zip me hota hai: `users.json`, `audit.jsonl`, conversations, feedback,
refresh tokens, docs manifest, chunks, vector store. **`.env` files
kabhi zip me nahi jate** (secret alag se sambhalo).

### Restore
```powershell
.\scripts\production_stop.ps1
python scripts\restore.py --backup backups\rtb-prod-backup-20261106-120000.zip --force
.\scripts\production_start.ps1
```
`--force` ke baghair restore mana hai (data-prod/ pehle se hai).
Restore se pehle hamesha pre-restore backup banta hai
(`backups\rtb-pre-restore-<stamp>.zip`) — galat restore bhi wapas
ho sakta hai.

### Rollback (production se staging/dev par wapas)
1. Production band karo: `.\scripts\production_stop.ps1`
2. Staging chalao: `.\scripts\staging_start.ps1` (API :8001) +
   staging web `:3001` — staging data (`data-staging/`) production
   se kabhi nahi mila, waisa ka waisa hai.
3. Code rollback: is version se pehle wala zip
   `Project-1-Frontend-v0.7.zip` se restore karo (v0.7 code wahi hai
   jo live smoke 13/13 pass tha). Production-only additions
   (hardening/scripts) us zip me nahi hain — rollback ke baad dobara
   v0.8 setup chalana hoga.
4. Secret leak hua to: `.env.production` delete karo, dobara setup
   chalao — naya random secret ban jayega. **Purane tokens turant
   invalid ho jayenge** (sab users dobara login karenge) — yehi
   sahi behavior hai. `.env.production` kabhi git ya zip me nahi jata.

### Runbook — masla ho to kya karein
| Masla | Kya karein |
|---|---|
| API start nahi hota: "PRODUCTION REFUSED TO START" | Message parho — ya to SECRET_KEY weak/placeholder hai (setup dobara chalao ya `python -c "import secrets; print(secrets.token_urlsafe(64))"` se naya banao), ya CORS me `*` hai (sirf `http://localhost:3000` rakho). |
| Port 8000 busy ("address already in use") | Dev ya purani production abhi bhi chal rahi hai. `.\scripts\production_stop.ps1` chalao, phir dobara start karo. |
| Login page par "Demo accounts" dikh rahe hain | Production API nahi chal rahi — browser staging/dev API se baat kar raha hai. Check karo ke `:8000` par environment `production` hai (`/api/v1/health`). |
| Login 429 "Too many attempts" | 5 ghalat password ek minute me — 60 second ruko, phir koshish karo. (Admin bhi is se nahi bachta — brute-force rokne ke liye hai.) |
| Chat slow hai (English 4–8 s) | Known — cross-encoder + RAM. §4 ka `RTB_RERANKER=off` test karo. |
| Server band ho gaya (crash) | Terminal me error dekho, phir `.\scripts\production_start.ps1` se dobara chalao. Data `data-prod/` me safe hai — restart se kuch nahi mit-ta. Agar data kharab lage to backup se restore karo (upar). |
| Users bhool gaye password | Abhi password reset flow nahi hai (FRONTEND.md §11). Admin `scripts/create_admin.py --email <same-email> --force` se user dobara bana sakta hai (purana role khatam ho jayega — phir Admin panel se role dobara set karo). |
| Health check karna ho | `python scripts\healthcheck.py` — exit 0 = healthy, 1 = masla hai. |

### Monitoring hooks (Monitoring phase ke liye taiyar)
- `/api/v1/health` extended hai (§1 item 11) — uptime, vector store,
  embeddings, generation mode sab batata hai.
- `scripts/healthcheck.py` exit 0/1 deta hai — Windows Task Scheduler
  ya cron se har 5 minute chalao aur fail hone par alert karo.
- Logs: uvicorn console par likhta hai (terminal me). File logging /
  rotation abhi nahi hai — Monitoring phase me `logs/` + rotation
  aayega. Tab tak API terminal ko band mat karo (us me logs hain).
- Koi external monitoring service nahi (budget $0).

## 6. v0.8 me kya badla (vs v0.7)

- `backend/app/core/config.py`: version **0.8.0**; `demo_accounts_enabled`
  (`RTB_DEMO_ACCOUNTS`), `debug`, `reranker_mode` (`RTB_RERANKER`);
  `validate_production_settings()` — production fail-fast.
- `backend/app/core/rate_limit.py` (NEW): in-memory sliding window
  (login 5 failed/min, register 3/min, per IP+email, 429 + Retry-After).
- `backend/app/core/users.py`: `seed_users()` demo flag off ho to kuch
  nahi karta; `DEMO_EMAILS` set.
- `backend/app/api/v1/auth.py`: demo login block + rate limiting
  (login/register), 429 envelope.
- `backend/app/api/v1/documents.py`: 10 MB upload limit (streaming,
  413 + partial delete).
- `backend/app/main.py`: security headers middleware; extended `/health`
  (`_health_extras()` — file reads only).
- `backend/app/services/retrieval.py`: `RTB_RERANKER=off` support.
- `frontend/src/pages/Login.tsx`: demo section `/health` se gate;
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

## 7. Is VM par live verification (2026-11-06, asal output)

### Fresh prod venv
- `~/rtb-prod-venv` — `backend/requirements.txt` se banaya.
- **bcrypt 4.0.1** ✓ (TESTING BUG-1 pin), fastapi 0.115.0, torch 2.15.0+cpu.
- Note: pehli setup koshish `.env.production` ki aik line par fail hui —
  `DATABASE_URL=<redacted>` (unquoted `<`/`>`) shell sourcing me
  syntax error deta hai. Fix: value quotes me ki
  (`DATABASE_URL="sqlite:///./rtb_intelligence_prod.db"`); PowerShell
  loaders bhi quotes strip karte hain. Dobara setup chala to **DONE**.

### Production setup
- `.env.production` bana, fresh 64-char SECRET_KEY generate hua (gitignored).
- `data-prod/`: 8 PDFs copy → ingestion **15 chunks** → index
  (all-MiniLM-L6-v2, 384-dim — BGE-M3 wahi honest fallback).
- **Demo users seed NAHI hue** — setup ke baad `data-prod/users.json`
  maujood hi nahi thi (pehle admin banane se pehle check kiya).
- Frontend prod build **PASS** (vite 5.4.21, 47 modules, 2.47 s,
  `dist/` — bundle me `127.0.0.1:8000` baked in, verify kiya).

### create_admin
- `prod-admin@rtb.local` → ADMIN bana ✓.
- Demo email `admin@rtb.local` → **refused** ("demo account address") ✓.
- Duplicate email → **refused** ("already exists — use --force") ✓.

### Pytest (staging venv, dev defaults)
- **81 passed, 0 failed** (69 purane + 12 naye `tests/test_production.py`).
  Rate limiting ne purane tests nahi tode (limiter per IP+email hai,
  sirf failed logins ginta hai).

### Live production API (:8000, ENV=production)
Health (asal output):
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
**koi `server` header nahi** (uvicorn `--no-server-header`) ✓.
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
| 18 | smoke user cleanup (data-prod se delete) | PASS |

Pehli smoke run 17/18 thi — RBAC check ka **ek FAIL meri smoke
script ki ghalti tha, app ki nahi**: script ne `data.mode` parha jo
field maujood hi nahi (sahi field `generation_mode` hai), aur staging
se alag sawal poocha tha ("AML policy for high-risk customers?").
Us sawal par asal jawab dekha: **5 citations, sab RETAIL**
(KYC/Loan/Account Opening) — **koi COMPLIANCE citation nahi, koi
leak nahi**. Wajah: KYC Policy me high-risk customers ka zikr hai,
is liye allowed retrieval strong tha aur RBAC-blocked detector
trigger nahi hua. Staging wala sawal ("What is the AML reporting
threshold?") production me bhi **refuse** hota hai (dobara smoke:
18/18 PASS). Ye detector ka pehle se maujood, sawal par munhasir
behavior hai (Sprint 4) — production regression nahi. Lekin note
karo: **RBAC refusal har AML-jaisi phrasing par guaranteed nahi
hai** — jo sawal RETAIL content se overlap kare (jaise high-risk
customers), us ka grounded RETAIL-only jawab milta hai, refusal
nahi. Citation me kabhi disallowed document nahi aata — ye security
property har test me qaim rahi (23 RBAC unit tests + journeys +
smoke).

### Upload limit (live, curl)
- Admin token se 11 MB PDF upload → **HTTP 413** ("File too large —
  maximum upload size is 10 MB"), file disk par save **nahi** hui,
  admin ko documents abhi bhi 8 dikhte hain ✓.

### Backup / restore (live)
- `python scripts/backup.py` → `backups/rtb-prod-backup-20261105-215752.zip`
  (**17 files, 0.34 MB**) ✓.
- Restore test (alag dir `/tmp/rtb-restore-test` me, data-prod ko
  chhede baghair): **17 files restore** hue, users me sirf
  `prod-admin@rtb.local` ✓. Test dir phir delete kar di.

### Frontend preview (:3000)
- `npx vite preview --port 3000` → `http://localhost:3000/` **HTTP 200** ✓.
- Bundle me `demo_accounts_enabled` gating + `127.0.0.1:8000` verify kiya ✓.

### Regression — staging smoke dobara
- Staging API :8001 + `scripts/staging_smoke.py` → **22/22 PASS**
  (pehle run 21/22 tha — sirf hardcoded version pin 0.6.0 fail hua
  tha, version ab 0.8.0 hai; pin update kar ke dobara chalaya to
  22/22). English latency dobara napi: **7.26 / 4.51 / 8.38 s,
  median 7.26 s** — target < 3 s abhi bhi miss (is VM par).
  Dev `data/audit.jsonl` staging smoke se untouched ✓.

## 8. Production ki honest limits (ye sab pehle jaisa hi hai)

1. **English latency 4–8 s** — target < 3 s miss (is VM par).
2. **Generation extractive-fallback** — is VM par Ollama nahi hai.
3. **Embeddings MiniLM (384-dim)** — BGE-M3 fallback.
4. **Arabic visual-order garbling** aur **relevancy 0.42–0.61**.
5. **Tokens localStorage me** — httpOnly cookie abhi baki hai (item 8).
6. **SQLite file inert hai** — asal stores JSONL files hain; PgVector
   test PC par baqi hai.
7. **Rate limiter in-memory, per-process hai** — production single
   worker chalata hai, is liye limit qaim rehti hai. `--workers > 1`
   mat chalao (shared store nahi hai).
8. **RBAC-blocked refusal sawal par munhasir hai** (§7 — leak kabhi
   nahi, lekin har AML-jaisi phrasing par refusal nahi milta).
9. **Koi file logging / rotation nahi** — logs API terminal par hain.
10. **Koi HTTPS nahi** — localhost-only demo hai; public URL par
    chalane se pehle reverse proxy + TLS + httpOnly cookies lazmi hain.
