"""REST API. Spec of record lives in platform-contracts (openapi/metadata-service.yaml)."""

from __future__ import annotations

from .metadata_store import MetadataStore
from .publisher import publish_dataset_changed

ROUTES = {}


def route(method: str, path: str):
    def wrap(fn):
        ROUTES[(method, path)] = fn
        return fn
    return wrap


@route("GET", "/v1/datasets/{urn}")
def get_dataset(store: MetadataStore, urn: str):
    ds = store.get(urn)
    if ds is None:
        return 404, {"error": "NOT_FOUND"}
    return 200, {"urn": ds.urn, "name": ds.name, "domain": ds.domain,
                 "owner": ds.owner, "quality_score": ds.quality_score,
                 "updated_at": ds.updated_at}


@route("GET", "/v1/datasets/{urn}/columns")
def get_columns(store: MetadataStore, urn: str):
    ds = store.get(urn)
    if ds is None:
        return 404, {"error": "NOT_FOUND"}
    return 200, {"urn": ds.urn, "columns": [
        {"name": c.name, "data_type": c.data_type, "nullable": c.nullable,
         "description": c.description} for c in ds.columns]}


@route("PUT", "/v1/datasets/{urn}/owner")
def set_owner(store: MetadataStore, urn: str, body: dict):
    ds = store.get(urn)
    if ds is None:
        return 404, {"error": "NOT_FOUND"}
    ds.owner = body["owner"]
    store.upsert(ds)
    publish_dataset_changed(ds, "UPDATED")
    return 200, {"urn": ds.urn, "owner": ds.owner}
