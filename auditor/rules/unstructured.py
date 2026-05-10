from __future__ import annotations

import re

from ..citation_types import detect_type
from ..models import Finding, ParamMeta, RuleMeta, Severity
from . import register_citation_rule
from ._util import citation_key, find_child, short_snippet, text_of

META = RuleMeta(
    id="unstructured_length",
    name="Unstructured citation length & glued-refs",
    description=(
        "Flags <unstructured_citation> values that are suspiciously short "
        "(likely a fragment) or suspiciously long (likely two or more "
        "references concatenated by a scraper)."
    ),
    scope="citation",
    default_severity=Severity.WARNING,
    default_enabled=True,
    params=[
        ParamMeta("min_words", "int", 5, "Below this word count, flag as fragment."),
        ParamMeta("max_words", "int", 60, "Above this word count, flag as likely glued references."),
        ParamMeta("max_year_count", "int", 1, "Number of 4-digit years that triggers a 'likely two refs glued' finding."),
        ParamMeta("max_semicolons", "int", 2, "Semicolon count that triggers a 'likely two refs glued' finding."),
    ],
)

YEAR_RE = re.compile(r"(?<!\d)(1[5-9]\d{2}|20\d{2}|2100)(?!\d)")
# Quoted-region detector. Handles straight quotes and Unicode smart quotes.
# Used to exclude year-like numbers that appear inside an article/chapter
# title (e.g. "The 1984 election" or "Year 2000 in retrospect"); those
# aren't second publication years, just numbers in titles.
QUOTED_REGION_RE = re.compile(r"[\"“][^\"“”]*[\"”]")


def _real_year_tokens(text: str) -> list[str]:
    """Year-looking tokens minus the obvious false positives.

    Excludes:
    - Years inside quoted titles (e.g. "The 1984 election" — title number,
      not a second publication year).
    - Volume markers like `1991(2)` (year followed by `(digit`).
    - URL/handle fragments like `/2027/...` or `2027.42` (preceded by `/`,
      `.`, or `=`, or followed by `.` then a digit).
    - Page ranges like `pp. 1991-1995` (year followed by `-` then a digit
      that's part of an obvious range with the preceding number close in
      magnitude — a 4-digit "year" inside `\\d{4}-\\d{4}` is much more often
      a page range than two distinct publication years).
    """
    quoted_spans = [(m.start(), m.end()) for m in QUOTED_REGION_RE.finditer(text)]

    out: list[str] = []
    for m in YEAR_RE.finditer(text):
        start, end = m.span()
        # Skip year-like numbers that fall inside a quoted title.
        if any(qs <= start < qe for qs, qe in quoted_spans):
            continue

        before_char = text[start - 1] if start > 0 else ""
        after = text[end:end + 5]

        # Volume marker: 1991(2)
        if after.startswith("(") and len(after) > 1 and after[1].isdigit():
            continue
        # URL / handle fragment: /2027/, =2027, .2027, 2027.42
        if before_char in "/.=":
            continue
        if after.startswith(".") and len(after) > 1 and after[1].isdigit():
            continue
        # Page range: 1991-1995 (and the preceding token was also year-ish)
        if after.startswith("-") and len(after) > 1 and after[1].isdigit():
            preceding = text[max(0, start - 5):start]
            if "pp." in preceding or preceding.endswith(", ") or preceding.endswith(": "):
                continue
        out.append(m.group(0))
    return out


@register_citation_rule(META)
def unstructured_length(elem, ctx) -> list[Finding]:
    sev = ctx.config.severity(META.id, META.default_severity.value)
    min_words = int(ctx.config.param(META.id, "min_words", 5))
    max_words = int(ctx.config.param(META.id, "max_words", 60))
    max_year_count = int(ctx.config.param(META.id, "max_year_count", 1))
    max_semis = int(ctx.config.param(META.id, "max_semicolons", 2))

    uc = find_child(elem, "unstructured_citation")
    if uc is None:
        return []

    text = text_of(uc)
    if not text:
        return [Finding(
            rule_id=META.id,
            severity=sev,
            message="Empty <unstructured_citation>.",
            line=elem.sourceline,
            citation_key=citation_key(elem),
        )]

    # If this citation looks like a non-Crossref-indexed source (conference
    # presentation, news/website article, software/code repo), skip the
    # length and multi-year heuristics entirely — these are normal for
    # those types (publication date + access date is two years; URLs and
    # access notes legitimately make the text long).
    cite_type = detect_type(text)

    words = text.split()
    findings: list[Finding] = []

    if len(words) < min_words:
        findings.append(Finding(
            rule_id=META.id,
            severity=sev,
            message=f"Unstructured citation is unusually short ({len(words)} words; min={min_words}). Likely a fragment.",
            line=elem.sourceline,
            citation_key=citation_key(elem),
            snippet=short_snippet(text),
        ))
    elif len(words) > max_words and cite_type is None:
        findings.append(Finding(
            rule_id=META.id,
            severity=sev,
            message=f"Unstructured citation is unusually long ({len(words)} words; max={max_words}). Likely a scraping error that glued multiple references together.",
            line=elem.sourceline,
            citation_key=citation_key(elem),
            snippet=short_snippet(text),
        ))

    if cite_type is None:
        years = _real_year_tokens(text)
        if len(years) > max_year_count:
            findings.append(Finding(
                rule_id=META.id,
                severity=sev,
                message=f"Unstructured citation contains {len(years)} year-like tokens ({', '.join(years)}). Likely two or more references glued together.",
                line=elem.sourceline,
                citation_key=citation_key(elem),
                snippet=short_snippet(text),
            ))

    semis = text.count(";")
    if semis > max_semis and cite_type is None:
        findings.append(Finding(
            rule_id=META.id,
            severity=sev,
            message=f"Unstructured citation contains {semis} semicolons. Likely multiple authors/references run together.",
            line=elem.sourceline,
            citation_key=citation_key(elem),
            snippet=short_snippet(text),
        ))

    return findings
