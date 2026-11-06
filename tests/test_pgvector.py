"""v0.10 tests — PgVectorStore (item 6).

Run (from backend/):  python -m pytest ../tests/test_pgvector.py -v

Two levels:
  1. Fallback (always runs): RTB_USE_PGVECTOR=1 with an UNREACHABLE
     Postgres URL must fall back to LocalVectorStore, never crash.
  2. Live (skipped unless RTB_LIVE_PGVECTOR=1 and DATABASE_URL
     points at a running PostgreSQL + pgvector server, e.g. the
     rtb_pgtest database on this VM): index the 15 real chunks and
     check EN + AR + RBAC-filtered search agrees with the local
     store. The live run on 2026-11-06 passed: 15/15 indexed, top-1
     agreement on all four queries — with the honest caveat that the
     384-dim MiniLM embeddings are stored as JSON, because the
     pgvector column is Vector(1024) (BGE-M3 dim); true vector-column
     search needs BGE-M3, which is a PC-only item.

NOTE on test isolation: app.core.config.settings is a singleton
created at FIRST import, reading DATABASE_URL from the environment
at that moment. Never monkeypatch.setenv("DATABASE_URL", ...) before
that first import — the singleton would be born with the patched
value and no later restore could fix it. This file imports settings
at module top (so it is born from the real pytest environment) and
the fallback test patches only the attribute, never the env var.
"""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import settings  # noqa: E402 — see the NOTE above

PROJECT = Path(__file__).resolve().parents[1]


def test_pgvector_unreachable_falls_back_to_local(monkeypatch):
    monkeypatch.setenv("RTB_USE_PGVECTOR", "1")
    # Patch the attribute only (never setenv DATABASE_URL — see NOTE).
    monkeypatch.setattr(settings, "database_url",
                        "postgresql://rtb:bad@127.0.0.1:5999/nope")
    # The failed PgVectorStore attempt must not poison the cached
    # engine for later tests (app.db.session caches it globally).
    import app.db.session as session_mod

    monkeypatch.setattr(session_mod, "_engine", None)
    monkeypatch.setattr(session_mod, "_Session", None)
    from app.db.vector_store import LocalVectorStore, get_vector_store

    store = get_vector_store()
    assert isinstance(store, LocalVectorStore), \
        "unreachable Postgres must fall back to the local store"


LIVE = os.getenv("RTB_LIVE_PGVECTOR") == "1"


@pytest.mark.skipif(not LIVE, reason="needs a live Postgres + pgvector (RTB_LIVE_PGVECTOR=1)")
def test_pgvector_live_index_and_search(monkeypatch):
    """Live run against DATABASE_URL (default: the rtb_pgtest DB)."""
    monkeypatch.setenv("RTB_USE_PGVECTOR", "1")
    # Defensive: a previous test may have patched the singleton's
    # URL — point it back at the real DATABASE_URL from the env.
    monkeypatch.setattr(settings, "database_url", os.environ["DATABASE_URL"])
    import app.db.session as session_mod

    session_mod._engine = None
    session_mod._Session = None
    from app.db.vector_store import PgVectorStore, get_vector_store, LocalVectorStore
    from app.services import embeddings as emb
    from app.services.ingestion import Chunk

    store = get_vector_store()
    assert isinstance(store, PgVectorStore), "PgVectorStore did not activate"
    # Clean slate: PgVectorStore.index() has no dedup, so a second
    # run against the same test DB would duplicate the rows.
    from sqlalchemy import text

    from app.db.session import get_engine

    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM chunks"))
        conn.execute(text("DELETE FROM documents"))
    rows = [json.loads(line) for line in
            (PROJECT / "data" / "chunks.jsonl").read_text().splitlines() if line.strip()]
    chunks = [Chunk(**{k: r[k] for k in
                       ("document_id", "chunk_index", "content", "title", "department",
                        "version", "language", "page_no", "tokens", "metadata")})
              for r in rows]
    vectors = emb.encode_texts([c.content for c in chunks])
    assert store.index(chunks, vectors) == 15
    local = LocalVectorStore()
    assert local.load()
    for question, departments in [
        ("What documents are needed for KYC account opening?", None),
        ("ما هو حد الإبلاغ عن المعاملات النقدية؟", None),
        ("What is the AML reporting threshold?", ["RETAIL"]),
    ]:
        qvec = emb.encode_query(question)
        pg = store.search(qvec, top_k=3, departments=departments)
        lo = local.search(qvec, top_k=3, departments=departments)
        assert pg, f"pgvector returned nothing for {question!r}"
        assert pg[0]["title"] == lo[0]["title"], \
            f"top-1 mismatch for {question!r}: pg={pg[0]['title']!r} local={lo[0]['title']!r}"
