"""Evaluation API — Sprint 4.

GET /eval/run — ADMIN only. Runs the fixed 20-question eval set
through the real pipeline (as ADMIN, all departments visible) and
stores the report in data/eval_results.json. This is SLOW on this
VM (a few minutes: the cross-encoder and embedding models load, and
each question runs full hybrid retrieval) — the endpoint runs
synchronously and the frontend says so. ?limit=N runs only the
first N questions (used by the automated tests).

GET /eval/results — ADMIN only. Returns the last stored eval report,
or a 404-style error when no eval run has happened yet.

The numbers are local RAGAS-STYLE metrics (see
app/services/evaluation.py) — never presented as official RAGAS
scores. A run that misses the Design targets is reported as-is.
"""
import logging

from fastapi import APIRouter, Depends, Query

from app.core.security import require_admin
from app.services.evaluation import read_eval_results, run_eval

logger = logging.getLogger("rtb.eval")
router = APIRouter()


def _envelope(data, request_id: str = "eval") -> dict:
    return {"success": True, "data": data, "error": None, "request_id": request_id}


@router.get("/eval/run")
async def eval_run(limit: int = Query(default=None, ge=1, le=20),
                   user: dict = Depends(require_admin)):
    report = run_eval(limit=limit)
    return _envelope(report)


@router.get("/eval/results")
async def eval_results(user: dict = Depends(require_admin)):
    report = read_eval_results()
    if report is None:
        return {
            "success": False, "data": None,
            "error": "No eval run yet — run GET /api/v1/eval/run first.",
            "request_id": "eval",
        }
    return _envelope(report)
