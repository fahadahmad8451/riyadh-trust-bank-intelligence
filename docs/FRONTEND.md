# Frontend Redesign — Professional Banking UI (v0.7)

**Status: DONE & build-verified + live-verified (2026-11-06).** Complete visual + UX redesign of the
Riyadh Trust Bank Enterprise Intelligence Platform frontend, plus the real Sign-Up backend it needs
(`POST /auth/register`, auto-login, `CUSTOMER_SERVICE` default) and Admin role management
(`PUT /admin/users/{email}/role`). No new npm dependencies. Work confined to `frontend/`,
`backend/app/api/v1/auth.py`, `backend/app/api/v1/admin.py`, `backend/app/core/users.py`,
`tests/test_auth_register.py`, version bump 0.7.0, and this doc.

## 1. Design system

- **Palette:** deep navy `#0b2c4a` (primary), gold `#c9a227` (accent), teal `#0e7c7b`
  (secondary). Light theme throughout — clean banking look.
- **Tokens:** `frontend/tailwind.config.js` — `navy` (50–950 scale), `gold` (400/500/600),
  `teal` (100/700/800) + `Inter` / `IBM Plex Sans Arabic` font stack.
- **Base styles:** `frontend/src/index.css` — page background `#f6f8fa`, typing-dot
  bounce animation for the chat indicator, subtle scrollbars.
- **Rules:** no lorem ipsum, no placeholder text. Every number shown is real: **8
  documents, 15 chunks (sections), 24 pages, 3 roles** (from the indexed knowledge
  base, docs/SPRINT1 + STAGING). Anything unknown is fetched from the API or omitted —
  never invented.

## 2. Pages & routes

| Route | Page | Access |
|---|---|---|
| `/` | Landing — hero, features (RAG + citations, RBAC, audit trail, Arabic+English), 3-step "how it works", role section, real stats, footer. Logged-in users are redirected to `/chat`. | Public |
| `/login` | Sign In — email + password, show/hide password, remember-me (persists email in `localStorage`), honest "Forgot password?" (no fake reset flow — it says reset is not available yet, contact the bank admin), inline validation, real backend errors, demo accounts (one click fills AND signs in). | Public |
| `/register` | Sign Up — full name, email, password with live strength meter (length / letter+digit / case mix), confirm password, required terms checkbox. Note: "New accounts start as Customer Service — an Admin can grant more access." Backend 400/409 errors shown as-is. Success auto-logs in → `/chat`. | Public |
| `/chat` | Chat — bubbles, citation cards (title + page + score + department badge), RBAC refusal as an amber warning card, suggested-question chips, animated typing dots, per-user history in `localStorage` (loaded on mount, "New chat" clears), copy-answer button, thumbs up/down feedback (unchanged behaviour). | Signed in |
| `/documents` | Documents — table (title, department badge, sections = `chunk_count`, visible-to roles, version), search box + department filter, Admin upload (file + title + department, real endpoint) and delete with confirm dialog. | Signed in |
| `/audit` | Audit Log — table (time, user, role badge, action, result badge, detail) with action-type dropdown + user search, newest-first pagination (100/page). | ADMIN only |
| `/evaluation` | Evaluation dashboard — CSS bar charts sized from real values, targets shown, per-question table, "Run evaluation" (slow, minutes). | ADMIN only |
| `/admin` | Admin — system status cards (backend health, environment, generation mode from last chat, embeddings model), users table with role-change dropdown + confirm dialog (own row disabled with a note), evaluation dashboard, feedback stats. | ADMIN only |

## 3. App shell & guards

- After login: **sidebar** (Chat, Documents, Audit Log, Evaluation, Admin) + **topbar**
  (user name + role badge + API status + logout). Sidebar collapses to a top nav on
  mobile (hamburger).
- Sidebar hides admin links for non-admins, but that is **not** the enforcement:
  `RequireAdmin` renders a clear **"Admin only"** page for non-admins visiting
  `/admin`, `/audit` or `/evaluation`, and the backend enforces it too (403).
- Unauthenticated users on any app route are redirected to `/login`.
- Toasts (`src/components/Toast.tsx`, provider at the App root) confirm or report
  errors on every data action. `Skeleton.tsx`, `EmptyState.tsx`, `ErrorState.tsx`
  are used on every data page (skeletons while fetching, empty states when lists
  are empty, retry on error).

## 4. Auth flow (text diagram)

```
Visitor
  └─ / ................. Landing (logged in → /chat)
  ├─ /login ............ email+password → POST /api/v1/auth/login
  │                        200 → store tokens (storeSession) → /chat
  │                        401 → "Invalid email or password." shown as-is
  │                     Demo account click → same login call with demo creds
  └─ /register ......... full name + email + password + confirm + terms
                           → POST /api/v1/auth/register
                           201 → auto-login (tokens stored like login) → /chat
                           400 → weak password / bad email / mismatch (as-is)
                           409 → "An account with this email already exists."

Signed-in user
  ├─ token in localStorage (demo setup — see §7 pending items)
  ├─ 401 on any call → one silent refresh via /auth/refresh → retry once
  │   refresh fails → "UNAUTHORIZED" → redirect to /login
  └─ Log out → POST /api/v1/auth/logout {refresh_token} → clear storage → /login
```

## 5. API client changes (`frontend/src/api/client.ts`)

- **Added:** `api.register(fullName, email, password, confirmPassword)`,
  `api.changeUserRole(email, role)`, `api.uploadDocument(file, title?, department?)`
  (multipart `FormData`), `api.deleteDocument(id)`, `api.document(id)`.
- **Added types:** `DocumentRow`, `AuditRow`, `Role`, `ROLES`, helpers `roleLabel()`
  and `rolesForDepartment()` (the SPRINT3 RBAC map, for the Documents "visible to" column).
- **Improved:** `request()` now surfaces the envelope's plain-English `error` string
  instead of the raw JSON body on failure (e.g. 400/403/409 messages shown as-is).
- **Unchanged:** the 401-refresh retry logic, `storeSession`, `logout`, all existing
  endpoints.

## 6. Demo accounts

| Email | Password | Role | Sees |
|---|---|---|---|
| admin@rtb.local | Admin123! | ADMIN | All 8 documents, upload, admin |
| compliance@rtb.local | Compliance123! | COMPLIANCE_OFFICER | RETAIL + COMPLIANCE (6 docs) |
| service@rtb.local | Service123! | CUSTOMER_SERVICE | RETAIL only (4 docs) |

**DEMO ONLY — change these passwords before any real use.**

## 7. Role matrix (enforced in the backend, mirrored in the UI)

| Role | RETAIL | COMPLIANCE | HR | Upload | Admin / Audit / Eval |
|---|---|---|---|---|---|
| Customer Service | ✅ | ❌ | ❌ | ❌ | ❌ |
| Compliance Officer | ✅ | ✅ | ❌ | ❌ | ❌ |
| Admin / Branch Manager | ✅ | ✅ | ✅ | ✅ | ✅ |

Departments: RETAIL — KYC, Account Opening, Personal Loan, Charges & Fees;
COMPLIANCE — AML Policy, SAMA Compliance Summary; HR (Admin only) — HR Leave Policy,
PDPL Data Privacy Summary.

## 8. Build results (2026-11-06, this VM)

```
npm run build
  tsc -b && vite build
  ✓ 47 modules transformed
  dist/index.html 0.63 kB · dist/assets/index-CBJqIXz0.css 19.35 kB
  dist/assets/index-zoECpNyE.js 224.02 kB (gzip 67.77 kB)
  ✓ built in 5.96s — ZERO tsc errors

npm run build -- --mode staging --config vite.config.staging.ts
  ✓ 47 modules transformed
  dist-staging/index.html 0.63 kB · dist-staging/assets/index-CBJqIXz0.css 19.35 kB
  dist-staging/assets/index-DvAUNLWl.js 224.04 kB (gzip 67.79 kB)
  ✓ built in 5.52s — ZERO tsc errors
  Verified: "127.0.0.1:8001" baked into the staging bundle.
```

Preview smoke check: `npx vite preview --port 3001 --config vite.config.staging.ts` →
`http://localhost:3001/` **HTTP 200** (preview stopped afterwards).

## 9. Screenshots (live staging, 2026-11-06 — real browser, Playwright + Chrome for Testing)

Chrome was downloaded from Google's Chrome-for-Testing CDN (the VM's own Chromium refuses to start:
`Hatch WebGL domain policy is required for browser startup`; Playwright's own CDN returns
`GatewayExceptionResponse`). Screenshots are real renders of the staging build at
`http://localhost:3001` — nothing faked.

- `docs/screenshots/01-landing.png` — landing page (hero, real stats 8 / 15 / 24 / 3)
- `docs/screenshots/02-signin.png` — Sign in page (form + demo accounts)
- `docs/screenshots/03-signup.png` — Create account page
- `docs/screenshots/04-chat.png` — Chat dashboard logged in as Admin (sidebar, API online v0.7.0, role badge, suggested questions)

## 10. Live verification (staging :8001 + :3001, 2026-11-06)

Pytest **69 passed, 0 failed** (57 existing + 12 new register/role tests, `tests/test_auth_register.py`).
Live smoke (`/tmp/v07_live_smoke.py`, staging API) **13/13 PASS**:

| # | Check | Result |
|---|---|---|
| 1 | health staging v0.7.0 | PASS |
| 2 | register 201 + auto-login tokens | PASS (role CUSTOMER_SERVICE) |
| 3 | new user default role = CUSTOMER_SERVICE | PASS |
| 4 | duplicate register → 409 | PASS ("An account with this email already exists.") |
| 5 | login with new user | PASS |
| 6 | EN chat answered + cited | PASS (5 citations, extractive-fallback; first call 25.5 s — models loading) |
| 7 | RBAC: new user (service) AML → refused, 0 citations | PASS (rbac-refusal) |
| 8 | admin login | PASS |
| 9 | admin role change → COMPLIANCE_OFFICER | PASS |
| 10 | re-login shows COMPLIANCE_OFFICER | PASS (departments COMPLIANCE, RETAIL) |
| 11 | after role change: AML cited | PASS (top 02-aml-policy.pdf) |
| 12 | documents list (compliance = 6) | PASS |
| 13 | admin users list includes new user | PASS (count 4) |

Browser login flow also verified with Playwright: form login as admin → `/chat` stays on `/chat`,
token + user stored in localStorage.

### Bug found by live browser testing — FIXED (v0.7)
**Login bounce:** after a successful login the app navigated to `/chat` and immediately back to
`/login`. Cause: `App.tsx` rendered `<Navigate to="/login">` from `user` state that was still
`null` — the effect that syncs state from `localStorage` had not run yet, and the Navigate effect
fired first. Fix: `App` now reads the stored session synchronously on every render
(`currentUser = user ?? getStoredUser()`). Rebuilt (dev + staging), re-tested in the browser:
login stays on `/chat`. This bug would have broken Sign In / Sign Up for every user — it was
only caught because the flow was tested in a real browser, not just with curl.

## 11. What is still pending (not built, not hidden)

1. **Password reset** — "Forgot password?" honestly says reset is not available yet;
   a real reset flow (email token or admin reset) is not built.
2. **httpOnly cookies** — tokens still live in `localStorage` (demo setup, same as
   Sprint 3). Production needs httpOnly cookies (promotion checklist item 8).
3. **Demo passwords** must be changed before any real use (promotion checklist item 1).
4. **Embeddings label is honest, not ideal** — the Admin status card shows
   `all-MiniLM-L6-v2 (384-dim)` labelled as the recorded fallback; BGE-M3 (1024-dim)
   is still not available on this VM (SPRINT1).
5. **Generation mode** on the Admin status card comes from the last chat in this
   browser (`localStorage`); if no chat has run yet it says "No chat yet".
6. **English latency** (4–8 s on this VM, target < 3 s) and **answer relevancy**
   (0.42–0.61 vs target 0.85) are unchanged by this redesign — see STAGING.md.
7. **Cosmetic:** the topbar shows the demo admin's name ("Branch Manager (Admin)") next to
   the role label ("Admin — Branch Manager") — the same words twice. Harmless, but the
   seed display names should be cleaned up before a portfolio demo.
