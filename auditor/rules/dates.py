from __future__ import annotations

import datetime as dt
import re

from ..models import Finding, ParamMeta, RuleMeta, Severity
from . import register_citation_rule
from ._util import citation_key, find_child, find_children, text_of

META = RuleMeta(
    id="date_validity",
    name="Date and year validity",
    description=(
        "Checks <cYear>, <year>, and structured month/day fields for plausible "
        "values — flags years before the floor, in the future, or with invalid "
        "month/day combinations."
    ),
    scope="citation",
    default_severity=Severity.WARNING,
    default_enabled=True,
    params=[
        ParamMeta("min_year", "int", 1500, "Earliest acceptable publication year."),
        ParamMeta("future_year_buffer", "int", 2, "Years past current allowed (e.g. 2 means 2026 + 2 = 2028 is the cap)."),
    ],
)

YEAR_RE = re.compile(r"^\d{4}$")


@register_citation_rule(META)
def date_validity(elem, ctx) -> list[Finding]:
    sev = ctx.config.severity(META.id, META.default_severity.value)
    min_year = int(ctx.config.param(META.id, "min_year", 1500))
    buffer = int(ctx.config.param(META.id, "future_year_buffer", 2))
    max_year = dt.date.today().year + buffer

    findings: list[Finding] = []

    # Year fields: <cYear> (Crossref-canonical) and <year> (alternate / loose)
    year_text: str | None = None
    for tag in ("cYear", "year"):
        for ye in find_children(elem, tag):
            raw = text_of(ye)
            if not raw:
                continue
            year_text = raw
            if not YEAR_RE.match(raw):
                findings.append(Finding(
                    rule_id=META.id,
                    severity=sev,
                    message=f"<{tag}> '{raw}' is not a 4-digit year.",
                    line=elem.sourceline,
                    citation_key=citation_key(elem),
                ))
            else:
                y = int(raw)
                if y < min_year:
                    findings.append(Finding(
                        rule_id=META.id,
                        severity=sev,
                        message=f"<{tag}> {y} is before {min_year}.",
                        line=elem.sourceline,
                        citation_key=citation_key(elem),
                    ))
                elif y > max_year:
                    findings.append(Finding(
                        rule_id=META.id,
                        severity=sev,
                        message=f"<{tag}> {y} is in the future (> {max_year}).",
                        line=elem.sourceline,
                        citation_key=citation_key(elem),
                    ))

    # Month/day if present (mostly in publication_date inside non-citation contexts,
    # but defensively check inside citation too)
    month = find_child(elem, "month")
    day = find_child(elem, "day")
    if month is not None:
        try:
            m = int(text_of(month))
            if not 1 <= m <= 12:
                findings.append(Finding(
                    rule_id=META.id,
                    severity=sev,
                    message=f"<month> {m} is out of range (1–12).",
                    line=elem.sourceline,
                    citation_key=citation_key(elem),
                ))
        except ValueError:
            findings.append(Finding(
                rule_id=META.id,
                severity=sev,
                message=f"<month> '{text_of(month)}' is not numeric.",
                line=elem.sourceline,
                citation_key=citation_key(elem),
            ))
    if day is not None:
        try:
            d = int(text_of(day))
            if not 1 <= d <= 31:
                findings.append(Finding(
                    rule_id=META.id,
                    severity=sev,
                    message=f"<day> {d} is out of range (1–31).",
                    line=elem.sourceline,
                    citation_key=citation_key(elem),
                ))
        except ValueError:
            findings.append(Finding(
                rule_id=META.id,
                severity=sev,
                message=f"<day> '{text_of(day)}' is not numeric.",
                line=elem.sourceline,
                citation_key=citation_key(elem),
            ))
    return findings
