from __future__ import annotations

import re

from ..models import Finding, ParamMeta, RuleMeta, Severity
from . import register_citation_rule
from ._util import citation_key, find_children, local_name, text_of

META = RuleMeta(
    id="orcid_format",
    name="ORCID format & checksum",
    description=(
        "Validates ORCID identifiers (in <ORCID> elements or person_name "
        "children) for the canonical 16-digit format and ISO/IEC 7064 MOD "
        "11-2 checksum."
    ),
    scope="citation",
    default_severity=Severity.ERROR,
    default_enabled=True,
    params=[],
)

ORCID_RE = re.compile(r"(\d{4}-\d{4}-\d{4}-\d{3}[\dX])$")


def _orcid_checksum_ok(orcid: str) -> bool:
    digits = orcid.replace("-", "")
    if len(digits) != 16:
        return False
    total = 0
    for ch in digits[:-1]:
        if not ch.isdigit():
            return False
        total = (total + int(ch)) * 2
    remainder = total % 11
    check = (12 - remainder) % 11
    expected = "X" if check == 10 else str(check)
    return digits[-1].upper() == expected


@register_citation_rule(META)
def orcid_format(elem, ctx) -> list[Finding]:
    sev = ctx.config.severity(META.id, META.default_severity.value)
    findings: list[Finding] = []

    candidates: list[tuple[str, str]] = []
    for o in find_children(elem, "ORCID"):
        candidates.append(("ORCID", text_of(o)))
    for pn in find_children(elem, "person_name"):
        for child in pn:
            if local_name(child.tag) == "ORCID":
                candidates.append(("ORCID", text_of(child)))

    for field_name, raw in candidates:
        if not raw:
            findings.append(Finding(
                rule_id=META.id,
                severity=sev,
                message=f"<{field_name}> is empty.",
                line=elem.sourceline,
                citation_key=citation_key(elem),
            ))
            continue
        m = ORCID_RE.search(raw)
        if not m:
            findings.append(Finding(
                rule_id=META.id,
                severity=sev,
                message=f"<{field_name}> '{raw}' is not in canonical ORCID format (XXXX-XXXX-XXXX-XXXX).",
                line=elem.sourceline,
                citation_key=citation_key(elem),
            ))
            continue
        if not _orcid_checksum_ok(m.group(1)):
            findings.append(Finding(
                rule_id=META.id,
                severity=sev,
                message=f"<{field_name}> '{m.group(1)}' has an invalid MOD 11-2 checksum.",
                line=elem.sourceline,
                citation_key=citation_key(elem),
            ))
    return findings
