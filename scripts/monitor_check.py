"""Monitoring check — v0.9. Runs every 5 minutes (Windows Task
Scheduler or cron — see docs/MONITORING.md § Scheduler; this VM does
NOT create a scheduled task, Fahad's PC is a different machine).

What it does:
  1. Probes /api/v1/health (same logic as scripts/healthcheck.py).
     Down/unhealthy -> CRITICAL alert "api_down".
  2. Loads metrics.jsonl + audit.jsonl from the data dir and
     evaluates every rule in app/monitoring/alert_rules.py.
  3. Writes NEW alerts to alerts.jsonl (same rule: no duplicate
     active alert inside the 30-minute cooldown).
  4. Prints a one-line-per-rule summary.

Exit codes: 0 = healthy, no active alert; 1 = at least one active
alert (HIGH/MEDIUM); 2 = CRITICAL alert active, or the API is down.
No dependencies beyond the standard library + the backend package.

Usage:
    python scripts/monitor_check.py                    # prod :8000, data-prod
    python scripts/monitor_check.py --port 8001 --data-dir data-staging
    python scripts/monitor_check.py --data-dir data --url http://127.0.0.1:8000/api/v1/health
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# The data dir must be chosen BEFORE importing app modules (they read
# RTB_DATA_DIR at call time, but the health probe URL does not need it).
parser = argparse.ArgumentParser(description="Evaluate monitoring alert rules.")
parser.add_argument("--port", type=int, default=8000, help="API port (default 8000)")
parser.add_argument("--url", default=None, help="Full health URL (overrides --port)")
parser.add_argument("--data-dir", default="data-prod",
                    help="Runtime data dir, relative to project root (default data-prod)")
parser.add_argument("--timeout", type=float, default=5.0, help="Health probe timeout (seconds)")
args = parser.parse_args()

data_dir = Path(args.data_dir)
if not data_dir.is_absolute():
    data_dir = ROOT / data_dir
os.environ["RTB_DATA_DIR"] = str(data_dir)

from app.core.audit import read_audit  # noqa: E402
from app.core.monitoring import create_alert, disk_info, read_alerts, read_metrics  # noqa: E402
from app.monitoring.alert_rules import evaluate  # noqa: E402


def probe_health(url: str, timeout: float) -> bool:
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as res:
            body = json.loads(res.read().decode("utf-8"))
        return bool(body.get("success") is True
                    and body.get("data", {}).get("status") == "ok")
    except Exception:  # noqa: BLE001 — any failure means unhealthy
        return False


def main() -> int:
    url = args.url or f"http://127.0.0.1:{args.port}/api/v1/health"
    health_ok = probe_health(url, args.timeout)
    print(f"health: {'OK' if health_ok else 'DOWN/UNHEALTHY'} ({url})")

    metrics = read_metrics()
    audit, _total = read_audit(limit=10000)
    disk = disk_info()
    disk_pct = disk.get("used_percent")

    fired = evaluate(metrics, audit, health_ok=health_ok,
                     disk_pct=disk_pct, now=datetime.now(timezone.utc))
    created = []
    for alert in fired:
        created.append(create_alert(alert["rule"], alert["severity"],
                                    alert["message"], alert.get("context")))
    for a in created:
        print(f"  ALERT [{a['severity']}] {a['rule']}: {a['message']}")
    if not fired:
        print("  no rules fired")

    active = [a for a in read_alerts() if a.get("status") == "active"]
    print(f"active alerts: {len(active)} "
          f"(CRITICAL {sum(1 for a in active if a['severity'] == 'CRITICAL')}, "
          f"HIGH {sum(1 for a in active if a['severity'] == 'HIGH')}, "
          f"MEDIUM {sum(1 for a in active if a['severity'] == 'MEDIUM')})")
    if not health_ok or any(a.get("severity") == "CRITICAL" for a in active):
        return 2
    if active:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
