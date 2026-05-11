from __future__ import annotations

from ..models import Finding, RuleMeta, Severity
from . import register_citation_rule
from ._util import citation_key, find_child, local_name, short_snippet, text_of


META = RuleMeta(
    id="incomplete_structured_citation",
    name="Structured citation missing Crossref's required fields",
    description=(
        "Flags <citation> elements that contain SOME structured metadata "
        "fields but not the minimum set Crossref's ingestion requires. "
        "When ANY of <article_title>, <volume_title>, <volume>, <issue>, "
        "<cYear>, <first_page>, <last_page>, or <doi> are present, "
        "Crossref also requires at least one of <journal_title>, "
        "<proceedings_title>, or <issn> (for the venue), AND at least "
        "one of <first_page> or <author> (for basic identification). "
        "This is a Crossref business rule that XSD validation cannot "
        "catch; the rule was identified from a failed test deposit. "
        "The cleanup tool auto-strips the structured fields and keeps "
        "the <unstructured_citation> only, which Crossref always accepts."
    ),
    scope="citation",
    default_severity=Severity.WARNING,
    default_enabled=True,
    params=[],
)

# Structured-content fields that "switch on" the business rule.
STRUCTURED_TRIGGERS = {
    "article_title", "volume", "issue",
    "cYear", "first_page", "last_page", "doi",
    "edition_number", "component_number",
}
# Venue identifier — at least one is required when structured fields present.
# Crossref accepts any of these to satisfy the venue requirement:
#   - journal_title / issn for journal articles
#   - proceedings_title for conference papers
#   - volume_title / series_title for book chapters and series volumes
#   - isbn as a machine identifier
# Confirmed empirically from a test deposit on 7,109 citations: Crossref
# only errors ("Either ISSN or Journal title or Proceedings title must be
# supplied") when NONE of these are present in a citation that otherwise
# has structured metadata.
VENUE_FIELDS = {
    "journal_title", "proceedings_title", "issn",
    "volume_title", "series_title", "isbn",
}
# Subset of VENUE_FIELDS that specifically marks the citation as a
# journal-article or conference-paper shape. The "first_page or author"
# business rule only fires for these shapes; book chapters identified
# only by <volume_title>/<series_title>/<isbn> are exempt.
JOURNAL_LIKE_VENUE = {"journal_title", "proceedings_title", "issn"}
# Basic identification — required when the citation is journal-shaped
# AND has <article_title>.
IDENT_FIELDS = {"first_page", "author"}


@register_citation_rule(META)
def incomplete_structured_citation(elem, ctx) -> list[Finding]:
    """Two sub-checks, calibrated against an actual Crossref test deposit:

    1. VENUE: any structured-content trigger present (article_title,
       volume, issue, cYear, first_page, last_page, doi, etc.) AND no
       venue identifier (journal_title, proceedings_title, volume_title,
       series_title, issn, isbn). Crossref error: "Either ISSN or
       Journal title or Proceedings title must be supplied."

    2. IDENT: <article_title> AND venue identifier both present AND
       neither <first_page> nor <author>. Crossref error: "Either first
       page or author must be supplied." Note this sub-check requires
       <article_title>; book chapters or other types without a title
       claim don't trigger it.
    """
    sev = ctx.config.severity(META.id, META.default_severity.value)
    present_tags = {local_name(child.tag) for child in elem}
    if not (present_tags & STRUCTURED_TRIGGERS):
        return []

    has_venue = bool(present_tags & VENUE_FIELDS)
    has_journal_venue = bool(present_tags & JOURNAL_LIKE_VENUE)
    has_ident = bool(present_tags & IDENT_FIELDS)
    has_article_title = "article_title" in present_tags

    missing_venue = not has_venue
    # Crossref only enforces "first_page or author" for journal-shape
    # citations (journal_title / proceedings_title / issn) that also
    # have <article_title>. Book chapters identified by <volume_title>
    # alone are not subject to this rule.
    missing_ident = has_article_title and has_journal_venue and not has_ident
    if not (missing_venue or missing_ident):
        return []

    uc = find_child(elem, "unstructured_citation")
    snippet_text = text_of(uc) if uc is not None else ""

    reasons: list[str] = []
    if missing_venue:
        reasons.append(
            "no <journal_title>, <proceedings_title>, <volume_title>, "
            "<series_title>, <issn>, or <isbn>"
        )
    if missing_ident:
        reasons.append("<article_title> and venue present but no <first_page> and no <author>")

    return [Finding(
        rule_id=META.id,
        severity=sev,
        message=(
            f"Citation has structured fields ({', '.join(sorted(present_tags & STRUCTURED_TRIGGERS))}) "
            f"but is missing Crossref's required minimums: "
            f"{'; '.join(reasons)}. The cleanup tool will auto-strip "
            "the structured fields, keeping only <unstructured_citation>."
        ),
        line=elem.sourceline,
        citation_key=citation_key(elem),
        snippet=short_snippet(snippet_text),
    )]
