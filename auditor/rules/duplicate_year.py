from __future__ import annotations

import re

from ..models import Finding, RuleMeta, Severity
from . import register_citation_rule
from ._util import citation_key, find_child, short_snippet, text_of


META = RuleMeta(
    id="duplicate_year_tokens",
    name="Two adjacent publication years",
    description=(
        "Flags <unstructured_citation> values containing two 4-digit "
        "years adjacent to each other (e.g., 'Ore, Ersula. 2019. 2015. \"…\"')"
        ". This is a common GROBID extraction artifact where the publication "
        "year is duplicated. The cleanup tool will attempt to auto-resolve "
        "by querying Crossref for the canonical year — when Crossref's "
        "high-confidence match returns a year that matches one of the two "
        "in the citation, the duplicate is auto-removed without manual review."
    ),
    scope="citation",
    default_severity=Severity.WARNING,
    default_enabled=True,
    params=[],
)

# Matches: "2019. 2015." or "2019, 2015," etc. — two 4-digit years separated
# only by a period or comma plus whitespace.
DUPLICATE_YEAR_RE = re.compile(
    r"\b(?P<first>1[5-9]\d{2}|20\d{2}|2100)[a-z]?[.,]\s+"
    r"(?P<second>1[5-9]\d{2}|20\d{2}|2100)[a-z]?[.,]"
)


@register_citation_rule(META)
def duplicate_year_tokens(elem, ctx) -> list[Finding]:
    sev = ctx.config.severity(META.id, META.default_severity.value)
    uc = find_child(elem, "unstructured_citation")
    if uc is None:
        return []
    text = text_of(uc).strip()
    m = DUPLICATE_YEAR_RE.search(text)
    if m is None:
        return []
    return [Finding(
        rule_id=META.id,
        severity=sev,
        message=(
            f"Two adjacent 4-digit years ({m.group('first')} and "
            f"{m.group('second')}). The cleanup tool will try to resolve "
            "this against Crossref."
        ),
        line=elem.sourceline,
        citation_key=citation_key(elem),
        snippet=short_snippet(text),
    )]
