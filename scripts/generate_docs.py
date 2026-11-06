"""Generate the 8 synthetic PDFs from data/docs_src/*.md.

Run from the project root:
    python scripts/generate_docs.py

All documents are FICTIONAL (Riyadh Trust Bank is not a real bank).
English body uses Noto Sans; Arabic lines are shaped with
arabic-reshaper + python-bidi and rendered in Noto Sans Arabic.
fpdf2 note: every multi_cell call passes new_x="LMARGIN", new_y="NEXT"
(the fpdf2 multi_cell cursor trap — see project notes).
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "data" / "docs_src"
OUT_DIR = ROOT / "data" / "docs"

AR_FONT = "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf"
AR_FONT_B = "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf"
EN_FONT = "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
EN_FONT_B = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"


def has_arabic(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06ff" for ch in text)


def shape_arabic(text: str) -> str:
    """Reshape + bidi so Arabic renders correctly in fpdf2."""
    import arabic_reshaper
    from bidi.algorithm import get_display

    # Noto Sans Arabic lacks ASCII ( ) glyphs — use Arabic ornate parens.
    text = text.replace("(", "\ufd3e").replace(")", "\ufd3f")
    return get_display(arabic_reshaper.reshape(text))


def build_pdf(md_path: Path, out_path: Path) -> int:
    from fpdf import FPDF

    lines = md_path.read_text(encoding="utf-8").splitlines()
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pdf.add_font("Noto", "", EN_FONT)
    pdf.add_font("Noto", "B", EN_FONT_B)
    pdf.add_font("NotoAr", "", AR_FONT)
    pdf.add_font("NotoAr", "B", AR_FONT_B)

    def write(text: str, size: int, bold: bool = False, align: str = "L"):
        font = "NotoAr" if has_arabic(text) else "Noto"
        if has_arabic(text):
            text = shape_arabic(text)
            align = "R"
        pdf.set_font(font, "B" if bold else "", size)
        pdf.multi_cell(0, 6, text, new_x="LMARGIN", new_y="NEXT", align=align)

    for raw in lines:
        line = raw.strip()
        if not line:
            pdf.ln(3)
            continue
        if line.startswith("# "):
            pdf.ln(2)
            write(line[2:], 16, bold=True)
            pdf.ln(2)
        elif line.startswith("## "):
            pdf.ln(3)
            write(line[3:], 13, bold=True)
        elif line.startswith("### "):
            pdf.ln(2)
            write(line[4:], 11, bold=True)
        elif line.startswith("- "):
            write("\u2022  " + line[2:], 10)
        else:
            write(line, 10)
    # Footer on every page: fictional-bank notice
    for i in range(len(pdf.pages)):
        pdf.page = i + 1
        pdf.set_y(-15)
        pdf.set_font("Noto", "", 8)
        pdf.cell(0, 10, "Riyadh Trust Bank — Synthetic Demo Document, not a real bank.", align="C")
    pdf.output(str(out_path))
    return len(pdf.pages)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    total_pages = 0
    for md in sorted(SRC_DIR.glob("*.md")):
        out = OUT_DIR / (md.stem + ".pdf")
        pages = build_pdf(md, out)
        total_pages += pages
        print(f"{md.name:35s} -> {out.name:30s} {pages} pages")
    print(f"Done: {len(list(SRC_DIR.glob('*.md')))} documents, {total_pages} pages total.")


if __name__ == "__main__":
    main()
