"""Monitoring store — v0.9 (Monitoring phase).

Request metrics and alerts live in the SAME JSONL-primary pattern as
the audit log (Sprint 3): no Postgres, no external service, budget $0.

  * metrics.jsonl — one JSON object per request: ts, endpoint, method,
    status, latency_ms, role. Appended by the middleware in app/main.py.
    Rotation: at most 10,000 lines; older lines are archived to
    archives/metrics-<timestamp>.jsonl.gz (see scripts/rotate_logs.py).
  * alerts.jsonl — one JSON object per alert: id, ts, rule, severity,
    message, status (active/acknowledged), acknowledged_by/at.

Paths resolve at CALL time (RTB_METRICS_FILE / RTB_ALERTS_FILE env
overrides win, else RTB_DATA_DIR — same precedence pattern as
app/core/audit.py), so tests can point them at tmp files without
touching real data. Nothing here ever raises into a request: the
middleware wraps record_request() in try/except.
"""
import gzip
import json
import logging
import os
import re
import shutil
import statistics
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("rtb.monitoring")

MAX_METRIC_LINES = 10_000
ARCHIVE_KEEP = 7  # max gz archives per file (see scripts/rotate_logs.py)
ALERT_COOLDOWN_MINUTES = 30  # same rule: no duplicate active alert inside this window


def metrics_path() -> Path:
    env = os.getenv("RTB_METRICS_FILE")
    if env:
        return Path(env)
    from app.core.paths import data_dir

    return data_dir() / "metrics.jsonl"


def alerts_path() -> Path:
    env = os.getenv("RTB_ALERTS_FILE")
    if env:
        return Path(env)
    from app.core.paths import data_dir

    return data_dir() / "alerts.jsonl"


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
_ID_LIKE = re.compile(r"^(\d+|[0-9a-f-]{8,})$")


def normalize_endpoint(path: str) -> str:
    """Collapse id-like path segments so /documents/abc-123 counts as
    one endpoint (/documents/{id}) instead of one per document."""
    parts = []
    for seg in (path or "/").split("/"):
        if _ID_LIKE.match(seg):
            parts.append("{id}")
        else:
            parts.append(seg)
    return "/".join(parts) or "/"


def _read_jsonl(path: Path) -> list[dict]:
    entries: list[dict] = []
    if not path.exists():
        return entries
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError as exc:
        logger.warning("Could not read %s: %s", path, exc)
    return entries


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _archive_oldest_lines(path: Path, keep_lines: int) -> str | None:
    """Move the oldest lines of `path` into a gz archive, keeping the
    newest `keep_lines`. Returns the archive filename, or None."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if len(lines) <= keep_lines:
        return None
    archive_dir = path.parent / "archives"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    archive = archive_dir / f"{path.stem}-{stamp}.jsonl.gz"
    with gzip.open(archive, "wt", encoding="utf-8") as gz:
        gz.writelines(lines[: len(lines) - keep_lines])
    path.write_text("".join(lines[len(lines) - keep_lines :]), encoding="utf-8")
    return archive.name


def record_request(endpoint: str, method: str, status: int, latency_ms: float,
                   role: str | None = None) -> None:
    """Append one request metric. Never raises."""
    try:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "endpoint": normalize_endpoint(endpoint),
            "method": (method or "").upper(),
            "status": int(status),
            "latency_ms": round(float(latency_ms), 2),
            "role": role,
        }
        path = metrics_path()
        _append_jsonl(path, record)
        # Rotation check (cheap: only count when the file is big
        # enough that it could plausibly hold 10k lines — ~1 MB).
        if path.stat().st_size > 1_000_000:
            lines = sum(1 for _ in path.open(encoding="utf-8"))
            if lines > MAX_METRIC_LINES:
                _archive_oldest_lines(path, MAX_METRIC_LINES // 2)
    except Exception as exc:  # noqa: BLE001 — monitoring must never break a request
        logger.warning("Could not record request metric: %s", exc)


def read_metrics() -> list[dict]:
    return _read_jsonl(metrics_path())


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(pct / 100.0 * len(ordered))))
    return round(float(ordered[idx]), 2)


def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


def summarize_metrics(entries: list[dict], uptime_seconds: float,
                      feedback: dict | None = None,
                      audit_entries: list[dict] | None = None) -> dict:
    """Aggregate summary over ALL recorded metrics (whole file)."""
    total = len(entries)
    by_endpoint: dict[str, int] = {}
    by_status: dict[str, int] = {}
    latencies: list[float] = []
    chat_latencies: list[float] = []
    errors_5xx = 0
    errors_4xx = 0
    chats = 0
    for e in entries:
        ep = e.get("endpoint", "?")
        by_endpoint[ep] = by_endpoint.get(ep, 0) + 1
        st = e.get("status")
        by_status[str(st)] = by_status.get(str(st), 0) + 1
        lat = e.get("latency_ms")
        if isinstance(lat, (int, float)):
            latencies.append(float(lat))
            if ep == "/api/v1/chat":
                chat_latencies.append(float(lat))
        if isinstance(st, int):
            if st >= 500:
                errors_5xx += 1
            elif st >= 400:
                errors_4xx += 1
        if ep == "/api/v1/chat" and e.get("method") == "POST":
            chats += 1
    fb = feedback or {"total": 0, "up": 0, "down": 0}
    audit = audit_entries if audit_entries is not None else []
    failed_logins = sum(
        1 for a in audit
        if a.get("action") == "LOGIN" and a.get("result") == "fail"
    )
    rbac_refusals = count_rbac_denials(audit)
    return {
        "total_requests": total,
        "requests_by_endpoint": dict(sorted(by_endpoint.items(), key=lambda kv: -kv[1])),
        "requests_by_status": dict(sorted(by_status.items())),
        "errors_5xx": errors_5xx,
        "errors_4xx": errors_4xx,
        "error_rate_5xx": round(errors_5xx / total, 4) if total else 0.0,
        "latency_ms_p50": _percentile(latencies, 50),
        "latency_ms_p95": _percentile(latencies, 95),
        "chat_latency_ms_p50": _percentile(chat_latencies, 50),
        "chat_latency_ms_p95": _percentile(chat_latencies, 95),
        "chats_total": chats,
        "rbac_refusals_total": rbac_refusals,
        "failed_logins_total": failed_logins,
        "feedback_total": fb.get("total", 0),
        "feedback_up": fb.get("up", 0),
        "feedback_down": fb.get("down", 0),
        "uptime_seconds": round(float(uptime_seconds), 2),
    }


def timeseries(entries: list[dict], hours: int = 24,
               now: datetime | None = None) -> list[dict]:
    """Per-hour buckets for the last `hours` hours (oldest first).
    Each bucket: hour (UTC ISO), requests, errors_5xx, chats, p95_ms."""
    now = now or datetime.now(timezone.utc)
    start = (now - timedelta(hours=hours)).replace(minute=0, second=0, microsecond=0)
    buckets: dict[str, dict] = {}
    cursor = start
    while cursor <= now:
        key = cursor.strftime("%Y-%m-%dT%H:00:00Z")
        buckets[key] = {"hour": key, "requests": 0, "errors_5xx": 0,
                        "chats": 0, "_lat": []}
        cursor += timedelta(hours=1)
    for e in entries:
        ts = _parse_ts(e.get("ts"))
        if ts is None or ts < start:
            continue
        key = ts.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:00:00Z")
        bucket = buckets.get(key)
        if bucket is None:
            continue
        bucket["requests"] += 1
        if isinstance(e.get("status"), int) and e["status"] >= 500:
            bucket["errors_5xx"] += 1
        if e.get("endpoint") == "/api/v1/chat" and e.get("method") == "POST":
            bucket["chats"] += 1
        lat = e.get("latency_ms")
        if isinstance(lat, (int, float)):
            bucket["_lat"].append(float(lat))
    out = []
    for b in buckets.values():
        out.append({
            "hour": b["hour"],
            "requests": b["requests"],
            "errors_5xx": b["errors_5xx"],
            "chats": b["chats"],
            "p95_ms": _percentile(b["_lat"], 95),
        })
    return out


def recent_errors(entries: list[dict], limit: int = 20) -> list[dict]:
    """Newest 5xx requests first (no body, no user data — endpoint +
    status + latency + time only)."""
    errs = [e for e in entries if isinstance(e.get("status"), int) and e["status"] >= 500]
    errs.sort(key=lambda e: e.get("ts", ""), reverse=True)
    return errs[:limit]


# ---------------------------------------------------------------------------
# Audit-derived counters (used by summary, alerts and daily reports)
# ---------------------------------------------------------------------------
def count_rbac_denials(audit_entries: list[dict], since: datetime | None = None) -> int:
    """RBAC denials = explicit ACCESS_DENIED entries + chat QUERY
    entries whose detail says refused=True (the Sprint 2/3 refusal).
    The v0.8 honest note applies: a refusal is only counted when the
    RBAC detector actually triggered — an AML-flavoured question that
    retrieved only RETAIL chunks is NOT a denial (no leak, no refusal)."""
    count = 0
    for a in audit_entries:
        if since is not None:
            ts = _parse_ts(a.get("ts"))
            if ts is None or ts < since:
                continue
        if a.get("action") == "ACCESS_DENIED":
            count += 1
        elif a.get("action") == "QUERY" and "refused=True" in str(a.get("detail") or ""):
            count += 1
    return count


def count_failed_logins(audit_entries: list[dict], since: datetime | None = None) -> int:
    count = 0
    for a in audit_entries:
        if a.get("action") != "LOGIN" or a.get("result") != "fail":
            continue
        if since is not None:
            ts = _parse_ts(a.get("ts"))
            if ts is None or ts < since:
                continue
        count += 1
    return count


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------
def read_alerts() -> list[dict]:
    return _read_jsonl(alerts_path())


def create_alert(rule: str, severity: str, message: str, context: dict | None = None) -> dict:
    """Create an alert, unless the same rule already has an ACTIVE
    alert inside the cooldown window (no alert spam every 5 min).
    Returns the alert dict (new or the existing one)."""
    now = datetime.now(timezone.utc)
    existing = read_alerts()
    for a in existing:
        if a.get("rule") != rule or a.get("status") != "active":
            continue
        ts = _parse_ts(a.get("ts"))
        if ts and (now - ts) < timedelta(minutes=ALERT_COOLDOWN_MINUTES):
            return a
    alert = {
        "id": str(uuid.uuid4()),
        "ts": now.isoformat(),
        "rule": rule,
        "severity": severity,
        "message": message,
        "status": "active",
        "context": context or {},
        "acknowledged_by": None,
        "acknowledged_at": None,
    }
    try:
        _append_jsonl(alerts_path(), alert)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not write alert: %s", exc)
    return alert


def acknowledge_alert(alert_id: str, by_email: str) -> dict | None:
    """Mark an alert acknowledged. Returns the updated alert, or None
    if the id does not exist. Rewrites the file (alerts are few)."""
    path = alerts_path()
    alerts = _read_jsonl(path)
    updated = None
    for a in alerts:
        if a.get("id") == alert_id:
            a["status"] = "acknowledged"
            a["acknowledged_by"] = by_email
            a["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
            updated = a
    if updated is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(a, ensure_ascii=False) + "\n" for a in alerts),
            encoding="utf-8",
        )
    return updated


# ---------------------------------------------------------------------------
# System info (real values, no model loading)
# ---------------------------------------------------------------------------
def disk_info() -> dict:
    from app.core.paths import data_dir

    try:
        usage = shutil.disk_usage(data_dir())
        pct = round(100.0 * usage.used / usage.total, 1) if usage.total else None
        return {
            "total_gb": round(usage.total / (1024 ** 3), 2),
            "used_gb": round(usage.used / (1024 ** 3), 2),
            "free_gb": round(usage.free / (1024 ** 3), 2),
            "used_percent": pct,
        }
    except OSError as exc:
        return {"error": str(exc), "used_percent": None}


def data_dir_size_mb() -> float | None:
    from app.core.paths import data_dir

    total = 0
    try:
        for root, _dirs, files in os.walk(data_dir()):
            for f in files:
                try:
                    total += (Path(root) / f).stat().st_size
                except OSError:
                    continue
        return round(total / (1024 * 1024), 2)
    except OSError:
        return None
