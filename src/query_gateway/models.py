"""Typed models for upstream payloads. Unknown fields are dropped."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    tags: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, d: dict) -> "Column":
        return cls(name=d["name"], type=d["type"], tags=tuple(d.get("tags", ())))
