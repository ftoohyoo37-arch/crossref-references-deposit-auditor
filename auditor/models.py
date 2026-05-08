from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Literal


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    @classmethod
    def coerce(cls, value: str | "Severity") -> "Severity":
        if isinstance(value, cls):
            return value
        return cls(value.lower())


@dataclass
class Finding:
    rule_id: str
    severity: str
    message: str
    line: int | None = None
    xpath: str | None = None
    citation_key: str | None = None
    snippet: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParamMeta:
    name: str
    type: Literal["int", "float", "str", "bool"]
    default: Any
    description: str


@dataclass
class RuleMeta:
    id: str
    name: str
    description: str
    scope: Literal["document", "citation", "post"]
    default_severity: Severity
    default_enabled: bool = True
    params: list[ParamMeta] = field(default_factory=list)


@dataclass
class RuleConfig:
    enabled: bool
    severity: str
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_meta(cls, meta: RuleMeta) -> "RuleConfig":
        return cls(
            enabled=meta.default_enabled,
            severity=meta.default_severity.value,
            params={p.name: p.default for p in meta.params},
        )


@dataclass
class AuditorConfig:
    rules: dict[str, RuleConfig] = field(default_factory=dict)

    def is_rule_enabled(self, rule_id: str) -> bool:
        rc = self.rules.get(rule_id)
        return rc.enabled if rc else True

    def severity(self, rule_id: str, default: str = "warning") -> str:
        rc = self.rules.get(rule_id)
        return rc.severity if rc else default

    def param(self, rule_id: str, name: str, default: Any) -> Any:
        rc = self.rules.get(rule_id)
        if not rc:
            return default
        return rc.params.get(name, default)

    def to_dict(self) -> dict[str, Any]:
        return {"rules": {rid: asdict(rc) for rid, rc in self.rules.items()}}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditorConfig":
        rules: dict[str, RuleConfig] = {}
        for rid, rc in data.get("rules", {}).items():
            rules[rid] = RuleConfig(
                enabled=bool(rc.get("enabled", True)),
                severity=str(rc.get("severity", "warning")),
                params=dict(rc.get("params", {})),
            )
        return cls(rules=rules)

    @classmethod
    def load(cls, path: Path) -> "AuditorConfig":
        if not path.exists():
            return cls()
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save(self, path: Path) -> None:
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(path)

    def merged_with_defaults(self, registry_metas: list[RuleMeta]) -> "AuditorConfig":
        """Ensure every registered rule has a config entry, filling defaults."""
        merged = AuditorConfig(rules=dict(self.rules))
        for meta in registry_metas:
            if meta.id not in merged.rules:
                merged.rules[meta.id] = RuleConfig.from_meta(meta)
            else:
                rc = merged.rules[meta.id]
                for p in meta.params:
                    rc.params.setdefault(p.name, p.default)
        return merged
