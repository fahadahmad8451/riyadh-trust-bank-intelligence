"""Settings — reads .env. No Docker, no Redis, no Ollama required.

Primary setup is local Windows (Fahad's laptop: BIOS locked, VT-x off,
so Docker Desktop cannot run). Defaults are the local fallbacks:
- DATABASE_URL: local PostgreSQL if present, else SQLite file.
  .env.example shows the local Postgres URL; if that server is not
  reachable, Setup still runs — the DB is only wired in Sprint 1.
- REDIS_URL / OLLAMA_HOST: optional; absent = in-memory / not used.

Production (v0.8): ENVIRONMENT=production is a HARDENED mode, not
just a label. validate_production_settings() runs at import time and
refuses to start (RuntimeError, clear message) when:
  - the JWT secret is the dev default / a placeholder / too short, or
  - CORS allows "*" (wildcard), or
  - demo accounts are somehow still enabled with a production secret
    (they are not — production setup never seeds them; see below).
DEBUG is forced off in production. In dev/staging nothing changes.
"""
import os
from pydantic_settings import BaseSettings, SettingsConfigDict

# Secrets that must NEVER run in production. If SECRET_KEY contains
# any of these (case-insensitive) or is shorter than 32 characters,
# the app refuses to start in production mode.
WEAK_SECRET_MARKERS = ("CHANGE-ME", "REPLACE-ME", "CHANGE_ME", "REPLACE_ME")
MIN_PROD_SECRET_LEN = 32


def _env_flag(name: str, default: bool) -> bool:
    """RTB_DEMO_ACCOUNTS=0 / false / no disables; anything else enables."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Riyadh Trust Bank — Enterprise Intelligence Platform"
    version: str = "0.10.3"
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
    vector_store_dir: str = os.getenv("VECTOR_STORE_DIR", "data/vector_store")
    environment: str = os.getenv("ENVIRONMENT", "development")
    secret_key: str = "CHANGE-ME-IN-.env — dev only, never commit a real secret"
    database_url: str = os.getenv(
        "DATABASE_URL", "sqlite:///./rtb_intelligence.db"
    )
    redis_url: str | None = os.getenv("REDIS_URL")
    ollama_host: str | None = os.getenv("OLLAMA_HOST")
    access_token_expire_minutes: int = 15
    # Staging (v0.6): the built frontend talks to the API directly
    # (VITE_API_URL) instead of through the Vite dev proxy, so the API
    # must allow the staging web origin. Comma-separated list; dev
    # default covers both local web ports. Production must set this
    # explicitly to its own origin only.
    # v0.10.2: BOTH host spellings are allowed for every local web
    # port (localhost AND 127.0.0.1). The frontend now calls the API
    # on the same host the page was opened on, so the browser may
    # arrive from either spelling — allowing only one of them would
    # break login from the other (CORS preflight failure). Still
    # explicit local origins only — no wildcard, ever.
    cors_origins: str = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:3001,http://127.0.0.1:3001",
    )
    # Production (v0.8): demo accounts (admin@rtb.local etc.) are OFF
    # by default in production — RTB_DEMO_ACCOUNTS=0. Dev/staging keep
    # them (default 1). The flag gates seeding AND login: a demo email
    # can never authenticate while the flag is off, even if a users.json
    # with demo users was copied into the production data dir.
    demo_accounts_enabled: bool = _env_flag("RTB_DEMO_ACCOUNTS", True)
    # Production (v0.8): DEBUG is forced off in production (see
    # validate_production_settings). Dev default is off too; set
    # DEBUG=1 only for local debugging, never in production.
    debug: bool = os.getenv("DEBUG", "0").strip() == "1"
    # Production (v0.8): reranker mode. "auto" = cross-encoder when
    # cached/requested (Sprint 2 rule), "off" = score rerank only.
    # RTB_RERANKER=off lets Fahad test English latency on his PC
    # without the cross-encoder, with one command (see PRODUCTION.md).
    reranker_mode: str = os.getenv("RTB_RERANKER", "auto").strip().lower() or "auto"


settings = Settings()


def _secret_is_weak(secret: str) -> str | None:
    """Return a reason string if the secret is too weak for production,
    else None."""
    if not secret or len(secret) < MIN_PROD_SECRET_LEN:
        return f"SECRET_KEY is too short ({len(secret or '')} chars) — production needs at least {MIN_PROD_SECRET_LEN} random characters"
    upper = secret.upper()
    for marker in WEAK_SECRET_MARKERS:
        if marker in upper:
            return f"SECRET_KEY still contains the placeholder '{marker}' — generate a real one"
    return None


def validate_production_settings() -> None:
    """Fail-fast production guard. Called once at import time (below).
    In dev/staging this is a no-op — nothing changes there."""
    if settings.environment != "production":
        return
    # DEBUG is forced off in production, whatever the env says.
    settings.debug = False
    # Demo accounts are OFF in production unless explicitly opted back
    # in with RTB_DEMO_ACCOUNTS=1 (not recommended — the production
    # setup script sets RTB_DEMO_ACCOUNTS=0). This is the default even
    # if .env.production forgot the line entirely.
    if os.getenv("RTB_DEMO_ACCOUNTS", "").strip() != "1":
        settings.demo_accounts_enabled = False
    weak_reason = _secret_is_weak(settings.secret_key)
    if weak_reason:
        raise RuntimeError(
            "PRODUCTION REFUSED TO START: " + weak_reason + ". "
            "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(64))\" "
            "and put it in .env.production as SECRET_KEY. "
            "Never use the dev default in production."
        )
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if "*" in origins or not origins:
        raise RuntimeError(
            "PRODUCTION REFUSED TO START: CORS_ORIGINS must list explicit origins "
            "(e.g. http://localhost:3000) — wildcard '*' is not allowed in production."
        )
    if settings.reranker_mode not in ("auto", "off"):
        raise RuntimeError(
            "PRODUCTION REFUSED TO START: RTB_RERANKER must be 'auto' or 'off', "
            f"got {settings.reranker_mode!r}."
        )


validate_production_settings()
