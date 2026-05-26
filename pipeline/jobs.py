"""Background job runner for pipeline stages.

Each stage (extract, enrich, recapture, audit-to-final) is fired as a
detached subprocess whose stdout/stderr is captured to a log file. Job
metadata + status lives in a `pipeline_jobs` table inside the existing
audits.db.

State machine: pending → running → done | failed | cancelled

The Flask process itself never blocks on a job — it just spawns and
returns. Job status is reconciled lazily on next inspection: if the row
says 'running' but the PID is dead, we update it.
"""
from __future__ import annotations

import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .discovery import PROJECT_ROOT


_AUDITOR_DIR = Path(__file__).resolve().parent.parent
DB_PATH = _AUDITOR_DIR / "audits.db"
LOG_DIR = _AUDITOR_DIR / "pipeline_logs"
LOG_DIR.mkdir(exist_ok=True)


SCHEMA = """
CREATE TABLE IF NOT EXISTS pipeline_jobs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    journal       TEXT NOT NULL,            -- journal name
    stage         TEXT NOT NULL,            -- 'extract' | 'enrich' | 'recapture' | 'audit_to_final'
    status        TEXT NOT NULL,            -- 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
    pid           INTEGER,
    cmd_json      TEXT NOT NULL,            -- JSON list[str], the argv
    log_path      TEXT NOT NULL,
    started_at    TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at   TEXT,
    exit_code     INTEGER
);
CREATE INDEX IF NOT EXISTS idx_pipeline_jobs_journal ON pipeline_jobs(journal);
CREATE INDEX IF NOT EXISTS idx_pipeline_jobs_status ON pipeline_jobs(status);
"""


# Map of stage_key -> human label + how to build the command line.
# The command builders receive the journal name and return a list[str]
# suitable for subprocess.Popen.
def _cmd_extract(journal_name: str) -> list[str]:
    return [sys.executable, "-u", "-m", "_shared._run_full_batch", journal_name]


def _cmd_recapture(journal_name: str) -> list[str]:
    return [sys.executable, "-u", "-m", "_shared._phase6_7_recapture", journal_name]


def _cmd_audit_to_final(journal_name: str) -> list[str]:
    return [sys.executable, "-u", "-m", "_shared._audit_to_final", journal_name]


def _cmd_enrich(journal_name: str, email: str = "deposits@example.org") -> list[str]:
    enricher = PROJECT_ROOT / journal_name / "Structured Scraper" / "enricher.py"
    if not enricher.exists():
        raise RuntimeError(f"No enricher.py at {enricher}")
    return [sys.executable, "-u", str(enricher), "--email", email]


# Working directory for each stage's subprocess
def _cwd_for(stage: str, journal_name: str) -> Path:
    if stage == "enrich":
        return PROJECT_ROOT / journal_name / "Structured Scraper"
    return PROJECT_ROOT


STAGES = {
    "extract": {
        "label": "Re-extract references",
        "blurb": "Run _run_full_batch on every volume/issue. Output: <Journal>/output/<batch>.xml",
        "cmd": _cmd_extract,
    },
    "recapture": {
        "label": "Full recapture (archive + re-extract + per-article max merge + enrich)",
        "blurb": "Phase-6.7 driver: archives the current outputs, re-extracts everything, "
                 "merges per-DOI maxes against the archive, re-enriches.",
        "cmd": _cmd_recapture,
    },
    "enrich": {
        "label": "Re-enrich (CrossRef DOI lookup only)",
        "blurb": "Run the journal's enricher.py against current output/. "
                 "Adds inline <doi> elements on confident matches.",
        "cmd": _cmd_enrich,
    },
    "audit_to_final": {
        "label": "Audit → final deposit XML",
        "blurb": "Upload every enriched XML to the Auditor, run safe auto-decide "
                 "(DOI-preserving), merge into <journal>-final.xml at the project root.",
        "cmd": _cmd_audit_to_final,
    },
}


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
        c.executescript(SCHEMA)


def _reconcile_status(row: sqlite3.Row) -> dict:
    """If a 'running' row's PID is no longer alive, mark it terminated.

    Returns the row as a dict, possibly with status updated.
    """
    d = dict(row)
    if d["status"] != "running" or not d["pid"]:
        return d
    if not _pid_alive(d["pid"]):
        # Process gone. Determine final status from log tail if possible.
        exit_code = _extract_exit_code(Path(d["log_path"]))
        new_status = "done" if exit_code == 0 else "failed"
        with _conn() as c:
            c.execute(
                "UPDATE pipeline_jobs SET status=?, finished_at=datetime('now'), "
                "exit_code=? WHERE id=?",
                (new_status, exit_code, d["id"]),
            )
        d["status"] = new_status
        d["exit_code"] = exit_code
        d["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return d


def _pid_alive(pid: int) -> bool:
    """OS-portable check for whether a PID is still alive."""
    if not pid:
        return False
    if sys.platform == "win32":
        # Use tasklist; expensive but rarely called
        try:
            out = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                stderr=subprocess.DEVNULL, text=True, timeout=5,
            )
            return str(pid) in out
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _extract_exit_code(log_path: Path) -> int:
    """No reliable way to recover an exit code after the fact on Windows,
    so default to 0 if the log appears clean; -1 if a Python traceback is
    visible in the last 200 lines.
    """
    if not log_path.exists():
        return -1
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return -1
    tail = "\n".join(text.splitlines()[-200:])
    if "Traceback (most recent call last)" in tail:
        return 1
    if "FAILED" in tail or "!! " in tail:
        return 1
    return 0


def start_job(journal_name: str, stage: str, extra_args: dict | None = None) -> int:
    """Spawn a job. Returns the new job_id.

    Raises ValueError if the stage is unknown.
    Raises RuntimeError if a job for this (journal, stage) is already running.
    """
    if stage not in STAGES:
        raise ValueError(f"Unknown stage: {stage}")
    init_db()

    # Block concurrent runs of the same (journal, stage)
    with _conn() as c:
        running = c.execute(
            "SELECT id, pid FROM pipeline_jobs WHERE journal=? AND stage=? AND status='running'",
            (journal_name, stage),
        ).fetchall()
        for row in running:
            if _pid_alive(row["pid"]):
                raise RuntimeError(
                    f"A '{stage}' job for {journal_name} is already running "
                    f"(job_id={row['id']}, pid={row['pid']})."
                )
            # Stale — mark failed and continue
            c.execute(
                "UPDATE pipeline_jobs SET status='failed', finished_at=datetime('now'), "
                "exit_code=-1 WHERE id=?",
                (row["id"],),
            )

    # Build command line
    builder = STAGES[stage]["cmd"]
    if stage == "enrich":
        email = (extra_args or {}).get("email") or "deposits@example.org"
        cmd = builder(journal_name, email)
    else:
        cmd = builder(journal_name)

    # Create log path
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_journal = "".join(ch if ch.isalnum() else "_" for ch in journal_name)[:40]
    log_path = LOG_DIR / f"{safe_journal}-{stage}-{ts}.log"

    cwd = _cwd_for(stage, journal_name)

    # Insert pending row first so we have an id
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO pipeline_jobs (journal, stage, status, cmd_json, log_path) "
            "VALUES (?, ?, 'pending', ?, ?)",
            (journal_name, stage, json.dumps(cmd), str(log_path)),
        )
        job_id = cur.lastrowid

    # Spawn the subprocess detached so it survives Flask request lifecycle
    log_fp = open(log_path, "wb")
    try:
        if sys.platform == "win32":
            # CREATE_NEW_PROCESS_GROUP so we can signal-stop later
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            proc = subprocess.Popen(
                cmd, cwd=str(cwd), stdout=log_fp, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, creationflags=creationflags,
            )
        else:
            proc = subprocess.Popen(
                cmd, cwd=str(cwd), stdout=log_fp, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, start_new_session=True,
            )
    except Exception as e:
        with _conn() as c:
            c.execute(
                "UPDATE pipeline_jobs SET status='failed', finished_at=datetime('now'), "
                "exit_code=-1 WHERE id=?",
                (job_id,),
            )
        log_fp.write(f"\n!! Failed to start subprocess: {e}\n".encode("utf-8"))
        log_fp.close()
        raise

    # NOTE: we intentionally don't close log_fp here — the child holds the
    # fd open. Flask's request finishes; the child keeps writing.
    with _conn() as c:
        c.execute(
            "UPDATE pipeline_jobs SET status='running', pid=? WHERE id=?",
            (proc.pid, job_id),
        )
    return job_id


def cancel_job(job_id: int) -> bool:
    """Best-effort kill of a running job. Returns True if a signal was sent."""
    row = get_job(job_id, reconcile=False)
    if not row or row["status"] != "running" or not row["pid"]:
        return False
    pid = row["pid"]
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, timeout=10)
        else:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
    except Exception:
        return False
    with _conn() as c:
        c.execute(
            "UPDATE pipeline_jobs SET status='cancelled', finished_at=datetime('now'), "
            "exit_code=-2 WHERE id=?",
            (job_id,),
        )
    return True


def get_job(job_id: int, reconcile: bool = True) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM pipeline_jobs WHERE id=?", (job_id,)
        ).fetchone()
    if row is None:
        return None
    return _reconcile_status(row) if reconcile else dict(row)


def list_jobs(journal: str | None = None, limit: int = 50) -> list[dict]:
    with _conn() as c:
        if journal:
            rows = c.execute(
                "SELECT * FROM pipeline_jobs WHERE journal=? ORDER BY id DESC LIMIT ?",
                (journal, limit),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM pipeline_jobs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [_reconcile_status(r) for r in rows]


def latest_job(journal: str, stage: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM pipeline_jobs WHERE journal=? AND stage=? ORDER BY id DESC LIMIT 1",
            (journal, stage),
        ).fetchone()
    return _reconcile_status(row) if row else None


def stream_log(log_path: Path, follow: bool = True,
               poll_interval: float = 0.5,
               stop_after_idle: float = 600.0) -> Iterator[str]:
    """Yield lines from log_path. If follow=True, keep tailing until the
    file stops growing for `stop_after_idle` seconds (then exit so the
    SSE connection doesn't hang forever on a dead job).
    """
    if not log_path.exists():
        # Wait briefly in case the file is about to appear
        for _ in range(10):
            if log_path.exists():
                break
            time.sleep(0.2)
        if not log_path.exists():
            yield "(log file not found)\n"
            return

    with open(log_path, "rb") as fp:
        last_change = time.time()
        while True:
            chunk = fp.read()
            if chunk:
                last_change = time.time()
                # Decode permissively; pipeline scripts write UTF-8 with
                # an explicit replace policy already
                yield chunk.decode("utf-8", errors="replace")
            else:
                if not follow:
                    return
                if time.time() - last_change > stop_after_idle:
                    yield "\n(stream idle for too long — closing)\n"
                    return
                time.sleep(poll_interval)
