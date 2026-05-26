"""Journal discovery + filesystem-state inspection.

The pipeline UI is read-mostly: it walks the project root, finds every
directory that contains a `journal.py`, and asks the filesystem what
stage(s) of the pipeline have been completed for each.

No state is duplicated in the DB. The filesystem IS the state.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path


# Project root is the parent of the Crossref Auditor directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Hand-maintained map from JOURNAL_NAME (the human title) to the
# project-root `<slug>-final.xml` filename. Mirrors the mapping in
# `_shared/_audit_to_final.py::OUT_NAMES` (kept in sync manually).
FINAL_XML_NAMES = {
    "Across the Disciplines": "atd-final.xml",
    "Double Helix": "dbh-final.xml",
    "Prompt": "prompt-final.xml",
    "The WAC Journal": "wacj-final.xml",
    "The Journal of Basic Writing": "jbw-final.xml",
}


# Optional human-friendly stable slug used in URLs. Falls back to a
# slugified journal name when missing.
URL_SLUGS = {
    "Across the Disciplines": "atd",
    "Double Helix": "dbh",
    "Prompt": "prompt",
    "The WAC Journal": "wacj",
    "The Journal of Basic Writing": "jbw",
    "The Journal of Writing Analytics": "jwa",
    "Reflections": "reflections",
}


@dataclass
class JournalState:
    """Per-journal pipeline state derived from the filesystem."""
    name: str
    slug: str            # URL slug for routing
    dir: Path
    batch_prefix: str    # e.g. "atd-volume" or "jbw"
    pdf_volume_count: int = 0
    pdf_file_count: int = 0
    extracted_count: int = 0
    enriched_count: int = 0
    final_xml: Path | None = None
    final_xml_size: int = 0
    final_xml_articles: int = 0
    final_xml_citations: int = 0
    final_xml_dois: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def is_extracted(self) -> bool:
        return self.extracted_count > 0

    @property
    def is_enriched(self) -> bool:
        return self.enriched_count > 0

    @property
    def is_finalized(self) -> bool:
        return self.final_xml is not None and self.final_xml.exists()

    @property
    def doi_pct(self) -> float:
        if not self.final_xml_citations:
            return 0.0
        return 100.0 * self.final_xml_dois / self.final_xml_citations


def _load_journal_module(journal_dir: Path):
    """Import the journal.py file from a journal directory.

    Returns None if import fails (treated as 'not a valid journal dir').
    """
    journal_py = journal_dir / "journal.py"
    if not journal_py.is_file():
        return None
    # Use a unique module name to avoid clobbering between journals
    mod_name = f"_pipeline_journal_{journal_dir.name.replace(' ', '_')}"
    spec = importlib.util.spec_from_file_location(mod_name, journal_py)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    # Many journal.py files do `import journal` themselves — make their
    # own dir importable before exec.
    sys.path.insert(0, str(journal_dir))
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return None
    finally:
        # Don't permanently pollute sys.path
        try:
            sys.path.remove(str(journal_dir))
        except ValueError:
            pass
    return mod


def _count_pdfs(journal_dir: Path) -> tuple[int, int]:
    """Return (volume_count, total_pdf_count) under journal_dir/pdfs/."""
    pdfs_root = journal_dir / "pdfs"
    if not pdfs_root.is_dir():
        return (0, 0)
    vol_count = 0
    pdf_count = 0
    for sub in pdfs_root.iterdir():
        if not sub.is_dir():
            continue
        vol_count += 1
        pdf_count += sum(1 for _ in sub.glob("*.pdf"))
    return (vol_count, pdf_count)


def _count_batch_xmls(directory: Path, prefix: str) -> int:
    """Count <prefix>-*.xml files in `directory`."""
    if not directory.is_dir():
        return 0
    return sum(1 for _ in directory.glob(f"{prefix}-*.xml"))


def _final_xml_stats(final_path: Path) -> tuple[int, int, int, int]:
    """Read the final XML and return (size_bytes, articles, citations, dois).

    Cheap-and-correct via xml.etree; this only runs when serving the
    dashboard, not in any hot loop.
    """
    if not final_path.exists():
        return (0, 0, 0, 0)
    size = final_path.stat().st_size
    try:
        import xml.etree.ElementTree as ET
        tree = ET.parse(str(final_path))
        root = tree.getroot()
        # Namespace is fixed in CrossRef deposits 4.3.6
        NS = "{http://www.crossref.org/doi_resources_schema/4.3.6}"
        arts = root.findall(f".//{NS}doi_citations")
        cits = root.findall(f".//{NS}citation")
        dois = sum(1 for c in cits if c.find(f"{NS}doi") is not None)
        return (size, len(arts), len(cits), dois)
    except Exception:
        return (size, 0, 0, 0)


def discover_journals() -> list[JournalState]:
    """Scan PROJECT_ROOT for journal directories and return their states.

    A journal directory is any top-level dir that contains a parseable
    journal.py defining JOURNAL_NAME + BATCH_ID_PREFIX. Anything else
    (utility dirs like `_shared`, `Crossref Auditor`, etc.) is skipped.
    """
    out: list[JournalState] = []
    for d in sorted(PROJECT_ROOT.iterdir()):
        if not d.is_dir() or d.name.startswith((".", "_")):
            continue
        if d.name == "Crossref Auditor":
            continue
        mod = _load_journal_module(d)
        if mod is None:
            continue
        name = getattr(mod, "JOURNAL_NAME", None)
        prefix = getattr(mod, "BATCH_ID_PREFIX", None)
        if not name or not prefix:
            continue

        slug = URL_SLUGS.get(name, d.name.lower().replace(" ", "-"))
        vol_count, pdf_count = _count_pdfs(d)
        out_dir = d / "output"
        enriched_dir = d / "Structured Scraper" / "enriched"
        extracted_n = _count_batch_xmls(out_dir, prefix)
        enriched_n = _count_batch_xmls(enriched_dir, prefix)

        final_name = FINAL_XML_NAMES.get(name)
        final_path = PROJECT_ROOT / final_name if final_name else None
        final_size = final_arts = final_cits = final_dois = 0
        if final_path and final_path.exists():
            final_size, final_arts, final_cits, final_dois = _final_xml_stats(final_path)

        state = JournalState(
            name=name,
            slug=slug,
            dir=d,
            batch_prefix=prefix,
            pdf_volume_count=vol_count,
            pdf_file_count=pdf_count,
            extracted_count=extracted_n,
            enriched_count=enriched_n,
            final_xml=final_path if (final_path and final_path.exists()) else None,
            final_xml_size=final_size,
            final_xml_articles=final_arts,
            final_xml_citations=final_cits,
            final_xml_dois=final_dois,
        )
        out.append(state)
    return out


def find_journal(slug: str) -> JournalState | None:
    """Find the journal with the given URL slug."""
    for j in discover_journals():
        if j.slug == slug:
            return j
    return None
