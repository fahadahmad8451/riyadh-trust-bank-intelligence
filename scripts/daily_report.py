"""Daily report generator — v0.9.

Builds a Markdown summary of the last 24 hours from the REAL
recorded data (metrics.jsonl + audit.jsonl + alerts.jsonl +
feedback.jsonl) and writes it to:

    <data-dir>/reports/daily-YYYY-MM-DD.md

No email, no SMTP — the report is a file, linked from the
Monitoring dashboard. Run it once a day (Task Scheduler / cron,
see docs/MONITORING.md § Scheduler) or by hand:

    python scripts/daily_report.py                     # prod, yesterday->today
    python scripts/daily_report.py --data-dir data-staging
    python scripts/daily_report.py --date 2026-11-05  # a specific day

Counts only — no question text, no user content, no PII. The top
endpoints are paths, the "top errors" are status codes.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

parser = argparse.ArgumentParser(description="Generate the daily monitoring report.")
parser.add_argument("--data-dir", default="data-prod",
                    help="Runtime data dir, relative to project root (default data-prod)")
parser.add_argument("--date", default=None,
                    help="Report date YYYY-MM-DD (default: today, UTC)")
args = parser.parse_args()

data_dir = Path(args.data_dir)
if not data_dir.is_absolute():
    data_dir = ROOT / data_dir
os.environ["RTB_DATA_DIR"] = str(data_dir)

from app.core.monitoring import (  # noqa: E402
    _parse_ts,
    _percentile,
    count_failed_logins,
    count_rbac_denials,
    read_alerts,
    read_metrics,
)
from app.core.audit import read_audit  # noqa: E402


def _read_jsonl(path: Path) -> list[dict]:
    out = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def main() -> int:
    if args.date:
        day = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = day
    end = day + timedelta(days=1)

    metrics = [e for e in read_metrics()
               if (t := _parse_ts(e.get("ts"))) is not None and start <= t < end]
    audit, _ = read_audit(limit=100000)
    audit = [a for a in audit
             if (t := _parse_ts(a.get("ts"))) is not None and start <= t < end]
    alerts = [a for a in read_alerts()
              if (t := _parse_ts(a.get("ts"))) is not None and start <= t < end]
    feedback = _read_jsonl(data_dir / "feedback.jsonl")
    feedback = [f for f in feedback
                if (t := _parse_ts(f.get("ts"))) is not None and start <= t < end]

    total = len(metrics)
    errors_5xx = sum(1 for e in metrics
                     if isinstance(e.get("status"), int) and e["status"] >= 500)
    lat = [float(e["latency_ms"]) for e in metrics
           if isinstance(e.get("latency_ms"), (int, float))]
    chat_lat = [float(e["latency_ms"]) for e in metrics
                if e.get("endpoint") == "/api/v1/chat"
                and isinstance(e.get("latency_ms"), (int, float))]
    chats = sum(1 for e in metrics
                if e.get("endpoint") == "/api/v1/chat" and e.get("method") == "POST")
    by_endpoint: dict[str, int] = {}
    for e in metrics:
        ep = e.get("endpoint", "?")
        by_endpoint[ep] = by_endpoint.get(ep, 0) + 1
    failed_logins = count_failed_logins(audit)
    rbac = count_rbac_denials(audit)
    ups = sum(1 for f in feedback if f.get("rating") == "up")
    downs = len(feedback) - ups

    date_str = day.strftime("%Y-%m-%d")
    lines = [
        f"# Daily report — {date_str}",
        "",
        "Riyadh Trust Bank — Enterprise Intelligence Platform. "
        "Counts only, generated from metrics.jsonl + audit.jsonl + "
        "alerts.jsonl + feedback.jsonl (no question text, no PII).",
        "",
        "## Traffic",
        "",
        f"- Total requests: **{total}**",
        f"- Chats (POST /api/v1/chat): **{chats}**",
        f"- 5xx errors: **{errors_5xx}**"
        + (f" ({errors_5xx / total:.1%} of requests)" if total else ""),
        f"- Latency p50: **{_percentile(lat, 50)} ms**, "
        f"p95: **{_percentile(lat, 95)} ms**",
        f"- Chat latency p50: **{_percentile(chat_lat, 50)} ms**, "
        f"p95: **{_percentile(chat_lat, 95)} ms**",
        "",
        "## Top endpoints",
        "",
    ]
    if by_endpoint:
        for ep, n in sorted(by_endpoint.items(), key=lambda kv: -kv[1])[:10]:
            lines.append(f"- `{ep}` — {n}")
    else:
        lines.append("- (no requests recorded)")
    lines += [
        "",
        "## Security",
        "",
        f"- Failed logins: **{failed_logins}**",
        f"- RBAC denials (ACCESS_DENIED + refused chats): **{rbac}**",
        "",
        "## Feedback",
        "",
        f"- Total: **{len(feedback)}** (up {ups}, down {downs})",
        "",
        "## Alerts fired",
        "",
    ]
    if alerts:
        for a in alerts:
            lines.append(f"- [{a.get('severity')}] **{a.get('rule')}** — {a.get('message')}")
    else:
        lines.append("- (none)")
    lines += [
        "",
        "## Notes",
        "",
        "- Latency is measured on this machine; the VM is RAM-starved, "
        "so English p95 above 3 s is expected here (see docs/PRODUCTION.md §4).",
        "- A day with zero requests means the API was not running, or "
        "no one used it — check the uptime, not just this file.",
        "",
    ]

    reports_dir = data_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    out_path = reports_dir / f"daily-{date_str}.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Daily report written: {out_path}")
    print(f"  requests={total} chats={chats} errors_5xx={errors_5xx} "
          f"failed_logins={failed_logins} rbac_denials={rbac} alerts={len(alerts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
