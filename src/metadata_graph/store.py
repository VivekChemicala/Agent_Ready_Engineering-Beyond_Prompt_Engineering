"""In-memory dataset store."""
import copy


class GraphStore:
    def __init__(self):
        self._datasets: dict[str, dict] = {}

    def get(self, urn: str) -> dict | None:
        ds = self._datasets.get(urn)
        return copy.deepcopy(ds) if ds else None

    def put(self, dataset: dict) -> None:
        self._datasets[dataset["urn"]] = copy.deepcopy(dataset)

    def exists(self, urn: str) -> bool:
        return urn in self._datasets
