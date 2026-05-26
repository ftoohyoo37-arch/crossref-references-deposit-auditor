"""Data shapes used across the minting workflow.

State is JSON-on-disk, not SQL — one sidecar file per issue PDF, kept
next to the source PDF. This matches the rest of the codebase's
disk-as-source-of-truth convention.

Sidecar location:
    <Journal>/issue_pdfs/<issue_slug>.pdf
    <Journal>/issue_pdfs/<issue_slug>.json   <-- this file
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class Article:
    """One article within an issue. `start_page`/`end_page` are 1-based
    inclusive page numbers in the source issue PDF."""
    start_page: int
    end_page: int
    filename: str = ""        # e.g. "morrison-anderson.pdf"
    title: str = ""
    authors: list[dict] = field(default_factory=list)   # [{given, surname}, ...]
    sequence: int = 0
    doi: str = ""             # populated by deposit_builder
    resource_url: str = ""    # public landing URL, if available
    abstract: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class IssueSidecar:
    """Per-issue metadata + article list. Persisted as <slug>.json
    next to <slug>.pdf in <Journal>/issue_pdfs/.
    """
    issue_slug: str            # e.g. "v53i2"
    issue_pdf: str             # filename of the issue PDF
    volume: int = 0
    issue: int = 0
    year: int = 0
    month: int = 0             # 1-12; 0 means "unknown"
    issue_title: str = ""      # e.g. "Fall 2025"
    articles: list[Article] = field(default_factory=list)
    # 1-based page numbers within issue_pdf that contain the table of
    # contents. Used by the OCR + parse pipeline to lift author / title /
    # start-page metadata for each article. Empty until the user marks them.
    toc_pages: list[int] = field(default_factory=list)
    # Cached OCR text from the most recent run on toc_pages; populated
    # by the OCR route. Stored here so re-parsing doesn't require
    # re-OCR'ing.
    toc_ocr_text: str = ""

    @classmethod
    def load(cls, path: Path) -> "IssueSidecar":
        data = json.loads(path.read_text(encoding="utf-8"))
        articles = [Article(**a) for a in data.pop("articles", [])]
        return cls(articles=articles, **data)

    def save(self, path: Path) -> None:
        d = asdict(self)
        path.write_text(json.dumps(d, indent=2), encoding="utf-8")

    @classmethod
    def new_for(cls, issue_pdf_path: Path) -> "IssueSidecar":
        slug = issue_pdf_path.stem
        return cls(issue_slug=slug, issue_pdf=issue_pdf_path.name)
