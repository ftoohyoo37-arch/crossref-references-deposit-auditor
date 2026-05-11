"""Match a free-text citation against the OpenAlex REST API.

OpenAlex (https://openalex.org) is a free, open, comprehensive index of
scholarly works built on Microsoft Academic Graph and Crossref data, plus
a wider range of sources Crossref doesn't index well: textbooks,
dissertations, conference proceedings without DOIs, working papers,
small open-access journals, and grey literature.

The cleanup tool uses OpenAlex as a fallback when Crossref's
bibliographic search returns low confidence — the broader coverage
typically resolves another 30-40% of citations on a Reflections-scale
deposit.

API: GET https://api.openalex.org/works?search=<text>&per-page=1
Free, no authentication required, but the polite pool wants a
contact email in the User-Agent or `mailto` query param. Returns JSON
with `id`, `doi`, `title`, `publication_year`, `authorships`, `score`.
"""
from __future__ import annotations

from typing import Any

import requests


OPENALEX_URL = "https://api.openalex.org/works"
USER_AGENT = "Crossref-Auditor/1.0 (mailto:your-email@example.com)"
TIMEOUT = 20


_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers.update({"User-Agent": USER_AGENT})
    return _session


def _format_authors(authorships: list[dict]) -> str:
    parts: list[str] = []
    for a in authorships[:6]:
        name = (a.get("author") or {}).get("display_name") or ""
        if not name:
            continue
        # Convert "First Middle Last" to "Last, F." for consistency with
        # Crossref-formatted output the rest of the tool uses.
        bits = name.split()
        if len(bits) >= 2:
            parts.append(f"{bits[-1]}, {bits[0][0]}.")
        else:
            parts.append(name)
    if len(authorships) > 6:
        parts.append("…")
    return "; ".join(parts) if parts else ""


def _normalise_score(score: float | None) -> str:
    """OpenAlex returns relevance_score in roughly the same range as
    Crossref (0–200+), so we map it onto the same coarse buckets the
    rest of the tool uses for confidence labels.
    """
    if score is None:
        return "?"
    if score >= 100:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def _strip_doi_prefix(doi: str | None) -> str | None:
    """OpenAlex returns DOIs as 'https://doi.org/10.x/y'; normalize to
    bare '10.x/y' to match Crossref's output."""
    if not doi:
        return None
    if doi.startswith("https://doi.org/"):
        return doi[len("https://doi.org/"):]
    if doi.startswith("http://doi.org/"):
        return doi[len("http://doi.org/"):]
    return doi


def match_citation(text: str, rows: int = 1) -> dict | None:
    """Query OpenAlex for the best match. Returns None on no result."""
    text = text.strip()
    if not text:
        return None
    try:
        r = _get_session().get(
            OPENALEX_URL,
            params={"search": text, "per-page": rows},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        return {"error": str(e), "doi": None, "title": None, "score": None,
                "authors": "", "year": None, "confidence": "?",
                "container": "", "url": None}

    payload = r.json()
    results = payload.get("results") or []
    if not results:
        return None
    item = results[0]
    container = ""
    primary_loc = item.get("primary_location") or {}
    source = primary_loc.get("source") or {}
    if source.get("display_name"):
        container = source["display_name"]

    return {
        "doi": _strip_doi_prefix(item.get("doi")),
        "title": item.get("title") or item.get("display_name") or "",
        "authors": _format_authors(item.get("authorships") or []),
        "year": item.get("publication_year"),
        "container": container,
        "score": item.get("relevance_score"),
        "confidence": _normalise_score(item.get("relevance_score")),
        "url": item.get("doi") or item.get("id"),
        "source": "openalex",
    }
