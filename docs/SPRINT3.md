# Sprint 3 — Login, RBAC, Audit Log, Admin UI (v0.4)

Status: DONE & VERIFIED (2026-11-06). No Docker used — local setup only.
Version: backend 0.4.0. Previous: Setup v0.1, Sprint 1 v0.2, Sprint 2 v0.3.
Retrieval/generation quality was NOT changed (Sprint 2 behaviour kept).

## 1. What was built

### Auth — `backend/app/api/v1/auth.py`, `app/core/security.py`
- `POST /api/v1/auth/login` `{email, password}` → access token (JWT,
  HS256, 15 min) + refresh token (JWT, 24 h, with `jti`).
- `POST /api/v1/auth/refresh` → new access token; the refresh token is
  ROTATED (old `jti` revoked, new one issued).
- `POST /api/v1/auth/logout` → revokes the refresh token (`jti` goes
  to `data/token_denylist.json`). Always returns 200, even for a bad
  token — there is nothing left to revoke and the frontend clears its
  stored tokens anyway.
- `GET /api/v1/auth/me` → current user (email, name, role, departments).
- Wrong password / unknown email → 401 with the same message (does not
  leak which one failed). No token / expired token / refresh token used
  as an access token → 401. Access tokens are stateless and cannot be
  revoked — that is why they live only 15 minutes; this is documented
  here, not hidden.
- Passwords: bcrypt (`passlib`), hashes only, in `data/users.json`.
  **Known gotcha, fixed in this sprint:** passlib 1.7.4 breaks with
  bcrypt ≥ 4.1 (`__about__` missing) — `bcrypt==4.0.1` is pinned in
  `backend/requirements.txt`.
- JWT secret comes from `.env` (`SECRET_KEY`). If the dev default is
  in use, the backend logs a warning at startup. Never commit a real
  secret.

### Demo users — `scripts/seed_users.py`, `backend/app/core/users.py`
Users live in `data/users.json` (gitignored, excluded from the zip) —
no PostgreSQL needed. Seed with `python scripts/seed_users.py`
(`--force` to overwrite, `--postgres` to also mirror into the
Postgres `users` table when reachable).

| Email | Password | Role | Sees |
|---|---|---|---|
| admin@rtb.local | Admin123! | ADMIN | Everything (RETAIL + COMPLIANCE + HR), upload, admin |
| compliance@rtb.local | Compliance123! | COMPLIANCE_OFFICER | RETAIL + COMPLIANCE |
| service@rtb.local | Service123! | CUSTOMER_SERVICE | RETAIL only |

⚠️ **DEMO ONLY — change these passwords before any real use.** They
are in the docs because a portfolio demo must be runnable by a
reviewer; they are not real credentials.

### RBAC — `backend/app/core/rbac.py` (the enforcement point)
RBAC is enforced in the BACKEND, before ranking — never only by
hiding things in the UI:

| Role | RETAIL docs | COMPLIANCE docs | HR docs | Upload | Admin |
|---|---|---|---|---|---|
| Customer Service | ✅ | ❌ | ❌ | ❌ | ❌ |
| Compliance Officer | ✅ | ✅ | ❌ | ❌ | ❌ |
| Admin / Branch Manager | ✅ | ✅ | ✅ | ✅ | ✅ |

Department mapping (8 synthetic docs):
- RETAIL — KYC Policy, Account Opening Policy, Personal Loan Policy, Charges & Fees Schedule
- COMPLIANCE — AML Policy, SAMA Compliance Summary
- HR (ADMIN only) — HR Leave Policy, PDPL Data Privacy Summary

**PDPL correction:** Sprint 1 stored the PDPL summary as COMPLIANCE
in the manifest, the vector-store metadata and `ingestion.py`. Sprint
3 corrects it to HR: in this demo the PDPL summary is an HR-owned
internal privacy policy, so only ADMIN sees it. The correction was
applied to all four places, and `rbac.py` reads the department from
the live manifest at runtime, so a stale label in any one file
cannot leak the document.

Enforcement points:
- `HybridRetriever.retrieve(..., allowed_departments)` — chunks are
  filtered BEFORE vector search and BEFORE the BM25 index is built
  for the query. A disallowed chunk is never retrieved, reranked,
  cited, or fed to the generator.
- `GET /api/v1/documents` — manifest filtered by role (ADMIN 8 docs,
  Compliance 6, Service 4).
- `GET /api/v1/documents/{id}` — 404 if the document does not exist
  OR the caller may not see it (existence is not leaked).
- `POST /api/v1/documents/upload`, `DELETE /api/v1/documents/{id}` —
  ADMIN only, others get 403 + ACCESS_DENIED audit. Built-in Sprint 1
  synthetic documents cannot be deleted via the API.
- `POST /api/v1/chat` — requires a valid token; response includes
  `rbac_enforced: true`, `role` and `allowed_departments`.
- `GET /api/v1/conversations` — a user sees only their own
  conversations; ADMIN sees all. Cross-user access returns 403.

### Audit log — `backend/app/core/audit.py`
Every LOGIN (success/fail), QUERY, UPLOAD and ACCESS_DENIED is logged
with timestamp + user + role + action + result + resource. Primary
store: `data/audit.jsonl` (one JSON object per line, gitignored,
excluded from the zip). The `audit_logs` DB table is mirrored only
when PostgreSQL is configured and reachable (with the default SQLite
fallback the table is not used — the shared models' pgvector Vector
column cannot be created on SQLite — and the JSONL file is the
record). QUERY entries store only the first 80 characters of the
question, never full PII; 10-digit ID-like numbers are masked.
- `GET /api/v1/admin/audit-logs?limit=100&offset=0` (ADMIN only,
  newest first), `GET /api/v1/admin/users` (ADMIN only, password
  hashes never returned).

### Frontend
- `Login.tsx` — real form + 3 clickable DEMO account buttons; 401
  shown in plain words; on success the token is stored and the user
  goes to /chat.
- `Chat.tsx` — sends `Authorization: Bearer` on every call; 401
  redirects to /login; shows the logged-in user + role badge + which
  departments they can see.
- `Admin.tsx` — real users / documents / audit-log tables from the
  API (no fake rows); non-admin gets the backend's 403, shown
  honestly.
- `App.tsx` — header shows the logged-in user + Logout (revokes the
  refresh token).
- Tokens live in `localStorage` (demo setup). A production deployment
  should use an httpOnly cookie — noted here as a known limitation,
  not silently presented as production-grade.

## 2. How to run on Windows (PowerShell, no Docker)

```powershell
cd riyadh-trust-bank-intelligence
cd backend
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python ..\scripts\seed_users.py
uvicorn app.main:app --reload --port 8000

# Login as admin (new terminal):
curl -X POST http://127.0.0.1:8000/api/v1/auth/login -H "Content-Type: application/json" `
  -d '{"email":"admin@rtb.local","password":"Admin123!"}'
# Copy access_token, then ask an AML question:
curl -X POST http://127.0.0.1:8000/api/v1/chat -H "Content-Type: application/json" `
  -H "Authorization: Bearer <access_token>" `
  -d '{"question":"What is the AML reporting threshold?"}'
```

## 3. Verification (this VM, 2026-11-06)

### Live API (uvicorn, TestClient + curl-style checks)
| Check | Result |
|---|---|
| No-token chat | 401 |
| Wrong password / unknown email | 401 |
| Expired token (exp in the past) | 401 |
| Refresh token used as access token | 401 |
| Admin login → `ADMIN`, departments `[COMPLIANCE, HR, RETAIL]` | 200 |
| Admin `GET /admin/users` | 200, 3 users, no password hashes |
| Admin `GET /documents` | 200, 8 docs |
| Service `GET /documents` | 200, 4 docs, all RETAIL |
| Compliance `GET /documents` | 200, 6 docs, RETAIL + COMPLIANCE |
| Service `GET /documents/02-aml-policy.pdf` | 404 (existence not leaked) |
| Compliance `GET /documents/02-aml-policy.pdf` | 200 |
| Service / Compliance upload | 403 + ACCESS_DENIED audit |
| Service / Compliance `GET /admin/audit-logs` | 403 |
| Refresh → new access token (rotated) | 200 |
| Logout → refresh again | 401 (revoked) |
| **Service asks AML question** | **refused, 0 citations** |
| **Compliance asks AML question** | **AML Policy cited (top)** |
| **Admin asks AML question** | **AML Policy cited (top)** |
| Compliance asks HR-leave question | No HR citation (no HR Leave / PDPL citation) |
| Admin asks HR-leave question | HR Leave Policy cited (top) |
| Service asks HR-leave question | No HR, no COMPLIANCE citation |
| Compliance asks PDPL question | No PDPL citation |
| Service asks KYC question | Answered, citations RETAIL only |

### pytest — full suite: 43 passed, 0 failed
`python -m pytest ../tests/ -v` — 43 passed (health 3 + ingestion 10
+ RAG 7 + RBAC 23). Older tests were updated for auth: health version
0.4.0, chat/documents tests now log in as admin first, the 501 test
now uses the Sprint 4 `/feedback` stub. One test failed on the first
full run and was fixed (it was a test bug, not an app bug — it
asserted every QUERY audit entry was admin's, but the shared audit
log also holds earlier tests' service queries; it now asserts the
admin query is recorded).

### Frontend
`npm install` + `npm run build` in a /tmp copy — **built cleanly in
2.15 s** (38 modules, no TypeScript errors).

### py_compile
All new/changed Python files OK.

### Bugs found by testing (fixed, not hidden)
1. `require_admin` first called `require_roles("ADMIN")(request)`
   directly, which passed FastAPI's `Depends` marker object as the
   `user` argument (`TypeError: 'Depends' object is not
   subscriptable`). Fixed by making `require_admin` a real dependency
   (`user: dict = Depends(get_current_user)` in its own signature)
   with a shared `_deny()` helper. Re-run after the fix — all checks
   above passed.
2. **Wrong data path in `backend/app/core/`**: `rbac.py`, `audit.py`,
   `users.py` and `refresh_tokens.py` used `parents[4]`, which from
   `backend/app/core/` resolves to the project's PARENT folder — so
   `users.json` / `audit.jsonl` / `refresh_tokens.json` were written
   to `~/workspace/projects/data/` instead of the project's `data/`,
   and RBAC read the manifest from a non-existent path (falling back
   to the hardcoded map, so behaviour was still correct). Fixed to
   `parents[3]`, the stray files were moved into the project's
   `data/`, and the full suite was re-run after the fix: **43 passed**.
   (The `api/v1/` files correctly use `parents[4]` — they sit one
   level deeper.)

## 4. Known limitations (honest, for later sprints)
- Tokens in `localStorage` (demo) — httpOnly cookie is the production fix.
- Access tokens cannot be revoked before their 15-minute expiry
  (refresh tokens can). This is standard for short-lived JWTs.
- Audit `audit_logs` DB table is only mirrored on PostgreSQL;
  JSONL is the record otherwise.
- Retrieval/generation unchanged from Sprint 2 (extractive-fallback
  on this VM — Ollama not reachable; Arabic quotes are visual-order
  text). RBAC filtering happens before ranking, so it cannot leak
  through the generator either.
- One quality note (not a leak): when a role asks about a document
  they cannot see, the extractive generator may still compose an
  answer from *allowed* chunks that share words with the question
  (e.g. Compliance asking about leave gets sentences from allowed
  docs). No disallowed citation ever appears — the RBAC guarantee
  holds — but a cleaner "you don't have access to that topic"
  refusal is a Sprint 4 polish item.

## 5. What is NOT built yet
- Sprint 4: RAGAS evaluation, feedback endpoint, SSE streaming,
  multilingual BGE reranker, logical-order Arabic, "no access to
  that topic" refusal polish.
