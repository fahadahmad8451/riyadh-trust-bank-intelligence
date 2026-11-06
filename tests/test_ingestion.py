"""Sprint 1 tests — ingestion + chunking + vector search.

Run (from backend/):  python -m pytest ../tests/test_ingestion.py -v
Chunking tests need no model. The search test uses the real indexed
store (data/vector_store/) if present, otherwise it is skipped.
The upload test monkeypatches the embedding call so it needs no model.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.db.vector_store import LocalVectorStore
from app.services.ingestion import (
    CHUNK_TOKENS,
    chunk_section,
    estimate_tokens,
    ingest_document,
    split_sections,
    PageText,
)

LONG_SECTION = ("This is a sentence about bank policy. " * 60).strip()
# ~2000 tokens — long enough that chunking must split it (used by the
# max-tokens / overlap tests). One sentence is only ~10 tokens.
VERY_LONG_SECTION = ("This is a sentence about bank policy. " * 200).strip()


def test_estimate_tokens_is_roughly_chars_over_four():
    assert estimate_tokens("abcd" * 100) == 100


def test_chunk_section_respects_max_tokens():
    pieces = chunk_section("1. Purpose", VERY_LONG_SECTION, 1)
    assert pieces, "expected at least one chunk"
    for piece in pieces:
        assert estimate_tokens(piece) <= CHUNK_TOKENS + 5
    # A long section must split into more than one chunk.
    assert len(pieces) >= 2


def test_chunk_section_keeps_heading_with_first_chunk():
    pieces = chunk_section("3. Documents Needed", LONG_SECTION, 2)
    assert pieces[0].startswith("3. Documents Needed")


def test_chunk_overlap_shares_text():
    pieces = chunk_section("1. Purpose", VERY_LONG_SECTION, 1)
    assert len(pieces) >= 2
    # Overlap: the tail of chunk 0 reappears at the start of chunk 1.
    assert pieces[0][-50:] in pieces[1] or pieces[1][:200] in pieces[0]


def test_split_sections_never_splits_heading_from_paragraph():
    pages = [PageText(page_no=1, text=(
        "KYC Policy\n\n1. Purpose\nThis is the purpose paragraph.\n\n"
        "2. Scope\nThis is the scope paragraph.\n"
    ))]
    sections = split_sections(pages)
    headings = [s["heading"] for s in sections]
    assert "1. Purpose" in headings and "2. Scope" in headings
    purpose = next(s for s in sections if s["heading"] == "1. Purpose")
    assert "purpose paragraph" in purpose["text"]


def test_ingest_real_pdf(tmp_path):
    from fpdf import FPDF

    pdf_path = tmp_path / "01-kyc-policy.pdf"
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, "KYC Policy", new_x="LMARGIN", new_y="NEXT")
    pdf.multi_cell(0, 6, "1. Purpose\n" + LONG_SECTION, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(pdf_path))
    record, chunks = ingest_document(pdf_path)
    assert record["document_id"] == "01-kyc-policy.pdf"
    assert record["title"] == "KYC Policy — Know Your Customer"
    assert len(chunks) >= 1
    assert all(c.tokens <= CHUNK_TOKENS + 5 for c in chunks)
    assert all(c.metadata["document_id"] == "01-kyc-policy.pdf" for c in chunks)


def test_local_vector_store_search(tmp_path):
    store = LocalVectorStore(tmp_path)
    meta = [
        {"document_id": "a.pdf", "title": "KYC Policy", "chunk_index": 0,
         "page_no": 1, "department": "RETAIL", "content": "KYC identity documents"},
        {"document_id": "b.pdf", "title": "AML Policy", "chunk_index": 0,
         "page_no": 1, "department": "COMPLIANCE", "content": "AML threshold sixty thousand"},
    ]

    class FakeChunk:
        def __init__(self, d):
            self._d = d

        def to_dict(self):
            return dict(self._d)

    vecs = np.array([[1.0, 0.0], [0.0, 1.0]], dtype="float32")
    assert store.index([FakeChunk(m) for m in meta], vecs) == 2
    # Re-indexing the same chunks must not duplicate them.
    assert store.index([FakeChunk(m) for m in meta], vecs) == 0
    results = store.search(np.array([1.0, 0.0], dtype="float32"), top_k=1)
    assert results[0]["document_id"] == "a.pdf"
    assert results[0]["score"] > 0.99
    # Department filter works.
    results = store.search(np.array([1.0, 0.0], dtype="float32"), top_k=5, department="COMPLIANCE")
    assert [r["document_id"] for r in results] == ["b.pdf"]


def test_search_against_real_store():
    """Uses the real Sprint 1 store if it has been indexed, else skips."""
    store = LocalVectorStore()
    if not store.load():
        pytest.skip("vector store not indexed yet — run scripts/index_chunks.py")
    assert len(store._meta) >= 8
    # Cosine search over the real store with a KYC-flavoured vector is
    # covered end-to-end by scripts/search_test.py; here we only check
    # that search returns well-formed results for a unit query vector.
    dim = store._embeddings.shape[1]
    query = np.zeros(dim, dtype="float32")
    query[0] = 1.0
    results = store.search(query, top_k=3)
    assert len(results) == 3
    assert all("title" in r and "score" in r and "content" in r for r in results)


def _admin_headers(client):
    """Sprint 3: /documents needs a JWT. Seed the demo users if needed
    and log in as admin (sees all departments)."""
    from app.core.users import load_users, seed_users

    if not load_users():
        seed_users()
    res = client.post("/api/v1/auth/login",
                      json={"email": "admin@rtb.local", "password": "Admin123!"})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {client.cookies.get('rtb_access')}"}


def test_documents_api_lists_manifest(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    # Sprint 3: unauthenticated listing is 401.
    assert client.get("/api/v1/documents").status_code == 401
    res = client.get("/api/v1/documents", headers=_admin_headers(client))
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    assert body["data"]["count"] >= 8
    titles = [d["title"] for d in body["data"]["documents"]]
    assert "Anti-Money Laundering (AML) Policy" in titles


def test_upload_endpoint_ingests_and_indexes(tmp_path, monkeypatch):
    """Upload path with the embedding call monkeypatched (no model load)."""
    from fastapi.testclient import TestClient

    import app.api.v1.documents as docs_mod
    from app.main import app

    # Isolate: upload into tmp dirs, not the real data/ folder.
    monkeypatch.setattr(docs_mod, "DOCS_DIR", tmp_path / "docs")
    monkeypatch.setattr(docs_mod, "MANIFEST_PATH", tmp_path / "manifest.json")
    store = LocalVectorStore(tmp_path / "store")
    monkeypatch.setattr(docs_mod, "get_vector_store", lambda: store)
    monkeypatch.setattr(
        docs_mod.emb, "encode_texts",
        lambda texts, **kw: np.eye(4, dtype="float32")[: len(texts)] if len(texts) <= 4
        else np.tile(np.eye(4, dtype="float32"), (len(texts) // 4 + 1, 1))[: len(texts)],
    )
    monkeypatch.setattr(docs_mod.emb, "model_info", lambda: {"model": "test", "dim": 4, "backend": "test"})

    from fpdf import FPDF

    pdf_path = tmp_path / "test-doc.pdf"
    pdf = FPDF(format="A4", unit="mm")
    pdf.add_page()
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, "1. Purpose\n" + LONG_SECTION, new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(pdf_path))

    client = TestClient(app)
    # Sprint 3: upload is ADMIN-only — unauthenticated is 401.
    with pdf_path.open("rb") as fh:
        assert client.post("/api/v1/documents/upload",
                           files={"file": ("test-doc.pdf", fh, "application/pdf")}).status_code == 401
    with pdf_path.open("rb") as fh:
        res = client.post("/api/v1/documents/upload",
                          files={"file": ("test-doc.pdf", fh, "application/pdf")},
                          headers=_admin_headers(client))
    assert res.status_code == 201, res.text
    body = res.json()["data"]
    assert body["chunk_count"] >= 1
    assert body["chunks_indexed"] >= 1
    assert body["rbac_enforced"] is True
    assert (tmp_path / "manifest.json").exists()
