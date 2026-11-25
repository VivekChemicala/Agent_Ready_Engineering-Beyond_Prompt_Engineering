from __future__ import annotations

from .model import Dataset


class MetadataStore:
    """In-memory stand-in for the metadata database."""

    def __init__(self) -> None:
        self._datasets: dict[str, Dataset] = {}

    def get(self, urn: str) -> Dataset | None:
        return self._datasets.get(urn)

    def upsert(self, dataset: Dataset) -> Dataset:
        self._datasets[dataset.urn] = dataset
        return dataset

    def all(self) -> list[Dataset]:
        return list(self._datasets.values())
