from __future__ import annotations

import re

from ..models import Finding, ParamMeta, RuleMeta, Severity
from . import register_citation_rule
from ._util import citation_key, find_children, local_name, short_snippet, text_of

META = RuleMeta(
    id="author_parsing",
    name="Author surname parsing leaks",
    description=(
        "Detects cases where the <author> field (or <person_name>/<surname> in "
        "structured citations) contains delimiters like ',', ';', ' and ', or "
        "trailing initials — indicating that multiple authors were jammed into "
        "a single field rather than parsed apart."
    ),
    scope="citation",
    default_severity=Severity.WARNING,
    default_enabled=True,
    params=[],
)

LEAK_DELIMITERS_RE = re.compile(r"\s*(?:;|,\s*[A-Z]\.|\s+and\s+|\s+&\s+)")
INITIALS_TRAIL_RE = re.compile(r",\s*(?:[A-Z]\.\s*){2,}")


def _check_text(field_name: str, raw: str) -> list[str]:
    msgs: list[str] = []
    if ";" in raw:
        msgs.append(f"<{field_name}> contains ';' — likely multiple authors in one field.")
    if re.search(r"\s+and\s+", raw):
        msgs.append(f"<{field_name}> contains ' and ' — likely multiple authors in one field.")
    if re.search(r"\s+&\s+", raw):
        msgs.append(f"<{field_name}> contains ' & ' — likely multiple authors in one field.")
    if INITIALS_TRAIL_RE.search(raw):
        msgs.append(f"<{field_name}> contains a sequence of initials — likely multiple authors in one field.")
    return msgs


@register_citation_rule(META)
def author_parsing(elem, ctx) -> list[Finding]:
    sev = ctx.config.severity(META.id, META.default_severity.value)
    findings: list[Finding] = []

    # Schema 4.x: <author>; structured deposits use <person_name><surname>...
    for tag in ("author", "surname"):
        for f in find_children(elem, tag):
            raw = text_of(f)
            for msg in _check_text(tag, raw):
                findings.append(Finding(
                    rule_id=META.id,
                    severity=sev,
                    message=msg,
                    line=elem.sourceline,
                    citation_key=citation_key(elem),
                    snippet=short_snippet(raw),
                ))

    # Also descend into person_name children
    for pn in find_children(elem, "person_name"):
        for child in pn:
            ln = local_name(child.tag)
            if ln in ("surname", "given_name", "suffix"):
                raw = text_of(child)
                for msg in _check_text(ln, raw):
                    findings.append(Finding(
                        rule_id=META.id,
                        severity=sev,
                        message=msg,
                        line=elem.sourceline,
                        citation_key=citation_key(elem),
                        snippet=short_snippet(raw),
                    ))
    return findings
