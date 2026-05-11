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
# URL region — covers https?://… up to the next whitespace. Years inside
# URL slugs ("/2018/", "from-1890-to-1965/") are not publication years.
URL_REGION_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def _real_year_tokens(text: str) -> list[str]:
    """Distinct year-like tokens minus the obvious false positives.

    Returns DISTINCT years (so "2021. … 2021." counts as one), in
    first-seen order. Exclusions applied before the dedup pass:

    - Years inside quoted titles: "The 1984 election" — title number,
      not a second publication year.
    - Years inside URLs: "/2018/" or "from-1890-to-1965/" — URL slug
      content, not a publication year.
    - Parenthesized journal-founding dates: "Atlantic Monthly (1993)" —
      year wrapped in parens with no digit immediately following the
      close paren is a metadata year, not a glued reference's publication
      year.
    - Volume markers: "1991(2)" — year followed by `(digit`.
    - URL/handle fragments: "/2027/", "=2027", ".2027", "2027.42"
      (preceded by `/`, `.`, or `=`, or followed by `.` then a digit).
    - Year ranges: "1991-1995", "1700-1964" — two adjacent year-like
      numbers separated by a hyphen are a date range, not two
      publication years (regardless of what precedes).
    """
    quoted_spans = [(m.start(), m.end()) for m in QUOTED_REGION_RE.finditer(text)]
    url_spans = [(m.start(), m.end()) for m in URL_REGION_RE.finditer(text)]

    seen: set[str] = set()
    out: list[str] = []
    for m in YEAR_RE.finditer(text):
        start, end = m.span()

        # Skip year-like numbers inside quoted titles.
        if any(qs <= start < qe for qs, qe in quoted_spans):
            continue
        # Skip year-like numbers inside URLs.
        if any(us <= start < ue for us, ue in url_spans):
            continue

        before_char = text[start - 1] if start > 0 else ""
        after = text[end:end + 5]

        # Volume marker: 1991(2)
        if after.startswith("(") and len(after) > 1 and after[1].isdigit():
            continue
        # Parenthesized metadata year: "Atlantic Monthly (1993) 320(3):"
        # Match (YYYY) when preceded by `(` and followed by `)`.
        if before_char == "(" and after.startswith(")"):
            continue
        # URL / handle fragment: /2027/, =2027, .2027, 2027.42
        if before_char in "/.=":
            continue
        if after.startswith(".") and len(after) > 1 and after[1].isdigit():
            continue
        # Year range: any YYYY-YYYY (e.g., 1700-1964, 1991-1995).
        # If this year is followed by `-` and then 4 digits forming
        # another year-like number, both ends of the range are date
        # markers, not separate publication years.
        if after.startswith("-") and len(after) > 4 and after[1:5].isdigit():
            continue
        # Mirror: skip if THIS year is the second half of a YYYY-YYYY
        # range (preceded by 4-digit-then-hyphen sequence).
        before5 = text[max(0, start - 5):start]
        if len(before5) >= 5 and before5[0].isdigit() and before5[-1] == "-":
            if before5[:4].isdigit():
                continue

        year = m.group(0)
        if year in seen:
            continue
        seen.add(year)
        out.append(year)
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
