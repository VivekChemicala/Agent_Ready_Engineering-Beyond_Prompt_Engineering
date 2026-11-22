from __future__ import annotations

import json
from pathlib import Path

import jsonschema

SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "schemas"
                     / "metadata.dataset.changed.v1.json").read_text())
TOPIC = "metadata.dataset.changed.v1"
DLQ = "search-indexer.dlq"


def handle(payload: dict, index, dlq) -> bool:
    try:
        jsonschema.validate(payload, SCHEMA)
    except jsonschema.ValidationError as exc:
        dlq.send(DLQ, {"payload": payload, "error": exc.message})
        return False
    ds = payload["dataset"]
    index.upsert(ds["urn"], {"name": ds["name"], "domain": ds["domain"],
                             "owner": ds["owner"],
                             "columns": [c["name"] for c in ds["columns"]]})
    return True
