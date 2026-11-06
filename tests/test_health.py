"""Setup v0.1 smoke test — /api/v1/health must return 200 + status ok.

Run (from backend/):  python -m pytest ../tests/test_health.py -v
No database, Redis, Celery or Ollama needed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_200_and_ok():
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["data"]["status"] == "ok"
    assert body["data"]["version"] == "0.10.2"


def test_metrics_lists_pending_endpoints():
    res = client.get("/api/v1/metrics")
    assert res.status_code == 200
    assert "/api/v1/health" in res.json()["data"]["endpoints_implemented"]


def test_no_endpoints_left_unimplemented():
    # Sprint 4 implemented the last stubs (feedback + evaluation), so
    # /api/v1/metrics must report an empty pending list in v0.5+.
    # (v0.6 is Staging: same endpoints, staging env/config only.)
    # (Replaces the old 501 test: there is no unimplemented endpoint
    # left to return 501, and inventing one would be a fake test.)
    res = client.get("/api/v1/metrics")
    assert res.status_code == 200
    assert res.json()["data"]["endpoints_pending"] == []
