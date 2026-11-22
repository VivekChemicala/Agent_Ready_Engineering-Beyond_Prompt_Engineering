from __future__ import annotations

from . import consumers
from .api import ROUTES
from .graph_store import GraphStore


def main() -> None:
    store = GraphStore()
    consumers.register(store)
    print(f"metadata-graph serving {len(ROUTES)} routes")


if __name__ == "__main__":
    main()
