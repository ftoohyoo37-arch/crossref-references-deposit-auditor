"""Detect and strip a Notes/Footnotes section appended to the last citation.

When the Works Cited section is immediately followed by a Notes (or
Endnotes / Footnotes) block in the source PDF, GROBID often glues the
section header and one or more footnotes onto the very last citation:

    White, Melissa Autumn. 2012. "Viral/Species/Crossing: Border Panics
    and Zoonotic Vulnerabilities." Women's Studies Quarterly 40, no. 1
    & 2: 117-137. Notes ↑1 We include "women" in parentheses because…
    ↑2 Popular culture in the mid-19th century…

The signature is the literal section header ("Notes", "Footnotes",
"Endnotes", optionally prefixed with "End ") immediately followed by a
footnote back-reference glyph and a digit. That combination is unique
to the page-chrome bleed; real citations don't end with that pattern.

The detector returns the position where the trailing artifact begins
so callers can either flag the citation (audit) or strip the artifact
(cleanup splitter).
"""
from __future__ import annotations

import re


# "Notes" / "Footnotes" / "Endnotes" / "End Notes" / "End-notes",
# whitespace, then a footnote glyph (↑ ↩ ⁋) immediately followed by
# digits. The footnote-glyph + digit lookahead is what makes this a
# strong, low-false-positive signal.
NOTES_SECTION_RE = re.compile(
    r"\s*\b"
    r"(?:End[\s\-]?)?"
    r"(?:Notes|Footnotes|Endnotes)"
    r"\s+"
    r"[↑↩⁋]\s*\d+",
    re.IGNORECASE,
)


def detect_notes_section(text: str) -> re.Match | None:
    """Return the regex match marking the start of a trailing Notes
    section, or None if no such pattern is present."""
    if not text:
        return None
    return NOTES_SECTION_RE.search(text)


def strip_notes_section(text: str) -> tuple[str, str | None]:
    """Return (cleaned_text, stripped_block_or_None).

    The cleaned text has the Notes section and everything after it
    removed; trailing whitespace and dangling punctuation are trimmed.
    If no Notes section is present, returns the input unchanged with
    None as the second element.
    """
    m = detect_notes_section(text)
    if m is None:
        return text, None
    cleaned = text[: m.start()].rstrip(" .,;")
    return cleaned, text[m.start():].strip()
