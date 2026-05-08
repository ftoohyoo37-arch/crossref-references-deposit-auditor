from __future__ import annotations

import re

from ..models import Finding, ParamMeta, RuleMeta, Severity
from . import register_citation_rule
from ._util import citation_key, find_children, short_snippet, text_of

META = RuleMeta(
    id="title_quality",
    name="Title field quality",
    description=(
        "Flags titles with leaked HTML/JATS tags, embedded newlines, suspicious "
        "ALL-CAPS formatting, or unbalanced quotes."
    ),
    scope="citation",
    default_severity=Severity.WARNING,
    default_enabled=True,
    params=[
        ParamMeta("min_caps_words", "int", 5, "Minimum word count for the ALL-CAPS check (avoid flagging short acronyms-as-titles)."),
    ],
)

TAG_LEAK_RE = re.compile(r"</?[a-z][a-z0-9:_-]*(\s[^>]*)?>", re.IGNORECASE)
ENTITY_LEAK_RE = re.compile(r"&(?:amp|lt|gt|quot|apos|nbsp|#\d+|#x[0-9a-fA-F]+);")
TITLE_FIELDS = ("article_title", "journal_title", "volume_title", "series_title", "chapter_title")


@register_citation_rule(META)
def title_quality(elem, ctx) -> list[Finding]:
    sev = ctx.config.severity(META.id, META.default_severity.value)
    min_caps_words = int(ctx.config.param(META.id, "min_caps_words", 5))
    findings: list[Finding] = []

    for tag in TITLE_FIELDS:
        for tf in find_children(elem, tag):
            raw = text_of(tf)
            if not raw:
                findings.append(Finding(
                    rule_id=META.id,
                    severity=sev,
                    message=f"<{tag}> is empty.",
                    line=elem.sourceline,
                    citation_key=citation_key(elem),
                ))
                continue
            if TAG_LEAK_RE.search(raw):
                findings.append(Finding(
                    rule_id=META.id,
                    severity=sev,
                    message=f"<{tag}> appears to contain leaked HTML/JATS tags.",
                    line=elem.sourceline,
                    citation_key=citation_key(elem),
                    snippet=short_snippet(raw),
                ))
            if ENTITY_LEAK_RE.search(raw):
                findings.append(Finding(
                    rule_id=META.id,
                    severity="info",
                    message=f"<{tag}> contains HTML entities — verify they're intended (XML escapes only & < > ' \").",
                    line=elem.sourceline,
                    citation_key=citation_key(elem),
                    snippet=short_snippet(raw),
                ))
            if "\n" in raw or "\r" in raw:
                findings.append(Finding(
                    rule_id=META.id,
                    severity=sev,
                    message=f"<{tag}> contains embedded newlines.",
                    line=elem.sourceline,
                    citation_key=citation_key(elem),
                    snippet=short_snippet(raw),
                ))
            words = [w for w in re.findall(r"[A-Za-z]+", raw) if len(w) > 1]
            if len(words) >= min_caps_words and all(w.isupper() for w in words):
                findings.append(Finding(
                    rule_id=META.id,
                    severity="info",
                    message=f"<{tag}> is entirely ALL CAPS — verify this is intentional.",
                    line=elem.sourceline,
                    citation_key=citation_key(elem),
                    snippet=short_snippet(raw),
                ))
    return findings
