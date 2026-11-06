"""v0.10.2 production-shaped browser test — real headless Chromium.

Production has demo accounts OFF, so this test registers a real user
through the UI (the same flow Fahad would use on his PC), then:
  register -> auto-login -> /chat (no bounce) -> chat POST 200
  -> reload (still logged in) -> logout -> /login
Run from http://localhost:3000 (page host localhost, API baked as
127.0.0.1:8000 — the exact cross-site shape that bounced before the
fix). The test user is deleted from data-prod/users.json afterwards
by the caller; this script only prints the email used.
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CHROME_HEADLESS_SHELL = "/tmp/chrome-headless-shell-linux64/chrome-headless-shell"
ORIGIN = "http://localhost:3000"
EMAIL = f"browsertest-{int(time.time())}@rtb.local"


def main() -> int:
    ok = True

    def check(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        print(f"  [{'PASS' if passed else 'FAIL'}] {name} {detail}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=CHROME_HEADLESS_SHELL)
        ctx = browser.new_context()
        page = ctx.new_page()
        try:
            r = page.goto(f"{ORIGIN}/register", wait_until="networkidle")
            check("register page loads", r is not None and r.status == 200, f"(HTTP {r.status if r else '?'})")
            page.fill("#reg-name", "Browser Test")
            page.fill("#reg-email", EMAIL)
            page.fill("#reg-password", "Browser123")
            page.fill("#reg-confirm", "Browser123")
            page.check("input[type='checkbox']")
            page.get_by_text("Create account", exact=True).click()
            try:
                page.wait_for_url("**/chat", timeout=15000)
                check("register -> auto-login -> /chat (no bounce)", True, f"(URL {page.url})")
            except Exception:
                check("register -> auto-login -> /chat (no bounce)", False, f"(URL {page.url})")
                print(f"TEST_EMAIL={EMAIL}")
                return 1
            cookies = {c["name"] for c in ctx.cookies()}
            check("auth cookies set", "rtb_access" in cookies and "rtb_refresh" in cookies,
                  f"(cookies: {sorted(cookies)})")
            chat = page.evaluate(
                """async (q) => {
                  const res = await fetch('/api/v1/chat', {
                    method: 'POST', credentials: 'include',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({question: q}),
                  });
                  const body = await res.json().catch(() => ({}));
                  return {status: res.status,
                          citations: (body.data && body.data.citations) ? body.data.citations.length : 0};
                }""",
                "What documents are needed for KYC account opening?",
            )
            check("chat POST from browser (cookies sent)", chat["status"] == 200 and chat["citations"] > 0,
                  f"(HTTP {chat['status']}, citations={chat['citations']})")
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(1500)
            check("reload keeps session (no bounce)", "/chat" in page.url, f"(URL {page.url})")
            page.screenshot(path=str(ROOT / "docs" / "screenshots" / "10-login-fixed-prod.png"))
            print(f"  screenshot -> docs/screenshots/10-login-fixed-prod.png")
            page.get_by_text("Log out", exact=True).first.click()
            try:
                page.wait_for_url("**/login", timeout=10000)
                check("logout -> /login", True, f"(URL {page.url})")
            except Exception:
                check("logout -> /login", False, f"(URL {page.url})")
        finally:
            browser.close()
    print(f"TEST_EMAIL={EMAIL}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
