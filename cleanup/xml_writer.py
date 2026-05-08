"""Apply cleanup decisions to a Crossref deposit XML and write the cleaned copy."""
from __future__ import annotations

import io
from pathlib import Path

from lxml import etree as ET


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def apply_decisions(
    xml_path: Path,
    decisions: dict[int, dict],
    output_path: Path,
) -> dict[str, int]:
    """Walk the XML; apply each decision keyed by citation source line.

    Returns a counts dict: {kept, deleted, split_into} — note `split_into`
    is the total number of NEW citations created from splits.
    """
    counts = {"kept": 0, "deleted": 0, "split_from": 0, "split_into": 0, "untouched": 0}

    parser = ET.XMLParser(remove_blank_text=False)
    tree = ET.parse(str(xml_path), parser)
    root = tree.getroot()

    # Walk every <citation> by local-name match (namespace-agnostic)
    citations: list[ET._Element] = []
    for elem in root.iter():
        if _local_name(elem.tag) == "citation":
            citations.append(elem)

    for elem in citations:
        line = elem.sourceline
        decision = decisions.get(line)
        if decision is None:
            counts["untouched"] += 1
            continue

        action = decision.get("action")
        if action == "keep":
            counts["kept"] += 1
            continue
        if action == "delete":
            parent = elem.getparent()
            if parent is not None:
                # Preserve the trailing whitespace tail-text by stripping it
                parent.remove(elem)
                counts["deleted"] += 1
            continue
        if action == "split":
            chunks: list[str] = decision.get("split_chunks") or []
            chunks = [c.strip() for c in chunks if c and c.strip()]
            if not chunks:
                counts["untouched"] += 1
                continue
            parent = elem.getparent()
            if parent is None:
                counts["untouched"] += 1
                continue
            base_key = elem.get("key") or "ref"
            ns_uri = elem.tag.rsplit("}", 1)[0].lstrip("{") if "}" in elem.tag else None
            citation_tag = elem.tag
            uc_local = "unstructured_citation"
            uc_tag = f"{{{ns_uri}}}{uc_local}" if ns_uri else uc_local

            new_elems: list[ET._Element] = []
            for i, chunk in enumerate(chunks):
                new_key = base_key if i == 0 else f"{base_key}{chr(ord('a') + i - 1)}"
                new_cit = ET.SubElement(parent, citation_tag) if False else ET.Element(citation_tag)
                new_cit.set("key", new_key)
                # Preserve the parent's indent on each new element
                new_cit.text = elem.text
                new_cit.tail = elem.tail if i == len(chunks) - 1 else "\n          "
                uc = ET.SubElement(new_cit, uc_tag)
                uc.text = chunk
                new_elems.append(new_cit)

            # Replace the original element with the new ones, preserving order
            idx = list(parent).index(elem)
            parent.remove(elem)
            for offset, new_cit in enumerate(new_elems):
                parent.insert(idx + offset, new_cit)
            counts["split_from"] += 1
            counts["split_into"] += len(new_elems)
            continue

        counts["untouched"] += 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + ".part")
    tree.write(str(tmp), xml_declaration=True, encoding="UTF-8", pretty_print=False)
    tmp.replace(output_path)
    return counts


def count_changes(decisions: dict[int, dict]) -> dict[str, int]:
    out = {"keep": 0, "delete": 0, "split": 0, "split_into": 0}
    for d in decisions.values():
        action = d.get("action")
        if action in ("keep", "delete", "split"):
            out[action] += 1
        if action == "split":
            chunks = d.get("split_chunks") or []
            out["split_into"] += len([c for c in chunks if c and c.strip()])
    return out
