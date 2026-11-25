from __future__ import annotations

from platform_sdk import events

from .metadata_store import MetadataStore
from .model import Column, Dataset
from .publisher import publish_dataset_changed

TOPIC_SCHEMA_DISCOVERED = "ingestion.schema.discovered.v1"
TOPIC_TRANSFORMATION_RESULT = "transformation.result.published.v1"


def on_schema_discovered(store: MetadataStore, payload: dict) -> Dataset:
    """Create or update a dataset from an ingestion schema-discovery event."""
    columns = [
        Column(name=c["name"], data_type=c["type"],
               nullable=c.get("nullable", True))
        for c in payload["columns"]
    ]
    existing = store.get(payload["dataset_urn"])
    if existing is None:
        ds = Dataset(urn=payload["dataset_urn"], name=payload["dataset_name"],
                     domain=payload["domain"], owner=payload.get("owner", "unassigned"),
                     columns=columns, updated_at=payload["discovered_at"])
        store.upsert(ds)
        publish_dataset_changed(ds, "CREATED")
        return ds
    existing.columns = columns
    existing.updated_at = payload["discovered_at"]
    store.upsert(existing)
    publish_dataset_changed(existing, "COLUMNS_CHANGED")
    return existing


def on_transformation_result(store: MetadataStore, payload: dict) -> None:
    ds = store.get(payload["dataset_urn"])
    if ds is None:
        return
    ds.quality_score = payload["score"]
    store.upsert(ds)
    publish_dataset_changed(ds, "UPDATED")


def register(store: MetadataStore) -> None:
    events.subscribe(TOPIC_SCHEMA_DISCOVERED,
                     lambda p: on_schema_discovered(store, p))
    events.subscribe(TOPIC_TRANSFORMATION_RESULT, lambda p: on_transformation_result(store, p))
