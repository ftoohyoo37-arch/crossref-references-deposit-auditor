from __future__ import annotations

import re

from ..models import Finding, ParamMeta, RuleMeta, Severity
from . import register_citation_rule
from ._util import citation_key, find_child, short_snippet, text_of


META = RuleMeta(
    id="repeat_author_marker",
    name="Repeat-author marker (___ / --- / ——)",
    description=(
        "Flags <unstructured_citation> values containing a bibliography-style "
        "repeat-author marker (3+ underscores, 3+ hyphens, or 2+ em-dashes "
        "followed by a year). These almost always indicate that the scraper "
        "captured multiple references in one citation, with later refs using "
        "the marker as a stand-in for the previous author. The cleanup tool "
        "can split these and substitute the marker with the real author block."
    ),
    scope="citation",
    default_severity=Severity.WARNING,
    default_enabled=True,
    params=[
        ParamMeta("min_chars", "int", 30,
                  "Skip citations shorter than this (always-OK)."),
    ],
)

# Match: 3+ underscores, 3+ hyphens, or 2+ em/en-dashes — standing alone as a
# token (whitespace before, whitespace or punctuation after). This catches
# both "Author, Year. Title" patterns and "Author. Title. Year" Chicago
# notes-and-bibliography style without requiring the year to follow the marker.
MARKER_RE = re.compile(
    r"(?:(?<=\s)|(?<=^))"
    r"(_{3,}|-{3,}|—{2,}|–{2,})"
    r"(?=[\s.,])"
)


@register_citation_rule(META)
def repeat_author_marker(elem, ctx) -> list[Finding]:
    sev = ctx.config.severity(META.id, META.default_severity.value)
    min_chars = int(ctx.config.param(META.id, "min_chars", 30))

    uc = find_child(elem, "unstructured_citation")
    if uc is None:
        return []
    text = text_of(uc).strip()
    if len(text) < min_chars:
        return []

    matches = list(MARKER_RE.finditer(text))
    if not matches:
        return []

    distinct = sorted({m.group(1) for m in matches})
    return [Finding(
        rule_id=META.id,
        severity=sev,
        message=(
            f"Contains {len(matches)} repeat-author marker(s) "
            f"({', '.join(repr(m) for m in distinct)}) — likely multiple "
            "references where later ones reuse the previous author. The "
            "cleanup tool will propose splitting these and substituting the "
            "marker with the real author block."
        ),
        line=elem.sourceline,
        citation_key=citation_key(elem),
        snippet=short_snippet(text),
    )]
