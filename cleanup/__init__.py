from __future__ import annotations

from .splitter import propose_splits
from .crossref_match import match_citation
from .openalex_match import match_citation as match_citation_openalex
from .xml_writer import apply_decisions, count_changes
from .year_fix import fix_duplicate_year

__all__ = [
    "propose_splits", "match_citation", "match_citation_openalex",
    "apply_decisions", "count_changes", "fix_duplicate_year",
]


def match_citation_with_fallback(text: str, min_score: float = 50.0) -> dict | None:
    """Query Crossref first; if it returns nothing or low confidence,
    fall back to OpenAlex. Returns the higher-confidence result, with a
    `source` key indicating which backend produced the match.
    """
    cr = match_citation(text)
    cr_score = (cr or {}).get("score") or 0
    if cr and not cr.get("error") and cr_score >= min_score:
        if "source" not in cr:
            cr["source"] = "crossref"
        return cr
    # Crossref came back empty or weak — try OpenAlex.
    oa = match_citation_openalex(text)
    if oa and not oa.get("error"):
        return oa
    # Neither backend helped — return whichever one we got (might be None).
    return cr or oa

