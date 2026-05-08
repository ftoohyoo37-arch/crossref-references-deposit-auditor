"""SQLite persistence for audit history.

Schema is intentionally tiny: one row per audit run, plus a child row per
finding. Exports re-assemble findings from these tables, so any past audit
can be re-exported in any format without re-running the auditor.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterator

from auditor.models import Finding


DB_PATH = Path(__file__).resolve().parent / "audits.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS audits (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    filename     TEXT NOT NULL,
    file_size    INTEGER NOT NULL,
    namespace    TEXT,
    citation_n   INTEGER NOT NULL DEFAULT 0,
    error_n      INTEGER NOT NULL DEFAULT 0,
    warning_n    INTEGER NOT NULL DEFAULT 0,
    info_n       INTEGER NOT NULL DEFAULT 0,
    config_json  TEXT,
    xml_path     TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS findings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id      INTEGER NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
    rule_id       TEXT NOT NULL,
    severity      TEXT NOT NULL,
    message       TEXT NOT NULL,
    line          INTEGER,
    xpath         TEXT,
    citation_key  TEXT,
    snippet       TEXT
);

CREATE TABLE IF NOT EXISTS cleanup_decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id        INTEGER NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
    citation_line   INTEGER NOT NULL,
    citation_key    TEXT,
    action          TEXT NOT NULL,           -- 'keep' | 'delete' | 'split'
    split_chunks    TEXT,                    -- JSON list[str] when action='split'
    crossref_data   TEXT,                    -- JSON list[dict|null] parallel to chunks
    notes           TEXT,
    decided_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (audit_id, citation_line)
);

CREATE INDEX IF NOT EXISTS idx_findings_audit_id ON findings(audit_id);
CREATE INDEX IF NOT EXISTS idx_findings_rule_id  ON findings(rule_id);
CREATE INDEX IF NOT EXISTS idx_findings_severity ON findings(severity);
CREATE INDEX IF NOT EXISTS idx_cleanup_audit_id  ON cleanup_decisions(audit_id);
"""


def _migrate_add_xml_path() -> None:
    """Add xml_path column to existing audits table if it's missing."""
    with connect() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(audits)")}
        if "xml_path" not in cols:
            conn.execute("ALTER TABLE audits ADD COLUMN xml_path TEXT")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
    _migrate_add_xml_path()


def set_audit_xml_path(audit_id: int, path: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE audits SET xml_path = ? WHERE id = ?", (path, audit_id))


def upsert_cleanup_decision(
    *,
    audit_id: int,
    citation_line: int,
    citation_key: str | None,
    action: str,
    split_chunks: list[str] | None = None,
    crossref_data: list[dict | None] | None = None,
    notes: str | None = None,
) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO cleanup_decisions
               (audit_id, citation_line, citation_key, action, split_chunks, crossref_data, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(audit_id, citation_line) DO UPDATE SET
                 citation_key = excluded.citation_key,
                 action       = excluded.action,
                 split_chunks = excluded.split_chunks,
                 crossref_data = excluded.crossref_data,
                 notes        = excluded.notes,
                 decided_at   = datetime('now')""",
            (
                audit_id, citation_line, citation_key, action,
                json.dumps(split_chunks) if split_chunks else None,
                json.dumps(crossref_data) if crossref_data else None,
                notes,
            ),
        )


def get_cleanup_decisions(audit_id: int) -> dict[int, dict]:
    """Return decisions keyed by citation_line."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM cleanup_decisions WHERE audit_id = ?",
            (audit_id,),
        ).fetchall()
    out: dict[int, dict] = {}
    for r in rows:
        out[r["citation_line"]] = {
            "action": r["action"],
            "citation_key": r["citation_key"],
            "split_chunks": json.loads(r["split_chunks"]) if r["split_chunks"] else None,
            "crossref_data": json.loads(r["crossref_data"]) if r["crossref_data"] else None,
            "notes": r["notes"],
            "decided_at": r["decided_at"],
        }
    return out


def insert_audit(
    *,
    filename: str,
    file_size: int,
    namespace: str | None,
    citation_n: int,
    findings: list[Finding],
    config_dict: dict | None = None,
) -> int:
    counts = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1

    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO audits
               (filename, file_size, namespace, citation_n,
                error_n, warning_n, info_n, config_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                filename,
                file_size,
                namespace,
                citation_n,
                counts["error"],
                counts["warning"],
                counts["info"],
                json.dumps(config_dict) if config_dict else None,
            ),
        )
        audit_id = cur.lastrowid
        if findings:
            conn.executemany(
                """INSERT INTO findings
                   (audit_id, rule_id, severity, message, line, xpath, citation_key, snippet)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        audit_id,
                        f.rule_id,
                        f.severity,
                        f.message,
                        f.line,
                        f.xpath,
                        f.citation_key,
                        f.snippet,
                    )
                    for f in findings
                ],
            )
        return audit_id


def list_audits(limit: int = 100) -> list[sqlite3.Row]:
    with connect() as conn:
        return list(conn.execute(
            "SELECT * FROM audits ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ))


def get_audit(audit_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM audits WHERE id = ?",
            (audit_id,),
        ).fetchone()


def get_findings(audit_id: int) -> list[Finding]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT rule_id, severity, message, line, xpath, citation_key, snippet
               FROM findings WHERE audit_id = ? ORDER BY id""",
            (audit_id,),
        ).fetchall()
    return [
        Finding(
            rule_id=r["rule_id"],
            severity=r["severity"],
            message=r["message"],
            line=r["line"],
            xpath=r["xpath"],
            citation_key=r["citation_key"],
            snippet=r["snippet"],
        )
        for r in rows
    ]


def delete_audit(audit_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM audits WHERE id = ?", (audit_id,))
