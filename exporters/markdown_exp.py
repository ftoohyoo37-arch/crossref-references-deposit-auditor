from __future__ import annotations

from typing import Any

from auditor.models import Finding

SEV_ORDER = {"error": 0, "warning": 1, "info": 2}


def _esc(text: str | None) -> str:
    if text is None:
        return ""
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def to_markdown(meta: dict[str, Any], findings: list[Finding]) -> bytes:
    lines: list[str] = []
    lines.append(f"# Crossref Audit Report — {meta.get('filename', 'unknown')}")
    lines.append("")
    lines.append(f"- **File:** `{meta.get('filename')}` ({meta.get('file_size', 0):,} bytes)")
    lines.append(f"- **Run at:** {meta.get('created_at')}")
    lines.append(f"- **Schema namespace:** `{meta.get('namespace') or 'unknown'}`")
    lines.append(f"- **Citations checked:** {meta.get('citation_n', 0):,}")
    lines.append(f"- **Findings:** {meta.get('error_n', 0)} error(s), "
                 f"{meta.get('warning_n', 0)} warning(s), {meta.get('info_n', 0)} info")
    lines.append("")

    if not findings:
        lines.append("_No findings — clean deposit._")
        return "\n".join(lines).encode("utf-8")

    by_rule: dict[str, list[Finding]] = {}
    for f in findings:
        by_rule.setdefault(f.rule_id, []).append(f)

    sorted_rules = sorted(
        by_rule.items(),
        key=lambda kv: (min(SEV_ORDER.get(f.severity, 9) for f in kv[1]), kv[0]),
    )

    for rule_id, items in sorted_rules:
        lines.append(f"## `{rule_id}` — {len(items)} finding(s)")
        lines.append("")
        lines.append("| Severity | Line | Citation key | Message | Snippet |")
        lines.append("| --- | --- | --- | --- | --- |")
        items.sort(key=lambda f: (SEV_ORDER.get(f.severity, 9), f.line or 0))
        for f in items:
            lines.append(
                f"| {_esc(f.severity)} | {_esc(f.line)} | {_esc(f.citation_key)} "
                f"| {_esc(f.message)} | {_esc(f.snippet)} |"
            )
        lines.append("")

    return "\n".join(lines).encode("utf-8")
