"""Index data/chunks.jsonl into the vector store (default: local file store).

Run from the backend/ directory:
    python ../scripts/index_chunks.py
    python ../scripts/index_chunks.py --store pgvector   # needs RTB_USE_PGVECTOR=1 + local Postgres

Writes data/vector_store/embedding_config.json with the embedding model
that was ACTUALLY used (BGE-M3 if it loaded, else the fallback).
"""
import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.db.vector_store import get_vector_store
from app.services import embeddings as emb
from app.services.ingestion import Chunk


def load_chunks(path: Path) -> list[Chunk]:
    chunks = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        chunks.append(Chunk(
            document_id=d["document_id"], chunk_index=d["chunk_index"],
            content=d["content"], title=d["title"], department=d["department"],
            version=d["version"], language=d["language"], page_no=d["page_no"],
            tokens=d.get("tokens", 0), metadata=d.get("metadata", {}),
        ))
    return chunks


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunks", default="../data/chunks.jsonl")
    parser.add_argument("--store", default="local", choices=["local", "pgvector"])
    args = parser.parse_args()

    chunks = load_chunks(Path(args.chunks))
    print(f"Chunks to index: {len(chunks)}")
    vectors = emb.encode_texts([c.content for c in chunks])
    print(f"Embedding model: {emb.model_info()}")
    if args.store == "pgvector":
        import os
        os.environ["RTB_USE_PGVECTOR"] = "1"
    store = get_vector_store()
    added = store.index(chunks, vectors)
    print(f"Chunks indexed (new): {added}")
    print(f"Store: {type(store).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
