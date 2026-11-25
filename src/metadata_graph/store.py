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

    def overrides(self, urn: str) -> dict[str, str]:
        """Steward sensitivity overrides of a dataset, by column name."""
        return dict(self._overrides.get(urn, {}))

    def set_overrides(self, urn: str, overrides: dict[str, str]) -> None:
        self._overrides[urn] = dict(overrides)
