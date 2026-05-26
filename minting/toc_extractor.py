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
from pathlib import Path

from pypdf import PdfReader

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
