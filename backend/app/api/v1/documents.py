"""Documents API — Sprint 3 (real, working, RBAC-enforced).

GET    /documents        — list ingested documents (only the caller's
                            departments; ADMIN sees all)
GET    /documents/{id}   — one document (404 if missing OR not allowed
                            — existence of a disallowed document is not
                            leaked)
POST   /documents/upload — ADMIN only; saves, ingests, embeds + indexes
DELETE /documents/{id}   — ADMIN only; removes manifest + vector chunks

Uploads are audit-logged (UPLOAD); denied uploads get 403 + an
ACCESS_DENIED audit entry.
"""
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import JSONResponse

from app.core.audit import append_audit
from app.core.rbac import DEPARTMENTS, filter_documents
from app.core.security import get_current_user, require_admin
from app.db.vector_store import get_vector_store
from app.services import embeddings as emb
from app.services.ingestion import DOCS, ingest_document

logger = logging.getLogger("rtb.documents")
router = APIRouter()

from app.core.paths import data_dir

ROOT = Path(__file__).resolve().parents[4]  # backend/app/api/v1 -> project root
DOCS_DIR = data_dir() / "docs"
MANIFEST_PATH = data_dir() / "docs_manifest.json"


def _read_manifest() -> list[dict]:
    if not MANIFEST_PATH.exists():
        return []
    data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return data.get("documents", [])


def _write_manifest(records: list[dict]) -> None:
    MANIFEST_PATH.write_text(
        json.dumps({"documents": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _envelope(data, request_id: str = "documents") -> dict:
    return {"success": True, "data": data, "error": None, "request_id": request_id}


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"success": False, "data": None, "error": detail, "request_id": "documents"},
    )


@router.get("/documents")
async def list_documents(user: dict = Depends(get_current_user)):
    docs = filter_documents(user["role"], _read_manifest())
    return _envelope({"documents": docs, "count": len(docs),
                      "rbac_enforced": True, "role": user["role"]})


@router.get("/documents/{document_id}")
async def get_document(document_id: str, user: dict = Depends(get_current_user)):
    docs = _read_manifest()
    record = next((d for d in docs if d["document_id"] == document_id), None)
    if record is None or record.get("department") not in _allowed(user):
        # 404 either way: do not leak whether a disallowed document exists.
        return _error(404, f"Document not found: {document_id}")
    return _envelope({"document": record, "rbac_enforced": True})


def _allowed(user: dict) -> set:
    from app.core.rbac import ROLE_DEPARTMENTS

    return ROLE_DEPARTMENTS.get(user["role"], set())


@router.post("/documents/upload", status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    department: str = Form(default="RETAIL"),
    user: dict = Depends(require_admin),
):
    if department not in DEPARTMENTS:
        return _error(400, f"Invalid department: {department} — use one of {list(DEPARTMENTS)}")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in (".pdf", ".docx", ".xlsx", ".xls"):
        return _error(400, f"Unsupported file type: {suffix or '(none)'} — use .pdf, .docx or .xlsx")
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    saved = DOCS_DIR / (file.filename or "upload.pdf")
    # Production (v0.8): 10 MB upload limit, enforced while streaming
    # so a huge file never lands on disk or in the ingester. Over the
    # limit -> 413 and the partial file is deleted.
    MAX_UPLOAD_BYTES = 10 * 1024 * 1024
    written = 0
    with saved.open("wb") as fh:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                fh.close()
                saved.unlink(missing_ok=True)
                append_audit("UPLOAD", user_email=user["email"], role=user["role"],
                             result="fail", resource="documents:upload",
                             detail=f"file too large ({written} bytes > 10 MB)")
                return _error(413, "File too large — maximum upload size is 10 MB.")
            fh.write(chunk)

    record, chunks = ingest_document(saved)
    if title:
        record["title"] = title
    record["department"] = department
    # Index the new chunks into the local vector store.
    texts = [c.content for c in chunks]
    vectors = emb.encode_texts(texts) if texts else None
    indexed = 0
    if vectors is not None:
        store = get_vector_store()
        indexed = store.index(chunks, vectors)

    records = [r for r in _read_manifest() if r["document_id"] != record["document_id"]]
    records.append(record)
    records.sort(key=lambda r: r["document_id"])
    _write_manifest(records)
    append_audit("UPLOAD", user_email=user["email"], role=user["role"], result="ok",
                 resource=f"documents:{record['document_id']}",
                 detail=f"{record['chunk_count']} chunks, {indexed} indexed, dept={department}")
    logger.info("Uploaded %s: %d chunks indexed", saved.name, indexed)
    return _envelope({
        "document_id": record["document_id"],
        "title": record["title"],
        "department": record["department"],
        "chunk_count": record["chunk_count"],
        "chunks_indexed": indexed,
        "embedding_model": emb.model_info(),
        "rbac_enforced": True,
    })


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str, user: dict = Depends(require_admin)):
    records = _read_manifest()
    record = next((d for d in records if d["document_id"] == document_id), None)
    if record is None:
        return _error(404, f"Document not found: {document_id}")
    # Never delete a built-in Sprint 1 synthetic document through the
    # API — they are the demo corpus. (Admin can delete uploads.)
    if document_id in DOCS:
        return _error(400, "Built-in synthetic documents cannot be deleted via the API.")
    store = get_vector_store()
    removed = 0
    try:
        removed = store.delete_document(document_id)
    except AttributeError:
        logger.warning("Vector store has no delete_document() — manifest only")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Vector-store delete failed (%s) — manifest still updated", exc)
    pdf = DOCS_DIR / document_id
    if pdf.exists():
        pdf.unlink()
    _write_manifest([r for r in records if r["document_id"] != document_id])
    append_audit("UPLOAD", user_email=user["email"], role=user["role"], result="ok",
                 resource=f"documents:{document_id}",
                 detail=f"deleted, {removed} chunks removed")
    return _envelope({
        "document_id": document_id,
        "deleted": True,
        "chunks_removed": removed,
        "rbac_enforced": True,
    })
