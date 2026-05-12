from __future__ import annotations

import re

from ..models import Finding, RuleMeta, Severity
from . import register_citation_rule
from ._util import citation_key, find_child, short_snippet, text_of


META = RuleMeta(
    id="stuck_whitespace",
    name="Mid-word whitespace from PDF extraction",
    description=(
        "Informational notice (not a deposit-blocking problem). Flags "
        "<unstructured_citation> values with extra spaces inserted "
        "mid-word, a common GROBID/PDF text-extraction artifact (e.g., "
        "'Hida lgo, Alexa ndra' or 'Riley-M u kavetz'). The citation "
        "deposits successfully as-is — Crossref doesn't validate word "
        "spacing — so these are flagged for awareness rather than "
        "action. Mechanical merging is unsafe (would damage legitimate "
        "hyphenated names or accented words), so no auto-fix is "
        "provided. These cards are deliberately excluded from the "
        "cleanup queue."
    ),
    scope="citation",
    default_severity=Severity.INFO,
    default_enabled=True,
    params=[],
)

# Pattern A: a single uppercase letter followed by a space and a 1-2 letter
# lowercase fragment starting another short word. Matches "Hida lgo" or
# "Alexa ndra". Anchored on word boundaries to avoid false-positives in
# genuine multi-word phrases.
SINGLE_CHUNK_RE = re.compile(
    r"\b[A-Z][a-z]+\s+[a-z]{1,3}(?=\b)"
)
# Pattern B: a single letter "word" embedded inside what should be a
# longer word, e.g. "M u kavetz" or "M atter". A single lowercase letter
# bounded by spaces is rarely a real word in citation text.
SINGLE_LETTER_RE = re.compile(r"\b[a-z]\s+(?=[a-z]{2,})")
# Common false-positive guards (do not flag these tokens as stuck whitespace):
SAFE_TOKENS = {
    "a", "i",  # English articles/pronouns
    "y", "e",  # Spanish "y" and "e"
    "o",       # Spanish "or"
    "à", "á", "è", "é", "ó", "ú",  # accented one-letter words across romance languages
}


@register_citation_rule(META)
def stuck_whitespace(elem, ctx) -> list[Finding]:
    sev = ctx.config.severity(META.id, META.default_severity.value)
    uc = find_child(elem, "unstructured_citation")
    if uc is None:
        return []
    text = text_of(uc)
    if not text:
        return []

    hits: list[str] = []

    # Strip URLs first — they legitimately contain `/` and other delimiters.
    text_for_scan = re.sub(r"https?://\S+", " ", text)

    for m in SINGLE_LETTER_RE.finditer(text_for_scan):
        # The single letter is at position m.start()
        letter = text_for_scan[m.start()]
        if letter in SAFE_TOKENS:
            continue
        # Get a small context window for the message
        ctx_start = max(0, m.start() - 6)
        ctx_end = min(len(text_for_scan), m.end() + 8)
        snippet = text_for_scan[ctx_start:ctx_end].replace("\n", " ").strip()
        hits.append(snippet)
        if len(hits) >= 3:
            break

    if not hits:
        return []

    return [Finding(
        rule_id=META.id,
        severity=sev,
        message=(
            f"Possible PDF-extraction whitespace artifacts (single "
            f"letters embedded mid-word): {', '.join(repr(h) for h in hits[:3])}. "
            "Manual review recommended; not auto-fixed because mechanical "
            "merging could damage legitimate hyphenated or accented names."
        ),
        line=elem.sourceline,
        citation_key=citation_key(elem),
        snippet=short_snippet(text),
    )]
