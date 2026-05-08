from __future__ import annotations

import re

from ..models import Finding, ParamMeta, RuleMeta, Severity
from . import register_citation_rule
from ._util import citation_key, find_child, short_snippet, text_of


META = RuleMeta(
    id="paragraph_shaped",
    name="Looks like a paragraph (not a citation)",
    description=(
        "Flags citations whose <unstructured_citation> reads like body text "
        "or a paragraph captured by the scraper rather than a bibliographic "
        "entry. Triggered by multiple long, flowing sentences without the "
        "typical author-block opening or (YEAR) marker."
    ),
    scope="citation",
    default_severity=Severity.WARNING,
    default_enabled=True,
    params=[
        ParamMeta("min_long_sentences", "int", 3,
                  "Minimum 8+-word sentences before considering paragraph-shape."),
        ParamMeta("min_chars", "int", 50,
                  "Skip citations shorter than this (always-OK)."),
    ],
)

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'])")
# Liberal year detection: (YYYY anywhere — handles (2016), (2016a), (2016, April), (2016/2017)
PAREN_YEAR_RE = re.compile(r"\((1[5-9]\d{2}|20\d{2}|2100)\b")
# Author-block opening — accept hyphens, apostrophes, internal capitals (MacDonald, O'Brien),
# institutional authors (American Psychological Association.), and Vancouver style (Smith J,).
AUTHOR_START_RE = re.compile(
    r"^[\"\(\[]?(?:"
    r"[A-Z][\w'\-]+"                         # surname (allow hyphens, apostrophes, internal caps)
    r"(?:\s+(?:[A-Z][\w'\-]+|de|van|der|von|la|le|du|el))*"  # multi-word names
    r")(?:,\s*[A-Z]|,\s+[A-Z][\w']+|\.|\s+[A-Z]\.)"
)


@register_citation_rule(META)
def paragraph_shaped(elem, ctx) -> list[Finding]:
    sev = ctx.config.severity(META.id, META.default_severity.value)
    min_long = int(ctx.config.param(META.id, "min_long_sentences", 3))
    min_chars = int(ctx.config.param(META.id, "min_chars", 50))

    uc = find_child(elem, "unstructured_citation")
    if uc is None:
        return []
    text = text_of(uc).strip()
    if len(text) < min_chars:
        return []

    sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]
    long_sents = [s for s in sentences if len(s.split()) >= 8]
    if len(long_sents) < min_long:
        return []

    starts_with_author = bool(AUTHOR_START_RE.match(text))
    has_paren_year = bool(PAREN_YEAR_RE.search(text))

    # Flag only if BOTH citation hallmarks are missing. A single hallmark
    # (institutional author OR an in-text year) is enough to give it the
    # benefit of the doubt and let the user manually delete if it's garbage.
    if starts_with_author or has_paren_year:
        return []

    reasons: list[str] = [
        f"{len(long_sents)} long sentences (8+ words each)",
        "no author block",
        "no (YEAR) marker",
    ]

    return [Finding(
        rule_id=META.id,
        severity=sev,
        message="Looks like body text or a paragraph: " + "; ".join(reasons) + ".",
        line=elem.sourceline,
        citation_key=citation_key(elem),
        snippet=short_snippet(text),
    )]
