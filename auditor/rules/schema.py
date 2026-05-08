from __future__ import annotations

from pathlib import Path

from lxml import etree as ET

from ..models import Finding, ParamMeta, RuleMeta, Severity
from . import register_document_rule


XSD_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "crossref_xsd"

META = RuleMeta(
    id="schema_validate",
    name="XSD schema validation",
    description=(
        "Validates the deposit against the bundled Crossref XSD matching the "
        "namespace declared on the root element. Files that fail this check "
        "will be rejected by Crossref."
    ),
    scope="document",
    default_severity=Severity.ERROR,
    default_enabled=True,
    params=[
        ParamMeta(
            name="max_findings",
            type="int",
            default=50,
            description="Cap on schema errors reported per audit (XSD validation can produce many cascading errors).",
        ),
    ],
)


def _xsd_filename_for_namespace(ns: str | None) -> str | None:
    if not ns:
        return None
    # Citation-update schema (used for adding refs to existing DOIs)
    if "doi_resources_schema" in ns:
        if "4.3.6" in ns:
            return "doi_resources4.3.6.xsd"
        if "4.4" in ns:
            return "doi_resources4.4.2.xsd"
    # Full deposit schema
    if "5.3.1" in ns:
        return "crossref5.3.1.xsd"
    if "5.3.0" in ns:
        return "crossref5.3.0.xsd"
    if "4.4" in ns:
        return "crossref4.4.2.xsd"
    if "4.3.6" in ns:
        return "crossref4.3.6.xsd"
    return None


@register_document_rule(META)
def schema_validate(root, raw_bytes, ctx) -> list[Finding]:
    sev = ctx.config.severity(META.id, META.default_severity.value)
    max_findings = int(ctx.config.param(META.id, "max_findings", 50))

    xsd_name = _xsd_filename_for_namespace(ctx.namespace)
    if xsd_name is None:
        return [Finding(
            rule_id=META.id,
            severity="warning",
            message=(
                f"Could not determine Crossref schema for namespace "
                f"{ctx.namespace!r}; schema validation skipped."
            ),
        )]

    xsd_path = XSD_DIR / xsd_name
    if not xsd_path.exists():
        return [Finding(
            rule_id=META.id,
            severity="warning",
            message=(
                f"Schema file {xsd_name} not found in config/crossref_xsd/. "
                f"Run `python fetch_xsds.py` to download official XSDs."
            ),
        )]

    try:
        xmlschema_doc = ET.parse(str(xsd_path))
        xmlschema = ET.XMLSchema(xmlschema_doc)
    except (ET.XMLSchemaParseError, ET.XMLSyntaxError) as e:
        return [Finding(
            rule_id=META.id,
            severity="error",
            message=f"Failed to load XSD {xsd_name}: {e}",
        )]

    if xmlschema.validate(root):
        return []

    findings: list[Finding] = []
    for err in xmlschema.error_log:
        if len(findings) >= max_findings:
            findings.append(Finding(
                rule_id=META.id,
                severity="info",
                message=f"... {len(xmlschema.error_log) - max_findings} more schema errors omitted.",
            ))
            break
        findings.append(Finding(
            rule_id=META.id,
            severity=sev,
            message=err.message,
            line=err.line,
            xpath=err.path,
        ))
    return findings
