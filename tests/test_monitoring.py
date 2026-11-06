"""v0.9 tests — Monitoring (metrics, alerts, rules, rotation).

Run (from backend/):  python -m pytest ../tests/test_monitoring.py -v

Isolation: user/audit/refresh/metrics/alerts files point at tmp
files (same pattern as tests/test_production.py) so these tests
never touch real data/. The alert RULES are tested as pure
functions on synthetic entries (no server needed); the endpoints
are tested live through TestClient; monitor_check.py is tested in
a subprocess against a dead port (exit 2 + api_down alert).

Covers: metrics recording + role, /admin/metrics summary (admin
only, 403 non-admin, 401 anonymous), timeseries buckets, alerts
list + acknowledge (403/404), every alert rule firing AND not
firing below threshold, alert cooldown dedup, monitor_check exit 2
on a down API, log rotation.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # for `import scripts.rotate_logs`
ADMIN = ("admin@rtb.local", "Admin123!")


@pytest.fixture(scope="module")
def isolated_env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("monitoring")
    os.environ["RTB_USERS_FILE"] = str(tmp / "users.json")
    os.environ["RTB_AUDIT_FILE"] = str(tmp / "audit.jsonl")
    os.environ["RTB_REFRESH_FILE"] = str(tmp / "refresh.json")
    os.environ["RTB_DENYLIST_FILE"] = str(tmp / "denylist.json")
    os.environ["RTB_METRICS_FILE"] = str(tmp / "metrics.jsonl")
    os.environ["RTB_ALERTS_FILE"] = str(tmp / "alerts.jsonl")
    os.environ["RTB_DATA_DIR"] = str(tmp)
    from app.core.users import seed_users

    seed_users(force=True)
    yield tmp
    # Restore: later test modules must not inherit our tmp data dir.
    for key in ("RTB_METRICS_FILE", "RTB_ALERTS_FILE", "RTB_DATA_DIR"):
        os.environ.pop(key, None)


@pytest.fixture(scope="module")
def client(isolated_env):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_monitoring_files(isolated_env):
    """Each test starts with empty metrics/alerts files."""
    for name in ("metrics.jsonl", "alerts.jsonl"):
        path = isolated_env / name
        if path.exists():
            path.unlink()
    yield


def _login(client, email, password):
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['data']['access_token']}"}


def _metric_entries(isolated_env, name="metrics.jsonl"):
    path = isolated_env / name
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _now_iso(minutes_ago: float = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _metric(ts, endpoint="/api/v1/chat", status=200, latency_ms=100.0, method="POST"):
    return {"ts": ts, "endpoint": endpoint, "method": method,
            "status": status, "latency_ms": latency_ms, "role": "ADMIN"}


def _failed_login(ts):
    return {"ts": ts, "user": "x@rtb.local", "role": None, "action": "LOGIN",
            "resource": "/api/v1/auth/login", "result": "fail",
            "detail": "invalid credentials", "ip": "127.0.0.1"}


# ---------------------------------------------------------------------------
# 1-2. Metrics recording (middleware)
# ---------------------------------------------------------------------------
def test_metrics_recorded_on_requests(client, isolated_env):
    client.get("/api/v1/health")
    client.get("/api/v1/health")
    entries = _metric_entries(isolated_env)
    health = [e for e in entries if e["endpoint"] == "/api/v1/health"]
    assert len(health) >= 2, entries
    assert all(e["status"] == 200 and e["latency_ms"] >= 0 for e in health)
    assert all(e["method"] == "GET" for e in health)


def test_metrics_role_recorded_for_authenticated_requests(client, isolated_env):
    headers = _login(client, *ADMIN)
    client.get("/api/v1/admin/metrics", headers=headers)
    entries = _metric_entries(isolated_env)
    admin_calls = [e for e in entries
                   if e["endpoint"] == "/api/v1/admin/metrics" and e["role"] == "ADMIN"]
    assert len(admin_calls) >= 1, entries


# ---------------------------------------------------------------------------
# 3-5. /admin/metrics summary + auth
# ---------------------------------------------------------------------------
def test_metrics_summary_admin(client):
    headers = _login(client, *ADMIN)
    client.get("/api/v1/health")
    res = client.get("/api/v1/admin/metrics", headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    for key in ("total_requests", "requests_by_endpoint", "error_rate_5xx",
                "latency_ms_p50", "latency_ms_p95", "chats_total",
                "rbac_refusals_total", "failed_logins_total", "feedback_total",
                "uptime_seconds"):
        assert key in data, key
    assert data["total_requests"] >= 1
    assert data["uptime_seconds"] >= 0


def test_metrics_forbidden_for_non_admin(client):
    res = client.post("/api/v1/auth/register", json={
        "full_name": "Service User", "email": "mon-service@rtb.local",
        "password": "Pass1234", "confirm_password": "Pass1234"})
    assert res.status_code == 201, res.text
    headers = {"Authorization": f"Bearer {res.json()['data']['access_token']}"}
    res = client.get("/api/v1/admin/metrics", headers=headers)
    assert res.status_code == 403, res.text


def test_metrics_unauthenticated_401(client):
    res = client.get("/api/v1/admin/metrics")
    assert res.status_code == 401, res.text


# ---------------------------------------------------------------------------
# 6. Timeseries buckets
# ---------------------------------------------------------------------------
def test_timeseries_buckets(client):
    headers = _login(client, *ADMIN)
    client.get("/api/v1/health")
    res = client.get("/api/v1/admin/metrics/timeseries?hours=2", headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["hours"] == 2
    assert len(data["buckets"]) == 3, data["buckets"]  # start hour .. now hour
    for b in data["buckets"]:
        for key in ("hour", "requests", "errors_5xx", "chats", "p95_ms"):
            assert key in b, key


# ---------------------------------------------------------------------------
# 7-9. Alerts list + acknowledge
# ---------------------------------------------------------------------------
def test_alerts_list_and_acknowledge(client, isolated_env):
    headers = _login(client, *ADMIN)
    res = client.get("/api/v1/admin/alerts", headers=headers)
    assert res.status_code == 200 and res.json()["data"]["count"] == 0
    from app.core.monitoring import create_alert

    alert = create_alert("disk_usage", "MEDIUM", "test alert")
    res = client.get("/api/v1/admin/alerts", headers=headers)
    assert res.json()["data"]["count"] == 1
    res = client.post(f"/api/v1/admin/alerts/{alert['id']}/acknowledge", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["data"]["alert"]["status"] == "acknowledged"
    assert res.json()["data"]["alert"]["acknowledged_by"] == ADMIN[0]


def test_acknowledge_unknown_alert_404(client):
    headers = _login(client, *ADMIN)
    res = client.post("/api/v1/admin/alerts/no-such-id/acknowledge", headers=headers)
    assert res.status_code == 404, res.text


def test_alerts_forbidden_for_non_admin(client):
    res = client.post("/api/v1/auth/register", json={
        "full_name": "Service Two", "email": "mon-service2@rtb.local",
        "password": "Pass1234", "confirm_password": "Pass1234"})
    assert res.status_code == 201, res.text
    headers = {"Authorization": f"Bearer {res.json()['data']['access_token']}"}
    assert client.get("/api/v1/admin/alerts", headers=headers).status_code == 403


# ---------------------------------------------------------------------------
# 10-14. Alert rules (pure functions, synthetic data — fires AND not)
# ---------------------------------------------------------------------------
def test_brute_force_rule_fires_at_threshold():
    from app.monitoring.alert_rules import evaluate

    now = datetime.now(timezone.utc)
    # 10 failures inside the 5-minute window (24 s apart).
    audit = [_failed_login(_now_iso(m * 0.4)) for m in range(10)]
    fired = evaluate([], audit, health_ok=True, disk_pct=10.0, now=now)
    assert any(a["rule"] == "brute_force" and a["severity"] == "HIGH" for a in fired)
    audit9 = [_failed_login(_now_iso(m * 0.4)) for m in range(9)]
    fired9 = evaluate([], audit9, health_ok=True, disk_pct=10.0, now=now)
    assert not any(a["rule"] == "brute_force" for a in fired9), "9 failures must not fire"
    old = [_failed_login(_now_iso(30 + m)) for m in range(10)]  # 30 min ago
    fired_old = evaluate([], old, health_ok=True, disk_pct=10.0, now=now)
    assert not any(a["rule"] == "brute_force" for a in fired_old), "old failures must not fire"


def test_error_rate_rule_needs_volume_and_threshold():
    from app.monitoring.alert_rules import evaluate

    now = datetime.now(timezone.utc)
    ts = _now_iso(10)
    many = [_metric(ts, status=500) for _ in range(6)] + \
           [_metric(ts, status=200) for _ in range(94)]
    fired = evaluate(many, [], health_ok=True, disk_pct=10.0, now=now)
    assert any(a["rule"] == "error_rate" for a in fired), "6% 5xx must fire"
    few = [_metric(ts, status=500)] + [_metric(ts, status=200) for _ in range(9)]
    assert not any(a["rule"] == "error_rate"
                   for a in evaluate(few, [], health_ok=True, disk_pct=10.0, now=now)), \
        "10 requests is below the 20-request minimum"


def test_p95_latency_rule():
    from app.monitoring.alert_rules import evaluate

    now = datetime.now(timezone.utc)
    ts = _now_iso(10)
    slow = [_metric(ts, latency_ms=12000.0) for _ in range(20)]
    fired = evaluate(slow, [], health_ok=True, disk_pct=10.0, now=now)
    assert any(a["rule"] == "p95_latency" for a in fired), "12s p95 must fire"
    fast = [_metric(ts, latency_ms=500.0) for _ in range(20)]
    assert not any(a["rule"] == "p95_latency"
                   for a in evaluate(fast, [], health_ok=True, disk_pct=10.0, now=now))


def test_rbac_spike_and_api_down_and_disk_rules():
    from app.monitoring.alert_rules import evaluate

    now = datetime.now(timezone.utc)
    ts = _now_iso(10)
    denied = [{"ts": ts, "action": "ACCESS_DENIED", "result": "denied"}
              for _ in range(21)]
    fired = evaluate([], denied, health_ok=True, disk_pct=10.0, now=now)
    assert any(a["rule"] == "rbac_spike" for a in fired), "21 denials must fire"
    fired20 = evaluate([], denied[:20], health_ok=True, disk_pct=10.0, now=now)
    assert not any(a["rule"] == "rbac_spike" for a in fired20), "20 is not > 20"
    down = evaluate([], [], health_ok=False, disk_pct=10.0, now=now)
    assert any(a["rule"] == "api_down" and a["severity"] == "CRITICAL" for a in down)
    assert not any(a["rule"] == "api_down"
                   for a in evaluate([], [], health_ok=True, disk_pct=10.0, now=now))
    assert any(a["rule"] == "disk_usage"
               for a in evaluate([], [], health_ok=True, disk_pct=85.0, now=now))
    assert not any(a["rule"] == "disk_usage"
                   for a in evaluate([], [], health_ok=True, disk_pct=50.0, now=now))


# ---------------------------------------------------------------------------
# 15. Alert cooldown — no duplicate active alert for the same rule
# ---------------------------------------------------------------------------
def test_alert_cooldown_dedup(isolated_env):
    from app.core.monitoring import create_alert, read_alerts

    first = create_alert("error_rate", "HIGH", "first")
    second = create_alert("error_rate", "HIGH", "second — must be deduped")
    assert first["id"] == second["id"], "same rule inside 30 min must return the same alert"
    assert len(read_alerts()) == 1


# ---------------------------------------------------------------------------
# 16. monitor_check.py — down API -> exit 2 + CRITICAL api_down alert
# ---------------------------------------------------------------------------
def test_monitor_check_down_api_exit_2(isolated_env, tmp_path):
    env = dict(os.environ)
    env["RTB_DATA_DIR"] = str(isolated_env)
    proc = subprocess.run(
        [sys.executable, "scripts/monitor_check.py",
         "--port", "59999", "--data-dir", str(isolated_env)],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "DOWN" in proc.stdout
    alerts = _metric_entries(isolated_env, "alerts.jsonl")
    assert any(a.get("rule") == "api_down" and a.get("severity") == "CRITICAL"
               for a in alerts), alerts


# ---------------------------------------------------------------------------
# 17. Log rotation
# ---------------------------------------------------------------------------
def test_rotate_logs_archives_old_lines(tmp_path):
    from scripts.rotate_logs import rotate_file

    path = tmp_path / "metrics.jsonl"
    path.write_text("".join(f'{{"n": {i}}}\n' for i in range(12)), encoding="utf-8")
    msg = rotate_file(path, max_lines=10, keep_lines=5, keep_archives=2)
    assert "archived 7 lines" in msg, msg
    kept = path.read_text(encoding="utf-8").splitlines()
    assert len(kept) == 5 and json.loads(kept[0])["n"] == 7
    archives = list((tmp_path / "archives").glob("metrics-*.jsonl.gz"))
    assert len(archives) == 1
    import gzip

    archived = gzip.open(archives[0], "rt", encoding="utf-8").read().splitlines()
    assert len(archived) == 7 and json.loads(archived[0])["n"] == 0


# ---------------------------------------------------------------------------
# 18-19. Overview + recent errors endpoints
# ---------------------------------------------------------------------------
def test_monitoring_overview_admin(client):
    headers = _login(client, *ADMIN)
    res = client.get("/api/v1/admin/monitoring/overview", headers=headers)
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    for key in ("health", "summary", "disk", "data_dir_mb",
                "alerts_active", "alerts_total", "recent_errors"):
        assert key in data, key
    assert data["health"]["status"] == "ok"
    assert data["disk"]["used_percent"] is not None


def test_recent_errors_empty_when_no_5xx(client):
    headers = _login(client, *ADMIN)
    res = client.get("/api/v1/admin/monitoring/recent-errors", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["data"]["count"] == 0
