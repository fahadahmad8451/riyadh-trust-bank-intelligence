"""Generate the 8 synthetic PDFs from data/docs_src/*.md.

Run from the project root:
    python scripts/generate_docs.py

All documents are FICTIONAL (Riyadh Trust Bank is not a real bank).

How the PDFs are built -- and why this way
-------------------------------------------
The old generator shaped Arabic with arabic-reshaper + python-bidi and
wrote it with fpdf2. That renders Arabic in VISUAL order (Arabic
Presentation Forms, U+FB50-U+FEFF): the PDF looks right to a human, but
PyMuPDF extraction returns the Arabic reversed/garbled instead of in
logical order.

Two HTML engines were tried and rejected before settling on this one:

* WeasyPrint (HTML -> PDF via Pango/HarfBuzz): shaping and display are
  correct, and pure-Arabic lines extract in logical order -- but Pango
  emits each visual line's bidi runs in visual (left-to-right) order, so
  on mixed lines the number runs come out displaced in plain
  ``get_text()`` ("60,000 ريال" becomes "ريال60,000" at the wrong place).
  It also splits some lines into overlapping Tj runs, so plain
  extraction inserts stray line breaks mid-sentence ("customer\\n.").
* MuPDF Story (``fitz.Story``): extraction order is logical, including
  numbers -- but it misplaces the paragraph-final full stop (draws it at
  the right edge instead of after the last word) and also splits it off
  as its own extraction line ("الموظفين .").

So this generator typesets with ReportLab + HarfBuzz (``uharfbuzz``)
directly, which gives full control over both the display and the text
layer:

* Each Arabic paragraph is split into directional runs (RTL Arabic,
  LTR numbers, parentheses) and shaped per run with HarfBuzz using a
  patched copy of Noto Sans Arabic (see ``_build_patched_arabic_font``).
* Glyphs are placed at their HarfBuzz-computed display positions (so the
  page shows connected, right-to-left Arabic with correct diacritics)
  but EMITTED into the content stream in LOGICAL order -- so plain
  ``fitz.open(pdf).load_page(n).get_text()`` reads every Arabic line
  exactly as in the ``.md`` source, numbers and parentheses included.
* The patched font has ALL GSUB ligature lookups emptied. Two extractors
  (PyMuPDF and poppler) both emit the codepoints of a multi-character
  ligature glyph in reverse order, so the stock font's lam+alef ligature
  extracted "العملاء" as "العمالء"; with no ligatures every glyph maps
  1:1 to one logical character. Positional forms (init/medi/fina/isol)
  are kept, so letters stay joined. The family is renamed to
  "Noto Sans Arabic NoLig" so nothing can substitute the system font.
* After ReportLab writes the PDF, the Arabic fonts' ToUnicode CMaps are
  rewritten (``_fix_arabic_tounicode``): ReportLab maps each shaped
  glyph to its presentation-form codepoint (e.g. U+FEAA); the rewrite
  maps it to the logical character (U+062F) via the glyph's immediate
  Unicode decomposition, so the text layer contains true logical
  codepoints and no presentation forms at all. ASCII parentheses, which
  the Arabic font lacks, are drawn as the ornate parens U+FD3E/U+FD3F
  (the correct Arabic parentheses) and mapped back to "(" / ")".
* English text is drawn one visual line per ``drawString`` (LTR, no
  shaping needed), so it extracts cleanly too.

Verification: ``scripts/verify_arabic_pdfs.py`` extracts every PDF with
PyMuPDF and compares each line against the ``.md`` source (exact match,
no normalisation needed).
"""
import os
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "data" / "docs_src"
OUT_DIR = ROOT / "data" / "docs"
FONT_CACHE = Path(__file__).resolve().parent / ".fontcache"

AR_FONT = "/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf"
AR_FONT_B = "/usr/share/fonts/truetype/noto/NotoSansArabic-Bold.ttf"
EN_FONT = "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
EN_FONT_B = "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"

PATCHED_FAMILY = "Noto Sans Arabic NoLig"
FOOTER = "Riyadh Trust Bank \u2014 Synthetic Demo Document, not a real bank."

# Layout (points; A4 = 595.27 x 841.89).
PAGE_W, PAGE_H = 595.27, 841.89
X_LEFT = 51.0    # ~18 mm
X_RIGHT = PAGE_W - 51.0
Y_TOP = PAGE_H - 57.0    # ~20 mm from the top
Y_BOTTOM = 57.0          # ~20 mm from the bottom
FOOTER_Y = 42.0
BODY_SIZE = 10
BODY_LEADING = 15.0


def has_arabic(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06ff" for ch in text)


# ---------------------------------------------------------------------------
# Patched Arabic fonts
# ---------------------------------------------------------------------------
def _build_patched_arabic_font(src: str, dst: Path) -> Path:
    """Patch a COPY of Noto Sans Arabic: drop every GSUB ligature.

    Only type-4 (LigatureSubst) lookups are emptied -- ``rlig`` (lam+alef
    fusions), ``ccmp`` (shadda+fatha as one glyph) and ``dlig``. With a
    ligature glyph gone, HarfBuzz renders the same characters as separate
    (still correctly joined) glyphs, and every glyph maps 1:1 to one
    logical character, which is what makes exact extraction possible.
    Positional forms (init/medi/fina/isol) are untouched. The family is
    renamed so no other tool can substitute the system font.
    """
    from fontTools.ttLib import TTFont

    src_path = Path(src)
    if not src_path.exists():
        raise FileNotFoundError(
            f"Arabic source font not found: {src} "
            "(generate_docs.py expects the system Noto fonts)"
        )
    if dst.exists():
        # Reuse the cache only if it is really patched.
        cached = TTFont(str(dst))
        remaining = sum(
            sum(len(v) for v in st.ligatures.values())
            for lk in cached["GSUB"].table.LookupList.Lookup
            if lk.LookupType == 4
            for st in lk.SubTable
        )
        if remaining == 0 and dst.stat().st_mtime >= src_path.stat().st_mtime:
            return dst
    font = TTFont(str(src_path))
    cleared = 0
    for lookup in font["GSUB"].table.LookupList.Lookup:
        if lookup.LookupType != 4:  # 4 = LigatureSubst
            continue
        for subtable in lookup.SubTable:
            cleared += sum(len(v) for v in subtable.ligatures.values())
            subtable.ligatures = {}
    name_table = font["name"]
    for record in name_table.names:
        try:
            text = record.toUnicode()
        except Exception:
            continue
        if "Noto Sans Arabic" in text:
            name_table.setName(
                text.replace("Noto Sans Arabic", PATCHED_FAMILY),
                record.nameID,
                record.platformID,
                record.platEncID,
                record.langID,
            )
    dst.parent.mkdir(parents=True, exist_ok=True)
    font.save(str(dst))
    print(f"  patched Arabic font: {src_path.name} "
          f"(removed {cleared} ligature entries) -> {dst.name}")
    return dst


def _patched_arabic_fonts() -> tuple[Path, Path]:
    regular = _build_patched_arabic_font(
        AR_FONT, FONT_CACHE / "NotoSansArabic-NoLig-Regular.ttf")
    bold = _build_patched_arabic_font(
        AR_FONT_B, FONT_CACHE / "NotoSansArabic-NoLig-Bold.ttf")
    return regular, bold


# ---------------------------------------------------------------------------
# HarfBuzz shaping for Arabic
# ---------------------------------------------------------------------------
class _HbFont:
    """One Arabic font file, shaped with HarfBuzz."""

    def __init__(self, path: Path):
        import uharfbuzz as hb

        self._hb = hb
        self.data = path.read_bytes()
        self.face = hb.Face(self.data)
        self.font = hb.Font(self.face)
        self.upem = self.face.upem
        from fontTools.ttLib import TTFont

        cmap = TTFont(str(path)).getBestCmap()  # unicode -> glyph name
        self.glyph_to_char: dict[str, str] = {}
        for uni, gname in cmap.items():
            self.glyph_to_char.setdefault(gname, chr(uni))
        self._shape_cache: dict = {}

    def shape(self, text: str, direction: str) -> list[dict]:
        """Shape one single-direction run.

        Returns glyphs in HarfBuzz (display) order: left-to-right as they
        appear on the page, each with advances/offsets in font units.
        """
        key = (text, direction)
        if key in self._shape_cache:
            return self._shape_cache[key]
        buf = self._hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        buf.direction = direction
        self._hb.shape(self.font, buf)
        glyphs = [
            {
                "name": self.font.get_glyph_name(info.codepoint),
                "x_advance": pos.x_advance,
                "x_offset": pos.x_offset,
                "y_offset": pos.y_offset,
            }
            for info, pos in zip(buf.glyph_infos, buf.glyph_positions)
        ]
        for glyph in glyphs:
            if glyph["name"] == ".notdef":
                raise ValueError(
                    f"character in {text!r} has no glyph in the Arabic font"
                )
            if glyph["name"] not in self.glyph_to_char:
                raise ValueError(
                    f"glyph {glyph['name']} (from {text!r}) has no cmap "
                    "character to draw it with"
                )
        self._shape_cache[key] = glyphs
        return glyphs

    def advance(self, text: str, direction: str) -> int:
        return sum(g["x_advance"] for g in self.shape(text, direction))


def _char_class(ch: str, prev_ch, next_ch) -> str:
    """'AR' | 'NUM' | 'PAREN' for one char in context (Arabic text only)."""
    if ch in "()":
        return "PAREN"
    if ch == "٪":  # U+066A Arabic percent sign: part of the number
        return "NUM"
    if "0" <= ch <= "9":
        return "NUM"
    if ch == ",":
        return "NUM"  # ASCII comma only occurs inside numbers here
    if ch == ".":
        # Decimal point inside a number, else sentence punctuation (RTL).
        if prev_ch and prev_ch.isdigit() and next_ch and next_ch.isdigit():
            return "NUM"
        return "AR"
    return "AR"


def _split_pieces(word: str) -> list[tuple[str, str]]:
    """Split one word into (kind, text) pieces: AR / NUM / PAREN."""
    pieces: list[tuple[str, str]] = []
    for i, ch in enumerate(word):
        kind = _char_class(
            ch, word[i - 1] if i else None,
            word[i + 1] if i + 1 < len(word) else None)
        if pieces and pieces[-1][0] == kind:
            pieces[-1] = (kind, pieces[-1][1] + ch)
        else:
            pieces.append((kind, ch))
    return pieces


class _ArabicTypesetter:
    """Lays out Arabic paragraphs: display positions from HarfBuzz,
    emission order logical."""

    ORNATE_OPEN = "﴾"   # U+FD3E: opening paren for RTL text
    ORNATE_CLOSE = "﴿"  # U+FD3F: closing paren for RTL text

    def __init__(self, regular_path: Path, bold_path: Path):
        self._fonts = {
            False: _HbFont(regular_path),
            True: _HbFont(bold_path),
        }

    def _piece_width(self, font: _HbFont, kind: str, text: str, scale: float) -> float:
        if kind == "PAREN":
            ch = self.ORNATE_OPEN if text == "(" else self.ORNATE_CLOSE
            return font.advance(ch, "rtl") * scale
        return font.advance(text, "rtl" if kind == "AR" else "ltr") * scale

    def wrap(self, text: str, width_pt: float, size: int, bold: bool = False) -> list[list[str]]:
        """Greedy word wrap. Returns lines; each line is a word list."""
        if any("a" <= ch <= "z" or "A" <= ch <= "Z" for ch in text):
            raise ValueError(
                "Latin letters in Arabic text are not supported by the "
                f"Arabic typesetter: {text[:60]!r}")
        font = self._fonts[bold]
        scale = size / font.upem
        space_w = font.advance(" ", "rtl") * scale
        words = text.split(" ")

        def word_width(word: str) -> float:
            return sum(
                self._piece_width(font, kind, piece, scale)
                for kind, piece in _split_pieces(word)
            )

        lines, cur, cur_w = [], [], 0.0
        for word in words:
            width = word_width(word)
            add = width if not cur else width + space_w
            if cur and cur_w + add > width_pt:
                lines.append(cur)
                cur, cur_w = [word], width
            else:
                cur.append(word)
                cur_w += add
        if cur:
            lines.append(cur)
        return lines

    def layout_line(self, words: list[str], x_left: float, x_right: float,
                    size: int, bold: bool = False) -> list[tuple[str, float, float]]:
        """Lay out one visual line (words in LOGICAL order).

        Returns (char, x_pt, y_offset_pt) in LOGICAL (emit) order, x
        absolute on the page, y_offset relative to the baseline.
        """
        font = self._fonts[bold]
        scale = size / font.upem
        space_w = font.advance(" ", "rtl") * scale

        def piece_width(kind: str, text: str) -> float:
            return self._piece_width(font, kind, text, scale)

        word_widths = [
            sum(piece_width(kind, piece) for kind, piece in _split_pieces(w))
            for w in words
        ]
        glyphs: list[tuple[str, float, float]] = []
        x_cursor = x_right
        for wi, word in enumerate(words):
            pieces = _split_pieces(word)
            box_right = x_cursor
            box_left = x_cursor - word_widths[wi]
            # Pieces are placed right-to-left in logical order.
            p_cursor = box_right
            for kind, text in pieces:
                p_width = piece_width(kind, text)
                p_box_left = p_cursor - p_width
                if kind == "PAREN":
                    ch = self.ORNATE_OPEN if text == "(" else self.ORNATE_CLOSE
                    glyphs.append((ch, p_box_left, 0.0))
                else:
                    direction = "rtl" if kind == "AR" else "ltr"
                    shaped = font.shape(text, direction)  # display order
                    x = p_box_left
                    placed = []
                    for glyph in shaped:
                        gx = x + glyph["x_offset"] * scale
                        gy = glyph["y_offset"] * scale
                        placed.append(
                            (font.glyph_to_char[glyph["name"]], gx, gy))
                        x += glyph["x_advance"] * scale
                    if kind == "AR":
                        placed.reverse()  # display order -> logical order
                    glyphs.extend(placed)
                p_cursor -= p_width
            x_cursor = box_left
            if wi < len(words) - 1:
                # The space after a word sits to its left (RTL).
                glyphs.append((" ", x_cursor - space_w, 0.0))
                x_cursor -= space_w
        return glyphs


# ---------------------------------------------------------------------------
# ToUnicode fix: presentation-form glyphs -> logical characters
# ---------------------------------------------------------------------------
def _logical_char(ch: str) -> str:
    """Map one ToUnicode character to the logical character it stands for.

    Only Arabic Presentation Forms are rewritten, using their IMMEDIATE
    (one-level) Unicode decomposition -- e.g. U+FE83 (alef-with-hamza
    FINAL form) -> U+0623 (precomposed alef-with-hamza), NOT the fully
    decomposed U+0627+U+0654 that NFKD would give. Ordinary characters
    are kept exactly as they are. Ornate parens map back to ASCII ones.
    """
    if ch == "﴾":
        return "("
    if ch == "﴿":
        return ")"
    if "\ufb50" <= ch <= "\ufdff" or "\ufe70" <= ch <= "\ufeff":
        decomp = unicodedata.decomposition(ch)
        if decomp:
            codepoints = [p for p in decomp.split() if not p.startswith("<")]
            return "".join(chr(int(cp, 16)) for cp in codepoints)
    return ch


def _fix_arabic_tounicode(pdf_path: Path) -> int:
    """Rewrite the Arabic fonts' ToUnicode CMaps in place.

    ReportLab maps each shaped glyph to its presentation-form codepoint
    (e.g. U+FEAA); this rewrites those entries to the logical character
    (U+062F), so the text layer holds true logical codepoints and no
    presentation forms at all. Returns the number of fonts rewritten.
    """
    import fitz

    doc = fitz.open(str(pdf_path))
    rewritten = 0
    for pno in range(len(doc)):
        for font in doc[pno].get_fonts(full=True):
            xref, basefont = font[0], font[3]
            if "NotoSansArabic" not in basefont:
                continue
            obj = doc.xref_object(xref)
            match = re.search(r"/ToUnicode (\d+) 0 R", obj)
            if not match:
                continue
            tu_xref = int(match.group(1))
            raw = doc.xref_stream(tu_xref).decode("latin-1")

            def repl(m: "re.Match[str]") -> str:
                code, uni_hex = m.group(1), m.group(2)
                chars = "".join(
                    chr(int(uni_hex[i:i + 4], 16))
                    for i in range(0, len(uni_hex), 4)
                )
                new = "".join(_logical_char(c) for c in chars)
                new_hex = "".join(f"{ord(c):04X}" for c in new)
                return f"<{code}> <{new_hex}>"

            new_raw, _n = re.subn(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]{4,})>", repl, raw)
            doc.update_stream(tu_xref, new_raw.encode("latin-1"))
            rewritten += 1
    if rewritten:
        tmp_path = pdf_path.with_suffix(".tmp.pdf")
        doc.save(str(tmp_path), garbage=0, deflate=True)
        doc.close()
        os.replace(tmp_path, pdf_path)
    else:
        doc.close()
    return rewritten


# ---------------------------------------------------------------------------
# Document builder (ReportLab canvas)
# ---------------------------------------------------------------------------
def _parse_blocks(md_path: Path):
    """Yield (kind, text) blocks: 'h1' | 'h2' | 'h3' | 'p' | 'li' | 'blank'."""
    for raw in md_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            yield ("blank", "")
        elif line.startswith("# "):
            yield ("h1", line[2:])
        elif line.startswith("## "):
            yield ("h2", line[3:])
        elif line.startswith("### "):
            yield ("h3", line[4:])
        elif line.startswith("- "):
            yield ("li", line[2:])
        else:
            yield ("p", line)


def build_pdf(md_path: Path, out_path: Path, typesetter: _ArabicTypesetter) -> int:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont as RLTTFont
    from reportlab.pdfgen import canvas as rl_canvas

    pdfmetrics.registerFont(RLTTFont("Noto", EN_FONT))
    pdfmetrics.registerFont(RLTTFont("Noto-Bold", EN_FONT_B))
    pdfmetrics.registerFont(RLTTFont("NotoSansArabic-NoLig", str(
        FONT_CACHE / "NotoSansArabic-NoLig-Regular.ttf")))
    pdfmetrics.registerFont(RLTTFont("NotoSansArabic-NoLig-Bold", str(
        FONT_CACHE / "NotoSansArabic-NoLig-Bold.ttf")))

    tmp_path = out_path.with_suffix(".tmp.pdf")
    pdf = rl_canvas.Canvas(str(tmp_path), pagesize=A4)
    pages = 1
    y = Y_TOP

    def draw_footer():
        pdf.setFont("Noto", 8)
        pdf.drawCentredString(PAGE_W / 2, FOOTER_Y, FOOTER)

    def new_page():
        nonlocal pages, y
        draw_footer()
        pdf.showPage()
        pages += 1
        y = Y_TOP

    def need_space(height: float):
        if y - height < Y_BOTTOM:
            new_page()

    def draw_english_lines(lines, size, bold, x_left, x_right, leading):
        nonlocal y
        font = "Noto-Bold" if bold else "Noto"
        for line in lines:
            need_space(leading)
            pdf.setFont(font, size)
            pdf.drawString(x_left, y, line)
            y -= leading

    def wrap_english(text, size, bold, width):
        font = "Noto-Bold" if bold else "Noto"
        lines, cur = [], ""
        for word in text.split(" "):
            trial = (cur + " " + word).strip()
            if cur and pdfmetrics.stringWidth(trial, font, size) > width:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        if cur:
            lines.append(cur)
        return lines

    def draw_arabic_lines(lines, size, bold, x_left, x_right, leading):
        nonlocal y
        font = ("NotoSansArabic-NoLig-Bold" if bold
                else "NotoSansArabic-NoLig")
        for words in lines:
            need_space(leading)
            pdf.setFont(font, size)
            for ch, gx, gy in typesetter.layout_line(
                    words, x_left, x_right, size, bold):
                pdf.drawString(gx, y + gy, ch)
            y -= leading

    for kind, text in _parse_blocks(md_path):
        if kind == "blank":
            y -= 8
            continue
        if kind == "h1":
            need_space(6 + 20)
            y -= 6
            draw_english_lines([text], 16, True, X_LEFT, X_RIGHT, 20)
            y -= 8
        elif kind == "h2":
            need_space(10 + 17)
            y -= 10
            if has_arabic(text):
                lines = typesetter.wrap(text, X_RIGHT - X_LEFT, 13, bold=True)
                draw_arabic_lines(lines, 13, True, X_LEFT, X_RIGHT, 17)
            else:
                draw_english_lines([text], 13, True, X_LEFT, X_RIGHT, 17)
            y -= 4
        elif kind == "h3":
            need_space(8 + 15)
            y -= 8
            draw_english_lines([text], 11, True, X_LEFT, X_RIGHT, 15)
            y -= 3
        elif kind == "p":
            if has_arabic(text):
                lines = typesetter.wrap(text, X_RIGHT - X_LEFT, BODY_SIZE)
                draw_arabic_lines(lines, BODY_SIZE, False,
                                  X_LEFT, X_RIGHT, BODY_LEADING)
            else:
                lines = wrap_english(text, BODY_SIZE, False,
                                     X_RIGHT - X_LEFT)
                draw_english_lines(lines, BODY_SIZE, False,
                                   X_LEFT, X_RIGHT, BODY_LEADING)
            y -= 2
        elif kind == "li":
            bullet_x = X_LEFT
            text_x = X_LEFT + 14
            width = X_RIGHT - text_x
            if has_arabic(text):
                lines = typesetter.wrap(text, width, BODY_SIZE)
                # Bullet marker goes on the right for RTL lines.
                first = True
                for words in lines:
                    need_space(BODY_LEADING)
                    if first:
                        pdf.setFont("NotoSansArabic-NoLig", BODY_SIZE)
                        pdf.drawString(X_RIGHT - 8, y, "\u2022")
                        first = False
                    draw_arabic_lines([words], BODY_SIZE, False,
                                      X_LEFT, X_RIGHT - 14, BODY_LEADING)
                    # draw_arabic_lines already advanced y; undo double count
                    # (it advanced once per line, which is what we want)
            else:
                lines = wrap_english(text, BODY_SIZE, False, width)
                for i, line in enumerate(lines):
                    need_space(BODY_LEADING)
                    pdf.setFont("Noto", BODY_SIZE)
                    if i == 0:
                        pdf.drawString(bullet_x, y, "\u2022")
                    pdf.drawString(text_x, y, line)
                    y -= BODY_LEADING
            y -= 2

    draw_footer()
    pdf.save()
    _fix_arabic_tounicode(tmp_path)
    os.replace(tmp_path, out_path)
    return pages


def main() -> None:
    ar_regular, ar_bold = _patched_arabic_fonts()
    typesetter = _ArabicTypesetter(ar_regular, ar_bold)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    total_pages = 0
    for md in sorted(SRC_DIR.glob("*.md")):
        out = OUT_DIR / (md.stem + ".pdf")
        pages = build_pdf(md, out, typesetter)
        total_pages += pages
        print(f"{md.name:35s} -> {out.name:30s} {pages} pages")
    print(f"Done: {len(list(SRC_DIR.glob('*.md')))} documents, {total_pages} pages total.")


if __name__ == "__main__":
    main()
