"""Generate a CrossRef content-registration deposit XML.

This uses CrossRef's `<journal>` / `<journal_issue>` / `<journal_article>`
schema (crossref/4.4.x) — distinct from the reference-deposit schema
the existing pipeline uses (doi_resources_schema/4.3.6).

The output XML is suitable for upload to CrossRef's deposit endpoint to
MINT NEW DOIS for each article. After CrossRef ingests it, the DOIs
become live and the existing reference-backfill pipeline can run
against the per-article PDFs to deposit their reference lists.

Optionally, this builder can embed a citation_list inside each
journal_article (CrossRef supports combined registration + references
in one deposit). That's the recommended path for journals brand new
to CrossRef.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from .models import Article, IssueSidecar


CROSSREF_NS = "http://www.crossref.org/schema/4.4.2"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
SCHEMA_LOC = (
    "http://www.crossref.org/schema/4.4.2 "
    "https://www.crossref.org/schemas/crossref4.4.2.xsd"
)


def _doi_from_template(template: str, *, prefix: str, slug: str,
                       year: int, vol: int, iss: int, seq: int) -> str:
    """Render a DOI from a template string.

    Supports {prefix}, {slug}, {year}, {vol}, {iss}, {seq}, {seq:02d}
    style placeholders.
    """
    return template.format(
        prefix=prefix, slug=slug, year=year, vol=vol, iss=iss, seq=seq,
    )


def assign_dois(sidecar: IssueSidecar, *, doi_prefix: str,
                journal_slug: str, doi_template: str,
                resource_base_url: str = "") -> list[Article]:
    """Mutate sidecar.articles in place, populating .doi for each.

    Returns the same list for convenience.
    """
    for i, art in enumerate(sidecar.articles):
        seq = art.sequence or (i + 1)
        if not art.doi:
            art.doi = _doi_from_template(
                doi_template,
                prefix=doi_prefix,
                slug=journal_slug,
                year=sidecar.year,
                vol=sidecar.volume,
                iss=sidecar.issue,
                seq=seq,
            )
        if not art.resource_url and resource_base_url and art.filename:
            sep = "" if resource_base_url.endswith("/") else "/"
            art.resource_url = f"{resource_base_url}{sep}{art.filename}"
        art.sequence = seq
    return sidecar.articles


def _e(parent, tag: str, text: str | None = None,
       attrib: dict | None = None) -> ET.Element:
    el = ET.SubElement(parent, f"{{{CROSSREF_NS}}}{tag}", attrib=attrib or {})
    if text is not None:
        el.text = text
    return el


def _month_str(month: int) -> str:
    return f"{month:02d}" if month and 1 <= month <= 12 else "00"


def build_deposit(
    sidecars: list[IssueSidecar],
    *,
    journal_full_title: str,
    journal_abbrev: str = "",
    issn: str = "",
    depositor_name: str,
    depositor_email: str,
    registrant: str = "",
    doi_batch_id: str | None = None,
    include_citations: bool = False,
    citation_lookup: callable = None,   # (filename) -> list[dict]
) -> ET.ElementTree:
    """Build the CrossRef content-registration tree across N issues.

    Each issue from `sidecars` becomes one <journal_issue> + N
    <journal_article> children inside a single <journal> wrapper.

    If `include_citations` is True, `citation_lookup` is called for
    each article's filename to retrieve a list of {key, unstructured}
    dicts to embed as a <citation_list>.
    """
    ET.register_namespace("", CROSSREF_NS)
    ET.register_namespace("xsi", XSI_NS)

    root = ET.Element(
        f"{{{CROSSREF_NS}}}doi_batch",
        attrib={
            "version": "4.4.2",
            f"{{{XSI_NS}}}schemaLocation": SCHEMA_LOC,
        },
    )

    head = _e(root, "head")
    batch_id = doi_batch_id or f"content-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    _e(head, "doi_batch_id", batch_id)
    _e(head, "timestamp", datetime.now().strftime("%Y%m%d%H%M%S"))
    dep = _e(head, "depositor")
    _e(dep, "depositor_name", depositor_name)
    _e(dep, "email_address", depositor_email)
    _e(head, "registrant", registrant or depositor_name)

    body = _e(root, "body")
    journal = _e(body, "journal")

    # journal_metadata (once per <journal>)
    jm = _e(journal, "journal_metadata")
    _e(jm, "full_title", journal_full_title)
    if journal_abbrev:
        _e(jm, "abbrev_title", journal_abbrev)
    if issn:
        _e(jm, "issn", issn)

    for sc in sidecars:
        # journal_issue
        ji = _e(journal, "journal_issue")
        pub_date = _e(ji, "publication_date", attrib={"media_type": "print"})
        _e(pub_date, "month", _month_str(sc.month))
        _e(pub_date, "year", str(sc.year or datetime.now().year))
        if sc.volume:
            jv = _e(ji, "journal_volume")
            _e(jv, "volume", str(sc.volume))
        if sc.issue:
            _e(ji, "issue", str(sc.issue))

        # journal_article for each
        for art in sc.articles:
            if not art.doi:
                continue   # caller should have assigned DOIs first
            ja = _e(journal, "journal_article",
                    attrib={"publication_type": "full_text"})
            titles = _e(ja, "titles")
            _e(titles, "title", art.title or art.filename or "(untitled)")

            if art.authors:
                contribs = _e(ja, "contributors")
                for idx, author in enumerate(art.authors):
                    role = "author"
                    sequence = "first" if idx == 0 else "additional"
                    pn = _e(contribs, "person_name",
                            attrib={"contributor_role": role,
                                    "sequence": sequence})
                    if author.get("given"):
                        _e(pn, "given_name", author["given"])
                    if author.get("surname"):
                        _e(pn, "surname", author["surname"])

            if art.abstract:
                # jats:abstract is the canonical, but plain <abstract> is
                # accepted by CrossRef's 4.4.x schema
                _e(ja, "abstract", art.abstract)

            apd = _e(ja, "publication_date", attrib={"media_type": "print"})
            _e(apd, "month", _month_str(sc.month))
            _e(apd, "year", str(sc.year or datetime.now().year))

            pages_el = _e(ja, "pages")
            _e(pages_el, "first_page", str(art.start_page))
            _e(pages_el, "last_page", str(art.end_page))

            doi_data = _e(ja, "doi_data")
            _e(doi_data, "doi", art.doi)
            if art.resource_url:
                _e(doi_data, "resource", art.resource_url)

            if include_citations and citation_lookup is not None:
                refs = citation_lookup(art.filename) or []
                if refs:
                    cl = _e(ja, "citation_list")
                    for ref in refs:
                        cit = _e(cl, "citation",
                                 attrib={"key": ref.get("key", "")})
                        unstruct = ref.get("unstructured", "").strip()
                        if unstruct:
                            _e(cit, "unstructured_citation", unstruct)
                        ref_doi = ref.get("doi", "").strip()
                        if ref_doi:
                            _e(cit, "doi", ref_doi)

    ET.indent(root, space="  ")
    return ET.ElementTree(root)


def write_deposit(tree: ET.ElementTree, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(str(output_path),
               xml_declaration=True,
               encoding="UTF-8")


# Sanity helper used by the routes layer to surface what would be minted
def preview_dois(sidecars: list[IssueSidecar]) -> list[dict]:
    out: list[dict] = []
    for sc in sidecars:
        for art in sc.articles:
            out.append({
                "issue_slug": sc.issue_slug,
                "filename": art.filename,
                "title": art.title,
                "doi": art.doi,
                "pages": f"{art.start_page}-{art.end_page}",
            })
    return out


# DOI format check — matches CrossRef's expected shape but doesn't
# verify uniqueness (that requires a CrossRef API call).
_DOI_RE = re.compile(r"^10\.\d{4,9}/[A-Za-z0-9._\-/:;()<>]+$")


def doi_format_ok(doi: str) -> bool:
    return bool(_DOI_RE.match(doi or ""))
