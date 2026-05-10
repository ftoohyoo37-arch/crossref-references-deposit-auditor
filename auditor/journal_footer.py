"""Detect and strip journal-page footer text glued onto the last citation.

GROBID extracts a real bibliographic entry, then runs straight into the
running header or footer of the next page. The single most diagnostic
pattern is the journal's volume/issue stamp:

    Reflections | Volume 24, Issue 2, Spring 2025

Pipe character, literal "Volume" + digit, literal "Issue" + digit,
optional season + four-digit year. No real bibliographic entry uses this
phrasing — published references use "5(2)" or "vol. 5, no. 2", not
spelled-out "Volume 24, Issue 2".

The detector returns the position where the footer suffix begins, so
callers can either flag the citation (audit) or strip the footer
(cleanup splitter).
"""
from __future__ import annotations

import re

# The signature pattern: a proper-noun journal name, pipe separator,
# Volume/Issue with digits, optional season+year, anchored to the end
# of the string (after optional trailing period and whitespace).
JOURNAL_FOOTER_RE = re.compile(
    r"(?P<journal>[A-Z][A-Za-z&\-\s]{2,40}?)"
    r"\s*\|\s*"
    r"Volume\s+\d+"
    r",\s*Issue\s+\d+"
    r"(?:,\s*"
    r"(?:Spring|Summer|Fall|Winter|Autumn|"
    r"January|February|March|April|May|June|"
    r"July|August|September|October|November|December)"
    r"\s+\d{4})?"
    r"\.?\s*$"
)


def detect_footer(text: str) -> re.Match | None:
    """Return the regex match for the trailing footer, or None.

    The match's `.start()` gives the index where the footer begins in the
    original text (suitable for slicing).
    """
    if not text:
        return None
    return JOURNAL_FOOTER_RE.search(text)


def strip_footer(text: str) -> tuple[str, str | None]:
    """Return (cleaned_text, footer_text_or_None).

    The cleaned text has any detected footer suffix removed and trailing
    whitespace/period trimmed. If no footer is present, returns the
    original text unchanged with None as the second element.
    """
    m = detect_footer(text)
    if m is None:
        return text, None
    cleaned = text[: m.start()].rstrip(" .,")
    return cleaned, text[m.start():].strip()
