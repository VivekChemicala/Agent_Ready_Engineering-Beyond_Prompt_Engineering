"""Typed models for upstream payloads. Unknown fields are dropped."""
from dataclasses import dataclass, field

PUBLIC = "PUBLIC"
INTERNAL = "INTERNAL"
CONFIDENTIAL = "CONFIDENTIAL"
PII = "PII"
SENSITIVITY_LEVELS = (PUBLIC, INTERNAL, CONFIDENTIAL, PII)
DEFAULT_SENSITIVITY = INTERNAL


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    sensitivity: str = DEFAULT_SENSITIVITY

    @classmethod
    def from_dict(cls, d: dict) -> "Column":
        return cls(
            name=d["name"],
            type=d["type"],
            tags=tuple(d.get("tags", ())),
            sensitivity=d.get("sensitivity") or DEFAULT_SENSITIVITY,
        )
