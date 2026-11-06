"""Retake ALL README screenshots (v0.10.3) — real headless Chromium (Playwright).

Why: the old v0.7 login screenshot (02-signin.png) still showed Roman Urdu
demo labels ("(sab kuch)", "(sirf Retail)") even though the code was
already English. Text scans cannot see inside images, so all 6 README
screenshots are retaken from the current build and verified visually + OCR.

Flow (staging, http://localhost:3001):
  01-landing.png        landing page (viewport 1280x900)
  02-signin.png         /login with English demo labels (viewport 1280x900)
  03-signup.png         /register (viewport 1280x900)
  04-chat.png           demo Admin login -> real question -> cited answer
                         (viewport 1280x900)
  05-monitoring.png     /monitoring Admin dashboard (full page, 1440 wide)
  06-landing-fixed.png  landing page again (full page, 1280 wide)

Usage: python scripts/retake_readme_screenshots.py
Requires staging API :8001 + web preview :3001 running.
Exit 0 only if all 6 shots are saved.
"""

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CHROME_HEADLESS_SHELL = "/tmp/chrome-headless-shell-linux64/chrome-headless-shell"
SHOTS = ROOT / "docs" / "screenshots"
ORIGIN = "http://localhost:3001"
QUESTION = "What documents are needed for KYC account opening?"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=CHROME_HEADLESS_SHELL)

        # --- 01 landing (viewport) ---
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        r = page.goto(f"{ORIGIN}/", wait_until="networkidle")
        check("01 landing loads", r is not None and r.status == 200, f"(HTTP {r.status if r else '?'})")
        check("01 hero text visible", "Bank knowledge, answered with proof." in page.content())
        page.screenshot(path=str(SHOTS / "01-landing.png"))
        print("  screenshot -> 01-landing.png")
        ctx.close()

        # --- 02 sign in (viewport) ---
        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        r = page.goto(f"{ORIGIN}/login", wait_until="networkidle")
        check("02 sign-in loads", r is not None and r.status == 200, f"(HTTP {r.status if r else '?'})")
        body = page.content()
        check("02 demo labels English", "Branch Manager (full access)" in body
              and "Customer Service (Retail only)" in body)
        check("02 no Roman Urdu labels", "(sab kuch)" not in body and "(sirf Retail)" not in body)
        page.screenshot(path=str(SHOTS / "02-signin.png"))
        print("  screenshot -> 02-signin.png")

        # --- 03 sign up (viewport, same context) ---
        r = page.goto(f"{ORIGIN}/register", wait_until="networkidle")
        check("03 sign-up loads", r is not None and r.status == 200, f"(HTTP {r.status if r else '?'})")
        check("03 create-account heading", "Create account" in page.content()
              or "Sign up" in page.content())
        page.screenshot(path=str(SHOTS / "03-signup.png"))
        print("  screenshot -> 03-signup.png")

        # --- 04 chat: demo Admin login, real question, cited answer ---
        page.goto(f"{ORIGIN}/login", wait_until="networkidle")
        page.get_by_text("Branch Manager (full access)").click()
        try:
            page.wait_for_url("**/chat", timeout=15000)
            check("04 demo Admin login -> /chat", True, f"(URL {page.url})")
        except Exception:
            check("04 demo Admin login -> /chat", False, f"(URL {page.url})")
            browser.close()
            return 1
        page.get_by_placeholder("Ask about KYC, AML, loans, leave, fees… (English or العربية)").fill(QUESTION)
        page.get_by_text("Ask", exact=True).click()
        try:
            page.get_by_text("Sources", exact=True).first.wait_for(timeout=120000)
            check("04 cited answer rendered", True, "(Sources block visible)")
        except Exception:
            check("04 cited answer rendered", False, "(no Sources block in 120s)")
            browser.close()
            return 1
        page.wait_for_timeout(800)
        # Scroll the message list so the user's question is visible at
        # the top of the shot (the list auto-scrolls to the bottom,
        # which hides the question; a plain scrollTop=0 on the
        # container did not stick, so scroll the question itself
        # into view).
        page.get_by_text(QUESTION, exact=True).first.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        page.screenshot(path=str(SHOTS / "04-chat.png"))
        print("  screenshot -> 04-chat.png")

        # --- 05 monitoring (full page, 1440 wide, SAME logged-in page) ---
        # NOTE: copying cookies into a fresh context did not carry the
        # Admin session (the page bounced to /login), so stay on the
        # already-logged-in page from step 04 instead.
        page.set_viewport_size({"width": 1440, "height": 900})
        r = page.goto(f"{ORIGIN}/monitoring", wait_until="networkidle")
        check("05 monitoring loads", r is not None and r.status == 200, f"(HTTP {r.status if r else '?'})")
        try:
            page.get_by_role("heading", name="Monitoring").wait_for(timeout=15000)
            check("05 monitoring heading", True, "(h1 Monitoring visible)")
        except Exception:
            check("05 monitoring heading", False, f"(URL {page.url})")
            browser.close()
            return 1
        page.wait_for_timeout(1000)
        page.screenshot(path=str(SHOTS / "05-monitoring.png"), full_page=True)
        print("  screenshot -> 05-monitoring.png")

        # --- 06 landing again (full page, 1280 wide) ---
        ctx3 = browser.new_context(viewport={"width": 1280, "height": 900})
        page3 = ctx3.new_page()
        r = page3.goto(f"{ORIGIN}/", wait_until="networkidle")
        check("06 landing loads", r is not None and r.status == 200, f"(HTTP {r.status if r else '?'})")
        page3.screenshot(path=str(SHOTS / "06-landing-fixed.png"), full_page=True)
        print("  screenshot -> 06-landing-fixed.png")
        ctx3.close()

        browser.close()

    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
