from __future__ import annotations

import re

from ..models import Finding, RuleMeta, Severity
from . import register_citation_rule
from ._util import citation_key, find_child, short_snippet, text_of


META = RuleMeta(
    id="footnote_artifact",
    name="Footnote captured as citation",
    description=(
        "Flags <unstructured_citation> values that begin with a footnote "
        "back-reference glyph (↑, ↩, ⁋) — typically followed by a footnote "
        "number and narrative prose like 'See also …' or 'Smith (2021) "
        "argues …'. These are footnotes accidentally pulled into the "
        "reference list by GROBID rather than bibliographic entries. The "
        "cleanup tool auto-deletes them without manual review."
    ),
    scope="citation",
    default_severity=Severity.WARNING,
    default_enabled=True,
    params=[],
)

# A footnote almost always begins with a back-reference glyph — the up arrow
# ↑ (U+2191), the leftward-with-hook ↩ (U+21A9), or the reversed pilcrow ⁋
# (U+204B) — usually followed by the footnote number. Anchored to the start
# of the citation text (after optional whitespace) so we don't false-positive
# on quoted material that happens to contain an arrow.
FOOTNOTE_MARKER_RE = re.compile(r"^\s*[↑↩⁋]")


@register_citation_rule(META)
def footnote_artifact(elem, ctx) -> list[Finding]:
    sev = ctx.config.severity(META.id, META.default_severity.value)
    uc = find_child(elem, "unstructured_citation")
    if uc is None:
        return []
    text = text_of(uc).strip()
    if not text:
        return []
    m = FOOTNOTE_MARKER_RE.match(text)
    if m is None:
        return []

    return [Finding(
        rule_id=META.id,
        severity=sev,
        message=(
            f"Citation begins with a footnote back-reference glyph "
            f"({m.group(0).strip()!r}). The cleanup tool will auto-delete "
            "this entry — footnotes are not bibliographic references and "
            "should not appear in the reference list."
        ),
        line=elem.sourceline,
        citation_key=citation_key(elem),
        snippet=short_snippet(text),
    )]
