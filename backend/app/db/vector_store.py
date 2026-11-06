"""Vector stores — Sprint 1. One interface, two backends.

LocalVectorStore (default): numpy .npz + JSON metadata in
data/vector_store/. Works with NO Docker and NO Postgres server, so
Sprint 1 runs on Fahad's Windows laptop as-is.

PgVectorStore: PostgreSQL + pgvector (Design). Activates only when
RTB_USE_PGVECTOR=1 and the Postgres server is reachable. If the stored
embedding dimension does not match the pgvector column (1024), or the
SQL cosine search fails, it stores/searches embeddings as JSON and
falls back to numpy cosine — and logs that it did so.

Both expose:
    index(chunks, embeddings) -> int   (chunks indexed)
    search(query_embedding, top_k=5, department=None) -> list[dict]
        each dict: document_id, title, chunk_index, page_no, content,
        department, score (cosine similarity, higher is better)
"""
import json
import logging
import os
from pathlib import Path

import numpy as np

from app.core.config import settings
from app.services.embeddings import write_embedding_config

logger = logging.getLogger("rtb.vector_store")

def _default_store_dir() -> Path:
    """Staging-aware default: RTB_DATA_DIR/vector_store when set,
    else data/vector_store. An explicit absolute VECTOR_STORE_DIR
    (env) wins over both — same rule as Sprint 1, plus staging."""
    env = os.getenv("VECTOR_STORE_DIR")
    if env:
        path = Path(env)
        return path if path.is_absolute() else Path(__file__).resolve().parents[3] / path
    from app.core.paths import data_dir

    return data_dir() / "vector_store"


DEFAULT_STORE_DIR = _default_store_dir()


def _cosine_search(embeddings: np.ndarray, query: np.ndarray, top_k: int):
    """embeddings are L2-normalised, so cosine = dot product."""
    scores = embeddings @ query
    order = np.argsort(-scores)[:top_k]
    return [(int(i), float(scores[i])) for i in order]


class LocalVectorStore:
    """File-based store: vectors.npz + meta.jsonl + embedding_config.json."""

    def __init__(self, store_dir: Path | None = None):
        self.store_dir = Path(store_dir) if store_dir else DEFAULT_STORE_DIR
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.vectors_path = self.store_dir / "vectors.npz"
        self.meta_path = self.store_dir / "meta.jsonl"
        self._embeddings: np.ndarray | None = None
        self._meta: list[dict] = []

    # -- indexing ---------------------------------------------------------
    def index(self, chunks: list, embeddings: np.ndarray) -> int:
        """Append chunks to the store (deduplicated by document_id +
        chunk_index, so re-indexing the same file does not duplicate it).
        Returns the number of NEW chunks added."""
        embeddings = np.asarray(embeddings, dtype="float32")
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        embeddings = embeddings / np.maximum(norms, 1e-9)
        self.load()
        existing_keys = {(m.get("document_id"), m.get("chunk_index")) for m in self._meta}
        new_records, new_vecs = [], []
        for chunk, vec in zip(chunks, embeddings):
            d = chunk.to_dict() if hasattr(chunk, "to_dict") else dict(chunk)
            key = (d.get("document_id"), d.get("chunk_index"))
            if key in existing_keys:
                continue
            existing_keys.add(key)
            new_records.append(d)
            new_vecs.append(vec)
        if new_vecs:
            all_vecs = (
                np.vstack([self._embeddings, np.stack(new_vecs)])
                if self._embeddings is not None and len(self._meta)
                else np.stack(new_vecs)
            )
            all_meta = self._meta + new_records
        else:
            all_vecs, all_meta = self._embeddings, self._meta
        if all_vecs is None:
            return 0
        np.savez_compressed(self.vectors_path, embeddings=all_vecs)
        with self.meta_path.open("w", encoding="utf-8") as fh:
            for record in all_meta:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        # Record the model that was actually used. If index() was called
        # without ever loading a model (e.g. in a unit test), do NOT
        # trigger a model download here — write a placeholder instead.
        try:
            write_embedding_config(self.store_dir)
        except Exception as exc:  # noqa: BLE001 — config is informational
            logger.warning("Could not record embedding config: %s", exc)
            (self.store_dir / "embedding_config.json").write_text(json.dumps({
                "model": "not-recorded (index called without a loaded embedding model)",
                "dim": int(all_vecs.shape[1]),
                "backend": "unknown",
            }, indent=2), encoding="utf-8")
        self._embeddings, self._meta = all_vecs, all_meta
        logger.info("LocalVectorStore: +%d chunks (%d total) -> %s",
                    len(new_records), len(all_meta), self.store_dir)
        return len(new_records)

    def delete_document(self, document_id: str) -> int:
        """Remove every chunk of one document from the store. Returns
        the number of chunks removed (0 if the document was not there)."""
        self.load()
        keep_meta, keep_idx = [], []
        removed = 0
        for i, m in enumerate(self._meta):
            if m.get("document_id") == document_id:
                removed += 1
            else:
                keep_meta.append(m)
                keep_idx.append(i)
        if removed == 0:
            return 0
        if keep_idx:
            all_vecs = self._embeddings[keep_idx]
            np.savez_compressed(self.vectors_path, embeddings=all_vecs)
        else:
            self.vectors_path.unlink(missing_ok=True)
            self._embeddings = None
        with self.meta_path.open("w", encoding="utf-8") as fh:
            for record in keep_meta:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._meta = keep_meta
        if keep_idx:
            self._embeddings = all_vecs
        logger.info("LocalVectorStore: removed %d chunks of %s", removed, document_id)
        return removed

    # -- loading ----------------------------------------------------------
    def load(self) -> bool:
        if not (self.vectors_path.exists() and self.meta_path.exists()):
            return False
        data = np.load(self.vectors_path)
        self._embeddings = np.asarray(data["embeddings"], dtype="float32")
        self._meta = [json.loads(line) for line in self.meta_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return True

    # -- search -----------------------------------------------------------
    def search(self, query_embedding: np.ndarray, top_k: int = 5, department: str | None = None,
               departments: list[str] | None = None) -> list[dict]:
        """Search restricted to one department (department=) or a list
        of departments (departments=, Sprint 3 RBAC). Both default to
        no restriction. The filter is applied BEFORE ranking, so
        disallowed chunks never appear in results."""
        if self._embeddings is None and not self.load():
            return []
        query = np.asarray(query_embedding, dtype="float32")
        query = query / max(np.linalg.norm(query), 1e-9)
        allowed = set(departments) if departments is not None else (
            {department} if department is not None else None)
        candidates = [
            (i, m) for i, m in enumerate(self._meta)
            if allowed is None or m.get("department") in allowed
        ]
        if not candidates:
            return []
        idxs = [i for i, _ in candidates]
        sub = self._embeddings[idxs]
        hits = _cosine_search(sub, query, top_k)
        results = []
        for rank, score in hits:
            meta = candidates[rank][1]
            results.append({
                "document_id": meta.get("document_id"),
                "title": meta.get("title"),
                "chunk_index": meta.get("chunk_index"),
                "page_no": meta.get("page_no"),
                "department": meta.get("department"),
                "content": meta.get("content"),
                "score": round(score, 4),
            })
        return results


class PgVectorStore:
    """PostgreSQL + pgvector store (Design). See module docstring for the
    honest JSON fallback when the pgvector column/dimension does not fit."""

    def __init__(self):
        from app.db.session import get_session, init_db

        self._session_factory = get_session
        self._status = init_db()
        self._use_vector_column = bool(self._status.get("pgvector"))

    def index(self, chunks: list, embeddings: np.ndarray) -> int:
        from app.db.models import Chunk, Document

        embeddings = np.asarray(embeddings, dtype="float32")
        session = self._session_factory()
        try:
            count = 0
            for chunk, emb in zip(chunks, embeddings):
                doc = session.query(Document).filter_by(title=chunk.title).first()
                if doc is None:
                    doc = Document(
                        title=chunk.title, title_ar=None, type="POLICY",
                        department=chunk.department, version=chunk.version,
                        language=chunk.language, file_path=chunk.document_id,
                        status="ready",
                    )
                    session.add(doc)
                    session.flush()
                row = Chunk(
                    document_id=doc.id, chunk_index=chunk.chunk_index,
                    content=chunk.content, page_no=chunk.page_no,
                )
                row.metadata_json = chunk.to_dict()["metadata"]
                if self._use_vector_column and embeddings.shape[1] == 1024:
                    row.embedding = emb.tolist()
                else:
                    # Dimension mismatch or no pgvector: keep the vector
                    # as JSON in metadata so search can still use it.
                    row.metadata_json = {**row.metadata_json, "embedding": emb.tolist()}
                    if self._use_vector_column:
                        logger.warning(
                            "pgvector column is 1024-dim but embeddings are %d-dim — "
                            "storing as JSON instead", embeddings.shape[1])
                session.add(row)
                count += 1
            session.commit()
            return count
        finally:
            session.close()

    def search(self, query_embedding: np.ndarray, top_k: int = 5, department: str | None = None,
               departments: list[str] | None = None) -> list[dict]:
        from app.db.models import Chunk, Document

        session = self._session_factory()
        try:
            query = session.query(Chunk, Document).join(Document, Chunk.document_id == Document.id)
            allowed = set(departments) if departments is not None else (
                {department} if department is not None else None)
            if allowed:
                query = query.filter(Document.department.in_(sorted(allowed)))
            rows = query.all()
            if not rows:
                return []
            vecs, metas = [], []
            for chunk, doc in rows:
                emb = None
                if isinstance(chunk.embedding, (list, tuple)):
                    emb = np.asarray(chunk.embedding, dtype="float32")
                elif chunk.metadata_json and "embedding" in chunk.metadata_json:
                    emb = np.asarray(chunk.metadata_json["embedding"], dtype="float32")
                if emb is None:
                    continue
                vecs.append(emb)
                metas.append((chunk, doc))
            if not vecs:
                return []
            embeddings = np.stack(vecs)
            norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
            embeddings = embeddings / np.maximum(norms, 1e-9)
            q = np.asarray(query_embedding, dtype="float32")
            q = q / max(np.linalg.norm(q), 1e-9)
            hits = _cosine_search(embeddings, q, top_k)
            results = []
            for rank, score in hits:
                chunk, doc = metas[rank]
                results.append({
                    "document_id": doc.file_path,
                    "title": doc.title,
                    "chunk_index": chunk.chunk_index,
                    "page_no": chunk.page_no,
                    "department": doc.department,
                    "content": chunk.content,
                    "score": round(score, 4),
                })
            return results
        finally:
            session.close()


def get_vector_store():
    """Default is the local file store (no Docker, no Postgres needed).
    Set RTB_USE_PGVECTOR=1 to try Postgres + pgvector; any failure falls
    back to the local store with a logged warning."""
    if os.getenv("RTB_USE_PGVECTOR") == "1" and settings.database_url.startswith("postgresql"):
        try:
            store = PgVectorStore()
            logger.info("Vector store: PgVectorStore (PostgreSQL + pgvector)")
            return store
        except Exception as exc:  # noqa: BLE001 — fall back, do not crash
            logger.warning("PgVectorStore unavailable (%s) — using LocalVectorStore", exc)
    return LocalVectorStore()
