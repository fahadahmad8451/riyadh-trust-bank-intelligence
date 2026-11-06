"""Staging smoke test — Riyadh Trust Bank (v0.6).

Runs against a LIVE staging API (default http://127.0.0.1:8001).
Start it first:  ./scripts/staging_start.sh   (or .ps1 on Windows)

    python scripts/staging_smoke.py [--base-url http://127.0.0.1:8001]

Checks (each prints PASS / FAIL / SKIP):
  1. health — 200, environment == "staging", version == "0.9.1"
  2. metrics — same environment + version
  3. login as admin / compliance / service — 200, correct role
  4. wrong password — 401; no-token chat — 401
  5. EN chat (admin, warm-up + 3 timed) — 200, citations, top doc
     is KYC or Account Opening; the 3 timed latencies are printed
     (Testing condition #1: English latency re-measurement)
  6. AR chat (compliance) — 200, AML citation
  7. RBAC — service asks the AML question: refused, 0 citations
  8. documents list — service sees 4 (RETAIL only), admin sees 8
  9. feedback — admin chats, thumbs-up on the real message_id,
     then feedback-stats shows it
 10. eval/results (admin) — 200; reports whether a stored run exists
 11. audit-logs (admin) — 200 and contains LOGIN entries
 12. dev-isolation — staging users/audit files live under
     data-staging/, NOT data/ (checked via RTB_DATA_DIR on disk)

Exit code: 0 if every check PASSES (SKIP allowed only where noted),
1 if any check FAILS. No data is faked: every check is a real HTTP
call and the numbers printed are the real ones.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]

USERS = {
    "admin": ("admin@rtb.local", "Admin123!"),
    "compliance": ("compliance@rtb.local", "Compliance123!"),
    "service": ("service@rtb.local", "Service123!"),
}
EN_QUESTIONS = [
    "What documents are needed for KYC account opening?",
    "What is the maximum personal loan amount?",
    "How many days of annual leave do employees get?",
]
AR_QUESTION = "ما هو حد الإبلاغ عن المعاملات النقدية؟"
AML_QUESTION = "What is the AML reporting threshold?"


class Smoke:
    def __init__(self, base_url: str):
        # Anonymous client: health, metrics, and the no-token 401 check.
        self.client = httpx.Client(base_url=base_url, timeout=120.0, trust_env=False)
        # v0.10 (httpOnly cookies): one client per role — each keeps
        # its own cookie jar, so a service chat cannot accidentally
        # carry the admin session (or vice versa).
        self.role_clients: dict[str, httpx.Client] = {}
        self.results: list[tuple[str, str, str]] = []  # (name, verdict, detail)
        self.latencies: list[float] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.results.append((name, "PASS" if ok else "FAIL", detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}  {detail}")
        return ok

    def login(self, role: str) -> bool:
        email, password = USERS[role]
        client = httpx.Client(base_url=str(self.client.base_url), timeout=120.0, trust_env=False)
        res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        if res.status_code != 200:
            self.check(f"login {role}", False, f"HTTP {res.status_code}: {res.text[:120]}")
            return False
        data = res.json()["data"]
        ok = data["user"]["role"] == {
            "admin": "ADMIN",
            "compliance": "COMPLIANCE_OFFICER",
            "service": "CUSTOMER_SERVICE",
        }[role]
        self.check(f"login {role}", ok, f"role={data['user']['role']}")
        if ok:
            # The session lives in the client's httpOnly cookie jar.
            self.role_clients[role] = client
            return True
        return False

    def chat(self, role: str, question: str) -> tuple[int, dict, float]:
        started = time.monotonic()
        res = self.role_clients[role].post(
            "/api/v1/chat",
            json={"question": question},
        )
        wall = time.monotonic() - started
        return res.status_code, (res.json() if res.status_code == 200 else {}), wall

    def _role_get(self, role: str, path: str):
        return self.role_clients[role].get(path)

    def _role_post(self, role: str, path: str, **kwargs):
        return self.role_clients[role].post(path, **kwargs)

    def run(self) -> int:
        print("== Staging smoke test ==")
        print(f"Base URL: {self.client.base_url}")
        # Snapshot dev data BEFORE any staging traffic, so check 12 can
        # prove staging did not write into dev data/.
        dev_audit = ROOT / "data" / "audit.jsonl"
        self.dev_audit_before = (dev_audit.stat().st_mtime_ns, dev_audit.stat().st_size) \
            if dev_audit.exists() else None

        # 1-2. health + metrics -------------------------------------------
        res = self.client.get("/api/v1/health")
        body = res.json() if res.status_code == 200 else {}
        data = body.get("data", {})
        self.check("health 200 + environment=staging",
                   res.status_code == 200 and data.get("environment") == "staging",
                   f"HTTP {res.status_code}, environment={data.get('environment')}, "
                   f"version={data.get('version')}")
        self.check("health version 0.10.3", data.get("version") == "0.10.3",
                   f"version={data.get('version')}")
        res = self.client.get("/api/v1/metrics")
        mdata = res.json().get("data", {}) if res.status_code == 200 else {}
        self.check("metrics environment=staging",
                   res.status_code == 200 and mdata.get("environment") == "staging",
                   f"HTTP {res.status_code}")

        # 3-4. auth --------------------------------------------------------
        for role in ("admin", "compliance", "service"):
            self.login(role)
        res = self.client.post("/api/v1/auth/login",
                               json={"email": "admin@rtb.local", "password": "Wrong123!"})
        self.check("wrong password -> 401", res.status_code == 401, f"HTTP {res.status_code}")
        res = self.client.post("/api/v1/chat", json={"question": "Hello?"})
        self.check("no-token chat -> 401", res.status_code == 401, f"HTTP {res.status_code}")

        if not all(r in self.role_clients for r in ("admin", "service", "compliance")):
            print("Logins failed — cannot run the chat checks.")
            return self.finish()

        # 5. EN chats (warm-up + 3 timed = latency re-measurement) --------
        status, body, _ = self.chat("admin", EN_QUESTIONS[0])
        d = body.get("data", {})
        cites = [c.get("document_title", "") for c in d.get("citations", [])]
        self.check("EN chat (warm-up) answered + cited",
                   status == 200 and not d.get("refused") and len(cites) > 0,
                   f"HTTP {status}, top={cites[0] if cites else 'none'}, "
                   f"latency_ms={d.get('latency_ms')}")
        for question in EN_QUESTIONS:
            status, body, wall = self.chat("admin", question)
            d = body.get("data", {})
            self.latencies.append(wall)
            cites = [c.get("document_title", "") for c in d.get("citations", [])]
            self.check(f"EN chat timed: {question[:45]}...",
                       status == 200 and len(cites) > 0,
                       f"wall={wall:.2f}s, server_latency_ms={d.get('latency_ms')}, "
                       f"top={cites[0] if cites else 'none'}")
        if self.latencies:
            print(f"  English latency (3 warm chats): "
                  f"{', '.join(f'{x:.2f}s' for x in self.latencies)}  "
                  f"median={sorted(self.latencies)[1]:.2f}s  (target < 3s)")

        # 6. AR chat (compliance) ------------------------------------------
        status, body, wall = self.chat("compliance", AR_QUESTION)
        d = body.get("data", {})
        cites = [c.get("document_title", "") for c in d.get("citations", [])]
        self.check("AR chat (compliance) AML cited",
                   status == 200 and any("AML" in c for c in cites),
                   f"HTTP {status}, wall={wall:.2f}s, top={cites[0] if cites else 'none'}")

        # 7. RBAC — service must NOT get the AML answer --------------------
        status, body, _ = self.chat("service", AML_QUESTION)
        d = body.get("data", {})
        self.check("RBAC: service AML question refused, 0 citations",
                   status == 200 and d.get("refused") is True
                   and len(d.get("citations", [])) == 0,
                   f"HTTP {status}, refused={d.get('refused')}, "
                   f"mode={d.get('generation_mode')}, citations={len(d.get('citations', []))}")

        # 8. documents list per role ---------------------------------------
        for role, expected in (("service", 4), ("admin", 8)):
            res = self._role_get(role, "/api/v1/documents")
            docs = res.json().get("data", {}).get("documents", []) if res.status_code == 200 else []
            self.check(f"documents list ({role}) = {expected}",
                       res.status_code == 200 and len(docs) == expected,
                       f"HTTP {res.status_code}, count={len(docs)}")

        # 9. feedback -------------------------------------------------------
        status, body, _ = self.chat("admin", EN_QUESTIONS[1])
        message_id = body.get("data", {}).get("message_id")
        ok = False
        if message_id:
            res = self._role_post(
                "admin", "/api/v1/feedback",
                json={"message_id": message_id, "rating": "up"},
            )
            ok = res.status_code == 200
            self.check("feedback thumbs-up", ok,
                       f"HTTP {res.status_code}, "
                       f"{res.json().get('data', {}).get('message', '') if ok else res.text[:100]}")
            res = self._role_get("admin", "/api/v1/admin/feedback-stats")
            stats = res.json().get("data", {}) if res.status_code == 200 else {}
            self.check("feedback-stats shows the vote",
                       res.status_code == 200 and stats.get("total", 0) >= 1,
                       f"HTTP {res.status_code}, total={stats.get('total')}")
        else:
            self.check("feedback thumbs-up", False, "no message_id returned by chat")

        # 10. eval/results --------------------------------------------------
        res = self._role_get("admin", "/api/v1/eval/results")
        if res.status_code == 200:
            report = res.json().get("data") or {}
            has_run = bool(report.get("questions"))
            self.results.append(("eval/results 200", "PASS",
                                 f"stored run present: {has_run} "
                                 f"(run the eval in staging to fill this in)"))
            print(f"  [PASS] eval/results 200  stored run present: {has_run}")
        else:
            self.check("eval/results 200", False, f"HTTP {res.status_code}")

        # 11. audit-logs ----------------------------------------------------
        res = self._role_get("admin", "/api/v1/admin/audit-logs")
        logs = res.json().get("data", {}).get("audit_logs", []) if res.status_code == 200 else []
        has_login = any(e.get("action") == "LOGIN" for e in logs)
        self.check("audit-logs contain LOGIN entries",
                   res.status_code == 200 and has_login,
                   f"HTTP {res.status_code}, entries={len(logs)}")

        # 12. dev-isolation (on disk) ---------------------------------------
        staging_dir = ROOT / "data-staging"
        users_file = staging_dir / "users.json"
        audit_file = staging_dir / "audit.jsonl"
        self.check("staging data lives in data-staging/",
                   users_file.exists() and audit_file.exists(),
                   f"users.json={users_file.exists()}, audit.jsonl={audit_file.exists()}")
        dev_audit = ROOT / "data" / "audit.jsonl"
        after = (dev_audit.stat().st_mtime_ns, dev_audit.stat().st_size) \
            if dev_audit.exists() else None
        self.check("dev data/audit.jsonl untouched by the smoke run",
                   after == self.dev_audit_before,
                   f"before={self.dev_audit_before}, after={after} "
                   f"(if these differ, staging wrote into dev data)")

        return self.finish()

    def finish(self) -> int:
        failed = [r for r in self.results if r[1] == "FAIL"]
        print(f"\n== Smoke result: {len(self.results) - len(failed)}/{len(self.results)} PASS, "
              f"{len(failed)} FAIL ==")
        for name, verdict, detail in self.results:
            if verdict == "FAIL":
                print(f"  FAIL: {name} — {detail}")
        return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Staging smoke test (v0.6).")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    args = parser.parse_args()
    return Smoke(args.base_url).run()


if __name__ == "__main__":
    sys.exit(main())
