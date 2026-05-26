"""Flask routes for the pipeline UI.

Mounted at /pipeline on the main Auditor app. Provides:
    GET  /pipeline                              dashboard (all journals)
    GET  /pipeline/<slug>                       per-journal stage view
    POST /pipeline/<slug>/run/<stage>           kick off a stage
    POST /pipeline/jobs/<job_id>/cancel         best-effort cancel
    GET  /pipeline/jobs/<job_id>                JSON status
    GET  /pipeline/jobs/<job_id>/stream         SSE log tail
    GET  /pipeline/<slug>/final                 serve the <slug>-final.xml
"""
from __future__ import annotations

import json
from pathlib import Path

from flask import (
    Blueprint, Response, abort, jsonify, redirect, render_template,
    request, send_file, url_for, stream_with_context, flash,
)

from . import discovery, jobs


bp = Blueprint("pipeline", __name__, url_prefix="/pipeline",
               template_folder="../templates/pipeline")


@bp.route("/")
def dashboard():
    journals = discovery.discover_journals()
    # Sort: finalized first, then by name
    journals.sort(key=lambda j: (not j.is_finalized, j.name))
    # Cross-journal totals across finalized XMLs
    totals = {
        "articles": sum(j.final_xml_articles for j in journals if j.is_finalized),
        "citations": sum(j.final_xml_citations for j in journals if j.is_finalized),
        "dois": sum(j.final_xml_dois for j in journals if j.is_finalized),
    }
    totals["doi_pct"] = (
        100.0 * totals["dois"] / totals["citations"] if totals["citations"] else 0.0
    )
    return render_template("pipeline/dashboard.html",
                           journals=journals, totals=totals)


@bp.route("/<slug>")
def journal_view(slug: str):
    j = discovery.find_journal(slug)
    if j is None:
        abort(404)
    # Latest job per stage
    last_jobs = {}
    for stage_key in jobs.STAGES.keys():
        last_jobs[stage_key] = jobs.latest_job(j.name, stage_key)
    recent = jobs.list_jobs(journal=j.name, limit=15)
    return render_template("pipeline/journal.html",
                           j=j, stages=jobs.STAGES,
                           last_jobs=last_jobs, recent=recent)


@bp.route("/<slug>/run/<stage>", methods=["POST"])
def run_stage(slug: str, stage: str):
    j = discovery.find_journal(slug)
    if j is None:
        abort(404)
    if stage not in jobs.STAGES:
        abort(400, description=f"Unknown stage: {stage}")
    extra = {}
    if stage == "enrich":
        email = (request.form.get("email") or "").strip()
        if email:
            extra["email"] = email
    try:
        job_id = jobs.start_job(j.name, stage, extra_args=extra or None)
    except RuntimeError as e:
        flash(str(e), "error")
        return redirect(url_for("pipeline.journal_view", slug=slug))
    return redirect(url_for("pipeline.journal_view", slug=slug) + f"#job-{job_id}")


@bp.route("/jobs/<int:job_id>/cancel", methods=["POST"])
def cancel(job_id: int):
    ok = jobs.cancel_job(job_id)
    if not ok:
        flash(f"Could not cancel job {job_id} (not running or already finished).",
              "warning")
    else:
        flash(f"Cancelled job {job_id}.", "info")
    job = jobs.get_job(job_id, reconcile=False)
    if job:
        # Find slug for redirect
        for jj in discovery.discover_journals():
            if jj.name == job["journal"]:
                return redirect(url_for("pipeline.journal_view", slug=jj.slug))
    return redirect(url_for("pipeline.dashboard"))


@bp.route("/jobs/<int:job_id>")
def job_status(job_id: int):
    job = jobs.get_job(job_id)
    if not job:
        abort(404)
    # Drop the cmd back to a list for the JSON
    if "cmd_json" in job:
        try:
            job["cmd"] = json.loads(job["cmd_json"])
        except Exception:
            job["cmd"] = []
    return jsonify(job)


@bp.route("/jobs/<int:job_id>/stream")
def job_stream(job_id: int):
    job = jobs.get_job(job_id, reconcile=False)
    if not job:
        abort(404)
    log_path = Path(job["log_path"])

    @stream_with_context
    def gen():
        # SSE preamble keeps proxies happy
        yield "retry: 1500\n\n"
        # Send any existing log content first, line by line
        buffer = ""
        for chunk in jobs.stream_log(log_path, follow=True,
                                     poll_interval=0.5,
                                     stop_after_idle=300.0):
            buffer += chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                # SSE: data lines, blank line terminator
                yield f"data: {line}\n\n"
            # Periodically re-check job status so we can close cleanly
            row = jobs.get_job(job_id, reconcile=True)
            if row and row["status"] in ("done", "failed", "cancelled"):
                if buffer:
                    yield f"data: {buffer}\n\n"
                    buffer = ""
                yield f"event: end\ndata: {row['status']}\n\n"
                return
        if buffer:
            yield f"data: {buffer}\n\n"
        yield "event: end\ndata: timeout\n\n"

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return Response(gen(), headers=headers)


@bp.route("/<slug>/final")
def serve_final(slug: str):
    j = discovery.find_journal(slug)
    if j is None or not j.is_finalized:
        abort(404)
    return send_file(
        str(j.final_xml),
        mimetype="application/xml",
        as_attachment=True,
        download_name=j.final_xml.name,
    )


def register(app) -> None:
    """Mount the pipeline blueprint on the given Flask app."""
    # Initialise the jobs DB table (idempotent)
    jobs.init_db()
    app.register_blueprint(bp)
