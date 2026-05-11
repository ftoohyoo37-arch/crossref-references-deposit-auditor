"""Resolve duplicate-year citations against Crossref, with positional fallbacks.

GROBID sometimes extracts the publication year twice in adjacent positions:

    Ore, Ersula. 2019. 2015. "They Call Me Dr. Ore." Present Tense 5, no. 2: 1-6.

Three resolution paths, in order:

  1. Same-year duplicates (e.g., "D'Angelo, Frank. 1974. 1974.") are
     dedup'd unconditionally — no risk and no API call needed.
  2. Different-year duplicates are sent to Crossref. If Crossref returns
     a high-confidence match whose canonical year matches one of the two
     candidates, that year wins.
  3. When Crossref disagrees (different year) or returns nothing, fall
     back to a positional heuristic. The configured strategy is one of:
       - 'keep_second' (default): the second year is positionally next
          to the title in Chicago author-date format, so it's the
          canonical publication year in most cases (~7 of 9 verified
          examples on the Reflections backfill).
       - 'keep_first':  the opposite — keep the leading year.
       - 'crossref_only': refuse to auto-fix, leave for manual review.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from auditor.rules.duplicate_year import DUPLICATE_YEAR_RE
from .crossref_match import match_citation
from .openalex_match import match_citation as match_citation_openalex


DEFAULT_MIN_SCORE = 50.0
FallbackStrategy = Literal["keep_second", "keep_first", "crossref_only"]


def _rewrite(text: str, m: re.Match, kept_year: str) -> str:
    """Replace the matched duplicate-year sequence with a single year."""
    corrected = (
        text[: m.start()].rstrip()
        + (" " if m.start() > 0 else "")
        + f"{kept_year}. "
        + text[m.end():].lstrip()
    )
    return re.sub(r"\s+", " ", corrected).strip()


def fix_duplicate_year(
    text: str,
    min_score: float = DEFAULT_MIN_SCORE,
    fallback: FallbackStrategy = "keep_second",
) -> dict[str, Any] | None:
    """Return a corrected citation, or None if no duplicate-year pattern
    is present (or if `fallback='crossref_only'` and Crossref can't help).

    Output: {'fixed': '<corrected text>', 'match': <crossref result | None>,
             'kept_year': '<year>', 'dropped_year': '<year>',
             'method': 'dedup_same_year' | 'crossref_verified' |
                       'fallback_keep_second' | 'fallback_keep_first'}.
    """
    text = text.strip()
    m = DUPLICATE_YEAR_RE.search(text)
    if m is None:
        return None

    first = m.group("first")
    second = m.group("second")

    # Path 1: same year repeated — unambiguous dedup, no Crossref call.
    if first == second:
        return {
            "fixed": _rewrite(text, m, first),
            "match": None,
            "kept_year": first,
            "dropped_year": first,
            "method": "dedup_same_year",
        }

    # Path 2: different years — query Crossref first, OpenAlex as fallback.
    cleaned_query = (text[: m.start()] + " " + text[m.end():]).strip()
    cleaned_query = re.sub(r"\s+", " ", cleaned_query)

    for backend, label in (
        (match_citation, "crossref_verified"),
        (match_citation_openalex, "openalex_verified"),
    ):
        match = backend(cleaned_query)
        if not match or match.get("error"):
            continue
        score = match.get("score") or 0
        canonical = match.get("year")
        if score < min_score or canonical is None:
            continue
        canonical_str = str(canonical)
        if canonical_str not in (first, second):
            continue
        dropped = first if canonical_str == second else second
        return {
            "fixed": _rewrite(text, m, canonical_str),
            "match": match,
            "kept_year": canonical_str,
            "dropped_year": dropped,
            "method": label,
        }

    # Path 3: Crossref couldn't disambiguate — apply positional fallback.
    if fallback == "crossref_only":
        return None
    if fallback == "keep_first":
        kept, dropped = first, second
    else:  # 'keep_second' (default)
        kept, dropped = second, first

    return {
        "fixed": _rewrite(text, m, kept),
        "match": match,
        "kept_year": kept,
        "dropped_year": dropped,
        "method": f"fallback_{fallback}",
    }
