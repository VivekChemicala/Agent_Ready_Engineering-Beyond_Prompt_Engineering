from __future__ import annotations

from datetime import datetime, timezone

from platform_sdk import events

from .model import Dataset

TOPIC_DATASET_CHANGED = "metadata.dataset.changed.v1"
SCHEMA_REF = "platform-contracts://events/metadata.dataset.changed.v1"


def dataset_changed_payload(dataset: Dataset, change_type: str) -> dict:
    return {
        "event_id": events.new_event_id(),
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "change_type": change_type,  # CREATED | UPDATED | COLUMNS_CHANGED
        "dataset": {
            "urn": dataset.urn,
            "name": dataset.name,
            "domain": dataset.domain,
            "owner": dataset.owner,
            "columns": [
                {"name": c.name, "data_type": c.data_type, "nullable": c.nullable}
                for c in dataset.columns
            ],
        },
    }


def publish_dataset_changed(dataset: Dataset, change_type: str) -> None:
    events.publish(TOPIC_DATASET_CHANGED,
                   dataset_changed_payload(dataset, change_type),
                   schema_ref=SCHEMA_REF)
