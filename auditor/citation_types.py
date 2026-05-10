"""Detect citation types that Crossref doesn't reliably index.

Conference presentations, news/website articles, and software/code
repositories are all legitimate citations that won't match against the
Crossref REST API (Crossref is built around DOI-bearing scholarly works).
Without this detector, these sources trip the multi-year and long-text
heuristics in `unstructured_length` and end up in the manual review pile
of the cleanup workflow.

The detector returns a single tag string when it's confident the citation
is one of these types, or None. Callers use the tag to:

  - suppress audit warnings that don't apply to non-Crossref-indexed work
    (multi-year is normal here: publication year + access date), and
  - auto-keep these citations during bulk cleanup without paying the
    Crossref REST round-trip.

Conservative by design — we'd rather miss a few legit cases than
auto-suppress warnings that turn out to matter.
"""
from __future__ import annotations

import re

# Software / code repository signals
_REPO_URL_RE = re.compile(
    r"https?://(?:www\.)?"
    r"(?:github|gitlab|bitbucket|codeberg|sourceforge|pypi|npmjs|cran\.r-project|crates|rubygems|hex\.pm)"
    r"\.(?:com|org|io|net|pm|dev)/",
    re.IGNORECASE,
)
_LANG_TAG_RE = re.compile(
    r"\[(?:"
    r"Python|R|JavaScript|TypeScript|Java|Go|Rust|Ruby|PHP|Perl|C|C\+\+|C#|Swift|Kotlin|"
    r"Computer\s+software|Software|Source\s+code|Code|Dataset|Data\s+set|Data|"
    r"Programming\s+language"
    r")\]",
    re.IGNORECASE,
)
_ORIG_PUB_RE = re.compile(r"Original\s+work\s+published\b", re.IGNORECASE)

# Conference / presentation signals — must follow a quote-period or sentence
# boundary so we don't false-positive on titles that happen to contain
# words like "Conference" or "Workshop".
_CONF_MARKER_RE = re.compile(
    r"(?:^|[.\"”]\s+)"
    r"(?:"
    r"Presentation|Paper\s+presented|Proceedings\s+of(?:\s+the)?|"
    r"Symposium\s+on|Workshop\s+on|Annual\s+Meeting|"
    r"Annual\s+Conference|Annual\s+Convention|Conference\s+on|"
    r"Talk\s+presented|Poster\s+presented|Keynote\s+address"
    r")\b"
)

# Website / news signals
# URL: either a fully-qualified http(s) URL OR a bare www. domain. The
# bare-domain form is common in Chicago notes-and-bibliography citations
# that quote the display URL without protocol.
_URL_RE = re.compile(
    r"(?:https?://|\bwww\.[a-z0-9\-]+\.[a-z]{2,})",
    re.IGNORECASE,
)
_MONTH_DAY_YEAR_RE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)\.?"
    r"\s+\d{1,2},?\s+\d{4}\b"
)
_RETRIEVED_RE = re.compile(r"\b(?:Retrieved\s+from|Retrieved\s+on|Accessed)\b", re.IGNORECASE)
# Patterns that signal a JOURNAL article (suppress 'website' classification)
_VOL_ISSUE_RE = re.compile(r"\d+\s*\(\s*\d+\s*\)")        # 5(2)
_PAGE_RANGE_TAIL_RE = re.compile(r",\s*\d+\s*[-–]\s*\d+\.?\s*$")
_VOL_LITERAL_RE = re.compile(r"\bvol\.?\s*\d+", re.IGNORECASE)


def detect_type(text: str) -> str | None:
    """Classify a citation as 'conference', 'website', 'software', or None.

    Conservative classifier: returns a tag only when strong signals are
    present. Intended to identify citations that legitimately won't match
    Crossref so the auditor and cleanup tool can stop flagging them.
    """
    if not text:
        return None

    # Software is the most specific — check first.
    if _REPO_URL_RE.search(text) or _LANG_TAG_RE.search(text) or _ORIG_PUB_RE.search(text):
        return "software"

    # Conference / presentation — anchored marker after sentence boundary.
    if _CONF_MARKER_RE.search(text):
        return "conference"

    # Website / news article — URL plus an access-style signal, but not
    # a journal article.
    has_url = bool(_URL_RE.search(text))
    if has_url:
        looks_like_journal = (
            _VOL_ISSUE_RE.search(text)
            or _VOL_LITERAL_RE.search(text)
            or _PAGE_RANGE_TAIL_RE.search(text.strip())
        )
        has_access_signal = bool(_MONTH_DAY_YEAR_RE.search(text) or _RETRIEVED_RE.search(text))
        if has_access_signal and not looks_like_journal:
            return "website"

    return None
