"""Platform protocol — what every platform module must define.

Each platform module exports a single `PLATFORM` instance of `Platform`.
The dispatch in `__init__.py::PLATFORMS` walks the list and the first
hit wins, so order matters (specific before generic).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Platform:
    """A hosting platform we know how to scaffold for.

    Fields:
      key: stable identifier used in URLs/forms ("wac", "ojs", "unknown")
      label: human-readable name shown in the UI
      detect: function (url, html_text) -> bool. Receives the probed URL
              and the body of the GET on that URL (may be empty if the
              probe failed). Returns True if this platform recognises the URL.
      default_slug: function (url) -> tuple[str, str, str] returning
                    (journal_name_guess, journal_slug_guess, batch_prefix_guess)
                    to pre-fill the wizard's "identity" step. Best-effort.
      scaffold: function (journal_dir: Path, ctx: dict) -> None writes the
                generated files into journal_dir. `ctx` contains the
                wizard's collected form data.
      notes: list[str] of platform-specific caveats shown to the user
             before they commit the wizard.
    """
    key: str
    label: str
    detect: Callable
    default_slug: Callable
    scaffold: Callable
    notes: list[str] = field(default_factory=list)


def _basic_slug(name: str) -> str:
    """Convert a journal name to a URL-safe lowercase slug."""
    out = []
    for ch in name.lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "-", "_"):
            out.append("-")
    s = "".join(out)
    # Collapse runs of dashes
    while "--" in s:
        s = s.replace("--", "-")
    return s.strip("-")
