from __future__ import annotations

import re

from ..models import Finding, RuleMeta, Severity
from . import register_citation_rule
from ._util import citation_key, find_child, short_snippet, text_of


META = RuleMeta(
    id="ligature_artifacts",
    name="Unicode ligature artifacts (ﬁ ﬀ ﬂ ﬃ ﬄ)",
    description=(
        "Flags <unstructured_citation> values containing Unicode ligature "
        "codepoints (ﬁ U+FB01, ﬀ U+FB00, ﬂ U+FB02, ﬃ U+FB03, ﬄ U+FB04, "
        "ﬅ U+FB05, ﬆ U+FB06). PDF text extractors sometimes preserve "
        "these typographic ligatures literally; Crossref expects the "
        "decomposed form (e.g., 'fi' not 'ﬁ'). The cleanup tool "
        "auto-normalizes any flagged ligature to its decomposed form."
    ),
    scope="citation",
    default_severity=Severity.WARNING,
    default_enabled=True,
    params=[],
)

LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",  # long-s + t
    "ﬆ": "st",
}
LIGATURE_RE = re.compile("[" + "".join(LIGATURES.keys()) + "]")


def normalize_ligatures(text: str) -> str:
    """Replace each ligature codepoint with its decomposed form."""
    return LIGATURE_RE.sub(lambda m: LIGATURES[m.group(0)], text)


@register_citation_rule(META)
def ligature_artifacts(elem, ctx) -> list[Finding]:
    sev = ctx.config.severity(META.id, META.default_severity.value)
    uc = find_child(elem, "unstructured_citation")
    if uc is None:
        return []
    text = text_of(uc)
    matches = LIGATURE_RE.findall(text)
    if not matches:
        return []
    distinct = sorted(set(matches))
    return [Finding(
        rule_id=META.id,
        severity=sev,
        message=(
            f"Found {len(matches)} Unicode ligature(s) "
            f"({', '.join(repr(c) for c in distinct)}) — should be "
            f"decomposed (e.g., {LIGATURES[distinct[0]]!r}). "
            "Auto-normalized by cleanup."
        ),
        line=elem.sourceline,
        citation_key=citation_key(elem),
        snippet=short_snippet(text),
    )]
