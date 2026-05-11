from __future__ import annotations

import re

from ..models import Finding, RuleMeta, Severity
from . import register_citation_rule
from ._util import citation_key, find_child, short_snippet, text_of


META = RuleMeta(
    id="embedded_doi",
    name="DOI buried in unstructured citation text",
    description=(
        "Flags <unstructured_citation> values that contain a DOI (either "
        "as a bare 10.xxxx/yyy pattern or as a doi.org URL) when the "
        "<citation> has no separate <doi> child element. Promoting the "
        "DOI to a structured field substantially improves Crossref's "
        "ability to match the reference, and the DOI is verifiable."
    ),
    scope="citation",
    default_severity=Severity.WARNING,
    default_enabled=True,
    params=[],
)

# Match either a doi.org URL or a bare 10.xxxx/yyy DOI. The trailing-char
# class stops at common citation delimiters so we don't swallow trailing
# punctuation or surrounding context.
DOI_IN_TEXT_RE = re.compile(
    r"(?:https?://(?:dx\.)?doi\.org/|\bdoi:\s*)?"
    r"(10\.\d{4,9}/[^\s,;\"'<>()\[\]]+)",
    re.IGNORECASE,
)


def _extract_doi_from_text(text: str) -> str | None:
    """Return the first DOI-like substring, normalized to bare form."""
    m = DOI_IN_TEXT_RE.search(text)
    if m is None:
        return None
    doi = m.group(1).rstrip(".,;:)")  # strip trailing sentence punctuation
    return doi


@register_citation_rule(META)
def embedded_doi(elem, ctx) -> list[Finding]:
    sev = ctx.config.severity(META.id, META.default_severity.value)
    # Only fire if the citation has no separate <doi> element already.
    if find_child(elem, "doi") is not None:
        return []
    uc = find_child(elem, "unstructured_citation")
    if uc is None:
        return []
    text = text_of(uc).strip()
    if not text:
        return []

    doi = _extract_doi_from_text(text)
    if doi is None:
        return []

    return [Finding(
        rule_id=META.id,
        severity=sev,
        message=(
            f"Citation contains an embedded DOI ({doi!r}) but no "
            f"<doi> structured field. Promoting it would improve "
            "Crossref matching and verifiability."
        ),
        line=elem.sourceline,
        citation_key=citation_key(elem),
        snippet=short_snippet(text),
    )]
