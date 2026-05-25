"""Merge multiple Crossref deposit XML files into a single submission.

Used for assembling per-volume deposits into one batch submission for
journals whose backfill is split across many files (e.g., Across the
Disciplines, with 22 volume-level XMLs that all share one depositor).

Hard constraints (Crossref will reject the submission otherwise):
  1. All input files must share the same schema namespace.
  2. All input files must share the same depositor (the email_address
     element inside <head>/<depositor> identifies the account that owns
     the parent DOIs). Mixing depositors in one batch fails ingestion.
  3. The merged file uses the FIRST input file's <head> envelope, with a
     fresh <doi_batch_id> and <timestamp>, plus every <doi_citations>
     block from every input concatenated under one <body>.

If a per-audit decisions dict is provided, decisions are applied to each
input's XML before extracting its <doi_citations> blocks, so the merged
file reflects the cleanup state of each volume.
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

from lxml import etree as ET

from .xml_writer import apply_decisions


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _find_child(elem: ET._Element, name: str) -> ET._Element | None:
    for c in elem:
        if _local(c.tag) == name:
            return c
    return None


def _depositor_signature(root: ET._Element) -> str:
    """Return a stable identifier for the depositor account. Uses the
    <email_address> inside <head>/<depositor> (Crossref's canonical
    depositor identifier) and falls back to <depositor_name> if email
    isn't present.
    """
    head = _find_child(root, "head")
    if head is None:
        return ""
    dep = _find_child(head, "depositor")
    if dep is None:
        return ""
    email = _find_child(dep, "email_address")
    if email is not None and email.text:
        return email.text.strip().lower()
    name = _find_child(dep, "depositor_name")
    if name is not None and name.text:
        return name.text.strip().lower()
    return ""


def merge_deposits(
    inputs: list[tuple[Path, dict | None]],
    output_path: Path,
    new_batch_id: str | None = None,
) -> dict:
    """Merge a list of (xml_path, decisions_or_None) inputs into one
    Crossref deposit XML written to output_path.

    Returns a summary dict with counts and any validation issues.
    """
    if not inputs:
        raise ValueError("merge_deposits called with no inputs")

    # Materialise each input (apply decisions if any), parse the result.
    parsed: list[tuple[Path, ET._ElementTree]] = []
    namespaces: set[str] = set()
    depositors: set[str] = set()
    citation_count = 0
    record_count = 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    work_dir = output_path.parent

    for src_path, decisions in inputs:
        if decisions:
            tmp = work_dir / f".merge_in_{src_path.stem}.xml"
            apply_decisions(src_path, decisions, tmp)
            read_path = tmp
        else:
            read_path = src_path
        tree = ET.parse(str(read_path))
        root = tree.getroot()
        m = root.tag.rsplit("}", 1)
        ns = m[0].lstrip("{") if len(m) == 2 else ""
        namespaces.add(ns)
        depositors.add(_depositor_signature(root))
        parsed.append((src_path, tree))

    if len(namespaces) > 1:
        raise ValueError(
            f"Cannot merge: inputs use different schema namespaces "
            f"({sorted(namespaces)}). Crossref deposits must use a single schema."
        )
    if len(depositors) > 1:
        raise ValueError(
            f"Cannot merge: inputs identify different depositors "
            f"({sorted(d for d in depositors if d)}). A single Crossref "
            "batch submission can only target DOIs owned by one depositor."
        )

    # Start from the first input's tree as the merged envelope.
    base_path, base_tree = parsed[0]
    base_root = base_tree.getroot()
    ns = next(iter(namespaces)) if namespaces else ""

    # Refresh <head>/<doi_batch_id> so the merged file is treated as a new
    # submission rather than a duplicate of the first input. Only update
    # <timestamp> IF it was already present — the doi_resources_schema
    # doesn't allow <timestamp> in <head>, only the full deposit schema does.
    # Creating one unconditionally breaks XSD validation on doi_resources.
    head = _find_child(base_root, "head")
    if head is not None:
        new_id = new_batch_id or f"merged-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        batch_id_el = _find_child(head, "doi_batch_id")
        if batch_id_el is None:
            batch_id_el = ET.SubElement(head, f"{{{ns}}}doi_batch_id" if ns else "doi_batch_id")
        batch_id_el.text = new_id

        ts_el = _find_child(head, "timestamp")
        if ts_el is not None:  # only refresh, never add
            ts_el.text = datetime.now().strftime("%Y%m%d%H%M%S")

    # Find <body> in the base; we'll append additional records here.
    base_body = _find_child(base_root, "body")
    if base_body is None:
        raise ValueError("First input file has no <body> element; can't merge")

    # Count records and citations already in base.
    for dc in base_body:
        if _local(dc.tag) == "doi_citations":
            record_count += 1
            cl = _find_child(dc, "citation_list")
            if cl is not None:
                citation_count += sum(1 for c in cl if _local(c.tag) == "citation")

    # Append all <doi_citations> from the remaining inputs.
    for src_path, tree in parsed[1:]:
        root = tree.getroot()
        body = _find_child(root, "body")
        if body is None:
            continue
        for dc in list(body):
            if _local(dc.tag) != "doi_citations":
                continue
            # Deep-copy by serialisation round-trip so we don't disturb
            # the source tree (matters if the same tree is touched again).
            copied = ET.fromstring(ET.tostring(dc))
            base_body.append(copied)
            record_count += 1
            cl = _find_child(copied, "citation_list")
            if cl is not None:
                citation_count += sum(1 for c in cl if _local(c.tag) == "citation")

    # Write atomically.
    tmp = output_path.with_suffix(output_path.suffix + ".part")
    base_tree.write(str(tmp), xml_declaration=True, encoding="UTF-8")
    tmp.replace(output_path)

    return {
        "namespace": ns,
        "depositor": next(iter(depositors)) if depositors else "",
        "input_count": len(inputs),
        "record_count": record_count,
        "citation_count": citation_count,
        "output_path": str(output_path),
    }
