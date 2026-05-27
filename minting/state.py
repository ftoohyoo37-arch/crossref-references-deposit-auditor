"""Discover per-journal minting state from the filesystem.

A journal participates in the minting workflow if it has an
`issue_pdfs/` subdirectory with at least one .pdf inside. Each such
PDF gets a sibling .json sidecar with the IssueSidecar shape; absent
sidecars are treated as "not yet split."
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import IssueSidecar


_VOLISS_SLUG = re.compile(r"^v(\d+)(?:i(\d+))?$", re.IGNORECASE)


def _issue_sort_key(slug: str) -> tuple:
    """Chronological key for an issue slug.

    'v1i1' / 'v1i2' / 'v10i1' sort as (1,1) < (1,2) < (10,1), which
    is the actual publication order rather than lexical (which puts
    v10i1 before v1i1 because '0' < 'i' in ASCII).

    Slugs that don't match the v<N>i<M> shape sort to the end,
    keyed by the raw string so they're still stable.
    """
    m = _VOLISS_SLUG.match(slug)
    if not m:
        return (10**9, 10**9, slug)
    vol = int(m.group(1))
    iss = int(m.group(2)) if m.group(2) else 0
    return (vol, iss, slug)


@dataclass
class IssueState:
    issue_pdf: Path
    slug: str
    sidecar_path: Path
    sidecar: IssueSidecar | None = None
    split_dir: Path | None = None
    split_count: int = 0
    has_doi_map: bool = False
    article_count: int = 0
    article_with_dois: int = 0

    @property
    def has_sidecar(self) -> bool:
        return self.sidecar_path.exists() and self.sidecar is not None

    @property
    def is_split(self) -> bool:
        return self.split_count > 0


def _journal_pdfs_root(journal_dir: Path) -> Path:
    """Return the per-article pdfs/ root used by the existing pipeline."""
    return journal_dir / "pdfs"


def _issue_split_dir(journal_dir: Path, slug: str) -> Path:
    """Where per-article PDFs for one issue land."""
    return _journal_pdfs_root(journal_dir) / slug


def list_issues(journal_dir: Path) -> list[IssueState]:
    """Walk <Journal>/issue_pdfs/ and return one IssueState per .pdf.

    Quiet if the directory doesn't exist.
    """
    issues_root = journal_dir / "issue_pdfs"
    if not issues_root.is_dir():
        return []
    out: list[IssueState] = []
    for pdf in sorted(issues_root.glob("*.pdf"),
                       key=lambda p: _issue_sort_key(p.stem)):
        slug = pdf.stem
        sidecar_path = pdf.with_suffix(".json")
        sidecar = None
        if sidecar_path.exists():
            try:
                sidecar = IssueSidecar.load(sidecar_path)
            except Exception:
                sidecar = None
        split_dir = _issue_split_dir(journal_dir, slug)
        split_count = 0
        if split_dir.is_dir():
            split_count = sum(1 for _ in split_dir.glob("*.pdf"))
        doi_map = split_dir / "doi-map.json"
        article_with_dois = 0
        if doi_map.exists():
            try:
                d = json.loads(doi_map.read_text(encoding="utf-8"))
                article_with_dois = sum(1 for v in d.values() if v)
            except Exception:
                pass
        out.append(IssueState(
            issue_pdf=pdf, slug=slug,
            sidecar_path=sidecar_path, sidecar=sidecar,
            split_dir=split_dir, split_count=split_count,
            has_doi_map=doi_map.exists(),
            article_count=len(sidecar.articles) if sidecar else 0,
            article_with_dois=article_with_dois,
        ))
    return out


def find_issue(journal_dir: Path, slug: str) -> IssueState | None:
    for issue in list_issues(journal_dir):
        if issue.slug == slug:
            return issue
    return None


def journal_minting_summary(journal_dir: Path) -> dict:
    """Compute aggregate counts for the dashboard."""
    issues = list_issues(journal_dir)
    return {
        "issue_count": len(issues),
        "split_count": sum(1 for i in issues if i.is_split),
        "total_articles": sum(i.article_count for i in issues),
        "articles_with_dois": sum(i.article_with_dois for i in issues),
    }
