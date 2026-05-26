"""Server-side PDF thumbnail rendering for the visual issue editor.

Each issue PDF page becomes a PNG thumbnail cached to disk; the issue
editor template embeds them via <img> tags so the user can click pages
to mark article boundaries / ToC pages / skip pages.

Two rendering paths in priority order:
  1. Ghostscript (`gswin64c` on Windows, `gs` elsewhere) — fastest and
     handles every PDF the existing pipeline already processes.
  2. pdftoppm — broadly available poppler tool, used as a fallback.

Cache location: <Auditor>/uploads/_thumbs/<journal-slug>/<issue-slug>/
                page-<NNN>.png

These are stable for a given (journal, issue, page) so the browser
caches them too. They get regenerated only when the source PDF
changes (mtime check) or on explicit cache clear.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


THUMB_DPI = 120   # 8.5x11 → ~1020x1320, ample for thumbnail viewing
PREVIEW_DPI = 220  # used when the user clicks to enlarge


_AUDITOR_DIR = Path(__file__).resolve().parent.parent
THUMB_ROOT = _AUDITOR_DIR / "uploads" / "_thumbs"


class ThumbnailError(Exception):
    pass


def _gs() -> str | None:
    return shutil.which("gswin64c") or shutil.which("gs")


def _pdftoppm() -> str | None:
    return shutil.which("pdftoppm")


def thumb_path(journal_slug: str, issue_slug: str, page: int,
               *, dpi: int = THUMB_DPI) -> Path:
    base = THUMB_ROOT / journal_slug / issue_slug / f"dpi{dpi}"
    return base / f"page-{page:03d}.png"


def _needs_render(target: Path, source_pdf: Path) -> bool:
    if not target.exists():
        return True
    if not source_pdf.exists():
        return False
    return target.stat().st_mtime < source_pdf.stat().st_mtime


def render_thumb(source_pdf: Path, page: int,
                 journal_slug: str, issue_slug: str,
                 *, dpi: int = THUMB_DPI) -> Path:
    """Render one page of source_pdf to PNG at the given DPI. Cached.

    Returns the path to the rendered PNG.
    """
    target = thumb_path(journal_slug, issue_slug, page, dpi=dpi)
    if not _needs_render(target, source_pdf):
        return target
    target.parent.mkdir(parents=True, exist_ok=True)

    gs = _gs()
    if gs:
        cmd = [
            gs, "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE",
            "-sDEVICE=png16m",
            f"-r{dpi}",
            f"-dFirstPage={page}", f"-dLastPage={page}",
            f"-sOutputFile={target}",
            str(source_pdf),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and target.exists() and target.stat().st_size > 0:
            return target
        # Fall through to pdftoppm

    pp = _pdftoppm()
    if pp:
        # pdftoppm writes <prefix>-N.png and we want exactly one file
        prefix = target.with_suffix("")
        cmd = [
            pp, "-r", str(dpi), "-png",
            "-f", str(page), "-l", str(page),
            str(source_pdf), str(prefix),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        # pdftoppm produces <prefix>-<page>.png — rename to our convention
        candidate = prefix.parent / f"{prefix.name}-{page}.png"
        if r.returncode == 0 and candidate.exists():
            candidate.replace(target)
            return target

    raise ThumbnailError(
        "Neither Ghostscript nor pdftoppm could render this page. "
        "Install one to enable the visual issue editor."
    )


def has_rasterizer() -> bool:
    """Quick check used by the UI to decide whether to render the visual editor."""
    return bool(_gs() or _pdftoppm())
