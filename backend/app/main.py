"""FastAPI entrypoint — Riyadh Trust Bank Enterprise Intelligence Platform.

Setup v0.1, NO Docker required. Runs on plain Windows:
    python -m venv venv
    venv\\Scripts\\activate
    pip install -r requirements.txt
    uvicorn app.main:app --reload --port 8000

Real, working: /api/v1/health and /api/v1/metrics, plus auth, admin,
documents, chat (Sprints 1-3) and feedback + evaluation (Sprint 4).
No 501 stubs remain — see app/api/v1/stubs.py (empty in v0.5).
Health is OK without PostgreSQL, Redis, Celery or Ollama — those are
optional in Setup and are wired in Sprints 1-3.
"""
import json
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import admin, auth, chat, documents, eval, feedback, monitoring, stubs
from app.core.config import settings

STARTED_AT = time.time()
IMPLEMENTED = [
    "/api/v1/health",
    "/api/v1/metrics",
    "GET /api/v1/documents (Sprint 1)",
    "POST /api/v1/documents/upload (Sprint 1, ADMIN-only in Sprint 3)",
    "GET /api/v1/documents/{id} (Sprint 3)",
    "DELETE /api/v1/documents/{id} (Sprint 3, ADMIN-only)",
    "POST /api/v1/chat (Sprint 2, auth + RBAC in Sprint 3)",
    "GET /api/v1/conversations (Sprint 2, auth in Sprint 3)",
    "GET /api/v1/conversations/{id} (Sprint 2, auth in Sprint 3)",
    "POST /api/v1/auth/login (Sprint 3)",
    "POST /api/v1/auth/register (v0.7, auto-login, CUSTOMER_SERVICE default)",
    "PUT /api/v1/admin/users/{email}/role (v0.7, ADMIN only)",
    "POST /api/v1/auth/refresh (Sprint 3)",
    "POST /api/v1/auth/logout (Sprint 3)",
    "GET /api/v1/auth/me (Sprint 3)",
    "GET /api/v1/admin/users (Sprint 3)",
    "GET /api/v1/admin/audit-logs (Sprint 3)",
    "POST /api/v1/feedback (Sprint 4)",
    "GET /api/v1/admin/feedback-stats (Sprint 4)",
    "GET /api/v1/eval/run (Sprint 4)",
    "GET /api/v1/eval/results (Sprint 4)",
    "Production hardening v0.8: demo accounts off in prod, security headers, "
    "login/register rate limiting, 10 MB upload limit, extended /health",
    "Monitoring v0.9: request metrics (metrics.jsonl), alert rules, "
    "GET /api/v1/admin/metrics + /timeseries + /alerts + /monitoring/overview",
]
PENDING = [f"{m} {p} ({s})" for m, p, s, _ in stubs.STUBS]


def envelope(data, request_id: str) -> dict:
    return {"success": True, "data": data, "error": None, "request_id": request_id}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup: no DB/Redis/Ollama connection here on purpose.
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    docs_url="/docs",
    lifespan=lifespan,
)

# Staging (v0.6): the built frontend calls the API directly
# (VITE_API_URL), so cross-origin requests from the local web ports
# must be allowed. Dev is unaffected (same-origin via the Vite proxy).
# Production must set CORS_ORIGINS to its own origin only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def record_metrics_middleware(request: Request, call_next):
    """Monitoring (v0.9): record every request (endpoint, method,
    status, latency, role) into metrics.jsonl. Best-effort only — a
    monitoring failure must never break the request itself. The role
    comes from the access token when present; public requests have
    role None. Runs OUTSIDE add_request_id so the latency measured
    here covers the whole request."""
    started = time.time()
    response = await call_next(request)
    try:
        from app.core.monitoring import record_request
        from app.core.security import decode_access_token

        role = None
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            payload = decode_access_token(auth_header[7:].strip())
            if payload:
                role = payload.get("role")
        record_request(
            endpoint=request.url.path,
            method=request.method,
            status=response.status_code,
            latency_ms=(time.time() - started) * 1000,
            role=role,
        )
    except Exception:  # noqa: BLE001 — monitoring never breaks a request
        pass
    return response


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    # Production (v0.8) security headers on EVERY response. No
    # Content-Security-Policy here on purpose: the Vite SPA serves
    # its own assets and an over-strict CSP would break the UI; the
    # three headers below are safe for this app. The "Server" header
    # is stripped by uvicorn itself — production start scripts use
    # --no-server-header (see scripts/production_start.*); if a
    # reverse proxy ever adds one, remove it there too.
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if "server" in response.headers:
        del response.headers["server"]
    return response


def _health_extras() -> dict:
    """Cheap, honest status for /health — file reads only, NO model
    loading and NO Ollama probe (health must answer in milliseconds).
    Embeddings info comes from the recorded embedding_config.json
    written at index time; if the store was never indexed it says so.
    Generation mode is the CONFIGURED mode: "ollama-configured" only
    means OLLAMA_HOST is set — Ollama may still be unreachable at
    chat time, in which case answers fall back to extractive mode
    (the response itself says which mode was used)."""
    from app.core.paths import data_dir

    d = data_dir()
    embeddings = {"model": "not indexed yet", "dim": None, "backend": None}
    cfg_path = d / "vector_store" / "embedding_config.json"
    try:
        if cfg_path.exists():
            embeddings = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        embeddings = {"model": "unreadable embedding_config.json", "dim": None, "backend": None}
    docs_count = None
    chunks_count = None
    try:
        manifest_path = d / "docs_manifest.json"
        if manifest_path.exists():
            docs_count = len(json.loads(manifest_path.read_text(encoding="utf-8")).get("documents", []))
        chunks_path = d / "chunks.jsonl"
        if chunks_path.exists():
            with chunks_path.open(encoding="utf-8") as fh:
                chunks_count = sum(1 for _ in fh)
    except (OSError, ValueError):
        pass
    vector_ok = docs_count is not None and chunks_count is not None and chunks_count > 0
    return {
        "uptime_seconds": round(time.time() - STARTED_AT, 2),
        "demo_accounts_enabled": settings.demo_accounts_enabled,
        "reranker": settings.reranker_mode,
        "embeddings": embeddings,
        "vector_store": {
            "status": "ok" if vector_ok else "not indexed",
            "documents": docs_count,
            "chunks": chunks_count,
        },
        "generation_mode": (
            "ollama-configured" if settings.ollama_host else "extractive-fallback"
        ),
        "database": (
            "postgresql" if settings.database_url.startswith("postgresql")
            else "sqlite (local file)"
        ),
    }


@app.get("/api/v1/health")
async def health(request: Request):
    return JSONResponse(
        envelope(
            {
                "status": "ok",
                "service": settings.app_name,
                "version": settings.version,
                "environment": settings.environment,
                **_health_extras(),
            },
            request.headers.get("X-Request-ID", str(uuid.uuid4())),
        )
    )


@app.get("/api/v1/metrics")
async def metrics(request: Request):
    return JSONResponse(
        envelope(
            {
                "uptime_seconds": round(time.time() - STARTED_AT, 2),
                "version": settings.version,
                "environment": settings.environment,
                "endpoints_implemented": IMPLEMENTED,
                "endpoints_pending": PENDING,
            },
            request.headers.get("X-Request-ID", str(uuid.uuid4())),
        )
    )


app.include_router(auth.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(monitoring.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(feedback.router, prefix="/api/v1")
app.include_router(eval.router, prefix="/api/v1")
app.include_router(stubs.router, prefix="/api/v1")
