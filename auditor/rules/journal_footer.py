from __future__ import annotations

from ..journal_footer import detect_footer
from ..models import Finding, RuleMeta, Severity
from . import register_citation_rule
from ._util import citation_key, find_child, short_snippet, text_of


META = RuleMeta(
    id="journal_footer_suffix",
    name="Journal page footer glued onto citation",
    description=(
        "Flags <unstructured_citation> values whose tail looks like a "
        "journal page footer (e.g., 'Reflections | Volume 24, Issue 2, "
        "Spring 2025'). This pattern almost never appears inside a real "
        "bibliographic entry; published references use '5(2)' or 'vol. 5, "
        "no. 2', not spelled-out 'Volume X, Issue Y'. The cleanup tool "
        "auto-strips the footer when this rule fires."
    ),
    scope="citation",
    default_severity=Severity.WARNING,
    default_enabled=True,
    params=[],
)


@register_citation_rule(META)
def journal_footer_suffix(elem, ctx) -> list[Finding]:
    sev = ctx.config.severity(META.id, META.default_severity.value)
    uc = find_child(elem, "unstructured_citation")
    if uc is None:
        return []
    text = text_of(uc).strip()
    m = detect_footer(text)
    if m is None:
        return []

    return [Finding(
        rule_id=META.id,
        severity=sev,
        message=(
            f"Trailing journal footer detected and will be auto-stripped "
            f"by the cleanup tool: {m.group(0)!r}."
        ),
        line=elem.sourceline,
        citation_key=citation_key(elem),
        snippet=short_snippet(text),
    )]
