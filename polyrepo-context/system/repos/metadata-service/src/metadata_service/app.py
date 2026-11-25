from __future__ import annotations

from . import consumers
from .api import ROUTES
from .metadata_store import MetadataStore


def main() -> None:
    store = MetadataStore()
    consumers.register(store)
    print(f"metadata-service serving {len(ROUTES)} routes")


if __name__ == "__main__":
    main()
