# Landing Fix v0.9.1 — blank/faint landing page on Fahad's PC

## Bug kya tha (Fahad ki photo se evidence)

Fahad ne apne laptop ki photo bheji (2026-11-06, `localhost:3000`, tab: "Riyadh Trust
Bank — Enterprise"):

- Hero section ki **navy background nahi dikh rahi** — poora page safed hai.
- Heading **"Bank knowledge, answered with proof." bilkul nahi dikh rahi**.
- Stats ke **numbers (8, 15, 24, 3) nahi dikh rahe** — sirf halke labels
  ("Indexed documents", "Searchable sections (chunks)" …) faint dikhte hain.
- "What the platform does" heading neeche dikh rahi hai — matlab page load hua,
  React chala, sirf hero ke colours gayab hain.

Ye EXACTLY **white-on-white** hai: safed text (`text-white` heading/numbers) safed
background par gayab, halka slate text (`text-slate-300` paragraph/labels) faint.

## Asal wajah (proof ke sath)

Is VM par build **sahi** hai — is liye code ka bug nahi, Fahad ke PC par **stale
build ya CSS na load hona** hai:

1. `frontend/dist/assets/*.css` me `.bg-navy-900` rule sahi hai
   (`background-color: rgb(11 44 74)`), Tailwind v3 config me navy/gold/teal
   defined hain, `Landing.tsx` code sahi hai.
2. **Live proof (is fix ke baad, isi VM par):** production build + API :8000 +
   frontend preview :3000 chalaye, headless Chrome se screenshot liya —
   `docs/screenshots/06-landing-fixed.png`. Computed styles probe:
   - hero background `rgb(11, 44, 74)` = `#0b2c4a` navy ✅
   - h1 colour `rgb(255, 255, 255)`, text "Bank knowledge, answered with proof." ✅
   - gold button background `rgb(201, 162, 39)` = `#c9a227`, text `#071f36` ✅
   - footer background `rgb(7, 31, 54)` ✅
   - stats `['8', '15', '24', '3']` ✅, version badge `v0.9.1` visible ✅
   - Screenshot me sab kuch aankh se bhi dikhta hai — navy hero, safed heading,
     gold button, stats, footer.
3. Is liye Fahad ke PC par jo chal raha tha wo **ye build nahi thi** — sab se
   likely: purani zip ka `dist/` ya purana dev server chal raha tha, ya browser
   ne purani CSS cache se li. (Ho sakta hai usne v0.9 zip extract kiya ho lekin
   `npm run build` dobara na chalaya ho, ya browser tab purana khula ho.)

## Fix kya kiya (code bulletproof banaya — sirf "cache clear karo" nahi kaha)

Sirf cache clear karne ko kehna kaafi nahi tha. Ab critical colours Tailwind par
depend nahi karte:

1. **Plain-CSS fallback** — `frontend/src/index.css` me plain classes (Tailwind
   ke SATH lagti hain, `!important` ke sath):
   - `.hero-bg` → `background-color: #0b2c4a` (hero section)
   - `.hero-bg h1` → white; `.hero-sub` / `.hero-stat-label` → `#cbd5e1`;
     `.hero-stat-value` → white; `.hero-kicker` → gold
   - `.hero-gold-btn` → gold bg `#c9a227`, dark text `#071f36`
   - `.hero-outline-btn` → white border + white text
   - `.footer-bg` → `#071f36`, `.footer-title` → white
   - `.dark-btn` → navy bg + white text (Sign in / Create account buttons)
   - `Landing.tsx`, `Login.tsx`, `Register.tsx` me ye classes Tailwind classes
     ke sath lagayi gayi hain. Ek fail ho to doosri bachaye. Koi aur page nahi
     chheda.
2. **Version badge** — hero me "Build v0.9.1 — landing fix" aur footer me
   "v0.9.1", taake Fahad dekh sake konsi build chal rahi hai. Version bump
   0.9.1 (`backend/app/core/config.py`, `tests/test_health.py`, dono smoke
   scripts).
3. **Verify** — upar § "Asal wajah" point 2 dekho: real headless-Chrome screenshot
   + computed-style probe, sab PASS.

## Verify results

- Pytest: **99 passed, 0 failed** (prod venv, ~173s) — koi backend change nahi,
  lekin poora suite dobara green.
- Frontend builds: dev `npm run build` PASS (2.67s), staging mode PASS (2.49s),
  zero tsc errors.
- Built CSS me `.hero-bg{background-color:#0b2c4a!important}` maujood (grep se
  verify), JS bundle me `v0.9.1`.
- Live prod: API :8000 health `version 0.9.1, environment production,
  demo_accounts_enabled false`; web :3000 HTTP 200; screenshot
  `docs/screenshots/06-landing-fixed.png`.

## Fahad ke liye EXACT steps (Windows)

Ye steps **lazmi** hain — purani build se naya fix nahi aayega:

1. Browser aur terminal band karo. Jo server chal raha ho usko roko (Ctrl+C).
2. **Purana project folder DELETE karo** (ya naya naam do, jaise
   `riyadh-trust-bank-intelligence-OLD`). Purane folder ke upar extract mat karo
   — purana `dist/` aur `node_modules/` reh jata hai, yehi bug ki wajah hai.
3. Naya zip `Project-1-LandingFix-v0.9.1.zip` extract karo.
4. PowerShell me project folder me jao, phir:
   ```powershell
   cd frontend
   npm install
   npm run build
   ```
   `npm run build` ke baad `dist` folder banna chahiye.
5. Production start karo (project root se):
   ```powershell
   .\scripts\production_start.ps1
   ```
   Doosri PowerShell window me:
   ```powershell
   .\scripts\production_start_web.ps1
   ```
   (Ya dono ke `.sh` nahi — Windows par `.ps1` wale chalao.)
6. Browser me `http://localhost:3000` kholo, phir **Ctrl+F5** (hard refresh —
   cache bypass). Sirf F5 nahi, **Ctrl+F5**.
7. **Check karo:** neeche footer me **v0.9.1** likha hona chahiye, aur hero ke
   neeche "Build v0.9.1 — landing fix". Agar v0.9.1 nahi dikh raha to samjho
   purani build hi chal rahi hai — step 2 se dobara karo.
8. Agar phir bhi safed dikhe to: **F12** dabao → **Network** tab → page reload
   karo → `index-*.css` wali line dekho: **200** honi chahiye. Agar **404** ya
   **failed** hai to uska screenshot bhejo — phir masla serve karne ka hai, code
   ka nahi.

## Kya pending hai (is fix se nahi badla)

- PC handover list (Ollama, PgVector, latency, httpOnly cookies, password reset,
  RBAC refusal phrasing) — `docs/MONITORING.md` §8 me hai, ye fix usko nahi
  chhedta.
- Ye fix sirf landing + login/register ke critical colours ka safety net hai.
  Baaki pages Tailwind par hi hain — agar kabhi wahan bhi aisa masla aaye to
  wahi plain-CSS pattern lagana hai.
