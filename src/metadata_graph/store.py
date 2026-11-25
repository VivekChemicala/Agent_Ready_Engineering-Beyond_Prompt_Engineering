"""In-memory dataset store."""
import copy


class GraphStore:
    def __init__(self):
        self._datasets: dict[str, dict] = {}
        self._overrides: dict[str, set[str]] = {}

    def get(self, urn: str) -> dict | None:
        ds = self._datasets.get(urn)
        return copy.deepcopy(ds) if ds else None

    def put(self, dataset: dict) -> None:
        self._datasets[dataset["urn"]] = copy.deepcopy(dataset)

    def exists(self, urn: str) -> bool:
        return urn in self._datasets

    def overridden_columns(self, urn: str) -> set[str]:
        """Names of the dataset's columns whose sensitivity a steward set (internal bookkeeping)."""
        return set(self._overrides.get(urn, set()))

    def set_overridden_columns(self, urn: str, names) -> None:
        self._overrides[urn] = set(names)
