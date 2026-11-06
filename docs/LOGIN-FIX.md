# Login bounce fix (v0.10.2)

## The problem

After the v0.10.0 httpOnly-cookie change, logging in from a real browser
bounced straight back to the sign-in page:

- The login POST returned **200** and the browser received the
  `Set-Cookie` headers — but the next `/chat` POST returned **401**,
  the refresh POST returned **401**, and the app sent the user back to
  `/login`.
- API clients (curl, pytest, the smoke tests) never showed this:
  `SameSite` cookie rules only apply inside a real browser.

## Root cause

The built frontend baked in `VITE_API_URL=http://127.0.0.1:<api-port>`
while the user opens the page at `http://localhost:<web-port>`.
`localhost` and `127.0.0.1` are different sites, so the request was
cross-site — and a `SameSite=Lax` cookie is **not** sent on a cross-site
`fetch` POST. The login succeeded (the cookie was set), but every later
authenticated call went out without cookies and failed with 401.

Staging had the same shape (`localhost:3001` page vs `127.0.0.1:8001`
API); production too (`localhost:3000` vs `127.0.0.1:8000`).

## The fix (two small changes, no auth behaviour changed)

1. **Same-host API base** — `frontend/src/api/client.ts`
   (`resolveApiBase()`): when `VITE_API_URL` is set, the code keeps its
   protocol, port and path, but replaces its hostname with
   `window.location.hostname` — the host the page was actually opened
   on. So the API is always same-site, whether the user opens
   `localhost` or `127.0.0.1`, and the cookies are sent. When
   `VITE_API_URL` is empty (dev), calls stay relative (`/api/...`) and
   go through the Vite dev proxy as before. If the env value cannot be
   parsed as a URL, it is used unchanged (fail-open).
2. **CORS allows both local host spellings** — `backend/app/core/config.py`
   default and the env files (`.env.production`, `.env.production.example`,
   `.env.staging`, `.env.staging.example`): `http://localhost:3000`,
   `http://127.0.0.1:3000`, `http://localhost:3001`,
   `http://127.0.0.1:3001`. The browser may arrive from either spelling,
   so the API must accept both. Still explicit local origins only — no
   wildcard, and the production fail-fast rules are unchanged.

Nothing else changed: httpOnly cookies, `SameSite=Lax`, 15-minute access
+ 24-hour refresh tokens, rate limits, RBAC — all exactly as before.
No proxy was added (the same-host fix makes it unnecessary).

## Verification (all real, no fakes)

- **Real headless-Chromium browser test, staging** —
  `scripts/browser_login_test.py`: **12/12 PASS** on BOTH
  `http://localhost:3001` and `http://127.0.0.1:3001`. Per origin:
  demo Admin login → `/chat` (no bounce) → `rtb_access` +
  `rtb_refresh` cookies set → chat POST **200, 5 citations** →
  page reload keeps the session (no bounce) → logout → `/login`.
- **Real headless-Chromium browser test, production shape** —
  `scripts/browser_login_prod_test.py`: **6/6 PASS** from
  `http://localhost:3000` (page `localhost`, API `127.0.0.1:8000` —
  the exact shape that bounced before). Demo accounts are OFF in
  production, so the test registered a real user through the UI,
  then chat POST **200, 5 citations**, reload kept the session,
  logout worked. The test user was deleted from `data-prod/users.json`
  afterwards (only `prod-admin@rtb.local` remains).
- **Screenshots** (viewed, not just saved):
  `docs/screenshots/09-login-fixed-chat.png` — logged-in Admin chat,
  "API online — v0.10.2"; `docs/screenshots/10-login-fixed-prod.png` —
  logged-in Customer Service chat in production shape.
- **Pytest: 142 passed, 1 skipped, 0 failed.**
- **Frontend builds:** dev PASS, staging PASS, production PASS.
- **Staging smoke: 22/22 PASS. Production smoke: 18/18 PASS.**

## For Fahad's PC

Delete the old project folder, extract `Project-1-LoginFix-v0.10.2.zip`,
then start as before (`production_start.ps1` + `production_start_web.ps1`).
Open either `http://localhost:3000` or `http://127.0.0.1:3000` — both
work now, and login stays logged in.
