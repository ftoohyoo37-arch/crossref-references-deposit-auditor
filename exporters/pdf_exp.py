from __future__ import annotations

import html
import io
from typing import Any

from xhtml2pdf import pisa

from auditor.models import Finding

SEV_ORDER = {"error": 0, "warning": 1, "info": 2}
SEV_COLOR = {
    "error":   "#a94442",
    "warning": "#8a6d3b",
    "info":    "#31708f",
}


def _row_html(f: Finding) -> str:
    return (
        "<tr>"
        f"<td style='color:{SEV_COLOR.get(f.severity, '#333')};font-weight:bold'>{html.escape(f.severity)}</td>"
        f"<td>{f.line if f.line is not None else ''}</td>"
        f"<td>{html.escape(f.citation_key or '')}</td>"
        f"<td>{html.escape(f.message)}</td>"
        f"<td><i>{html.escape(f.snippet or '')}</i></td>"
        "</tr>"
    )


def _build_html(meta: dict[str, Any], findings: list[Finding]) -> str:
    by_rule: dict[str, list[Finding]] = {}
    for f in findings:
        by_rule.setdefault(f.rule_id, []).append(f)
    sorted_rules = sorted(
        by_rule.items(),
        key=lambda kv: (min(SEV_ORDER.get(f.severity, 9) for f in kv[1]), kv[0]),
    )

    parts: list[str] = []
    parts.append("""
    <html><head><style>
      body { font-family: Georgia, serif; font-size: 10pt; color: #222; }
      h1 { font-size: 18pt; margin-bottom: 4pt; }
      h2 { font-size: 12pt; margin-top: 16pt; border-bottom: 1px solid #ccc; padding-bottom: 2pt; }
      .meta { color: #555; font-size: 9pt; margin-bottom: 12pt; }
      table { width: 100%; border-collapse: collapse; margin-top: 4pt; }
      th, td { border: 1px solid #ccc; padding: 4pt; vertical-align: top; text-align: left; font-size: 9pt; }
      th { background: #f4f1ec; }
      .none { color: #060; font-style: italic; }
    </style></head><body>
    """)
    parts.append(f"<h1>Crossref Audit Report</h1>")
    parts.append("<div class='meta'>")
    parts.append(f"<b>File:</b> {html.escape(meta.get('filename', ''))} "
                 f"({meta.get('file_size', 0):,} bytes)<br/>")
    parts.append(f"<b>Run at:</b> {html.escape(str(meta.get('created_at', '')))}<br/>")
    parts.append(f"<b>Schema namespace:</b> {html.escape(meta.get('namespace') or 'unknown')}<br/>")
    parts.append(f"<b>Citations checked:</b> {meta.get('citation_n', 0):,}<br/>")
    parts.append(f"<b>Findings:</b> {meta.get('error_n', 0)} error(s), "
                 f"{meta.get('warning_n', 0)} warning(s), {meta.get('info_n', 0)} info")
    parts.append("</div>")

    if not findings:
        parts.append("<p class='none'>No findings — clean deposit.</p>")
    else:
        for rule_id, items in sorted_rules:
            parts.append(f"<h2>{html.escape(rule_id)} — {len(items)} finding(s)</h2>")
            parts.append("<table>")
            parts.append("<tr><th>Severity</th><th>Line</th><th>Key</th><th>Message</th><th>Snippet</th></tr>")
            items.sort(key=lambda f: (SEV_ORDER.get(f.severity, 9), f.line or 0))
            for f in items:
                parts.append(_row_html(f))
            parts.append("</table>")

    parts.append("</body></html>")
    return "".join(parts)


def to_pdf(meta: dict[str, Any], findings: list[Finding]) -> bytes:
    html_str = _build_html(meta, findings)
    buf = io.BytesIO()
    pisa.CreatePDF(src=html_str, dest=buf, encoding="utf-8")
    return buf.getvalue()
