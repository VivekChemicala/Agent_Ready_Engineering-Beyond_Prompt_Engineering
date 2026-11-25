"""Typed models for upstream payloads. Unknown fields are dropped."""
from dataclasses import dataclass, field

PUBLIC = "PUBLIC"
INTERNAL = "INTERNAL"
CONFIDENTIAL = "CONFIDENTIAL"
PII = "PII"
SENSITIVITY_LEVELS = (PUBLIC, INTERNAL, CONFIDENTIAL, PII)
DEFAULT_SENSITIVITY = INTERNAL


def _level(value) -> str | None:
    """A level from a plain string or from an object such as {"level": ..., "override": ...}."""
    if isinstance(value, str):
        return value if value in SENSITIVITY_LEVELS else None
    if isinstance(value, dict):
        for key in ("override", "steward", "effective", "level", "value", "sensitivity", "suggested"):
            level = _level(value.get(key))
            if level:
                return level
    return None


def _is_override_key(key: str) -> bool:
    return "sensitivity" in key and ("override" in key or "steward" in key)


def effective_sensitivity(d: dict) -> str:
    """The level the gateway enforces for a column payload.

    A steward override wins over the stored/suggested level, whether the upstream sends it
    as the column's `sensitivity` or alongside it; a column without any level is INTERNAL.
    """
    candidates = [v for k, v in d.items() if k == "effective_sensitivity"]
    candidates += [v for k, v in d.items() if _is_override_key(k)]
    candidates.append(d.get("sensitivity"))
    candidates += [v for k, v in d.items() if "sensitivity" in k and "suggest" in k]
    for value in candidates:
        level = _level(value)
        if level:
            return level
    return DEFAULT_SENSITIVITY


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    sensitivity: str = DEFAULT_SENSITIVITY

    @classmethod
    def from_dict(cls, d: dict) -> "Column":
        return cls(name=d["name"], type=d["type"], tags=tuple(d.get("tags", ())),
                   sensitivity=effective_sensitivity(d))
