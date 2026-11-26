"""Publishes metadata.dataset.changed.v1 events to a sink (a list in tests, a topic in production)."""
from platform_contracts import DEFAULT_SENSITIVITY, validate

TOPIC = "metadata.dataset.changed.v1"


def column_view(column: dict) -> dict:
    """Public shape of a column: name, type, tags and sensitivity (INTERNAL when absent)."""
    return {
        "name": column["name"],
        "type": column["type"],
        "tags": list(column["tags"]),
        "sensitivity": column.get("sensitivity") or DEFAULT_SENSITIVITY,
    }


class EventPublisher:
    def __init__(self, sink: list):
        self.sink = sink

    def dataset_changed(self, dataset: dict, change: str) -> dict:
        event = {
            "event_type": "metadata.dataset.changed",
            "urn": dataset["urn"],
            "change": change,
            "owner": dataset["owner"],
            "columns": [column_view(c) for c in dataset["columns"]],
        }
        validate(TOPIC, event)
        self.sink.append(event)
        return event
