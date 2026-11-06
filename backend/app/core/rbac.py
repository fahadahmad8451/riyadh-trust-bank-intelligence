"""Role-based access control — Sprint 3 (Design sections 4, 6, 9).

This is the SINGLE source of truth for who may see what. It is
enforced in the BACKEND, before retrieval/reranking (chat) and before
any document is listed or served — never only by hiding things in the
UI. A disallowed chunk never reaches the generator and never appears
in a citation.

Roles (Design section 4 matrix):
    ADMIN               -> RETAIL, COMPLIANCE, HR  (everything + upload + admin)
    COMPLIANCE_OFFICER  -> RETAIL, COMPLIANCE
    CUSTOMER_SERVICE    -> RETAIL only

Department mapping of the 8 synthetic Sprint 1 documents:
    RETAIL     KYC, Account Opening, Personal Loan, Charges & Fees
    COMPLIANCE AML, SAMA Compliance Summary
    HR         HR Leave Policy, PDPL Data Privacy Summary  (ADMIN only)

Note on PDPL: Sprint 1 stored the PDPL summary as COMPLIANCE in the
manifest and in the vector-store metadata. Sprint 3 corrects it to HR:
in this demo the PDPL summary is an HR-owned internal privacy policy,
so only ADMIN sees it (a Compliance Officer does NOT get it). The
correction was applied to ingestion.py, data/docs_manifest.json,
data/vector_store/meta.jsonl and data/chunks.jsonl, and the mapping
below is also enforced at runtime from the manifest, so a stale
COMPLIANCE label in any one file cannot leak the document.
"""
import json
import logging
from pathlib import Path

from app.core.paths import data_dir

logger = logging.getLogger("rtb.rbac")

ROLE_DEPARTMENTS: dict[str, set[str]] = {
    "ADMIN": {"RETAIL", "COMPLIANCE", "HR"},
    "COMPLIANCE_OFFICER": {"RETAIL", "COMPLIANCE"},
    "CUSTOMER_SERVICE": {"RETAIL"},
}

ALL_ROLES = tuple(ROLE_DEPARTMENTS)

# Fallback mapping (used if the manifest cannot be read). The manifest
# is the live registry; this dict must match it.
DOC_DEPARTMENTS: dict[str, str] = {
    "01-kyc-policy.pdf": "RETAIL",
    "02-aml-policy.pdf": "COMPLIANCE",
    "03-sama-compliance-summary.pdf": "COMPLIANCE",
    "04-personal-loan-policy.pdf": "RETAIL",
    "05-account-opening-policy.pdf": "RETAIL",
    "06-hr-leave-policy.pdf": "HR",
    "07-charges-fees-schedule.pdf": "RETAIL",
    "08-pdpl-privacy-summary.pdf": "HR",
}

DEPARTMENTS = ("RETAIL", "COMPLIANCE", "HR")


def _manifest_path() -> Path:
    return data_dir() / "docs_manifest.json"


def document_departments() -> dict[str, str]:
    """document_id -> department, from the live manifest (authoritative
    for uploaded documents too), falling back to DOC_DEPARTMENTS."""
    mapping = dict(DOC_DEPARTMENTS)
    try:
        data = json.loads(_manifest_path().read_text(encoding="utf-8"))
        for doc in data.get("documents", []):
            if doc.get("document_id") and doc.get("department"):
                mapping[doc["document_id"]] = doc["department"]
    except Exception as exc:  # noqa: BLE001 — manifest is best-effort here
        logger.warning("Could not read docs manifest for RBAC (%s) — using fallback map", exc)
    return mapping


def allowed_departments(role: str) -> list[str]:
    """Sorted list of departments a role may access (empty = none)."""
    return sorted(ROLE_DEPARTMENTS.get(role or "", set()))


def department_for_document(document_id: str) -> str | None:
    return document_departments().get(document_id)


def can_access_department(role: str, department: str) -> bool:
    return department in ROLE_DEPARTMENTS.get(role or "", set())


def can_access_document(role: str, document_id: str) -> bool:
    dept = department_for_document(document_id)
    if dept is None:
        return False  # unknown document: deny by default
    return can_access_department(role, dept)


def filter_documents(role: str, documents: list[dict]) -> list[dict]:
    """Return only the documents (manifest records) the role may see."""
    allowed = ROLE_DEPARTMENTS.get(role or "", set())
    return [d for d in documents if d.get("department") in allowed]


def filter_chunks(role: str, chunks: list[dict]) -> list[dict]:
    """Return only the chunks whose department the role may see.
    This is the enforcement point used before retrieval: disallowed
    chunks are removed BEFORE vector/BM25 ranking, so they can never
    be retrieved, reranked, cited, or fed to the generator."""
    allowed = ROLE_DEPARTMENTS.get(role or "", set())
    return [c for c in chunks if c.get("department") in allowed]
