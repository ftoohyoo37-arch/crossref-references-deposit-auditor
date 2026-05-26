"""Probe a URL and figure out which platform it belongs to.

The probe makes a single GET (with a short timeout + polite User-Agent),
parses minimal HTML, and walks the platform registry. Returns a
ProbeResult with the matched Platform plus pre-filled identity guesses
the wizard can show on the next step.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

from . import platforms


USER_AGENT = "journal-pipeline-wizard/0.1 (+local research tool)"


@dataclass
class ProbeResult:
    url: str
    final_url: str            # after redirects
    platform_key: str         # 'wac' | 'ojs' | 'unknown'
    platform_label: str
    name_guess: str
    slug_guess: str
    batch_prefix_guess: str
    ok: bool = True
    error: str = ""
    page_title: str = ""


def _extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    title = re.sub(r"\s+", " ", m.group(1)).strip()
    return title[:120]


def probe(url: str, timeout: float = 12.0) -> ProbeResult:
    """Fetch the URL, sniff the response, return a ProbeResult.

    Failure modes (connection refused, timeout, 404) still return a
    ProbeResult — they just default to the 'unknown' platform with an
    error string the UI can surface.
    """
    if not url or not urlparse(url).scheme:
        unk = platforms.by_key("unknown")
        name, slug, prefix = unk.default_slug(url)
        return ProbeResult(
            url=url, final_url=url,
            platform_key=unk.key, platform_label=unk.label,
            name_guess=name, slug_guess=slug, batch_prefix_guess=prefix,
            ok=False, error="URL must include a scheme (http:// or https://)",
        )

    try:
        r = requests.get(
            url, timeout=timeout, allow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )
        html = r.text if r.ok else ""
        final_url = str(r.url)
        ok = r.ok
        err = "" if r.ok else f"HTTP {r.status_code}"
        page_title = _extract_title(html)
    except requests.RequestException as e:
        html = ""
        final_url = url
        ok = False
        err = f"Probe failed: {type(e).__name__}: {e}"
        page_title = ""

    matched = None
    for plat in platforms.PLATFORMS:
        if plat.key == "unknown":
            continue
        try:
            if plat.detect(final_url, html):
                matched = plat
                break
        except Exception:
            continue
    if matched is None:
        matched = platforms.by_key("unknown")

    name, slug, prefix = matched.default_slug(final_url)
    # Prefer page title as the journal name when it looks plausible
    if page_title and len(page_title) >= 4 and "404" not in page_title:
        # Trim common suffixes like " | OJS" or " — Archive"
        clean_title = re.split(r"\s*[|·•]\s*", page_title, maxsplit=1)[0].strip()
        if clean_title and clean_title.lower() not in (name.lower(),):
            name = clean_title[:80]

    return ProbeResult(
        url=url, final_url=final_url,
        platform_key=matched.key, platform_label=matched.label,
        name_guess=name, slug_guess=slug, batch_prefix_guess=prefix,
        ok=ok, error=err, page_title=page_title,
    )
