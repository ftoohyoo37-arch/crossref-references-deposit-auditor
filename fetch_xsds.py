#!/usr/bin/env python
"""Download Crossref deposit XSDs into config/crossref_xsd/.

Crossref's top-level schemas include / import a chain of dependencies, so this
script recursively follows <xs:include> and <xs:import> until it has the full
set. Run once after install.

Usage: python fetch_xsds.py
"""
from __future__ import annotations

import sys
import urllib.parse
from pathlib import Path
from typing import Iterable

import requests
from lxml import etree as ET


XSD_BASE = "https://www.crossref.org/schemas/"
TOP_LEVEL = [
    "crossref4.3.6.xsd",
    "crossref4.4.2.xsd",
    "crossref5.3.0.xsd",
    "crossref5.3.1.xsd",
    "doi_resources4.3.6.xsd",
    "doi_resources4.4.2.xsd",
]
OUT_DIR = Path(__file__).resolve().parent / "config" / "crossref_xsd"
XS_NS = "http://www.w3.org/2001/XMLSchema"


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)


def _includes(xsd_bytes: bytes) -> Iterable[str]:
    """Yield schemaLocation values from <xs:include>/<xs:import>."""
    try:
        root = ET.fromstring(xsd_bytes)
    except ET.XMLSyntaxError as e:
        print(f"!! parse error: {e}", file=sys.stderr)
        return []
    for tag in (f"{{{XS_NS}}}include", f"{{{XS_NS}}}import"):
        for el in root.iter(tag):
            loc = el.get("schemaLocation")
            if loc:
                yield loc


def _download(url: str, session: requests.Session) -> bytes:
    print(f"  fetching {url}")
    r = session.get(url, timeout=30)
    r.raise_for_status()
    return r.content


def fetch_all() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    queue: list[str] = list(TOP_LEVEL)
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Crossref-Auditor/1.0 (mailto:youremail@example.com)",
    })

    failures = 0
    while queue:
        name = queue.pop(0)
        if name in seen:
            continue
        seen.add(name)

        # Resolve URL — names may be relative or absolute paths
        if name.startswith("http"):
            url = name
            fname = Path(urllib.parse.urlparse(url).path).name
        else:
            url = urllib.parse.urljoin(XSD_BASE, name)
            fname = Path(name).name

        try:
            data = _download(url, session)
        except requests.HTTPError as e:
            print(f"!! {name}: HTTP {e.response.status_code}", file=sys.stderr)
            failures += 1
            continue
        except requests.RequestException as e:
            print(f"!! {name}: {e}", file=sys.stderr)
            failures += 1
            continue

        _atomic_write(OUT_DIR / fname, data)
        for loc in _includes(data):
            if loc not in seen:
                queue.append(loc)

    print(f"\nFetched {len(seen) - failures}/{len(seen)} XSD files into {OUT_DIR}")
    return 0 if failures == 0 else 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    return fetch_all()


if __name__ == "__main__":
    sys.exit(main())
