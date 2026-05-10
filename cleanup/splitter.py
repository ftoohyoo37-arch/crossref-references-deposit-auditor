"""Propose where to split a glued unstructured citation.

Heuristic: real publication years almost always sit in `(YYYY)` form. So we
find each `(YYYY)` after the first one and walk backward to the nearest
sentence boundary (period followed by whitespace + capital letter, or the
end of a publisher block) to find where the next reference's author block
begins. That boundary is the split point.

Returns a list of cleaned chunks. If we can't find good split points, the
input is returned as a single-element list.
"""
from __future__ import annotations

import re

from auditor.journal_footer import strip_footer
from auditor.notes_section import strip_notes_section


YEAR_PARENS_RE = re.compile(r"\((1[5-9]\d{2}|20\d{2}|2100)[a-z]?\)")
# Sentence-end candidates: period followed by space then capital letter,
# OR a closing-paren-period sequence.
SENTENCE_BOUNDARY_RE = re.compile(r"\.\s+(?=[A-Z])")

# Repeat-author marker: 3+ underscores, 3+ hyphens, or 2+ em/en-dashes,
# standing alone as a token (whitespace before, whitespace or punctuation
# after). Doesn't require a year to follow — Chicago notes-and-bibliography
# style puts the year at the end of the entry.
MARKER_RE = re.compile(
    r"(?:(?<=\s)|(?<=^))"
    r"(_{3,}|-{3,}|—{2,}|–{2,})"
    r"(?=[\s.,])"
)

# Author block at the start of a citation: from the first character up to
# (but not including) the year marker `(YYYY)` or the first standalone year.
# Conservative — backs off to "first sentence" if the year regex doesn't match.
AUTHOR_BLOCK_HEAD_RE = re.compile(
    r"^(.*?)(?=\s*\(?(?:1[5-9]\d{2}|20\d{2}|2100)[a-z]?\)?\.?\s)"
)


def _find_split_point_before(text: str, year_pos: int) -> int | None:
    """Walk backward from year_pos to find the start of this reference.

    The heuristic: between the previous reference's end and this year's
    parenthesis is the new author block. We anchor on the most recent
    sentence boundary before year_pos.
    """
    # Look at text up to year position
    head = text[:year_pos]
    # Find the rightmost sentence boundary
    matches = list(SENTENCE_BOUNDARY_RE.finditer(head))
    if not matches:
        return None
    # The split point is just AFTER the boundary's whitespace
    last = matches[-1]
    return last.end()


_INITIAL_RE = re.compile(r"\b[A-Z]\.\s*$")

# Detect whether a chunk already starts with its own author block —
# e.g. "Lu, M in-Zhan and Bruce Horner." or "Hizer, Millie, …". If so,
# the marker between this chunk and the prior one is acting as a
# bibliography-entry separator between different authors, not as a
# "same author" placeholder, and we should NOT substitute.
HAS_AUTHOR_START_RE = re.compile(r"^[A-Z][\w'\-]+,\s+[A-Z]")


def _author_block(chunk: str) -> str:
    """Extract just the author-block prefix of a citation chunk.

    Strategy: the author block ends at the FIRST of these:
      - opening quote (Chicago N&B: `Smith, John. "Title."`)
      - opening parenthesis-year (APA: `Smith, J. (2020).`)
      - any 4-digit year (Chicago author-date: `Smith, John. 2020.`)
    Falls back to the first sentence boundary, taking care not to break on
    period-space sequences that follow an initial like `M.` or `H.`.
    """
    candidates: list[int] = []

    q = chunk.find('"')
    if q > 0:
        candidates.append(q)

    p = chunk.find("(")
    if p > 0 and re.match(r"\d{4}", chunk[p + 1:p + 5] or ""):
        candidates.append(p)

    ym = re.search(r"\b(1[5-9]\d{2}|20\d{2}|2100)\b", chunk)
    if ym:
        candidates.append(ym.start())

    if candidates:
        end = min(candidates)
        head = chunk[:end].rstrip(" .,;:\"'(")
        if head:
            return head

    # Fallback: first period-space NOT immediately following an initial.
    # Walk through every ". " position and pick the first valid one.
    for i in range(len(chunk) - 1):
        if chunk[i] == "." and chunk[i + 1] == " ":
            preceding = chunk[max(0, i - 2):i + 1]  # e.g., "H." or "th."
            if _INITIAL_RE.search(preceding):
                continue
            return chunk[:i].rstrip()
    return chunk[:80].strip()


def _split_at_markers(text: str) -> list[str]:
    """If text contains repeat-author markers, split at each and substitute
    each marker with the FIRST chunk's author block.

    "Same author" markers in a glued citation always refer back to the
    citation's leading author, not to the preceding split-chunk (which is
    itself usually a 'same author' entry). So we lock in `first_author`
    from the first chunk and reuse it for every subsequent substitution.
    """
    matches = list(MARKER_RE.finditer(text))
    if not matches:
        return []

    chunks: list[str] = []
    cursor = 0
    first_author: str | None = None
    for m in matches:
        before = text[cursor:m.start()].strip()
        if before:
            chunks.append(before)
            if first_author is None:
                first_author = _author_block(before)
        cursor = m.end()
    tail = text[cursor:].strip()
    if tail:
        chunks.append(tail)

    if first_author is None or len(chunks) < 2:
        return chunks

    rewritten: list[str] = [chunks[0]]
    for c in chunks[1:]:
        body = c.lstrip(" .,;-—–")
        if HAS_AUTHOR_START_RE.match(body):
            # This chunk has its own author block — the marker was acting
            # as an entry separator, not as a "same author" placeholder.
            # Split only, don't substitute.
            rewritten.append(body)
        else:
            rewritten.append(f"{first_author}. {body}")
    return rewritten


def propose_splits(text: str, max_splits: int = 5) -> list[str]:
    """Return the citation split into chunks at proposed boundaries.

    Three passes: first strip any trailing journal-page footer (e.g.,
    "Reflections | Volume 24, Issue 2, Spring 2025"), since these are
    typesetting artifacts pulled in by GROBID rather than citation text.
    Then attempt to split on repeat-author markers (___, ---, ——),
    substituting the marker with the previous chunk's author block. If
    that yields a multi-chunk result, return it. Otherwise fall back to
    the year-anchored sentence-boundary heuristic.

    Returns [cleaned_text] if a footer was stripped but no further splits
    apply (single chunk that differs from the original). Returns [text]
    unchanged when no footer and no split points exist.
    """
    text = text.strip()

    # Pass 0a: strip an appended Notes/Footnotes section if present
    text, _notes = strip_notes_section(text)

    # Pass 0b: strip journal-page footer suffix if present
    text, _footer = strip_footer(text)

    # Pass 1: repeat-author markers
    marker_chunks = _split_at_markers(text)
    if len(marker_chunks) >= 2:
        return marker_chunks

    # Pass 2: year-anchored boundaries
    year_matches = list(YEAR_PARENS_RE.finditer(text))
    if len(year_matches) < 2:
        return [text]

    split_points: list[int] = []
    for ym in year_matches[1:]:  # skip the first year (belongs to first ref)
        sp = _find_split_point_before(text, ym.start())
        if sp is None:
            continue
        # Avoid trivial / duplicate split points
        if split_points and sp - split_points[-1] < 20:
            continue
        if sp < 20:
            continue
        split_points.append(sp)
        if len(split_points) >= max_splits:
            break

    if not split_points:
        return [text]

    chunks: list[str] = []
    prev = 0
    for sp in split_points:
        chunk = text[prev:sp].strip()
        if chunk:
            chunks.append(chunk)
        prev = sp
    tail = text[prev:].strip()
    if tail:
        chunks.append(tail)
    return chunks if len(chunks) >= 2 else [text]
