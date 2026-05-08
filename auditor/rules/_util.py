from __future__ import annotations

import re
from lxml import etree as ET


def local_name(tag: str) -> str:
    """Strip the namespace from an lxml element tag."""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def find_child(elem: ET._Element, name: str) -> ET._Element | None:
    """Find a direct child by local name (namespace-agnostic)."""
    for child in elem:
        if local_name(child.tag) == name:
            return child
    return None


def find_children(elem: ET._Element, name: str) -> list[ET._Element]:
    return [c for c in elem if local_name(c.tag) == name]


def text_of(elem: ET._Element | None) -> str:
    if elem is None:
        return ""
    # Concatenate all text descendants — handles mixed-content elements
    return "".join(elem.itertext()).strip()


def short_snippet(text: str, n: int = 120) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def citation_key(elem: ET._Element) -> str | None:
    return elem.get("key")
