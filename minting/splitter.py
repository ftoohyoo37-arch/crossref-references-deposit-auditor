"""PDF splitter: whole-issue PDF → per-article PDFs.

Given an IssueSidecar with `articles[]` containing start_page / end_page
and a target filename for each, slice the source PDF into N output
PDFs in the journal's pdfs/<issue_slug>/ directory.

Also writes a doi-map.json sidecar mapping basename → DOI (or empty
string if the DOI hasn't been minted yet — the deposit_builder fills
those in once it generates the content-registration XML).
"""
from __future__ import annotations

import json
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from .models import IssueSidecar


class SplitError(Exception):
    pass


def validate_boundaries(sidecar: IssueSidecar, page_count: int) -> list[str]:
    """Return a list of human-readable error strings; empty if valid."""
    errors: list[str] = []
    if not sidecar.articles:
        errors.append("No articles defined.")
        return errors

    seen_filenames: set[str] = set()
    for i, art in enumerate(sidecar.articles):
        prefix = f"Article {i + 1}"
        if not art.filename:
            errors.append(f"{prefix}: missing filename.")
        elif not art.filename.endswith(".pdf"):
            errors.append(f"{prefix}: filename must end in .pdf "
                          f"(got '{art.filename}').")
        elif art.filename in seen_filenames:
            errors.append(f"{prefix}: duplicate filename '{art.filename}'.")
        else:
            seen_filenames.add(art.filename)

        if art.start_page < 1:
            errors.append(f"{prefix}: start_page must be >= 1 "
                          f"(got {art.start_page}).")
        if art.end_page > page_count:
            errors.append(f"{prefix}: end_page {art.end_page} exceeds "
                          f"PDF length {page_count}.")
        if art.start_page > art.end_page:
            errors.append(f"{prefix}: start_page > end_page "
                          f"({art.start_page} > {art.end_page}).")

    # Overlap detection
    sorted_arts = sorted(
        enumerate(sidecar.articles, start=1),
        key=lambda x: x[1].start_page,
    )
    for (i_a, art_a), (i_b, art_b) in zip(sorted_arts, sorted_arts[1:]):
        if art_a.end_page >= art_b.start_page:
            errors.append(
                f"Article {i_a} (pp.{art_a.start_page}-{art_a.end_page}) "
                f"overlaps Article {i_b} (pp.{art_b.start_page}-{art_b.end_page})."
            )

    return errors


def split_issue(issue_pdf: Path, sidecar: IssueSidecar,
                output_dir: Path,
                *, overwrite: bool = False) -> dict:
    """Slice issue_pdf into per-article PDFs in output_dir.

    Returns a summary dict with the list of written paths + any
    warnings/errors. Raises SplitError on hard validation failures.
    """
    if not issue_pdf.exists():
        raise SplitError(f"Source PDF not found: {issue_pdf}")

    reader = PdfReader(str(issue_pdf))
    page_count = len(reader.pages)

    errors = validate_boundaries(sidecar, page_count)
    if errors:
        raise SplitError("Boundaries invalid:\n  - " + "\n  - ".join(errors))

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[dict] = []
    skipped: list[str] = []
    for art in sidecar.articles:
        target = output_dir / art.filename
        if target.exists() and not overwrite:
            skipped.append(art.filename)
            continue
        writer = PdfWriter()
        # 1-based inclusive → 0-based slice
        for p in range(art.start_page - 1, art.end_page):
            writer.add_page(reader.pages[p])
        # Preserve PDF metadata in a minimal way; CrossRef registration
        # XML carries the canonical metadata anyway.
        if art.title:
            writer.add_metadata({"/Title": art.title})
        with open(target, "wb") as fp:
            writer.write(fp)
        written.append({
            "filename": art.filename,
            "pages": (art.start_page, art.end_page),
            "size_kb": target.stat().st_size // 1024,
        })

    # Write doi-map.json sidecar (empty DOIs until minting deposit runs)
    doi_map_path = output_dir / "doi-map.json"
    existing: dict = {}
    if doi_map_path.exists():
        try:
            existing = json.loads(doi_map_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    for art in sidecar.articles:
        # Don't clobber an existing minted DOI on re-split
        if art.filename not in existing:
            existing[art.filename] = art.doi or ""
    doi_map_path.write_text(
        json.dumps(existing, indent=2),
        encoding="utf-8",
    )

    return {
        "written": written,
        "skipped": skipped,
        "page_count": page_count,
        "output_dir": str(output_dir),
        "doi_map": str(doi_map_path),
    }
