from __future__ import annotations

import json
from typing import Any

from auditor.models import Finding


def to_json(meta: dict[str, Any], findings: list[Finding]) -> bytes:
    payload = {
        "audit": meta,
        "findings": [f.to_dict() for f in findings],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
