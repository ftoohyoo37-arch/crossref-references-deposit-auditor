from __future__ import annotations

import re

from ..models import Finding, ParamMeta, RuleMeta, Severity
from . import register_citation_rule
from ._util import citation_key, find_child, short_snippet, text_of

META = RuleMeta(
    id="doi_format",
    name="DOI format check",
    description=(
        "Checks that <doi> values match the canonical DOI pattern "
        "(`10.xxxx/...`) and are not wrapped in URLs like doi.org/dx.doi.org."
    ),
    scope="citation",
    default_severity=Severity.ERROR,
    default_enabled=True,
    params=[],
)

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
DOI_URL_RE = re.compile(r"(?:https?://)?(?:dx\.)?doi\.org/", re.IGNORECASE)


@register_citation_rule(META)
def doi_format(elem, ctx) -> list[Finding]:
    sev = ctx.config.severity(META.id, META.default_severity.value)
    doi_elem = find_child(elem, "doi")
    if doi_elem is None:
        return []
    raw = text_of(doi_elem)
    if not raw:
        return [Finding(
            rule_id=META.id,
            severity=sev,
            message="<doi> element is empty.",
            line=elem.sourceline,
            citation_key=citation_key(elem),
        )]

    findings: list[Finding] = []
    if DOI_URL_RE.search(raw):
        findings.append(Finding(
            rule_id=META.id,
            severity=sev,
            message="DOI value is wrapped in a doi.org URL; Crossref expects the bare DOI (e.g. '10.1234/abc').",
            line=elem.sourceline,
            citation_key=citation_key(elem),
            snippet=short_snippet(raw),
        ))
    elif not DOI_RE.match(raw):
        findings.append(Finding(
            rule_id=META.id,
            severity=sev,
            message="DOI value does not match the pattern '10.xxxx/...'.",
            line=elem.sourceline,
            citation_key=citation_key(elem),
            snippet=short_snippet(raw),
        ))

    if raw != raw.strip():
        findings.append(Finding(
            rule_id=META.id,
            severity="warning",
            message="DOI value has leading or trailing whitespace.",
            line=elem.sourceline,
            citation_key=citation_key(elem),
            snippet=short_snippet(raw),
        ))

    return findings
