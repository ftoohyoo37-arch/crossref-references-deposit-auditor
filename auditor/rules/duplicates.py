from __future__ import annotations

from ..models import Finding, RuleMeta, Severity
from . import register_post_rule

META = RuleMeta(
    id="duplicate_keys",
    name="Duplicate citation keys",
    description=(
        "Reports any `key` attribute that appears on more than one <citation> "
        "element within the same deposit."
    ),
    scope="post",
    default_severity=Severity.ERROR,
    default_enabled=True,
    params=[],
)


@register_post_rule(META)
def duplicate_keys(ctx) -> list[Finding]:
    sev = ctx.config.severity(META.id, META.default_severity.value)
    findings: list[Finding] = []
    for list_line, keys in ctx.citation_keys_by_list.items():
        for key, lines in keys.items():
            if len(lines) > 1:
                findings.append(Finding(
                    rule_id=META.id,
                    severity=sev,
                    message=(
                        f"Citation key '{key}' is duplicated {len(lines)} times "
                        f"within the <citation_list> at line {list_line} "
                        f"(citation lines: {', '.join(str(l) for l in lines)})."
                    ),
                    line=lines[0],
                    citation_key=key,
                ))
    return findings
