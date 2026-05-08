"""Match a free-text citation against the Crossref REST API."""
from __future__ import annotations

import re
from typing import Any

import requests


CROSSREF_URL = "https://api.crossref.org/works"
# Crossref's "polite pool" wants a User-Agent with a contact email so they
# can reach you about API misuse. Replace the address below with your own
# before deploying. See https://api.crossref.org/swagger-ui/index.html
USER_AGENT = "Crossref-Auditor/1.0 (mailto:your-email@example.com)"
TIMEOUT = 20


_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": USER_AGENT})
    return _session


def _format_authors(authors: list[dict]) -> str:
    parts: list[str] = []
    for a in authors[:6]:
        given = (a.get("given") or "").strip()
        family = (a.get("family") or "").strip()
        initial = f"{given[0]}." if given else ""
        if family:
            parts.append(f"{family}, {initial}".strip(", "))
    if len(authors) > 6:
        parts.append("…")
    return "; ".join(parts) if parts else ""


def _year(item: dict) -> int | None:
    issued = item.get("issued") or {}
    parts = issued.get("date-parts") or [[None]]
    if not parts or not parts[0]:
        return None
    val = parts[0][0]
    return int(val) if val else None


def _normalise_score(score: float | None) -> str:
    if score is None:
        return "?"
    if score >= 100:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def match_citation(text: str, rows: int = 1) -> dict | None:
    """Query Crossref for the best match. Returns None on no result."""
    text = text.strip()
    if not text:
        return None
    try:
        r = _get_session().get(
            CROSSREF_URL,
            params={"query.bibliographic": text, "rows": rows},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        return {"error": str(e), "doi": None, "title": None, "score": None,
                "authors": "", "year": None, "confidence": "?", "container": ""}

    payload = r.json()
    items = (payload.get("message") or {}).get("items") or []
    if not items:
        return None
    item = items[0]
    return {
        "doi": item.get("DOI"),
        "title": (item.get("title") or [""])[0],
        "authors": _format_authors(item.get("author") or []),
        "year": _year(item),
        "container": (item.get("container-title") or [""])[0],
        "score": item.get("score"),
        "confidence": _normalise_score(item.get("score")),
        "url": item.get("URL"),
    }
