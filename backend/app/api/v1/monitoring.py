"""Monitoring API — v0.9 (ADMIN only, every route).

GET  /admin/metrics                  — summary over all recorded requests
GET  /admin/metrics/timeseries       — per-hour buckets (?hours=24)
GET  /admin/monitoring/overview      — health + summary + disk + alert counts
GET  /admin/monitoring/recent-errors — newest 5xx requests (?limit=20)
GET  /admin/alerts                   — alerts, newest first (?status=active)
POST /admin/alerts/{id}/acknowledge  — mark an alert acknowledged

All data is REAL: recorded request metrics (middleware in
app/main.py), the audit log, feedback.jsonl and the alerts file.
Nothing here is sampled or invented — an empty system honestly
reports zeros. Non-admins get 403 + ACCESS_DENIED audit, exactly
like the other admin routes.
"""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.api.v1.feedback import feedback_stats
from app.core.audit import read_audit
from app.core.monitoring import (
    acknowledge_alert,
    data_dir_size_mb,
    disk_info,
    read_alerts,
    read_metrics,
    recent_errors,
    summarize_metrics,
    timeseries,
)
from app.core.security import require_admin
import time

router = APIRouter()


def _envelope(data: dict) -> dict:
    return {"success": True, "data": data, "error": None, "request_id": "monitoring"}


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"success": False, "data": None, "error": detail,
                 "request_id": "monitoring"},
    )


def _summary() -> dict:
    # Imported here (not at module top): app.main imports this router,
    # so a top-level `from app.main import ...` is a circular import.
    # At request time the app module is fully initialised.
    from app.main import STARTED_AT

    entries = read_metrics()
    audit, _total = read_audit(limit=10000)
    return summarize_metrics(
        entries, uptime_seconds=time.time() - STARTED_AT,
        feedback=feedback_stats(), audit_entries=audit,
    )


@router.get("/admin/metrics")
async def admin_metrics(user: dict = Depends(require_admin)):
    return _envelope(_summary())


@router.get("/admin/metrics/timeseries")
async def admin_metrics_timeseries(
    hours: int = Query(default=24, ge=1, le=168),
    user: dict = Depends(require_admin),
):
    buckets = timeseries(read_metrics(), hours=hours)
    return _envelope({"hours": hours, "buckets": buckets})


@router.get("/admin/monitoring/overview")
async def admin_monitoring_overview(user: dict = Depends(require_admin)):
    from app.core.config import settings
    from app.main import _health_extras

    summary = _summary()
    alerts = read_alerts()
    active = [a for a in alerts if a.get("status") == "active"]
    return _envelope({
        # _health_extras() has no version/environment/service — the
        # /health endpoint adds those itself, so add them here too
        # (the frontend shows "vundefined" without them).
        "health": {"status": "ok", "service": settings.app_name,
                   "version": settings.version,
                   "environment": settings.environment, **_health_extras()},
        "summary": summary,
        "disk": disk_info(),
        "data_dir_mb": data_dir_size_mb(),
        "alerts_active": len(active),
        "alerts_critical_active": len(
            [a for a in active if a.get("severity") == "CRITICAL"]),
        "alerts_high_active": len(
            [a for a in active if a.get("severity") == "HIGH"]),
        "alerts_total": len(alerts),
        "recent_errors": recent_errors(read_metrics(), limit=5),
    })


@router.get("/admin/monitoring/recent-errors")
async def admin_recent_errors(
    limit: int = Query(default=20, ge=1, le=100),
    user: dict = Depends(require_admin),
):
    errs = recent_errors(read_metrics(), limit=limit)
    return _envelope({"errors": errs, "count": len(errs)})


@router.get("/admin/alerts")
async def admin_alerts(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    user: dict = Depends(require_admin),
):
    alerts = read_alerts()
    alerts.sort(key=lambda a: a.get("ts", ""), reverse=True)
    if status:
        alerts = [a for a in alerts if a.get("status") == status]
    return _envelope({
        "alerts": alerts[:limit],
        "count": len(alerts[:limit]),
        "total": len(alerts),
        "active": len([a for a in alerts if a.get("status") == "active"]),
    })


@router.post("/admin/alerts/{alert_id}/acknowledge")
async def admin_acknowledge_alert(alert_id: str, user: dict = Depends(require_admin)):
    updated = acknowledge_alert(alert_id, user["email"])
    if updated is None:
        return _error(404, f"Alert not found: {alert_id}")
    return _envelope({"alert": updated})
