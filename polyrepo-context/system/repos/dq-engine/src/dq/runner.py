from __future__ import annotations

from platform_sdk import MetadataClient, events

from .rules import RULES

DEFAULT_BINDINGS = {"string": ["not_null"], "integer": ["not_null"]}


def run_batch(metadata: MetadataClient, payload: dict, read_batch) -> dict:
    urn = payload["dataset_urn"]
    columns = metadata.get_columns(urn)
    data = read_batch(payload["path"])
    results = []
    for col in columns:
        for rule in DEFAULT_BINDINGS.get(col.data_type, []):
            results.append({"column": col.name, "rule": rule,
                            "passed": RULES[rule](data[col.name])})
    score = sum(r["passed"] for r in results) / max(len(results), 1)
    events.publish("dq.result.published.v1", {
        "event_id": events.new_event_id(), "dataset_urn": urn,
        "batch_id": payload["batch_id"], "score": score, "results": results,
    }, schema_ref="platform-contracts://events/dq.result.published.v1")
    return {"score": score, "results": results}


def register(metadata, read_batch) -> None:
    events.subscribe("ingestion.batch.landed.v1",
                     lambda p: run_batch(metadata, p, read_batch))
