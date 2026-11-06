# Landing Fix v0.9.1 — blank/faint landing page on Fahad's PC

## What the bug was (evidence from Fahad's photo)

Fahad sent a photo of his laptop (2026-11-06, `localhost:3000`, tab: "Riyadh Trust
Bank — Enterprise"):

- The hero section's **navy background was not visible** — the entire page was white.
- The heading **"Bank knowledge, answered with proof." was not visible at all**.
- The stats **numbers (8, 15, 24, 3) were not visible** — only the faint labels
  ("Indexed documents", "Searchable sections (chunks)" …) were faintly visible.
- The "What the platform does" heading was visible further down the page — meaning
  the page had loaded and React was running; only the hero colours were missing.

This is EXACTLY **white-on-white**: white text (`text-white` heading/numbers)
invisible on a white background, and light slate text (`text-slate-300`
paragraph/labels) faint.

## Root cause (with proof)

The build on this VM is **correct** — so this is not a code bug; it is a **stale
build or CSS not loading** on Fahad's PC:

1. `frontend/dist/assets/*.css` contains the correct `.bg-navy-900` rule
   (`background-color: rgb(11 44 74)`), the Tailwind v3 config defines
   navy/gold/teal, and the `Landing.tsx` code is correct.
2. **Live proof (after this fix, on this VM):** the production build + API :8000 +
   frontend preview :3000 were run, and a screenshot was taken with headless
   Chrome — `docs/screenshots/06-landing-fixed.png`. Computed styles probe:
   - hero background `rgb(11, 44, 74)` = `#0b2c4a` navy ✅
   - h1 colour `rgb(255, 255, 255)`, text "Bank knowledge, answered with proof." ✅
   - gold button background `rgb(201, 162, 39)` = `#c9a227`, text `#071f36` ✅
   - footer background `rgb(7, 31, 54)` ✅
   - stats `['8', '15', '24', '3']` ✅, version badge `v0.9.1` visible ✅
   - Everything is also visible to the eye in the screenshot — navy hero, white
     heading, gold button, stats, footer.
3. Therefore what was running on Fahad's PC was **not this build** — most
   likely: the old zip's `dist/` or an old dev server was still running, or the
   browser loaded old CSS from cache. (He may have extracted the v0.9 zip but
   not re-run `npm run build`, or the browser tab was an old one.)

## What the fix did (made the code bulletproof — not just "clear the cache")

Simply asking him to clear the cache was not enough. The critical colours no
longer depend on Tailwind:

1. **Plain-CSS fallback** — `frontend/src/index.css` now has plain classes
   (applied ALONGSIDE Tailwind, with `!important`):
   - `.hero-bg` → `background-color: #0b2c4a` (hero section)
   - `.hero-bg h1` → white; `.hero-sub` / `.hero-stat-label` → `#cbd5e1`;
     `.hero-stat-value` → white; `.hero-kicker` → gold
   - `.hero-gold-btn` → gold bg `#c9a227`, dark text `#071f36`
   - `.hero-outline-btn` → white border + white text
   - `.footer-bg` → `#071f36`, `.footer-title` → white
   - `.dark-btn` → navy bg + white text (Sign in / Create account buttons)
   - These classes were added in `Landing.tsx`, `Login.tsx`, and
     `Register.tsx` alongside the Tailwind classes. If one fails, the other
     protects the colours. No other page was touched.
2. **Version badge** — "Build v0.9.1 — landing fix" in the hero and
   "v0.9.1" in the footer, so Fahad can see which build is running. Version
   bump to 0.9.1 (`backend/app/core/config.py`, `tests/test_health.py`, and
   both smoke scripts).
3. **Verify** — see § "Root cause", point 2 above: a real headless-Chrome
   screenshot + computed-style probe, all PASS.

## Verify results

- Pytest: **99 passed, 0 failed** (prod venv, ~173s) — no backend change,
  but the full suite was re-run and is green.
- Frontend builds: dev `npm run build` PASS (2.67s), staging mode PASS (2.49s),
  zero tsc errors.
- The built CSS contains `.hero-bg{background-color:#0b2c4a!important}`
  (verified by grep), and the JS bundle contains `v0.9.1`.
- Live prod: API :8000 health `version 0.9.1, environment production,
  demo_accounts_enabled false`; web :3000 HTTP 200; screenshot
  `docs/screenshots/06-landing-fixed.png`.

## EXACT steps for Fahad (Windows)

These steps are **mandatory** — the new fix will not arrive from the old build:

1. Close the browser and terminal. Stop any server that is running (Ctrl+C).
2. **DELETE the old project folder** (or rename it, for example
   `riyadh-trust-bank-intelligence-OLD`). Do not extract over the old folder
   — the old `dist/` and `node_modules/` remain, and that is the cause of
   this bug.
3. Extract the new zip `Project-1-LandingFix-v0.9.1.zip`.
4. In PowerShell, go to the project folder, then:
   ```powershell
   cd frontend
   npm install
   npm run build
   ```
   After `npm run build`, the `dist` folder must exist.
5. Start production (from the project root):
   ```powershell
   .\scripts\production_start.ps1
   ```
   In a second PowerShell window:
   ```powershell
   .\scripts\production_start_web.ps1
   ```
   (Do not use the `.sh` files — on Windows, run the `.ps1` ones.)
6. Open `http://localhost:3000` in the browser, then press **Ctrl+F5** (hard
   refresh — bypasses the cache). Not just F5, **Ctrl+F5**.
7. **Check:** the footer below must say **v0.9.1**, and below the hero it must
   say "Build v0.9.1 — landing fix". If v0.9.1 is not visible, the old build
   is still running — repeat from step 2.
8. If it still appears white: press **F12** → **Network** tab → reload the
   page → look at the `index-*.css` line: it must be **200**. If it is **404**
   or **failed**, send a screenshot of it — then the problem is serving the
   file, not the code.

## What is pending (not changed by this fix)

- PC handover list (Ollama, PgVector, latency, httpOnly cookies, password reset,
  RBAC refusal phrasing) — in `docs/MONITORING.md` §8; this fix does not
  touch it.
- This fix is only a safety net for the critical colours of the landing page
  and login/register pages. The remaining pages still rely on Tailwind — if
  the same issue ever appears there, apply the same plain-CSS pattern.
