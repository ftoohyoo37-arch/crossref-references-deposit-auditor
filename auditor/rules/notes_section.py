from __future__ import annotations

from ..models import Finding, RuleMeta, Severity
from ..notes_section import detect_notes_section
from . import register_citation_rule
from ._util import citation_key, find_child, short_snippet, text_of


META = RuleMeta(
    id="notes_section_appended",
    name="Notes / Footnotes section appended to citation",
    description=(
        "Flags <unstructured_citation> values that have a 'Notes' (or "
        "'Footnotes' / 'Endnotes') section header followed by one or "
        "more footnote arrows (↑1 …) appended to the end. This pattern "
        "appears when GROBID concatenates the article's notes section "
        "onto the last entry of the works cited. The cleanup tool "
        "auto-strips the appended block, keeping only the real citation."
    ),
    scope="citation",
    default_severity=Severity.WARNING,
    default_enabled=True,
    params=[],
)


@register_citation_rule(META)
def notes_section_appended(elem, ctx) -> list[Finding]:
    sev = ctx.config.severity(META.id, META.default_severity.value)
    uc = find_child(elem, "unstructured_citation")
    if uc is None:
        return []
    text = text_of(uc).strip()
    m = detect_notes_section(text)
    if m is None:
        return []

    # Only flag if the Notes section is genuinely a SUFFIX — i.e., there
    # is real citation content before it. If the citation begins with
    # the Notes pattern, footnote_artifact already handles it.
    if m.start() < 30:
        return []

    return [Finding(
        rule_id=META.id,
        severity=sev,
        message=(
            f"Notes/Footnotes section appended to citation (starts at "
            f"char {m.start()}: {m.group(0).strip()!r}). The cleanup "
            "tool will auto-strip the appended block, keeping only the "
            "real citation."
        ),
        line=elem.sourceline,
        citation_key=citation_key(elem),
        snippet=short_snippet(text),
    )]
