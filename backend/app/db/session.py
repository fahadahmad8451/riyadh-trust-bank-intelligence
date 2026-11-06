"""Database engine/session — Sprint 1.

PostgreSQL (local, no Docker) when DATABASE_URL points at Postgres and
the server is reachable; otherwise the SQLite fallback from config.
init_db() creates the tables from Design section 4 and, on PostgreSQL,
tries CREATE EXTENSION vector (pgvector) — failure is logged, not fatal:
the local file vector store works without it.
"""
import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.models import Base

logger = logging.getLogger("rtb.db")

_engine = None
_Session = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, pool_pre_ping=True)
    return _engine


def get_session():
    global _Session
    if _Session is None:
        _Session = sessionmaker(bind=get_engine())
    return _Session()


def is_postgres() -> bool:
    return settings.database_url.startswith("postgresql")


def init_db() -> dict:
    """Create tables; try the pgvector extension on Postgres. Returns a
    status dict so callers (and tests) can see what actually happened."""
    engine = get_engine()
    status = {"database_url": settings.database_url, "pgvector": False, "tables": False}
    if is_postgres():
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            status["pgvector"] = True
        except Exception as exc:  # noqa: BLE001 — extension is optional
            logger.warning("pgvector extension not available: %s", exc)
    Base.metadata.create_all(engine)
    status["tables"] = True
    return status
