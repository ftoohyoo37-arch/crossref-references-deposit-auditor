from __future__ import annotations

import re

from ..models import Finding, ParamMeta, RuleMeta, Severity
from . import register_citation_rule
from ._util import citation_key, find_child, text_of

META = RuleMeta(
    id="page_range",
    name="Page range integrity",
    description=(
        "Checks that <first_page> and <last_page> are numeric and that "
        "last_page >= first_page (or that letter-prefixed pages share a prefix)."
    ),
    scope="citation",
    default_severity=Severity.WARNING,
    default_enabled=True,
    params=[],
)

PAGE_RE = re.compile(r"^([A-Za-z]*)(\d+)([A-Za-z]?)$")


def _parse_page(raw: str):
    m = PAGE_RE.match(raw.strip())
    if not m:
        return None
    prefix, num, suffix = m.groups()
    return prefix, int(num), suffix


@register_citation_rule(META)
def page_range(elem, ctx) -> list[Finding]:
    sev = ctx.config.severity(META.id, META.default_severity.value)
    first = find_child(elem, "first_page")
    last = find_child(elem, "last_page")
    if first is None and last is None:
        return []

    findings: list[Finding] = []
    fp_raw = text_of(first) if first is not None else None
    lp_raw = text_of(last) if last is not None else None

    if first is not None and not fp_raw:
        findings.append(Finding(
            rule_id=META.id,
            severity=sev,
            message="<first_page> is empty.",
            line=elem.sourceline,
            citation_key=citation_key(elem),
        ))
    if last is not None and not lp_raw:
        findings.append(Finding(
            rule_id=META.id,
            severity=sev,
            message="<last_page> is empty.",
            line=elem.sourceline,
            citation_key=citation_key(elem),
        ))

    if fp_raw and lp_raw:
        fp = _parse_page(fp_raw)
        lp = _parse_page(lp_raw)
        if fp is None or lp is None:
            findings.append(Finding(
                rule_id=META.id,
                severity=sev,
                message=f"Page range '{fp_raw}–{lp_raw}' has non-standard format.",
                line=elem.sourceline,
                citation_key=citation_key(elem),
            ))
        else:
            fp_pre, fp_num, _ = fp
            lp_pre, lp_num, _ = lp
            if fp_pre != lp_pre:
                findings.append(Finding(
                    rule_id=META.id,
                    severity=sev,
                    message=f"Page prefixes differ: '{fp_raw}' vs '{lp_raw}'.",
                    line=elem.sourceline,
                    citation_key=citation_key(elem),
                ))
            elif lp_num < fp_num:
                findings.append(Finding(
                    rule_id=META.id,
                    severity=sev,
                    message=f"<last_page> ({lp_raw}) is less than <first_page> ({fp_raw}).",
                    line=elem.sourceline,
                    citation_key=citation_key(elem),
                ))
    return findings
