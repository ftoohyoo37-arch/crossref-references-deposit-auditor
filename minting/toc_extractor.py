"""Best-effort table-of-contents inference from an issue PDF.

The goal is to pre-fill the article boundary editor so the user has
something to edit instead of an empty form. Three signal sources, in
priority order:

  1. The PDF's own bookmark / outline tree (if the publisher used one,
     which is rare but cheap to check).
  2. Heuristic ToC-page scrape: pull the text of pages 1-3, look for
     a line pattern like "<title> ... <page_number>" and map each
     start page to an article.
  3. Empty placeholder articles so the UI has rows to edit.

This is intentionally fuzzy — the UI is designed to accept user
corrections, not to be a fully automated solution.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from .models import Article, IssueSidecar


_TOC_HEADER_PATTERNS = [
    re.compile(r"\b(table of contents|contents|in this issue)\b", re.IGNORECASE),
]

# Match a ToC line ending in a page number, e.g.
#   "Smith, John. On Genre and Discourse ......................... 12"
#   "Smith, J. ON GENRE AND DISCOURSE  12"
# Anchored on a 1-3 digit page number at end of line.
_TOC_LINE = re.compile(
    r"^\s*(?P<title>[^\d\n]{6,160}?)\s*[.·•\s]{2,}\s*(?P<page>\d{1,4})\s*$",
    re.MULTILINE,
)


def _read_text(reader: PdfReader, start: int, end: int) -> str:
    out: list[str] = []
    for i in range(start, min(end, len(reader.pages))):
        try:
            out.append(reader.pages[i].extract_text() or "")
        except Exception:
            out.append("")
    return "\n".join(out)


def _from_outline(reader: PdfReader) -> list[Article]:
    """If the PDF has a bookmark tree, harvest top-level entries as articles."""
    try:
        outline = reader.outline
    except Exception:
        return []
    if not outline:
        return []
    out: list[Article] = []
    for item in outline:
        # Nested bookmarks come as lists; only walk flat top-level for V1
        if isinstance(item, list):
            continue
        try:
            title = (item.title or "").strip()
            dest = reader.get_destination_page_number(item)
        except Exception:
            continue
        if not title:
            continue
        # +1 because pypdf returns 0-based; sidecar uses 1-based pages
        out.append(Article(
            start_page=dest + 1,
            end_page=dest + 1,   # filled in after the loop
            title=title,
        ))
    # Fill end_page from the next entry's start (last one runs to PDF end)
    for i, art in enumerate(out):
        if i + 1 < len(out):
            art.end_page = out[i + 1].start_page - 1
    return out


def _from_toc_text(reader: PdfReader) -> list[Article]:
    """Scrape ToC pages and extract title/page candidates."""
    text = _read_text(reader, 0, 4)  # first 4 pages cover most ToCs
    if not any(p.search(text) for p in _TOC_HEADER_PATTERNS):
        return []
    out: list[Article] = []
    for m in _TOC_LINE.finditer(text):
        title = m.group("title").strip()
        page = int(m.group("page"))
        if page < 1 or page > 999:
            continue
        # Skip headers/footers that incidentally match
        if title.lower() in ("contents", "table of contents", "in this issue"):
            continue
        out.append(Article(
            start_page=page,
            end_page=page,
            title=title,
        ))
    if not out:
        return []
    # Sort by start_page, dedupe close duplicates, fill end_page from next start
    out.sort(key=lambda a: a.start_page)
    deduped: list[Article] = []
    for a in out:
        if deduped and a.start_page == deduped[-1].start_page:
            # Keep the longer title
            if len(a.title) > len(deduped[-1].title):
                deduped[-1] = a
            continue
        deduped.append(a)
    for i, art in enumerate(deduped):
        if i + 1 < len(deduped):
            art.end_page = deduped[i + 1].start_page - 1
    return deduped


def infer_toc(issue_pdf: Path) -> tuple[list[Article], str]:
    """Return (articles, source) where `source` describes which signal won.

    Never raises — on any failure returns ([], 'none').
    """
    try:
        reader = PdfReader(str(issue_pdf))
    except Exception:
        return ([], "open-failed")

    page_count = len(reader.pages)

    arts = _from_outline(reader)
    if arts:
        # Cap end_page at the actual PDF length
        for a in arts:
            a.end_page = min(a.end_page or a.start_page, page_count)
        return (arts, "outline")

    arts = _from_toc_text(reader)
    if arts:
        for a in arts:
            a.end_page = min(a.end_page or a.start_page, page_count)
        return (arts, "toc-text")

    return ([], "none")


def populate_sidecar(sidecar: IssueSidecar, issue_pdf: Path) -> str:
    """Fill sidecar.articles from automatic inference if it's empty.

    Returns the source string ('outline' / 'toc-text' / 'none').
    """
    if sidecar.articles:
        return "already-populated"
    arts, source = infer_toc(issue_pdf)
    if arts:
        for i, a in enumerate(arts):
            a.sequence = i + 1
        sidecar.articles = arts
    return source


# ----------- OCR-driven ToC extraction (user-marked pages) -----------

class OCRUnavailable(Exception):
    """Raised when neither ocrmypdf nor Tesseract is available."""


def _check_ocr_tools() -> str:
    """Return a description of available OCR tooling, or raise."""
    if shutil.which("ocrmypdf"):
        return "ocrmypdf"
    if shutil.which("tesseract"):
        return "tesseract"
    raise OCRUnavailable(
        "Neither `ocrmypdf` nor `tesseract` was found on PATH. "
        "Install Tesseract (https://github.com/tesseract-ocr/tesseract) "
        "or ocrmypdf (`pip install ocrmypdf`) to use ToC OCR."
    )


def _extract_pages_to_pdf(source_pdf: Path, pages: list[int],
                          target: Path) -> int:
    """Slice the given (1-based, inclusive) page numbers from source_pdf
    into a new PDF at target. Returns the page count written.
    """
    reader = PdfReader(str(source_pdf))
    writer = PdfWriter()
    n = 0
    total = len(reader.pages)
    for p in pages:
        if p < 1 or p > total:
            continue
        writer.add_page(reader.pages[p - 1])
        n += 1
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "wb") as fp:
        writer.write(fp)
    return n


def ocr_toc_pages(issue_pdf: Path, pages: list[int]) -> str:
    """Run a forced OCR pass on the specified pages of issue_pdf and
    return the extracted text.

    Uses ocrmypdf when available (best quality, handles deskew /
    layout normalization). Falls back to Tesseract via a pdftoppm
    rasterization pass for environments where only Tesseract is on PATH.

    Pages are 1-based and may be out of order; we honour the order in
    `pages` so the caller can reorder ToC pages if useful.
    """
    if not pages:
        return ""
    tool = _check_ocr_tools()
    with tempfile.TemporaryDirectory(prefix="toc-ocr-") as td:
        td_path = Path(td)
        slice_pdf = td_path / "toc-slice.pdf"
        n_pages = _extract_pages_to_pdf(issue_pdf, pages, slice_pdf)
        if n_pages == 0:
            return ""

        if tool == "ocrmypdf":
            out_pdf = td_path / "toc-slice.ocr.pdf"
            cmd = [
                "ocrmypdf",
                "--force-ocr",        # ignore any existing (probably bad) text layer
                "--optimize", "0",    # minimize wall time
                "--quiet",
                str(slice_pdf), str(out_pdf),
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if r.returncode != 0:
                # Fall back to raw tesseract on rasterized pages
                return _ocr_via_tesseract(slice_pdf, td_path)
            reader = PdfReader(str(out_pdf))
            return "\n\n".join(
                (p.extract_text() or "") for p in reader.pages
            )
        else:
            return _ocr_via_tesseract(slice_pdf, td_path)


def _ocr_via_tesseract(slice_pdf: Path, td: Path) -> str:
    """Rasterize the slice PDF page-by-page (via Ghostscript if available;
    otherwise pdftoppm) and run Tesseract on each page image.
    """
    # Try Ghostscript first (usually available alongside ocrmypdf)
    gs = shutil.which("gswin64c") or shutil.which("gs")
    if gs:
        out_pattern = td / "page-%03d.png"
        subprocess.run(
            [gs, "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE",
             "-sDEVICE=png16m", "-r300",
             f"-sOutputFile={out_pattern}", str(slice_pdf)],
            check=True, timeout=300,
        )
    else:
        # pdftoppm produces page-XXX.png style output
        pp = shutil.which("pdftoppm")
        if not pp:
            raise OCRUnavailable("No rasterizer (Ghostscript or pdftoppm) found.")
        subprocess.run(
            [pp, "-r", "300", "-png", str(slice_pdf), str(td / "page")],
            check=True, timeout=300,
        )

    pieces: list[str] = []
    for img in sorted(td.glob("page-*.png")) + sorted(td.glob("page-*.ppm")):
        r = subprocess.run(
            ["tesseract", str(img), "-", "--psm", "6", "-l", "eng"],
            capture_output=True, text=True, timeout=120,
        )
        pieces.append(r.stdout)
    return "\n\n".join(pieces)


# Lines in a ToC that point at an article. Trying to be permissive so
# OCR-noisy lines still get a chance. Two main shapes:
#   "Author, Title ........... 12"         (page-number at end of line)
#   "Title                    Author 12"   (less common in CS)
_TOC_ENTRY = re.compile(
    r"^[\s•·•·]*"
    r"(?P<line>[A-Z][^\n]{8,200}?)"
    r"\s*[.·•·•\s]{2,}\s*"
    r"(?P<page>\d{1,4})\s*$",
    re.MULTILINE,
)


def parse_toc_text(text: str, *, page_count: int = 9999) -> list[Article]:
    """Walk OCR'd ToC text and return candidate Article rows.

    Pulls author/title/page from each plausible line. We split each
    line into a leading author block (everything up to the first
    period/title-case break) and the remainder as the title.
    """
    out: list[Article] = []
    for m in _TOC_ENTRY.finditer(text):
        raw = m.group("line").strip()
        try:
            page = int(m.group("page"))
        except ValueError:
            continue
        if page < 1 or page > page_count:
            continue
        # Reject obvious noise / headers
        if raw.lower().rstrip(".:- ") in (
            "contents", "table of contents", "in this issue",
            "from the editors", "editors note", "front matter",
        ):
            continue
        # Heuristic split: "Surname, Given Title."  → author=Surname, Given
        title, authors = _split_author_title(raw)
        out.append(Article(
            start_page=page,
            end_page=page,
            title=title,
            authors=authors,
        ))

    # Sort by start_page, dedupe duplicate page anchors (longer title wins)
    out.sort(key=lambda a: a.start_page)
    deduped: list[Article] = []
    for a in out:
        if deduped and a.start_page == deduped[-1].start_page:
            if len(a.title) > len(deduped[-1].title):
                deduped[-1] = a
            continue
        deduped.append(a)
    # Fill end_page from next start_page; last gets a cap of page_count
    for i, art in enumerate(deduped):
        if i + 1 < len(deduped):
            art.end_page = deduped[i + 1].start_page - 1
        else:
            art.end_page = page_count
    return deduped


_AUTHOR_LEAD = re.compile(
    r"^([A-Z][A-Za-z'\.\-]+,(?:\s+[A-Z][A-Za-z'\.\-]+)+"
    r"(?:\s+(?:and|&)\s+[A-Z][A-Za-z'\.\-]+(?:\s+[A-Z][A-Za-z'\.\-]+)*)*)"
    r"[.\s]+(.+)$"
)


def _split_author_title(line: str) -> tuple[str, list[dict]]:
    """Best-effort split: 'Smith, John. On Genre.' →
    title='On Genre', authors=[{given:'John', surname:'Smith'}]
    """
    m = _AUTHOR_LEAD.match(line.strip())
    if not m:
        return (line.strip().rstrip("."), [])
    author_block, title = m.group(1), m.group(2).strip().rstrip(".")
    # Split on " and " / " & " for co-authors
    parts = re.split(r"\s+(?:and|&)\s+", author_block)
    authors: list[dict] = []
    for p in parts:
        p = p.strip().rstrip(",.")
        if "," in p:
            sur, _, giv = p.partition(",")
            authors.append({
                "given": giv.strip(),
                "surname": sur.strip(),
            })
        else:
            authors.append({"given": "", "surname": p})
    return (title, authors)


def populate_from_ocr(sidecar: IssueSidecar, issue_pdf: Path,
                      page_count: int) -> tuple[int, str]:
    """Run OCR on sidecar.toc_pages, parse the result, populate
    sidecar.articles (overwriting any existing).

    Returns (article_count, ocr_text). ocr_text is also stashed on the
    sidecar for re-parse without a second OCR pass.
    """
    text = ocr_toc_pages(issue_pdf, sidecar.toc_pages)
    sidecar.toc_ocr_text = text
    if not text.strip():
        sidecar.articles = []
        return (0, text)
    arts = parse_toc_text(text, page_count=page_count)
    for i, a in enumerate(arts):
        a.sequence = i + 1
    sidecar.articles = arts
    return (len(arts), text)


def reparse_from_cached_ocr(sidecar: IssueSidecar,
                             page_count: int) -> int:
    """Re-parse the cached toc_ocr_text without re-running OCR.
    Useful after a parser tweak.
    """
    if not sidecar.toc_ocr_text.strip():
        return 0
    arts = parse_toc_text(sidecar.toc_ocr_text, page_count=page_count)
    for i, a in enumerate(arts):
        a.sequence = i + 1
    sidecar.articles = arts
    return len(arts)
