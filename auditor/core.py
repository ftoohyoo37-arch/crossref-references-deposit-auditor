from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any

from lxml import etree as ET

from .models import AuditorConfig, Finding
from . import rules as _rules_pkg

def _is_crossref_ns(uri: str) -> bool:
    return bool(uri) and "crossref.org" in uri and ("schema" in uri)


@dataclass
class AuditContext:
    """Carries cross-rule state during an audit (e.g. duplicate trackers).

    `citation_keys_by_list` groups keys by their parent <citation_list>
    element's source line, so duplicate detection scopes to one list at a
    time — Crossref only requires keys to be unique within a single list.
    """
    config: AuditorConfig
    namespace: str | None = None
    citation_keys_by_list: dict[int, dict[str, list[int]]] = field(default_factory=dict)
    citation_count: int = 0
    extras: dict[str, Any] = field(default_factory=dict)


def detect_namespace(root: ET._Element) -> str | None:
    """Return the Crossref namespace declared on the root element, if any.
    Recognises both the full deposit schema (`crossref.org/schema/X.Y.Z`)
    and the citation-update schema (`crossref.org/doi_resources_schema/X.Y.Z`).
    """
    for uri in root.nsmap.values():
        if _is_crossref_ns(uri):
            return uri
    m = re.match(r"\{([^}]+)\}", root.tag)
    if m and _is_crossref_ns(m.group(1)):
        return m.group(1)
    return None


def audit(xml_bytes: bytes, config: AuditorConfig | None = None) -> list[Finding]:
    """Audit a Crossref deposit XML document.

    Streams citation elements via iterparse for memory efficiency. Document-
    level rules see the parsed root once; citation-level rules run per
    `<citation>`; post-process rules run after streaming completes.
    """
    if config is None:
        config = AuditorConfig()
    config = config.merged_with_defaults(_rules_pkg.all_rule_metas())

    findings: list[Finding] = []

    # Parse root once for document-level rules. lxml uses a C-backed tree, so
    # even a 7000-citation file is comfortably small in RAM.
    try:
        root = ET.fromstring(xml_bytes)
    except ET.XMLSyntaxError as e:
        findings.append(Finding(
            rule_id="xml_parse",
            severity="error",
            message=f"XML failed to parse: {e}",
            line=getattr(e, "lineno", None),
        ))
        return findings

    ns = detect_namespace(root)
    ctx = AuditContext(config=config, namespace=ns)

    for meta, fn in _rules_pkg.document_rules():
        if not config.is_rule_enabled(meta.id):
            continue
        try:
            findings.extend(fn(root, xml_bytes, ctx))
        except Exception as e:  # noqa: BLE001 - rule isolation
            findings.append(Finding(
                rule_id=meta.id,
                severity="error",
                message=f"Rule crashed: {e!r}",
            ))

    # Citation streaming pass
    citation_tag = f"{{{ns}}}citation" if ns else "citation"
    citation_fns = _rules_pkg.citation_rules()

    if citation_fns or _rules_pkg.post_rules():
        try:
            context = ET.iterparse(
                io.BytesIO(xml_bytes),
                events=("end",),
                tag=citation_tag,
            )
            for _event, elem in context:
                ctx.citation_count += 1
                key = elem.get("key")
                if key:
                    parent = elem.getparent()
                    list_id = parent.sourceline if parent is not None else 0
                    list_bucket = ctx.citation_keys_by_list.setdefault(list_id, {})
                    list_bucket.setdefault(key, []).append(elem.sourceline or 0)

                for meta, fn in citation_fns:
                    if not config.is_rule_enabled(meta.id):
                        continue
                    try:
                        findings.extend(fn(elem, ctx))
                    except Exception as e:  # noqa: BLE001
                        findings.append(Finding(
                            rule_id=meta.id,
                            severity="error",
                            message=f"Rule crashed on citation: {e!r}",
                            line=elem.sourceline,
                            citation_key=key,
                        ))

                # Memory hygiene: drop the element and its preceding siblings
                elem.clear()
                while elem.getprevious() is not None:
                    parent = elem.getparent()
                    if parent is None:
                        break
                    del parent[0]
        except ET.XMLSyntaxError as e:
            findings.append(Finding(
                rule_id="xml_parse",
                severity="error",
                message=f"XML stream failed mid-parse: {e}",
                line=getattr(e, "lineno", None),
            ))

    # Post-process rules (cross-citation aggregates)
    for meta, fn in _rules_pkg.post_rules():
        if not config.is_rule_enabled(meta.id):
            continue
        try:
            findings.extend(fn(ctx))
        except Exception as e:  # noqa: BLE001
            findings.append(Finding(
                rule_id=meta.id,
                severity="error",
                message=f"Post-rule crashed: {e!r}",
            ))

    return findings


def summarize(findings: list[Finding]) -> dict[str, int]:
    """Count findings by severity."""
    out = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        out[f.severity] = out.get(f.severity, 0) + 1
    out["total"] = len(findings)
    return out
