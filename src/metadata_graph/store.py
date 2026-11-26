"""In-memory dataset store."""
import copy


class GraphStore:
    def __init__(self):
        self._datasets: dict[str, dict] = {}
        self._overrides: dict[str, dict[str, str]] = {}

    def get(self, urn: str) -> dict | None:
        ds = self._datasets.get(urn)
        return copy.deepcopy(ds) if ds else None

    def put(self, dataset: dict) -> None:
        self._datasets[dataset["urn"]] = copy.deepcopy(dataset)

    def exists(self, urn: str) -> bool:
        return urn in self._datasets

    def get_overrides(self, urn: str) -> dict[str, str]:
        """Steward sensitivity overrides of a dataset, keyed by column name."""
        return dict(self._overrides.get(urn, {}))

    def set_override(self, urn: str, column: str, sensitivity: str) -> None:
        self._overrides.setdefault(urn, {})[column] = sensitivity

    def retain_overrides(self, urn: str, columns: set[str]) -> None:
        """Discard overrides of columns that are no longer in the dataset."""
        kept = {c: s for c, s in self._overrides.get(urn, {}).items() if c in columns}
        if kept:
            self._overrides[urn] = kept
        else:
            self._overrides.pop(urn, None)
