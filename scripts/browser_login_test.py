"""v0.10.2 login-bounce browser test — real headless Chromium (Playwright).

Tests BOTH host spellings of the staging web, because that is the bug:
  1. http://localhost:3001  (page host = localhost)
  2. http://127.0.0.1:3001  (page host = 127.0.0.1)

Per origin, the full flow:
  login page -> click demo Admin -> /chat (no bounce) -> cookies set?
  -> chat POST from page context (credentials: include) -> 200
  -> page reload -> still on /chat (refresh cookie works, no bounce)
  -> Log out -> back on /login
Every step prints its HTTP status / URL as evidence. Exit 0 only if
every check passes on BOTH origins. Saves one screenshot of the
logged-in chat page (localhost run) to docs/screenshots/09-login-fixed-chat.png.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CHROME_HEADLESS_SHELL = "/tmp/chrome-headless-shell-linux64/chrome-headless-shell"
# Chrome-for-Testing headless shell already on this VM (used by the
# v0.10.1 screenshot run). Playwright's own cache only holds a stub
# shell.zip, so launch against this binary explicitly.
SCREENSHOT = ROOT / "docs" / "screenshots" / "09-login-fixed-chat.png"

ORIGINS = ["http://localhost:3001", "http://127.0.0.1:3001"]
CHAT_QUESTION = "What documents are needed for KYC account opening?"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")


def run_origin(pw, origin: str, screenshot: bool) -> None:
    print(f"\n== {origin} ==")
    browser = pw.chromium.launch(headless=True, executable_path=CHROME_HEADLESS_SHELL)
    ctx = browser.new_context()
    page = ctx.new_page()
    try:
        # 1. Login page loads
        r = page.goto(f"{origin}/login", wait_until="networkidle")
        check("login page loads", r is not None and r.status == 200, f"(HTTP {r.status if r else '?'})")

        # 2. One-click demo Admin login (button label is unique on the page)
        page.get_by_text("Branch Manager (full access)").click()
        try:
            page.wait_for_url("**/chat", timeout=15000)
            check("demo Admin login -> /chat (no bounce)", True, f"(URL {page.url})")
        except Exception:
            check("demo Admin login -> /chat (no bounce)", False, f"(URL {page.url})")
            return

        # 3. Cookies present after login (httpOnly -> visible via context cookies)
        cookies = {c["name"]: c for c in ctx.cookies()}
        check(
            "auth cookies set",
            "rtb_access" in cookies and "rtb_refresh" in cookies,
            f"(cookies: {sorted(cookies)})",
        )

        # 4. Chat POST from the page context — the exact call that 401'd before
        chat = page.evaluate(
            """async (q) => {
              const res = await fetch('/api/v1/chat', {
                method: 'POST',
                credentials: 'include',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({question: q}),
              });
              const body = await res.json().catch(() => ({}));
              return {status: res.status,
                      citations: (body.data && body.data.citations) ? body.data.citations.length : 0,
                      error: body.error || null};
            }""",
            CHAT_QUESTION,
        )
        check(
            "chat POST from browser (cookies sent)",
            chat["status"] == 200 and chat["citations"] > 0,
            f"(HTTP {chat['status']}, citations={chat['citations']}, error={chat['error']})",
        )

        # 5. Reload — still logged in (refresh token flow, no bounce to /login)
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1500)
        check("reload keeps session (no bounce)", "/chat" in page.url, f"(URL {page.url})")

        if screenshot:
            page.screenshot(path=str(SCREENSHOT))
            print(f"  screenshot -> {SCREENSHOT}")

        # 6. Log out works and lands back on /login
        page.get_by_text("Log out", exact=True).first.click()
        try:
            page.wait_for_url("**/login", timeout=10000)
            check("logout -> /login", True, f"(URL {page.url})")
        except Exception:
            check("logout -> /login", False, f"(URL {page.url})")
    finally:
        browser.close()


def main() -> int:
    with sync_playwright() as pw:
        for i, origin in enumerate(ORIGINS):
            run_origin(pw, origin, screenshot=(i == 0))
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} browser checks PASSED")
    if failed:
        print("FAILED:")
        for name, _, detail in failed:
            print(f"  - {name} {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
