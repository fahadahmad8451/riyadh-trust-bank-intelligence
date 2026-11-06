"""Alert rules — v0.9 (Monitoring phase).

Pure functions: evaluate() takes already-loaded metric + audit
entries and returns the alerts that SHOULD fire (dicts without id /
status — the store assigns those). Pure on purpose, so tests can feed
synthetic entries and prove each rule triggers (and does NOT trigger
below its threshold) without a running server.

Rules (threshold + severity + what to do — see docs/MONITORING.md):
  brute_force   10+ failed logins in 5 min            HIGH
  error_rate    5xx rate > 5% over the last hour
                (needs >= 20 requests, else noise)    HIGH
  p95_latency   chat p95 latency > 10 s (last hour)   MEDIUM
  rbac_spike    > 20 RBAC denials in 1 hour           MEDIUM
  api_down      health endpoint unreachable / not ok  CRITICAL
  disk_usage    disk used > 80%                       MEDIUM
"""
from datetime import datetime, timedelta, timezone

from app.core.monitoring import (
    _parse_ts,
    _percentile,
    count_failed_logins,
    count_rbac_denials,
)

RULES = [
    {"rule": "brute_force", "severity": "HIGH",
     "threshold": "10+ failed logins in 5 minutes",
     "action": "Check the audit log for the source IPs; the login rate limiter (5/min per email) already slows the attacker. Consider blocking the IP at the firewall."},
    {"rule": "error_rate", "severity": "HIGH",
     "threshold": "5xx rate > 5% over the last hour (min 20 requests)",
     "action": "Check the recent-errors list and the API logs; look for the failing endpoint and the first time it failed."},
    {"rule": "p95_latency", "severity": "MEDIUM",
     "threshold": "chat p95 latency > 10 s over the last hour",
     "action": "The cross-encoder reranker is the usual cause on low-RAM machines. Test RTB_RERANKER=off (see docs/PRODUCTION.md §4) and compare."},
    {"rule": "rbac_spike", "severity": "MEDIUM",
     "threshold": "> 20 RBAC denials in 1 hour",
     "action": "Look at which users/roles are being denied — either an attack probe or a role that legitimately needs more access (Admin can raise the role)."},
    {"rule": "api_down", "severity": "CRITICAL",
     "threshold": "health endpoint unreachable or status != ok",
     "action": "Restart the API (scripts/production_start.sh / .ps1). If it fails to start, read the startup error — a weak SECRET_KEY or wildcard CORS refuses to start by design."},
    {"rule": "disk_usage", "severity": "MEDIUM",
     "threshold": "disk used > 80%",
     "action": "Run scripts/rotate_logs.py to archive old logs, and delete old backups in backups/."},
]

BRUTE_FORCE_WINDOW_MINUTES = 5
BRUTE_FORCE_MIN = 10
ERROR_RATE_MIN_REQUESTS = 20
ERROR_RATE_THRESHOLD = 0.05
P95_LATENCY_MS = 10_000
RBAC_SPIKE_PER_HOUR = 20
DISK_USAGE_PCT = 80.0


def evaluate(metrics_entries: list[dict], audit_entries: list[dict],
             *, health_ok: bool, disk_pct: float | None,
             now: datetime | None = None) -> list[dict]:
    """Return the alerts that should fire right now. Each dict has
    rule / severity / message / context (no id, no status)."""
    now = now or datetime.now(timezone.utc)
    alerts: list[dict] = []

    # (e) API down — CRITICAL, checked first.
    if not health_ok:
        alerts.append({
            "rule": "api_down", "severity": "CRITICAL",
            "message": "API health check failed — the API is down or unhealthy.",
            "context": {"checked_at": now.isoformat()},
        })

    # (a) Brute force: 10+ failed logins in the last 5 minutes.
    failed_5m = count_failed_logins(
        audit_entries, since=now - timedelta(minutes=BRUTE_FORCE_WINDOW_MINUTES))
    if failed_5m >= BRUTE_FORCE_MIN:
        alerts.append({
            "rule": "brute_force", "severity": "HIGH",
            "message": f"Possible brute force: {failed_5m} failed logins in the last "
                       f"{BRUTE_FORCE_WINDOW_MINUTES} minutes.",
            "context": {"failed_logins_5m": failed_5m},
        })

    hour_ago = now - timedelta(hours=1)
    hour_metrics = [e for e in metrics_entries
                    if (_parse_ts(e.get("ts")) or now) >= hour_ago]

    # (b) Error rate: 5xx > 5% over the last hour (min 20 requests).
    if len(hour_metrics) >= ERROR_RATE_MIN_REQUESTS:
        errors = sum(1 for e in hour_metrics
                     if isinstance(e.get("status"), int) and e["status"] >= 500)
        rate = errors / len(hour_metrics)
        if rate > ERROR_RATE_THRESHOLD:
            alerts.append({
                "rule": "error_rate", "severity": "HIGH",
                "message": f"Error rate {rate:.1%} over the last hour "
                           f"({errors} of {len(hour_metrics)} requests are 5xx).",
                "context": {"error_rate": round(rate, 4),
                            "errors_5xx": errors,
                            "requests_1h": len(hour_metrics)},
            })

    # (c) p95 chat latency > 10 s over the last hour.
    chat_lat = [float(e["latency_ms"]) for e in hour_metrics
                if e.get("endpoint") == "/api/v1/chat"
                and isinstance(e.get("latency_ms"), (int, float))]
    p95 = _percentile(chat_lat, 95)
    if p95 is not None and p95 > P95_LATENCY_MS:
        alerts.append({
            "rule": "p95_latency", "severity": "MEDIUM",
            "message": f"Chat p95 latency is {p95 / 1000:.1f}s over the last hour "
                       f"(threshold 10s, {len(chat_lat)} chats).",
            "context": {"chat_p95_ms": p95, "chats_1h": len(chat_lat)},
        })

    # (d) RBAC denials spike: > 20 in the last hour.
    denials_1h = count_rbac_denials(audit_entries, since=hour_ago)
    if denials_1h > RBAC_SPIKE_PER_HOUR:
        alerts.append({
            "rule": "rbac_spike", "severity": "MEDIUM",
            "message": f"RBAC denials spike: {denials_1h} denials in the last hour.",
            "context": {"rbac_denials_1h": denials_1h},
        })

    # (f) Disk usage > 80%.
    if disk_pct is not None and disk_pct > DISK_USAGE_PCT:
        alerts.append({
            "rule": "disk_usage", "severity": "MEDIUM",
            "message": f"Disk usage is {disk_pct}% (threshold 80%).",
            "context": {"disk_used_percent": disk_pct},
        })

    return alerts
