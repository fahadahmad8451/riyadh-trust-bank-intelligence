# Staging — Riyadh Trust Bank Enterprise Intelligence Platform (v0.6)

**Status: Staging DONE & verified on this VM (2026-11-06).**
Testing ka faisla tha **CONDITIONAL GO** (docs/TESTING.md) — Staging us ka agla step hai.
Koi naya feature nahi bana; sirf environment, config aur scripts.

## Staging kya hai — aur kya NAHI hai

**Hai:** wahi code jo dev me hai, lekin alag environment me — alag ports, alag
data, DEBUG off, fresh JWT secret. Production jaisa behave karne ki koshish,
bina Docker aur bina paid cloud ke (budget $0).

**NAHI hai:**
- Koi cloud deployment nahi, koi public URL nahi — sab kuch `localhost` par hai.
- Koi asal user nahi — sirf 3 demo accounts (neeche).
- Koi asal customer data nahi — wahi 8 synthetic PDFs.
- Production nahi — Production ke liye promotion checklist (neeche) poora hona zaroori hai.

## Port map (dev vs staging)

| Cheez | Dev | Staging |
|---|---|---|
| API | http://127.0.0.1:8000 | **http://127.0.0.1:8001** |
| Web | http://localhost:3000 | **http://localhost:3001** |
| Data dir | `data/` | **`data-staging/`** |
| Database file | `rtb_intelligence.db` (SQLite, inert — neeche dekho) | `rtb_intelligence_staging.db` |
| JWT secret | dev default (`.env`) | fresh random (`.env.staging`, gitignored) |
| Frontend build | `frontend/dist/` | `frontend/dist-staging/` |

Dev aur staging **ek saath** chal sakte hain — ports aur data alag hain.

## v0.6 me kya badla (vs v0.5)

- `backend/app/core/paths.py` (NEW): `data_dir()` — `RTB_DATA_DIR` env var se
  data dir milta hai (default `data/`). Staging `data-staging/` use karta hai.
- `backend/app/core/config.py`: version **0.6.0**; `cors_origins` setting
  (default `http://localhost:3000,http://localhost:3001`).
- `backend/app/main.py`: CORS middleware (staging web :3001 se direct API
  calls ke liye zaroori).
- `frontend/src/api/client.ts`: `VITE_API_URL` support — staging build me
  API base `http://127.0.0.1:8001` bundle me baked hota hai; dev me khaali
  rehta hai to calls pehle ki tarah Vite proxy (`:8000`) se jati hain.
- `frontend/src/vite-env.d.ts` (NEW): `vite/client` types — is ke baghair
  `import.meta.env` par `tsc` error deta tha (staging build fail hota tha).
- `frontend/vite.config.staging.ts` (NEW): port 3001, proxy → :8001,
  output `dist-staging/` (dev `dist/` untouched).
- `frontend/.env.staging` (NEW): `VITE_API_URL=http://127.0.0.1:8001`.
- `.env.staging.example` (NEW): staging env template (secret placeholder).
- `scripts/staging_setup.sh` + `scripts/staging_setup.ps1` (NEW):
  fresh venv → pip install → fresh JWT secret → `data-staging/` banao
  (PDFs copy + ingestion + seed users + index).
- `scripts/staging_start.sh` + `scripts/staging_start.ps1` (NEW):
  staging API :8001 start karo.
- `scripts/staging_smoke.py` (NEW): 22-check smoke test.
- `tests/test_health.py`: version assertion 0.5.0 → 0.6.0 (version bump
  ke sath test update — behavior change nahi).
- README.md: status + Staging section.
- `.gitignore`: `.env.staging`, `data-staging/`, `frontend/dist-staging/`.

## Windows PC par chalana (PowerShell) — step by step

**Zaroorat:** Python 3.12+, Node.js 20+, PostgreSQL (optional — staging
SQLite file par bhi chalta hai; PgVector test ke liye Postgres chahiye).
Docker **nahi** chahiye. Ollama **nahi** chahiye (bina is ke extractive mode chalta hai).

```powershell
# 1. Project folder kholo
cd riyadh-trust-bank-intelligence

# 2. Staging setup (pehli dafa; 5-10 minute — venv + packages + index)
#    Agar Activate.ps1 error de to pehle ye chalao:
#    Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
.\scripts\staging_setup.ps1

# 3. Staging API start karo — Terminal 1 (foreground, Ctrl+C se band)
.\scripts\staging_start.ps1
# Check: http://127.0.0.1:8001/api/v1/health
#   -> {"success": true, "data": {"status": "ok", "environment": "staging", "version": "0.6.0"}}

# 4. Smoke test — Terminal 2
python scripts\staging_smoke.py
#   -> 22/22 PASS hona chahiye

# 5. Staging frontend — Terminal 3
cd frontend
npm install
npm run build -- --mode staging --config vite.config.staging.ts
npx vite preview --port 3001 --config vite.config.staging.ts
# Open: http://localhost:3001  (login page; demo accounts neeche)
```

Dobara setup karna ho (fresh data): `.\scripts\staging_setup.ps1 -Fresh`
Setup + start ek saath: `.\scripts\staging_setup.ps1 -Start`

Linux (is VM jaisa): `./scripts/staging_setup.sh` / `./scripts/staging_start.sh` —
same steps. Venv `~/rtb-staging-venv` me banta hai (project ke andar nahi).

**Demo accounts (DEMO ONLY — Production se pehle passwords badlo):**
admin@rtb.local / Admin123! (ADMIN) · compliance@rtb.local / Compliance123!
(COMPLIANCE_OFFICER) · service@rtb.local / Service123! (CUSTOMER_SERVICE)

## Is VM par live verification (2026-11-06, asal output)

### Fresh venv
- `~/rtb-staging-venv` — `backend/requirements.txt` se banaya.
- **bcrypt 4.0.1** ✓ (TESTING BUG-1 pin — passlib bcrypt ≥ 4.1 ke sath tootta hai).
- fastapi 0.115.0, sentence-transformers 3.1.1, torch 2.15.0+cpu.
- Note: pehli koshish me PyPI se torch wheel download fail hua (network stall,
  165/539 MB) — setup scripts ab pehle CPU-only torch PyTorch CPU index se
  install karte hain, phir baqi requirements. `TMPDIR` bhi home par set hai
  (is VM ka /tmp sirf 512 MB hai, torch wheel ~540 MB).

### Pytest (fresh staging venv, dev defaults)
- **57 passed, 0 failed.** Pehle run me 56 pass + 1 fail tha — fail sirf
  `test_health` me hardcoded version "0.5.0" tha; 0.6.0 bump ke sath test
  update kiya, phir 3/3 health tests pass. (Poora suite dobara nahi chalaya —
  baqi 56 pehle hi pass the aur fail ki wajah sabit thi.)

### Staging setup
- `.env.staging` bana, fresh random SECRET_KEY generate hua (gitignored).
- `data-staging/`: 8 PDFs copy → ingestion **15 chunks, avg 528.1 tokens**
  (dev jaisa hi) → 3 demo users seed → vector store index (15 chunks,
  all-MiniLM-L6-v2, 384-dim — BGE-M3 wahi honest fallback, Sprint 1 jaisa).
- Dev `data/` ko staging setup ne **nahi** chhua (audit.jsonl mtime
  2026-11-05 20:19, setup se pehle ka).

### Smoke test — `scripts/staging_smoke.py` → **22/22 PASS, 0 FAIL**

| # | Check | Result |
|---|---|---|
| 1 | health 200 + environment=staging | PASS (version 0.6.0) |
| 2 | health version 0.6.0 | PASS |
| 3 | metrics environment=staging | PASS |
| 4–6 | login admin / compliance / service | PASS (roles sahi) |
| 7 | wrong password → 401 | PASS |
| 8 | no-token chat → 401 | PASS |
| 9 | EN chat (warm-up) answered + cited | PASS (top: KYC Policy, 25.7 s — pehli call, models load) |
| 10–12 | EN chat timed ×3 (latency re-measurement) | PASS — **6.78 s / 4.50 s / 8.22 s**, median **6.78 s** |
| 13 | AR chat (compliance) AML cited | PASS (0.33 s, top: AML Policy) |
| 14 | RBAC: service AML → refused, 0 citations | PASS (mode: rbac-refusal) |
| 15–16 | documents list: service = 4, admin = 8 | PASS |
| 17–18 | feedback thumbs-up + feedback-stats | PASS ("Shukriya, feedback mil gaya.", total=1) |
| 19 | eval/results 200 | PASS (us waqt koi stored run nahi tha) |
| 20 | audit-logs contain LOGIN entries | PASS (13 entries) |
| 21 | staging data lives in data-staging/ | PASS (users.json + audit.jsonl) |
| 22 | dev data/audit.jsonl untouched by smoke | PASS (mtime + size before/after identical) |

### English latency re-measurement (Testing condition #1)
- **3 warm EN chats: 6.78 s, 4.50 s, 8.22 s — median 6.78 s.**
- Testing me tha 4.3–8.4 s steady-state — **koi behtri nahi, wahi range hai.**
  Target < 3 s abhi bhi **miss** hai is VM par.
- Wajah wahi hai jo Testing me likhi thi: cross-encoder reranker + RBAC
  probe, RAM-starved VM (~1 GB free). AR chat 0.33 s hai (score-based
  reranker, cross-encoder nahi) — is se saaf hai ke English latency ka
  bottleneck cross-encoder hai.
- **Asal faisla Fahad ke PC par hoga** — wahan RAM zyada hai; agar wahan
  bhi > 3 s rahe to cross-encoder ko sirf top-k par lagana ya band karna
  Production promotion se pehle decide karna hoga.

### Eval (staging, limit=3, 21.8 s)
- faithfulness **1.00** ✓ (target ≥ 0.85), context_recall **1.00** ✓
  (target ≥ 0.80), answer_relevancy **0.6118** ✗ (target ≥ 0.85 —
  wahi MiniLM English-only limit; Sprint 4 ke 20-sawal eval me 0.4172 tha),
  top-doc accuracy **1.00** (3/3), latency p50 **8.31 s** / p95 **9.58 s**.
- Report `data-staging/eval_results.json` me save hui; `GET /eval/results`
  ab stored run deta hai. (Poora 20-sawal eval staging me nahi chalaya —
  3-sawal run pipeline prove karta hai; poora eval Production se pehle
  Fahad ke PC par chalega.)

### Frontend staging build + preview + CORS
- `npm run build -- --mode staging` **PASS** (vite 5.4.21, 38 modules,
  `dist-staging/` — JS bundle me `127.0.0.1:8001` baked in, verify kiya).
- Dev build bhi **PASS** (client.ts change ne dev nahi toda).
- Preview `http://localhost:3001/` **HTTP 200** — staging bundle serve hota hai.
  (Note: preview `[::1]:3001` par listen karta hai — `127.0.0.1:3001` se
  curl fail hota hai, `localhost:3001` se chalta hai.)
- CORS: preflight + real GET dono par
  `access-control-allow-origin: http://localhost:3001` ✓.

## Staging ki honest limits (ye sab dev jaisa hi hai — staging ne kuch nahi badla)

1. **English latency 4–8 s** — target < 3 s miss (upar dekho). Fahad ke PC
   par dobara napna hai.
2. **SQLite file inert hai:** staging `DATABASE_URL` alag file ki taraf
   point karta hai (`rtb_intelligence_staging.db`), lekin runtime par
   **koi .db file banti hi nahi** — `init_db()` sirf Postgres paths se
   call hota hai. Dev me bhi koi .db file nahi hai. Asal stores JSONL
   files hain (`data-staging/`). PgVector ka asal test Fahad ke PC par
   Postgres (port 5432) se hoga — Promotion checklist dekho.
3. **Embeddings MiniLM (384-dim)** — BGE-M3 (1024-dim) is VM par download
   nahi hua (Sprint 1 se wahi fallback); config me record hai.
4. **Generation extractive-fallback** — is VM par Ollama nahi hai; jawab
   sirf retrieved chunks se banta hai (response me mode likha hota hai).
   Asal LLM ke liye Windows par Ollama + llama3.1:8b chahiye.
5. **Arabic visual-order garbling** aur **relevancy 0.42–0.61** — Sprint 4
   se known limitations, staging me bhi wahi hain.
6. **Tokens localStorage me** (demo) — Production me httpOnly cookie chahiye.
7. **Dev data ko pytest ne chhua:** is session me full pytest fresh venv
   me dev defaults par chala (har sprint me aisa hi hota hai) — us ne
   `data/conversations.jsonl` aur `data/eval_results.json` update kiye.
   **Staging traffic ne dev data nahi chhua** — smoke test ne audit.jsonl
   ka before/after snapshot le kar prove kiya, aur staging ki tamam
   files `data-staging/` me hain.

## Promotion checklist — Production se pehle ye sab TRUE hona chahiye

| # | Item | Status |
|---|---|---|
| 1 | Demo passwords badle gaye (3 accounts) | ⏳ PENDING — Fahad Production par karega |
| 2 | JWT secret set (Production ke liye alag, lamba random) | ⏳ PENDING — `.env.staging` wala sirf staging ke liye hai |
| 3 | Ollama running + llama3.1:8b (asal LLM answers) | ⏳ PENDING — Windows installer se |
| 4 | PgVector tested on Fahad's PC (port 5432) | ⏳ PENDING — is VM par Postgres nahi tha |
| 5 | English latency decision (Fahad ke PC par re-measure; agar > 3 s to cross-encoder fix) | ⏳ PENDING — is VM par 4.5–8.2 s |
| 6 | Arabic garbling + relevancy 0.42 — accept ya fix ka faisla | ⏳ PENDING |
| 7 | Full 20-question eval staging/Production env par | ⏳ PENDING — staging me sirf limit=3 chala |
| 8 | Tokens localStorage → httpOnly cookie (ya risk accept) | ⏳ PENDING |
| 9 | Staging smoke 22/22 PASS (is VM par) | ✅ DONE |
| 10 | Fresh venv bcrypt 4.0.1 + pytest 57/57 | ✅ DONE |

**Jab tak 1–8 pending hain, Production mat karo.** Staging sirf demo aur
verification ke liye hai.

## Rollback plan

- **Staging band karo:** API terminal me Ctrl+C; preview terminal me Ctrl+C.
  Kuch uninstall nahi karna — staging sirf processes + files hain.
- **Dev bilkul untouched hai:** dev `data/`, dev venv aur dev ports (:8000/:3000)
  staging se alag hain. Staging band karne ke baad dev waisa hi chalega
  jaisa pehle chalta tha.
- **Staging data wipe:** `rm -rf data-staging/` (Linux) ya
  `Remove-Item -Recurse data-staging\` (PowerShell), phir
  `./scripts/staging_setup.sh --fresh` se dobara banao.
- **Code rollback:** is version se pehle wala zip
  `Project-1-Sprint4-v0.5.zip` se restore karo (v0.5 code wahi hai jo
  Testing me CONDITIONAL GO mila tha).
- **Secret leak hua to:** `.env.staging` delete karo, dobara setup chalao —
  naya random secret ban jayega. `.env.staging` kabhi git ya zip me nahi jata.
