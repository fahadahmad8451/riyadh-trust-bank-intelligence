"""Verify the generated PDFs store Arabic in LOGICAL order.

Run from the project root:
    python scripts/verify_arabic_pdfs.py

For each of the 8 documents (data/docs_src/*.md -> data/docs/*.pdf) it
extracts the PDF text with PyMuPDF (the same call the ingestion service
uses: ``fitz.open(pdf).load_page(n).get_text()``) and checks:

1. every Arabic line from the .md source reads in logical order in the
   extracted text (comparison under NFKD + whitespace normalisation --
   the same normalisation the retrieval service applies; the only
   difference NFKD absorbs is the canonical ordering of the
   shadda+fatha pair, U+0651 U+064E vs U+064E U+0651);
2. no Arabic Presentation Forms (U+FB50-U+FEFF) anywhere in the
   extracted text -- their presence would mean the PDF still stores
   Arabic in visual order;
3. the "Synthetic Demo Document" footer is present on EVERY page;
4. every English content line from the .md is present too (regression
   check that the ReportLab rebuild did not lose body text).

Two extraction artifacts are normalised away in the comparison (both
are PyMuPDF word-segmentation behaviour, not content errors, and both
are applied symmetrically to the source line and the extraction):

* the footer text is stripped from the joined extraction before the
  content comparison -- a paragraph that spans a page break otherwise
  has the footer injected between its two halves;
* a space that PyMuPDF inserts immediately before a punctuation mark
  is removed. The generator emits Arabic glyphs one by one (that is
  what lets the text layer be in logical order while the display is
  right-to-left), and PyMuPDF's word segmentation puts a word break
  after a combining mark, after an ornate parenthesis, and after an
  LTR number run -- so "شهراً." extracts as "شهراً ." and "(ساما)،"
  as "(ساما) ،". The words, numbers and letters are all in the right
  order; only the space before the punctuation is spurious.

Prints PASS/FAIL per document and exits non-zero if any check fails.
"""
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "data" / "docs_src"
OUT_DIR = ROOT / "data" / "docs"

FOOTER_FRAGMENT = "Synthetic Demo Document, not a real bank"
FOOTER_FULL = "Riyadh Trust Bank \u2014 Synthetic Demo Document, not a real bank."

# Punctuation before which PyMuPDF's word segmentation can insert a
# spurious space when glyphs are emitted one by one (see docstring).
_PUNCT = r".,،,:;!?)؟"
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([%s])" % re.escape(_PUNCT))
_SPACE_AFTER_OPEN_PAREN = re.compile(r"([(﴾])\s+")


def norm(text: str) -> str:
    """NFKD + collapse whitespace + drop spaces around punctuation.

    PDF line-wrap is not in the .md, and PyMuPDF inserts a word break
    before punctuation after a combining mark / ornate parenthesis /
    LTR number run, so those spaces are removed on both sides of the
    comparison.
    """
    text = unicodedata.normalize("NFKD", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    text = _SPACE_AFTER_OPEN_PAREN.sub(r"\1", text)
    return " ".join(text.split())


def has_arabic(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06ff" for ch in text)


def has_presentation_forms(text: str) -> bool:
    return any("\ufb50" <= ch <= "\ufeff" for ch in text)


def content_lines(md_path: Path) -> list[str]:
    """Non-empty .md lines with their markdown markers stripped."""
    lines = []
    for raw in md_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        for prefix in ("# ", "## ", "### ", "- "):
            if line.startswith(prefix):
                line = line[len(prefix):]
                break
        lines.append(line)
    return lines


def verify_one(md_path: Path) -> tuple[bool, list[str]]:
    import fitz

    pdf_path = OUT_DIR / (md_path.stem + ".pdf")
    problems: list[str] = []
    if not pdf_path.exists():
        return False, [f"missing PDF: {pdf_path.name}"]
    doc = fitz.open(str(pdf_path))
    if len(doc) == 0:
        return False, ["PDF has no pages"]
    pages_text = [page.get_text() for page in doc]
    full_text = "\n".join(pages_text)
    # Strip the footer before the content comparison: a paragraph that
    # spans a page break would otherwise have the footer injected
    # between its two halves. (The footer is checked per page below.)
    flat = norm(full_text.replace(FOOTER_FULL, " "))

    if has_presentation_forms(full_text):
        problems.append(
            "extracted text contains Arabic Presentation Forms "
            "(U+FB50-U+FEFF) -- PDF still stores visual-order Arabic"
        )
    for i, page_text in enumerate(pages_text, start=1):
        if FOOTER_FRAGMENT not in page_text:
            problems.append(f"footer missing on page {i}")

    n_arabic = 0
    for line in content_lines(md_path):
        if line == FOOTER_FULL:
            continue  # footer is checked per page, not as body content
        if has_arabic(line):
            n_arabic += 1
            if norm(line) not in flat:
                problems.append(
                    "Arabic line not in logical order in extraction: "
                    + repr(line[:80])
                )
        else:
            if norm(line) not in flat:
                problems.append(
                    "English line missing from extraction: " + repr(line[:80])
                )
    if n_arabic == 0:
        problems.append("no Arabic lines found in .md source (unexpected)")
    return (not problems), problems


def main() -> int:
    mds = sorted(SRC_DIR.glob("*.md"))
    if not mds:
        print("FAIL: no .md sources found")
        return 1
    all_ok = True
    for md in mds:
        ok, problems = verify_one(md)
        status = "PASS" if ok else "FAIL"
        print(f"{status}: {md.stem}.pdf")
        for problem in problems:
            print(f"       - {problem}")
        all_ok &= ok
    print(f"\n{'All 8 PDFs PASS' if all_ok else 'FAILURES -- see above'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
