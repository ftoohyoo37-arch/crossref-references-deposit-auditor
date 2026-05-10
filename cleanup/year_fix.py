"""Resolve duplicate-year citations against Crossref.

GROBID sometimes extracts the publication year twice in adjacent positions:

    Ore, Ersula. 2019. 2015. "They Call Me Dr. Ore." Present Tense 5, no. 2: 1-6.

Without external information we can't tell which of the two years is the
real publication year (here it's 2015 — the 2019 is a scrape artifact).
This module strips the duplicate-year sequence from the text, queries
Crossref for a canonical match, and — only when the canonical year matches
one of the two candidates with high confidence — returns a corrected
citation string with the duplicate removed.

Conservative by design: if Crossref returns a third year (matching neither
candidate), or if the match score is below the configured threshold, the
function returns None so the cleanup tool falls back to manual review.
"""
from __future__ import annotations

import re
from typing import Any

from auditor.rules.duplicate_year import DUPLICATE_YEAR_RE
from .crossref_match import match_citation


DEFAULT_MIN_SCORE = 50.0


def fix_duplicate_year(text: str, min_score: float = DEFAULT_MIN_SCORE) -> dict[str, Any] | None:
    """Return a corrected citation if Crossref confirms the canonical year.

    Output: {'fixed': '<corrected text>', 'match': <crossref result>,
             'kept_year': '<year>', 'dropped_year': '<year>'}.
    Returns None when no duplicate-year pattern, no Crossref match,
    low confidence, or Crossref's year matches neither candidate.
    """
    text = text.strip()
    m = DUPLICATE_YEAR_RE.search(text)
    if m is None:
        return None

    first = m.group("first")
    second = m.group("second")

    # Build a clean query by stripping just the duplicate-year sequence.
    cleaned_query = (text[: m.start()] + " " + text[m.end():]).strip()
    cleaned_query = re.sub(r"\s+", " ", cleaned_query)

    match = match_citation(cleaned_query)
    if match is None:
        return None
    if match.get("error"):
        return None
    score = match.get("score") or 0
    if score < min_score:
        return None

    canonical = match.get("year")
    if canonical is None:
        return None
    canonical_str = str(canonical)

    if canonical_str not in (first, second):
        # Crossref disagrees with both candidates — too risky to silently
        # rewrite. Let the user decide.
        return None

    dropped = first if canonical_str == second else second

    # Replace the entire "YYYY. YYYY." (or comma-variant) sequence with
    # just the canonical year + a period and a space, preserving whatever
    # follows in the original text.
    corrected = (
        text[: m.start()].rstrip()
        + (" " if m.start() > 0 else "")
        + f"{canonical_str}. "
        + text[m.end():].lstrip()
    )
    corrected = re.sub(r"\s+", " ", corrected).strip()

    return {
        "fixed": corrected,
        "match": match,
        "kept_year": canonical_str,
        "dropped_year": dropped,
    }
