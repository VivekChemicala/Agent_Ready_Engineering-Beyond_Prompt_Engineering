"""Tolerant consumer of metadata.dataset.changed.v1."""


class ColumnMeter:
    def __init__(self):
        self._by_dataset: dict[str, tuple[str, int]] = {}

    def on_dataset_changed(self, event: dict) -> None:
        self._by_dataset[event["urn"]] = (event["owner"], len(event.get("columns", [])))

    def columns_by_owner(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for owner, count in self._by_dataset.values():
            totals[owner] = totals.get(owner, 0) + count
        return totals
