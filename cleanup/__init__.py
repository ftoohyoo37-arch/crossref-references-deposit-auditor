from __future__ import annotations

from .splitter import propose_splits
from .crossref_match import match_citation
from .xml_writer import apply_decisions, count_changes
from .year_fix import fix_duplicate_year

__all__ = [
    "propose_splits", "match_citation", "apply_decisions", "count_changes",
    "fix_duplicate_year",
]
