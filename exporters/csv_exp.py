from __future__ import annotations

import csv
import io
from typing import Any

from auditor.models import Finding


def to_csv(meta: dict[str, Any], findings: list[Finding]) -> bytes:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        "filename", "audit_created_at",
        "rule_id", "severity", "line", "citation_key", "message", "snippet", "xpath",
    ])
    fname = meta.get("filename", "")
    created = meta.get("created_at", "")
    for f in findings:
        writer.writerow([
            fname, created,
            f.rule_id, f.severity, f.line or "", f.citation_key or "",
            f.message, f.snippet or "", f.xpath or "",
        ])
    # Excel handles BOM-prefixed UTF-8 better
    return ("﻿" + buf.getvalue()).encode("utf-8")
