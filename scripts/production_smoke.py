"""Production smoke test — Riyadh Trust Bank (v0.8).

Runs against a LIVE production API (default http://127.0.0.1:8000).
Start it first:  ./scripts/production_start.sh  (or .ps1 on Windows).

    python scripts/production_smoke.py
    python scripts/production_smoke.py --base http://127.0.0.1:8000

Checks (all must PASS):
  1-4.  health: 200, environment=production, version 0.9.1,
         demo_accounts_enabled=false, vector_store ok (8 docs, 15 chunks)
  5.    security headers present (nosniff / DENY / no-referrer), no Server header
  6.    demo login (admin@rtb.local / Admin123!) -> 401 (demo accounts OFF)
  7.    register a new user -> 201, role CUSTOMER_SERVICE
  8.    login with the new user -> 200
  9.    EN chat -> 200 + citations
  10.   RBAC: new user (Customer Service) AML question -> refused, 0 citations
  11.   rate limit: 6 rapid wrong logins, same email -> 6th is 429 + Retry-After
  12.   metrics: 200, environment=production

Cleanup: the smoke users it registers are deleted from
data-prod/users.json at the end (file-side, same store the server
reads), so the production user list stays clean. Exit code 0 only
when every check passes.
"""
import argparse
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

BASE = "http://127.0.0.1:8000"
PASS = 0
FAIL = 0
CREATED_EMAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {name}" + (f" — {detail}" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL  {name}" + (f" — {detail}" if detail else ""))


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the live production API.")
    parser.add_argument("--base", default=BASE, help="Production API base URL")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    stamp = str(int(time.time()))
    smoke_email = f"smoke-{stamp}@rtb.local"
    rl_email = f"ratelimit-{stamp}@rtb.local"

    print(f"== Production smoke test against {base} ==")
    client = httpx.Client(base_url=base, timeout=120.0, trust_env=False)
    try:
        # 1-4. Health -------------------------------------------------------
        res = client.get("/api/v1/health")
        check("health 200", res.status_code == 200, f"HTTP {res.status_code}")
        body = res.json().get("data", {}) if res.status_code == 200 else {}
        check("health environment=production", body.get("environment") == "production",
              f"got {body.get('environment')!r}")
        check("health version 0.10.1", body.get("version") == "0.10.1",
              f"got {body.get('version')!r}")
        check("health demo_accounts_enabled=false",
              body.get("demo_accounts_enabled") is False,
              f"got {body.get('demo_accounts_enabled')!r}")
        vs = body.get("vector_store", {})
        check("health vector_store ok (8 docs, 15 chunks)",
              vs.get("status") == "ok" and vs.get("documents") == 8 and vs.get("chunks") == 15,
              f"got {vs}")

        # 5. Security headers ----------------------------------------------
        h = res.headers
        check("header X-Content-Type-Options: nosniff",
              h.get("x-content-type-options") == "nosniff", h.get("x-content-type-options", ""))
        check("header X-Frame-Options: DENY",
              h.get("x-frame-options") == "DENY", h.get("x-frame-options", ""))
        check("header Referrer-Policy: no-referrer",
              h.get("referrer-policy") == "no-referrer", h.get("referrer-policy", ""))
        check("no Server header leaked", "server" not in h, h.get("server", "(absent)"))

        # 6. Demo login must FAIL ------------------------------------------
        res = client.post("/api/v1/auth/login",
                          json={"email": "admin@rtb.local", "password": "Admin123!"})
        check("demo login admin@rtb.local -> 401", res.status_code == 401,
              f"HTTP {res.status_code}")

        # 7-8. Register + login a real user ---------------------------------
        res = client.post("/api/v1/auth/register", json={
            "full_name": "Smoke Test", "email": smoke_email,
            "password": "Smoke1234", "confirm_password": "Smoke1234",
        })
        check("register new user -> 201", res.status_code == 201, f"HTTP {res.status_code}")
        if res.status_code == 201:
            CREATED_EMAILS.append(smoke_email)
            check("new user role CUSTOMER_SERVICE",
                  res.json()["data"]["user"]["role"] == "CUSTOMER_SERVICE")
        res = client.post("/api/v1/auth/login",
                          json={"email": smoke_email, "password": "Smoke1234"})
        check("login new user -> 200", res.status_code == 200, f"HTTP {res.status_code}")
        # v0.10: the session lives in the httpOnly cookie jar — no
        # token in the body, no Authorization header needed.
        logged_in = res.status_code == 200

        # 9-10. Chat + RBAC --------------------------------------------------
        if logged_in:
            res = client.post("/api/v1/chat",
                              json={"question": "What documents do I need to open a personal account?"})
            cited = res.json().get("data", {}).get("citations", []) if res.status_code == 200 else []
            check("EN chat answered + cited", res.status_code == 200 and len(cited) > 0,
                  f"HTTP {res.status_code}, {len(cited)} citations")
            res = client.post("/api/v1/chat",
                              json={"question": "What is the AML reporting threshold?"})
            data = res.json().get("data", {}) if res.status_code == 200 else {}
            check("RBAC: service AML -> refused, 0 citations",
                  data.get("refused") is True
                  and data.get("generation_mode") == "rbac-refusal"
                  and len(data.get("citations", [])) == 0,
                  f"refused={data.get('refused')}, mode={data.get('generation_mode')}, "
                  f"citations={len(data.get('citations', []))}")

        # 11. Rate limit ------------------------------------------------------
        codes = []
        for _ in range(6):
            r = client.post("/api/v1/auth/login",
                            json={"email": rl_email, "password": "Wrong1234"})
            codes.append(r.status_code)
        check("rate limit: 6th wrong login -> 429",
              codes[:5] == [401] * 5 and codes[5] == 429, f"got {codes}")
        r = client.post("/api/v1/auth/login",
                        json={"email": rl_email, "password": "Wrong1234"})
        check("rate limit: Retry-After header present",
              r.status_code == 429 and "retry-after" in r.headers,
              f"HTTP {r.status_code}, Retry-After={r.headers.get('retry-after')}")

        # 12. Metrics ----------------------------------------------------------
        res = client.get("/api/v1/metrics")
        check("metrics 200 + environment=production",
              res.status_code == 200 and res.json()["data"]["environment"] == "production",
              f"HTTP {res.status_code}")
    finally:
        client.close()

    # Cleanup: remove the smoke users from the production user store.
    if CREATED_EMAILS:
        os.environ["RTB_DATA_DIR"] = str(ROOT / "data-prod")
        from app.core.users import load_users, save_users

        users = [u for u in load_users() if u.get("email") not in CREATED_EMAILS]
        save_users(users)
        print(f"  Cleanup: removed smoke users {CREATED_EMAILS} from data-prod/users.json")

    print(f"\n== Production smoke: {PASS} PASS, {FAIL} FAIL ==")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
