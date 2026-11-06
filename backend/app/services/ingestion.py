"""Document ingestion — Sprint 1.

Real, working: PDF (PyMuPDF), Word (python-docx), Excel (openpyxl).
OCR fallback: tries PaddleOCR; if it is not installed it logs a clear
warning and continues with the text layer — it never fakes OCR output.

Chunking (Design section 5): ~800 tokens per chunk, ~150 tokens overlap,
section-aware — a heading is never split from its paragraph.

CLI:
    python -m app.services.ingestion --docs data/docs --out data/chunks.jsonl
    python -m app.services.ingestion --docs data/docs --out data/chunks.jsonl --manifest data/docs_manifest.json

Run from the backend/ directory (so `app` is importable).
"""
import argparse
import json
import logging
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger("rtb.ingestion")

# ~4 characters per token is the standard rough estimate for English text.
CHARS_PER_TOKEN = 4
CHUNK_TOKENS = 800
OVERLAP_TOKENS = 150
CHUNK_CHARS = CHUNK_TOKENS * CHARS_PER_TOKEN
OVERLAP_CHARS = OVERLAP_TOKENS * CHARS_PER_TOKEN

# ---------------------------------------------------------------------------
# Document registry — the 8 synthetic Sprint 1 documents.
# Keys are the PDF filenames in data/docs/. Titles/departments are the
# single source of truth for chunk metadata (and for the /documents API).
# ---------------------------------------------------------------------------
DOCS = {
    "01-kyc-policy.pdf": {
        "title": "KYC Policy — Know Your Customer",
        "title_ar": "سياسة اعرف عميلك",
        "type": "POLICY",
        "department": "RETAIL",
        "version": "1.0",
        "language": "en",
    },
    "02-aml-policy.pdf": {
        "title": "Anti-Money Laundering (AML) Policy",
        "title_ar": "سياسة مكافحة غسل الأموال",
        "type": "POLICY",
        "department": "COMPLIANCE",
        "version": "1.0",
        "language": "en",
    },
    "03-sama-compliance-summary.pdf": {
        "title": "SAMA Compliance Summary",
        "title_ar": "ملخص الامتثال لدى ساما",
        "type": "CIRCULAR",
        "department": "COMPLIANCE",
        "version": "1.0",
        "language": "en",
    },
    "04-personal-loan-policy.pdf": {
        "title": "Personal Loan Policy",
        "title_ar": "سياسة القرض الشخصي",
        "type": "POLICY",
        "department": "RETAIL",
        "version": "1.0",
        "language": "en",
    },
    "05-account-opening-policy.pdf": {
        "title": "Account Opening Policy",
        "title_ar": "سياسة فتح الحساب",
        "type": "POLICY",
        "department": "RETAIL",
        "version": "1.0",
        "language": "en",
    },
    "06-hr-leave-policy.pdf": {
        "title": "HR Leave Policy",
        "title_ar": "سياسة إجازات الموارد البشرية",
        "type": "POLICY",
        "department": "HR",
        "version": "1.0",
        "language": "en",
    },
    "07-charges-fees-schedule.pdf": {
        "title": "Charges and Fees Schedule",
        "title_ar": "جدول الرسوم والمصاريف",
        "type": "PROCEDURE",
        "department": "RETAIL",
        "version": "1.0",
        "language": "en",
    },
    "08-pdpl-privacy-summary.pdf": {
        "title": "PDPL Data Privacy Summary",
        "title_ar": "ملخص حماية البيانات الشخصية",
        "type": "CIRCULAR",
        "department": "HR",
        "version": "1.0",
        "language": "en",
    },
}

HEADING_RE = re.compile(r"^(\d+)\.\s+([A-Z][A-Za-z0-9 ,&()\-/]+)$")
HEADER_FOOTER_RE = re.compile(
    r"Riyadh Trust Bank — Synthetic Demo Document, not a real bank\.?"
)


def estimate_tokens(text: str) -> int:
    """Rough token estimate (chars / 4). Used for chunk sizing only."""
    return max(1, len(text) // CHARS_PER_TOKEN)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class PageText:
    page_no: int
    text: str


@dataclass
class Chunk:
    document_id: str  # filename, e.g. "01-kyc-policy.pdf"
    chunk_index: int
    content: str
    title: str
    department: str
    version: str
    language: str
    page_no: int | None
    tokens: int = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["metadata"] = {
            "document_id": self.document_id,
            "title": self.title,
            "department": self.department,
            "version": self.version,
            "language": self.language,
            "page_no": self.page_no,
        }
        return d


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------
def parse_pdf(path: Path) -> list[PageText]:
    """Extract text per page with PyMuPDF. OCR fallback if a page is empty."""
    import fitz  # PyMuPDF

    doc = fitz.open(str(path))
    pages: list[PageText] = []
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text")
        if not text.strip():
            text = _ocr_page(page, i)
        pages.append(PageText(page_no=i, text=text))
    return pages


def _ocr_page(page, page_no: int) -> str:
    """OCR a scanned (image-only) page. Honest fallback: if PaddleOCR is
    not installed, log a warning and return '' — never invent text."""
    try:
        from paddleocr import PaddleOCR  # type: ignore
    except ImportError:
        logger.warning(
            "Page %s has no text layer and PaddleOCR is not installed — "
            "OCR skipped for this page (no text extracted, nothing faked).",
            page_no,
        )
        return ""
    try:
        ocr = PaddleOCR(use_angle_cls=True, lang="en")
        pix = page.get_pixmap(dpi=200)
        import numpy as np

        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width, pix.n
        )
        result = ocr.ocr(img, cls=True)
        lines = []
        for block in result or []:
            for line in block or []:
                lines.append(line[1][0])
        return "\n".join(lines)
    except Exception as exc:  # OCR must never crash ingestion
        logger.warning("OCR failed on page %s: %s", page_no, exc)
        return ""


def parse_docx(path: Path) -> list[PageText]:
    """Word documents: paragraphs joined; one logical page."""
    import docx

    doc = docx.Document(str(path))
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    return [PageText(page_no=1, text=text)]


def parse_xlsx(path: Path) -> list[PageText]:
    """Excel: every sheet becomes text (header row + rows, tab separated)."""
    import openpyxl

    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    chunks: list[str] = []
    for sheet in wb.worksheets:
        lines = [f"Sheet: {sheet.title}"]
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None]
            if cells:
                lines.append("\t".join(cells))
        chunks.append("\n".join(lines))
    return [PageText(page_no=1, text="\n\n".join(chunks))]


def parse_file(path: Path) -> list[PageText]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(path)
    if suffix == ".docx":
        return parse_docx(path)
    if suffix in (".xlsx", ".xls"):
        return parse_xlsx(path)
    raise ValueError(f"Unsupported file type: {suffix} ({path.name})")


# ---------------------------------------------------------------------------
# Cleaning + section-aware chunking
# ---------------------------------------------------------------------------
def clean_text(text: str) -> str:
    """Remove repeated header/footer lines; collapse blank lines."""
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if HEADER_FOOTER_RE.search(line):
            continue
        lines.append(line)
    return "\n".join(lines)


def split_sections(pages: list[PageText]) -> list[dict]:
    """Split cleaned text into sections. A section starts at a heading
    line (e.g. '3. Documents Needed...') or at a document title.
    Returns [{heading, text, page_no}]."""
    sections: list[dict] = []
    current = {"heading": "", "text": "", "page_no": None}
    for page in pages:
        for line in clean_text(page.text).splitlines():
            if HEADING_RE.match(line) or (
                line and len(line) < 80 and line[0].isupper()
                and line.rstrip().endswith(("Policy", "Summary", "Schedule"))
            ):
                if current["text"].strip():
                    sections.append(current)
                current = {"heading": line, "text": "", "page_no": page.page_no}
            else:
                if current["page_no"] is None:
                    current["page_no"] = page.page_no
                current["text"] += line + "\n"
    if current["text"].strip():
        sections.append(current)
    return sections


def chunk_section(heading: str, text: str, page_no: int | None) -> list[str]:
    """Chunk one section into ~800-token pieces with ~150-token overlap.
    Splits on sentence boundaries; a heading stays attached to the
    first chunk of its section."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    sentences = [s for s in sentences if s]
    if not sentences:
        return []
    chunks: list[str] = []
    buf = heading + "\n" if heading else ""
    for sentence in sentences:
        candidate = buf + sentence + " "
        if estimate_tokens(candidate) > CHUNK_TOKENS and buf.strip():
            chunks.append(buf.strip())
            # Overlap: carry the last ~150 tokens of the finished chunk.
            overlap = buf[-OVERLAP_CHARS:]
            cut = overlap.find(". ")
            if cut != -1:
                overlap = overlap[cut + 2:]
            buf = (heading + "\n" if heading else "") + overlap + sentence + " "
        else:
            buf = candidate
    if buf.strip():
        chunks.append(buf.strip())
    return chunks


def ingest_document(path: Path) -> tuple[dict, list[Chunk]]:
    """Ingest one file -> (document record, chunks)."""
    meta = DOCS.get(path.name, {
        "title": path.stem.replace("-", " ").title(),
        "title_ar": None,
        "type": "POLICY",
        "department": "RETAIL",
        "version": "1.0",
        "language": "en",
    })
    pages = parse_file(path)
    sections = split_sections(pages)
    # Merge small consecutive sections into ~800-token groups first, so a
    # chunk is not limited to one short section. Headings stay attached
    # to their own paragraphs inside the merged text.
    groups: list[dict] = []
    for section in sections:
        text = (section["heading"] + "\n" + section["text"]).strip()
        if groups and estimate_tokens(groups[-1]["text"]) + estimate_tokens(text) <= CHUNK_TOKENS:
            groups[-1]["text"] += "\n" + text
        else:
            groups.append({"heading": section["heading"], "text": text,
                           "page_no": section["page_no"]})
    chunks: list[Chunk] = []
    for group in groups:
        # heading="" here: the merged text already carries its headings.
        for piece in chunk_section("", group["text"], group["page_no"]):
            chunks.append(Chunk(
                document_id=path.name,
                chunk_index=len(chunks),
                content=piece,
                title=meta["title"],
                department=meta["department"],
                version=meta["version"],
                language=meta["language"],
                page_no=group["page_no"],
                tokens=estimate_tokens(piece),
                metadata={
                    "document_id": path.name,
                    "title": meta["title"],
                    "department": meta["department"],
                    "version": meta["version"],
                    "language": meta["language"],
                    "page_no": group["page_no"],
                },
            ))
    record = {
        "document_id": path.name,
        "title": meta["title"],
        "title_ar": meta["title_ar"],
        "type": meta["type"],
        "department": meta["department"],
        "version": meta["version"],
        "language": meta["language"],
        "file_path": str(path),
        "chunk_count": len(chunks),
        "pages": len(pages),
    }
    return record, chunks


def ingest_directory(docs_dir: Path) -> tuple[list[dict], list[Chunk]]:
    """Ingest every supported file in a directory (sorted, deterministic)."""
    records: list[dict] = []
    all_chunks: list[Chunk] = []
    for path in sorted(docs_dir.iterdir()):
        if path.suffix.lower() not in (".pdf", ".docx", ".xlsx", ".xls"):
            continue
        try:
            record, chunks = ingest_document(path)
        except Exception as exc:
            logger.warning("Skipping %s: %s", path.name, exc)
            continue
        records.append(record)
        all_chunks.extend(chunks)
        logger.info("%s: %d pages, %d chunks", path.name, record["pages"], len(chunks))
    return records, all_chunks


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Ingest documents into chunks.")
    parser.add_argument("--docs", required=True, help="Directory with .pdf/.docx/.xlsx files")
    parser.add_argument("--out", required=True, help="Output chunks JSONL file")
    parser.add_argument("--manifest", default=None, help="Output manifest JSON file")
    args = parser.parse_args(argv)

    docs_dir = Path(args.docs)
    records, chunks = ingest_directory(docs_dir)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")

    total_tokens = sum(c.tokens for c in chunks)
    print(f"Documents ingested: {len(records)}")
    for r in records:
        print(f"  {r['document_id']:40s} {r['pages']} pages, {r['chunk_count']} chunks")
    print(f"Total chunks: {len(chunks)}")
    print(f"Average chunk tokens: {total_tokens / max(len(chunks), 1):.1f}")
    print(f"Chunks written to: {out_path}")

    if args.manifest:
        manifest_path = Path(args.manifest)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps({"documents": records}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Manifest written to: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
