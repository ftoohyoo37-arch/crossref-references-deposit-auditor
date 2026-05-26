"""Flask routes for the DOI-minting workflow.

Mounted at /mint on the Auditor app. Provides:
    GET  /mint                                    minting dashboard (per journal)
    GET  /mint/<slug>                             journal minting view (issue list)
    GET  /mint/<slug>/issue/<issue_slug>          edit/review one issue's sidecar
    POST /mint/<slug>/issue/<issue_slug>/save     save sidecar (article boundaries + metadata)
    POST /mint/<slug>/issue/<issue_slug>/infer    auto-populate from ToC heuristics
    POST /mint/<slug>/issue/<issue_slug>/split    split issue PDF into per-article PDFs
    POST /mint/<slug>/build                       generate the content-registration XML
    GET  /mint/<slug>/deposit.xml                 download the generated deposit XML
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from flask import (
    Blueprint, abort, flash, redirect, render_template, request,
    send_file, url_for,
)

from pipeline import discovery
from . import state, splitter, toc_extractor, deposit_builder
from .models import Article, IssueSidecar


bp = Blueprint("mint", __name__, url_prefix="/mint",
               template_folder="../templates/mint")


# ----------------------- helpers --------------------------------------

def _resolve_journal(slug: str):
    j = discovery.find_journal(slug)
    if j is None:
        abort(404)
    return j


def _depositor_info(journal_dir: Path) -> dict:
    """Read <Journal>/depositor.json (or fall back to empty dict)."""
    dep_path = journal_dir / "depositor.json"
    if not dep_path.exists():
        return {}
    try:
        return json.loads(dep_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_journal_meta(journal_dir: Path) -> dict:
    """Pull JOURNAL_NAME, JOURNAL_SLUG, BATCH_ID_PREFIX, DOI_TEMPLATE,
    DOI_PREFIX from journal.py via importlib.
    """
    import importlib.util, sys
    mod_path = journal_dir / "journal.py"
    if not mod_path.is_file():
        return {}
    spec = importlib.util.spec_from_file_location(
        f"_mint_journal_{journal_dir.name.replace(' ', '_')}",
        mod_path,
    )
    if spec is None or spec.loader is None:
        return {}
    mod = importlib.util.module_from_spec(spec)
    # Make the journal dir importable in case journal.py imports siblings
    if str(journal_dir) not in sys.path:
        sys.path.insert(0, str(journal_dir))
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return {}
    return {
        "name": getattr(mod, "JOURNAL_NAME", ""),
        "slug": getattr(mod, "JOURNAL_SLUG", ""),
        "batch_prefix": getattr(mod, "BATCH_ID_PREFIX", ""),
        "doi_template": getattr(mod, "DOI_TEMPLATE",
                                 "{prefix}/{slug}.{year}.{vol}.{iss}.{seq:02d}"),
        "doi_prefix": getattr(mod, "DOI_PREFIX", ""),
        "issn": getattr(mod, "ISSN", ""),
        "resource_base_url": getattr(mod, "RESOURCE_BASE_URL", ""),
    }


# ----------------------- routes ---------------------------------------

@bp.route("/")
def dashboard():
    """Minting dashboard — list every journal with issue_pdfs/ present."""
    journals = []
    for j in discovery.discover_journals():
        summary = state.journal_minting_summary(j.dir)
        if summary["issue_count"] == 0:
            continue
        journals.append({"j": j, "summary": summary})
    return render_template("mint/dashboard.html", journals=journals)


@bp.route("/<slug>")
def journal_view(slug: str):
    j = _resolve_journal(slug)
    issues = state.list_issues(j.dir)
    meta = _read_journal_meta(j.dir)
    return render_template("mint/journal.html",
                           j=j, issues=issues, meta=meta)


@bp.route("/<slug>/issue/<issue_slug>")
def issue_view(slug: str, issue_slug: str):
    j = _resolve_journal(slug)
    issue = state.find_issue(j.dir, issue_slug)
    if issue is None:
        abort(404)
    # Get page count from the PDF for boundary validation
    from pypdf import PdfReader
    try:
        page_count = len(PdfReader(str(issue.issue_pdf)).pages)
    except Exception:
        page_count = 0

    if issue.sidecar is None:
        issue.sidecar = IssueSidecar.new_for(issue.issue_pdf)
    meta = _read_journal_meta(j.dir)
    return render_template("mint/issue.html",
                           j=j, issue=issue, sidecar=issue.sidecar,
                           page_count=page_count, meta=meta)


@bp.route("/<slug>/issue/<issue_slug>/infer", methods=["POST"])
def issue_infer(slug: str, issue_slug: str):
    """Auto-populate the sidecar from PDF outline / ToC text scrape."""
    j = _resolve_journal(slug)
    issue = state.find_issue(j.dir, issue_slug)
    if issue is None:
        abort(404)
    sidecar = issue.sidecar or IssueSidecar.new_for(issue.issue_pdf)
    if sidecar.articles:
        flash("Sidecar already has articles — clear them before re-inferring.",
              "warning")
    else:
        source = toc_extractor.populate_sidecar(sidecar, issue.issue_pdf)
        if sidecar.articles:
            sidecar.save(issue.sidecar_path)
            flash(f"Found {len(sidecar.articles)} candidate article(s) via "
                  f"{source}.", "info")
        else:
            flash(f"Auto-inference found nothing (source: {source}). "
                  f"Enter article boundaries manually below.", "warning")
    return redirect(url_for("mint.issue_view", slug=slug, issue_slug=issue_slug))


@bp.route("/<slug>/issue/<issue_slug>/save", methods=["POST"])
def issue_save(slug: str, issue_slug: str):
    j = _resolve_journal(slug)
    issue = state.find_issue(j.dir, issue_slug)
    if issue is None:
        abort(404)
    sidecar = issue.sidecar or IssueSidecar.new_for(issue.issue_pdf)
    # Top-level issue metadata
    sidecar.volume = int(request.form.get("volume", 0) or 0)
    sidecar.issue = int(request.form.get("issue", 0) or 0)
    sidecar.year = int(request.form.get("year", 0) or 0)
    sidecar.month = int(request.form.get("month", 0) or 0)
    sidecar.issue_title = (request.form.get("issue_title") or "").strip()

    # Articles — form arrays are name="articles-<n>-<field>"
    rows = _parse_article_rows(request.form)
    rows.sort(key=lambda a: a.start_page or 0)
    for i, art in enumerate(rows):
        art.sequence = i + 1
    sidecar.articles = rows
    sidecar.save(issue.sidecar_path)
    flash(f"Saved {len(rows)} article(s).", "info")
    return redirect(url_for("mint.issue_view", slug=slug, issue_slug=issue_slug))


@bp.route("/<slug>/issue/<issue_slug>/split", methods=["POST"])
def issue_split_route(slug: str, issue_slug: str):
    j = _resolve_journal(slug)
    issue = state.find_issue(j.dir, issue_slug)
    if issue is None or issue.sidecar is None:
        flash("Save the sidecar before splitting.", "error")
        return redirect(url_for("mint.issue_view", slug=slug, issue_slug=issue_slug))
    output_dir = j.dir / "pdfs" / issue.slug
    overwrite = bool(request.form.get("overwrite"))
    try:
        result = splitter.split_issue(issue.issue_pdf, issue.sidecar,
                                       output_dir, overwrite=overwrite)
    except splitter.SplitError as e:
        flash(f"Split failed: {e}", "error")
        return redirect(url_for("mint.issue_view", slug=slug, issue_slug=issue_slug))
    flash(f"Wrote {len(result['written'])} per-article PDF(s) to "
          f"{output_dir.name}/ "
          f"({len(result['skipped'])} skipped, page_count={result['page_count']}).",
          "info")
    return redirect(url_for("mint.issue_view", slug=slug, issue_slug=issue_slug))


@bp.route("/<slug>/build", methods=["POST"])
def build_deposit_route(slug: str):
    j = _resolve_journal(slug)
    meta = _read_journal_meta(j.dir)
    depositor = _depositor_info(j.dir)

    doi_prefix = (request.form.get("doi_prefix")
                  or meta.get("doi_prefix")
                  or "").strip()
    doi_template = (request.form.get("doi_template")
                    or meta.get("doi_template")
                    or "{prefix}/{slug}.{year}.{vol}.{iss}.{seq:02d}").strip()
    issn = (request.form.get("issn") or meta.get("issn", "")).strip()
    full_title = (request.form.get("journal_full_title")
                  or meta.get("name", j.name)).strip()
    resource_base = (request.form.get("resource_base_url")
                     or meta.get("resource_base_url", "")).strip()
    include_citations = bool(request.form.get("include_citations"))
    selected_slugs = request.form.getlist("include_issue")

    if not doi_prefix:
        flash("Need a CrossRef DOI prefix to mint DOIs. "
              "Set DOI_PREFIX in journal.py or fill the field above.", "error")
        return redirect(url_for("mint.journal_view", slug=slug))

    sidecars: list[IssueSidecar] = []
    for issue in state.list_issues(j.dir):
        if selected_slugs and issue.slug not in selected_slugs:
            continue
        if issue.sidecar is None or not issue.sidecar.articles:
            continue
        deposit_builder.assign_dois(
            issue.sidecar,
            doi_prefix=doi_prefix,
            journal_slug=meta.get("slug") or j.slug,
            doi_template=doi_template,
            resource_base_url=resource_base,
        )
        # Persist the assigned DOIs back to the sidecar
        issue.sidecar.save(issue.sidecar_path)
        # Also update the per-issue doi-map.json so the downstream
        # extraction pipeline knows which DOI to attribute references to
        _update_doi_map(j.dir / "pdfs" / issue.slug, issue.sidecar)
        sidecars.append(issue.sidecar)

    if not sidecars:
        flash("No issues with saved article boundaries to mint.", "error")
        return redirect(url_for("mint.journal_view", slug=slug))

    tree = deposit_builder.build_deposit(
        sidecars,
        journal_full_title=full_title,
        issn=issn,
        depositor_name=depositor.get("depositor_name", j.name),
        depositor_email=depositor.get("email_address", "deposits@example.org"),
        include_citations=include_citations,
    )
    out_path = j.dir / "output" / (
        f"{meta.get('batch_prefix', j.slug)}"
        f"-content-registration-"
        f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.xml"
    )
    deposit_builder.write_deposit(tree, out_path)
    flash(f"Generated {out_path.name} "
          f"({sum(len(s.articles) for s in sidecars)} article(s) across "
          f"{len(sidecars)} issue(s)).", "info")
    return redirect(url_for("mint.journal_view", slug=slug) + "#latest-deposit")


@bp.route("/<slug>/deposit/<path:filename>")
def serve_deposit(slug: str, filename: str):
    j = _resolve_journal(slug)
    target = j.dir / "output" / filename
    if not target.exists():
        abort(404)
    return send_file(str(target),
                     mimetype="application/xml",
                     as_attachment=True,
                     download_name=target.name)


# ----------------------- internals ------------------------------------

_ARTICLE_FIELD = re.compile(r"^articles-(\d+)-(\w+)$")


def _parse_article_rows(form) -> list[Article]:
    """Form has names like articles-0-start_page, articles-0-title etc.

    Author fields are articles-<i>-author-<j>-given / -surname.
    """
    rows: dict[int, dict] = {}
    author_rows: dict[int, dict[int, dict]] = {}
    for key in form.keys():
        m = _ARTICLE_FIELD.match(key)
        if not m:
            # Also handle author sub-rows
            am = re.match(r"^articles-(\d+)-author-(\d+)-(given|surname)$", key)
            if am:
                ai, aj, field = int(am.group(1)), int(am.group(2)), am.group(3)
                author_rows.setdefault(ai, {}).setdefault(aj, {})[field] = (
                    form.get(key, "").strip()
                )
            continue
        idx, field = int(m.group(1)), m.group(2)
        rows.setdefault(idx, {})[field] = form.get(key, "").strip()

    out: list[Article] = []
    for idx in sorted(rows.keys()):
        r = rows[idx]
        if not r.get("title") and not r.get("filename"):
            continue   # blank row
        try:
            start = int(r.get("start_page") or 0)
            end = int(r.get("end_page") or 0)
        except ValueError:
            start = end = 0
        authors = []
        for aj in sorted(author_rows.get(idx, {}).keys()):
            a = author_rows[idx][aj]
            if a.get("given") or a.get("surname"):
                authors.append({
                    "given": a.get("given", ""),
                    "surname": a.get("surname", ""),
                })
        out.append(Article(
            start_page=start, end_page=end,
            filename=r.get("filename", ""),
            title=r.get("title", ""),
            authors=authors,
        ))
    return out


def _update_doi_map(pdfs_dir: Path, sidecar: IssueSidecar) -> None:
    """Sync doi-map.json with the newly assigned DOIs."""
    if not pdfs_dir.is_dir():
        return
    doi_map_path = pdfs_dir / "doi-map.json"
    existing: dict = {}
    if doi_map_path.exists():
        try:
            existing = json.loads(doi_map_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    for art in sidecar.articles:
        if art.filename and art.doi:
            existing[art.filename] = art.doi
    doi_map_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def register(app) -> None:
    """Mount the minting blueprint on the given Flask app."""
    app.register_blueprint(bp)
