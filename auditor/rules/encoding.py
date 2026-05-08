from __future__ import annotations

import re

from ..models import Finding, ParamMeta, RuleMeta, Severity
from . import register_document_rule

META = RuleMeta(
    id="encoding_mojibake",
    name="Mojibake / encoding sniff",
    description=(
        "Scans the raw bytes for common UTF-8/Latin-1 round-trip artifacts "
        "(e.g. 'Ã©', 'â€™', 'Â '), which usually indicate that a scraped "
        "page was decoded with the wrong codec before being written out."
    ),
    scope="document",
    default_severity=Severity.WARNING,
    default_enabled=True,
    params=[
        ParamMeta("max_examples", "int", 5, "Maximum number of distinct mojibake examples to report."),
    ],
)

MOJIBAKE_TOKENS = [
    "Ã©", "Ã¨", "Ã ", "Ã¢", "Ã®", "Ã´", "Ã»", "Ã§",
    "Ã“", "Ã‰", "Ãˆ",
    "â€™", "â€˜", "â€œ", "â€\x9d", "â€“", "â€”", "â€¦",
    "Â§", "Â¶", "Â©", "Â®", "Â°",
    "Â\xa0",
]
MOJIBAKE_RE = re.compile("|".join(re.escape(t) for t in MOJIBAKE_TOKENS))


@register_document_rule(META)
def encoding_mojibake(root, raw_bytes, ctx) -> list[Finding]:
    sev = ctx.config.severity(META.id, META.default_severity.value)
    max_examples = int(ctx.config.param(META.id, "max_examples", 5))

    try:
        text = raw_bytes.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return [Finding(
            rule_id=META.id,
            severity=sev,
            message="Document bytes did not decode as UTF-8.",
        )]

    counts: dict[str, int] = {}
    for m in MOJIBAKE_RE.finditer(text):
        counts[m.group(0)] = counts.get(m.group(0), 0) + 1

    if not counts:
        return []

    items = sorted(counts.items(), key=lambda kv: -kv[1])
    total = sum(counts.values())
    examples = ", ".join(f"{tok!r}×{n}" for tok, n in items[:max_examples])

    return [Finding(
        rule_id=META.id,
        severity=sev,
        message=(
            f"Found {total} likely mojibake occurrence(s) across "
            f"{len(counts)} distinct token(s). Examples: {examples}."
        ),
    )]
