"""Crossref Auditor — Flask GUI for the deposit auditor.

Runs at http://localhost:5001 by default. Sibling tool to the per-journal
scrapers; consumes the same `<doi_batch>` XML they emit.
"""
from __future__ import annotations

import sys
from pathlib import Path

from flask import (
    Flask, abort, flash, jsonify, redirect, render_template,
    request, send_file, url_for,
)

import db
from auditor import audit
from auditor.core import detect_namespace
from auditor.models import AuditorConfig, RuleConfig
from auditor import rules as rules_pkg
from auditor.citation_types import detect_type
from auditor.rules._util import find_child, text_of
from cleanup import (
    propose_splits, match_citation, apply_decisions, count_changes,
    fix_duplicate_year, match_citation_with_fallback,
)
from exporters import EXPORTERS

import io
from lxml import etree as ET

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config" / "auditor_config.json"
UPLOAD_DIR = ROOT / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200 MB
app.secret_key = "crossref-auditor-local-only"


def _load_config() -> AuditorConfig:
    cfg = AuditorConfig.load(CONFIG_PATH)
    return cfg.merged_with_defaults(rules_pkg.all_rule_metas())


def _meta_dict(audit_row) -> dict:
    return {
        "id": audit_row["id"],
        "filename": audit_row["filename"],
        "file_size": audit_row["file_size"],
        "namespace": audit_row["namespace"],
        "citation_n": audit_row["citation_n"],
        "error_n": audit_row["error_n"],
        "warning_n": audit_row["warning_n"],
        "info_n": audit_row["info_n"],
        "created_at": audit_row["created_at"],
    }


@app.route("/")
def index():
    audits = db.list_audits(limit=25)
    return render_template("index.html", audits=audits)


@app.route("/audit", methods=["POST"])
def run_audit():
    file = request.files.get("xmlfile")
    if not file or not file.filename:
        flash("No file selected.", "error")
        return redirect(url_for("index"))

    raw = file.read()
    if not raw:
        flash("Uploaded file is empty.", "error")
        return redirect(url_for("index"))

    cfg = _load_config()
    findings = audit(raw, cfg)

    # Determine namespace and citation count for display
    try:
        root = ET.fromstring(raw)
        ns = detect_namespace(root)
        citation_tag = f"{{{ns}}}citation" if ns else "citation"
        n_citations = sum(
            1 for _ in ET.iterparse(io.BytesIO(raw), events=("end",), tag=citation_tag)
        )
    except ET.XMLSyntaxError:
        ns = None
        n_citations = 0

    audit_id = db.insert_audit(
        filename=file.filename,
        file_size=len(raw),
        namespace=ns,
        citation_n=n_citations,
        findings=findings,
        config_dict=cfg.to_dict(),
    )

    # Persist the uploaded XML so cleanup can read it back later
    upload_path = UPLOAD_DIR / f"audit_{audit_id}.xml"
    tmp = upload_path.with_suffix(upload_path.suffix + ".part")
    tmp.write_bytes(raw)
    tmp.replace(upload_path)
    db.set_audit_xml_path(audit_id, str(upload_path))

    return redirect(url_for("report", audit_id=audit_id))


@app.route("/report/<int:audit_id>")
def report(audit_id: int):
    row = db.get_audit(audit_id)
    if row is None:
        abort(404)
    findings = db.get_findings(audit_id)
    severity_filter = request.args.get("severity")
    rule_filter = request.args.get("rule")
    filtered = [
        f for f in findings
        if (not severity_filter or f.severity == severity_filter)
        and (not rule_filter or f.rule_id == rule_filter)
    ]
    rules_present = sorted({f.rule_id for f in findings})
    return render_template(
        "report.html",
        meta=_meta_dict(row),
        findings=filtered,
        all_count=len(findings),
        rules_present=rules_present,
        severity_filter=severity_filter,
        rule_filter=rule_filter,
    )


@app.route("/export/<int:audit_id>/<fmt>")
def export(audit_id: int, fmt: str):
    if fmt not in EXPORTERS:
        abort(404)
    row = db.get_audit(audit_id)
    if row is None:
        abort(404)
    findings = db.get_findings(audit_id)
    fn, mime, ext = EXPORTERS[fmt]
    data = fn(_meta_dict(row), findings)

    base = Path(row["filename"]).stem or "audit"
    download_name = f"{base}.audit-{audit_id}.{ext}"
    return send_file(
        io.BytesIO(data),
        mimetype=mime,
        as_attachment=True,
        download_name=download_name,
    )


@app.route("/history/<int:audit_id>/delete", methods=["POST"])
def delete_audit(audit_id: int):
    db.delete_audit(audit_id)
    flash(f"Deleted audit #{audit_id}.", "ok")
    return redirect(url_for("index"))


# ---------- Cleanup routes ----------

def _load_citation_index(xml_path: Path) -> dict[int, tuple[str | None, str | None, str | None]]:
    """Parse the deposit XML ONCE and return a mapping
    {citation_source_line: (citation_key, unstructured_text, parent_doi)}.

    parent_doi is the <doi> child of the enclosing <doi_citations> block
    (one article's worth of references), used to drive the per-article
    filter on the cleanup page.

    Cleanup views need the text for every flagged citation; calling this
    once and looking up O(1) per card avoids re-parsing the whole tree
    per card (which was O(N**2) and timed out on 1k+ card cleanups).
    """
    parser = ET.XMLParser(remove_blank_text=False)
    tree = ET.parse(str(xml_path), parser)
    index: dict[int, tuple[str | None, str | None, str | None]] = {}
    for elem in tree.getroot().iter():
        if elem.tag.rsplit("}", 1)[-1] != "citation":
            continue
        uc = find_child(elem, "unstructured_citation")
        text = text_of(uc) if uc is not None else None
        line = elem.sourceline
        if line is None:
            continue
        # Walk up to find the <doi_citations> ancestor and its <doi> child.
        parent_doi: str | None = None
        a = elem.getparent()
        while a is not None:
            if a.tag.rsplit("}", 1)[-1] == "doi_citations":
                doi_el = find_child(a, "doi")
                if doi_el is not None:
                    parent_doi = text_of(doi_el).strip() or None
                break
            a = a.getparent()
        index[line] = (elem.get("key"), text, parent_doi)
    return index


@app.route("/cleanup/<int:audit_id>")
def cleanup(audit_id: int):
    row = db.get_audit(audit_id)
    if row is None:
        abort(404)
    if not row["xml_path"] or not Path(row["xml_path"]).exists():
        flash("Original XML for this audit isn't available — re-upload to enable cleanup.", "error")
        return redirect(url_for("report", audit_id=audit_id))

    # Pull warnings from rules that flag glued/garbage/footer-bleed citations
    cleanup_rule_ids = {
        "unstructured_length",
        "paragraph_shaped",
        "repeat_author_marker",
        "journal_footer_suffix",
        "duplicate_year_tokens",
        "footnote_artifact",
        "notes_section_appended",
        "embedded_doi",
        "ligature_artifacts",
        "stuck_whitespace",
    }
    findings = [f for f in db.get_findings(audit_id) if f.rule_id in cleanup_rule_ids]

    # De-duplicate by citation_line so each citation appears once even if it
    # tripped multiple sub-checks
    by_line: dict[int, list] = {}
    for f in findings:
        if f.line:
            by_line.setdefault(f.line, []).append(f)

    decisions = db.get_cleanup_decisions(audit_id)

    # Pull each citation's full text and propose splits (cheap; no Crossref yet)
    xml_path = Path(row["xml_path"])
    citation_index = _load_citation_index(xml_path)  # parse once, O(1) per card
    cards: list[dict] = []
    parent_dois: list[str] = []
    for line in sorted(by_line.keys()):
        info = citation_index.get(line)
        if info is None:
            continue
        key, full_text, parent_doi = info
        if full_text is None:
            continue
        proposed = propose_splits(full_text)
        decision = decisions.get(line)
        rule_ids = sorted({f.rule_id for f in by_line[line]})
        cite_type = detect_type(full_text)
        if parent_doi and parent_doi not in parent_dois:
            parent_dois.append(parent_doi)
        cards.append({
            "line": line,
            "citation_key": key,
            "full_text": full_text,
            "messages": [f.message for f in by_line[line]],
            "rule_ids": rule_ids,
            "proposed_splits": proposed,
            "decision": decision,
            "citation_type": cite_type,
            "parent_doi": parent_doi,
        })

    summary = count_changes(decisions)
    summary["pending"] = len(cards) - len(decisions)
    return render_template(
        "cleanup.html",
        meta=_meta_dict(row),
        cards=cards,
        summary=summary,
        parent_dois=parent_dois,
    )


@app.route("/cleanup/<int:audit_id>/match", methods=["POST"])
def cleanup_match(audit_id: int):
    """AJAX: fetch a citation match. Queries Crossref first; if confidence
    is low or no result, falls back to OpenAlex. The response's `source`
    field indicates which backend produced the match."""
    payload = request.json or {}
    text = payload.get("text", "")
    if not text.strip():
        return jsonify({"error": "empty text"}), 400
    threshold = float(payload.get("min_score") or 50)
    result = match_citation_with_fallback(text, min_score=threshold)
    return jsonify(result or {"empty": True})


@app.route("/cleanup/<int:audit_id>/fix_duplicate_year", methods=["POST"])
def cleanup_fix_duplicate_year(audit_id: int):
    """AJAX: try to auto-resolve a duplicate-year citation against Crossref.
    Returns {'fixed': '<corrected text>', 'match': {...}, 'kept_year': '<y>',
    'dropped_year': '<y>'} on success; {'fixed': null, 'reason': '...'} when
    confidence is too low or Crossref disagrees with both candidates.
    """
    payload = request.json or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return jsonify({"error": "empty text"}), 400
    threshold = float(payload.get("min_score") or 50)
    fallback = payload.get("fallback") or "keep_second"
    if fallback not in ("keep_second", "keep_first", "crossref_only"):
        fallback = "keep_second"
    result = fix_duplicate_year(text, min_score=threshold, fallback=fallback)
    if result is None:
        return jsonify({"fixed": None, "reason": "no duplicate-year pattern (or crossref_only mode and no match)"})
    return jsonify(result)


@app.route("/cleanup/<int:audit_id>/decision", methods=["POST"])
def cleanup_decision(audit_id: int):
    """AJAX: save one decision."""
    payload = request.json or {}
    line = int(payload.get("line", 0))
    if line <= 0:
        return jsonify({"error": "missing line"}), 400
    decided_by = payload.get("decided_by") or "manual"
    db.upsert_cleanup_decision(
        audit_id=audit_id,
        citation_line=line,
        citation_key=payload.get("citation_key"),
        action=payload.get("action", "keep"),
        split_chunks=payload.get("split_chunks"),
        crossref_data=payload.get("crossref_data"),
        notes=decided_by,  # store 'auto' or 'manual' in notes
    )
    return jsonify({"ok": True})


@app.route("/cleanup/<int:audit_id>/download")
def cleanup_download(audit_id: int):
    row = db.get_audit(audit_id)
    if row is None or not row["xml_path"]:
        abort(404)
    decisions = db.get_cleanup_decisions(audit_id)
    src = Path(row["xml_path"])
    out = UPLOAD_DIR / f"audit_{audit_id}.cleaned.xml"
    counts = apply_decisions(src, decisions, out)
    base = Path(row["filename"]).stem or "deposit"
    return send_file(
        out,
        mimetype="application/xml",
        as_attachment=True,
        download_name=f"{base}.cleaned.xml",
    )


@app.route("/iterate/<int:audit_id>", methods=["POST"])
def iterate_to_convergence(audit_id: int):
    """Run the audit -> auto-decide -> download -> audit loop until
    findings stop dropping (or max_iters is reached). Returns the final
    audit ID and the per-iteration finding counts so the user can see
    the convergence trajectory.

    The auto-decide logic mirrors what the cleanup page's JS does, but
    runs server-side so a single click can chain multiple iterations.
    """
    from auditor.rules._util import find_child as _find_child, text_of as _text_of
    from auditor.citation_types import detect_type as _detect_type
    from cleanup import fix_duplicate_year as _fix_dup
    from cleanup.splitter import propose_splits as _propose

    payload = request.json or {}
    max_iters = int(payload.get("max_iters") or 5)
    min_score = float(payload.get("min_score") or 50)
    year_fallback = payload.get("year_fallback") or "keep_second"

    history = []
    current = audit_id
    last_count = None

    for it in range(max_iters):
        row = db.get_audit(current)
        if row is None or not row["xml_path"]:
            return jsonify({"error": f"audit #{current} has no saved XML"}), 400
        findings = db.get_findings(current)
        history.append({"iter": it, "audit_id": current, "findings": len(findings)})

        # Convergence check: if findings haven't dropped since last iter, stop.
        if last_count is not None and len(findings) >= last_count:
            break
        last_count = len(findings)

        # Apply all auto-decide passes server-side.
        xml_path = Path(row["xml_path"])
        tree = ET.parse(str(xml_path))
        by_line = {e.sourceline: e for e in tree.getroot().iter()
                   if e.tag.rsplit("}", 1)[-1] == "citation"}
        rules_by_line: dict[int, set[str]] = {}
        keys_by_line: dict[int, str | None] = {}
        for f in findings:
            if f.line:
                rules_by_line.setdefault(f.line, set()).add(f.rule_id)
                keys_by_line[f.line] = f.citation_key

        for line, rules in rules_by_line.items():
            elem = by_line.get(line)
            if elem is None:
                continue
            uc = _find_child(elem, "unstructured_citation")
            if uc is None:
                continue
            citation_text = _text_of(uc)

            action = None
            chunks = None
            notes = ""
            if "paragraph_shaped" in rules or "footnote_artifact" in rules:
                action = "delete"
                why = "footnote_artifact" if "footnote_artifact" in rules else "paragraph_shaped"
                notes = f"auto-deleted ({why})"
            elif "duplicate_year_tokens" in rules:
                r = _fix_dup(citation_text, min_score=min_score, fallback=year_fallback)
                if r:
                    action = "split"
                    chunks = [r["fixed"]]
                    notes = f"auto-fixed duplicate years ({r['method']})"
            elif "journal_footer_suffix" in rules or "notes_section_appended" in rules:
                proposed = _propose(citation_text)
                if proposed:
                    action = "split"
                    chunks = proposed
                    why = "notes_section_appended" if "notes_section_appended" in rules else "journal_footer_suffix"
                    notes = f"auto-stripped ({why})"
            elif _detect_type(citation_text):
                action = "keep"
                notes = f"auto-kept ({_detect_type(citation_text)})"

            if action:
                db.upsert_cleanup_decision(
                    audit_id=current,
                    citation_line=line,
                    citation_key=keys_by_line.get(line),
                    action=action,
                    split_chunks=chunks,
                    crossref_data=None,
                    notes=notes,
                )

        # Generate cleaned XML and audit it.
        decisions = db.get_cleanup_decisions(current)
        out_path = UPLOAD_DIR / f"audit_{current}.cleaned.xml"
        apply_decisions(Path(row["xml_path"]), decisions, out_path)

        with open(out_path, "rb") as f:
            cleaned_bytes = f.read()
        cfg = _load_config()
        new_findings = audit(cleaned_bytes, cfg)
        try:
            new_root = ET.fromstring(cleaned_bytes)
            ns = detect_namespace(new_root)
            citation_tag = f"{{{ns}}}citation" if ns else "citation"
            n_cites = sum(1 for _ in ET.iterparse(io.BytesIO(cleaned_bytes), events=("end",), tag=citation_tag))
        except ET.XMLSyntaxError:
            ns = None
            n_cites = 0

        new_id = db.insert_audit(
            filename=f"{Path(row['filename']).stem}.cleaned.iter{it+1}.xml",
            file_size=len(cleaned_bytes),
            namespace=ns,
            citation_n=n_cites,
            findings=new_findings,
            config_dict=cfg.to_dict(),
        )
        save_path = UPLOAD_DIR / f"audit_{new_id}.xml"
        save_path.write_bytes(cleaned_bytes)
        db.set_audit_xml_path(new_id, str(save_path))
        current = new_id

    # Always report the actual finding count of the final audit (not the
    # last_count captured before the last iteration's auto-decide).
    final_findings = db.get_findings(current)
    history.append({"iter": "final", "audit_id": current,
                    "findings": len(final_findings)})
    return jsonify({"final_audit_id": current, "history": history,
                    "iterations": len(history) - 1})


@app.route("/dryrun/<int:audit_id>", methods=["POST"])
def dryrun_submit(audit_id: int):
    """Submit the cleaned XML to Crossref's TEST endpoint to surface any
    business-rule rejections that XSD validation alone won't catch.

    Requires the user to have a Crossref test account; credentials are
    posted with the request body and never stored. Returns Crossref's
    raw response (as text) plus the HTTP status code.
    """
    payload = request.json or {}
    username = (payload.get("username") or "").strip()
    password = (payload.get("password") or "").strip()
    if not username or not password:
        return jsonify({
            "error": "Crossref test credentials required",
            "help": (
                "Create a free test account at https://test.crossref.org/ — "
                "credentials are posted per-request and never stored on disk."
            ),
        }), 400

    row = db.get_audit(audit_id)
    if row is None or not row["xml_path"]:
        abort(404)
    src = Path(row["xml_path"])

    # If decisions exist, submit the cleaned version; otherwise the raw upload.
    decisions = db.get_cleanup_decisions(audit_id)
    if decisions:
        cleaned = UPLOAD_DIR / f"audit_{audit_id}.cleaned.xml"
        apply_decisions(src, decisions, cleaned)
        submit_path = cleaned
    else:
        submit_path = src

    import requests as _requests
    try:
        with open(submit_path, "rb") as fh:
            r = _requests.post(
                "https://test.crossref.org/servlet/deposit",
                data={
                    "operation": "doMDUpload",
                    "login_id": username,
                    "login_passwd": password,
                },
                files={"fname": (submit_path.name, fh, "application/xml")},
                timeout=60,
            )
        return jsonify({
            "status_code": r.status_code,
            "ok": r.ok,
            "response": r.text[:5000],
            "submit_url": "https://test.crossref.org/servlet/deposit",
        })
    except _requests.RequestException as e:
        return jsonify({"error": f"submission failed: {e}"}), 500


@app.route("/settings", methods=["GET", "POST"])
def settings():
    metas = sorted(rules_pkg.all_rule_metas(), key=lambda m: (m.scope, m.id))
    if request.method == "POST":
        new_rules: dict[str, RuleConfig] = {}
        for meta in metas:
            enabled = request.form.get(f"{meta.id}__enabled") == "on"
            severity = request.form.get(f"{meta.id}__severity", meta.default_severity.value)
            params: dict = {}
            for p in meta.params:
                key = f"{meta.id}__param__{p.name}"
                raw = request.form.get(key)
                if raw is None or raw == "":
                    params[p.name] = p.default
                    continue
                try:
                    if p.type == "int":
                        params[p.name] = int(raw)
                    elif p.type == "float":
                        params[p.name] = float(raw)
                    elif p.type == "bool":
                        params[p.name] = raw.lower() in ("1", "true", "yes", "on")
                    else:
                        params[p.name] = raw
                except ValueError:
                    params[p.name] = p.default
            new_rules[meta.id] = RuleConfig(enabled=enabled, severity=severity, params=params)
        AuditorConfig(rules=new_rules).save(CONFIG_PATH)
        flash("Settings saved.", "ok")
        return redirect(url_for("settings"))

    cfg = _load_config()
    return render_template("settings.html", metas=metas, cfg=cfg)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    db.init_db()
    app.run(host="127.0.0.1", port=5001, debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
