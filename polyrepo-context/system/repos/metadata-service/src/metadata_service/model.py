from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Column:
    name: str
    data_type: str
    nullable: bool = True
    description: str | None = None


@dataclass
class Dataset:
    urn: str
    name: str
    domain: str
    owner: str
    columns: list[Column] = field(default_factory=list)
    quality_score: float | None = None
    updated_at: str | None = None

    def column(self, name: str) -> Column | None:
        return next((c for c in self.columns if c.name == name), None)
