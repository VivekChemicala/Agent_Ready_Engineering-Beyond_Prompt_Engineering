"""Publishes metadata.dataset.changed.v1 events to a sink (a list in tests, a topic in production)."""
from platform_contracts import validate

from metadata_graph.sensitivity import level_of

TOPIC = "metadata.dataset.changed.v1"


class EventPublisher:
    def __init__(self, sink: list):
        self.sink = sink

    def dataset_changed(self, dataset: dict, change: str) -> dict:
        event = {
            "event_type": "metadata.dataset.changed",
            "urn": dataset["urn"],
            "change": change,
            "owner": dataset["owner"],
            "columns": [{**c, "sensitivity": level_of(c)} for c in dataset["columns"]],
        }
        validate(TOPIC, event)
        self.sink.append(event)
        return event
