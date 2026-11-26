"""Metadata API handlers. Each returns (status, body)."""
from platform_contracts import ContractError, validate

from metadata_graph.events import EventPublisher, column_view
from metadata_graph.sensitivity import suggest_sensitivity
from metadata_graph.store import GraphStore

ROUTES: list[tuple[str, str, object]] = []


def route(method: str, pattern: str):
    def deco(fn):
        ROUTES.append((method, pattern, fn))
        return fn
    return deco


def error(status: int, code: str, message: str):
    return status, {"error": {"code": code, "message": message}}


def _is_steward(headers: dict) -> bool:
    roles = headers.get("X-Roles", "")
    return "steward" in {r.strip() for r in roles.split(",")}


@route("POST", "/v1/datasets")
def register_dataset(store: GraphStore, events: EventPublisher, params: dict, body, headers: dict):
    try:
        validate("metadata.dataset.register.request.v1", body)
    except ContractError as exc:
        return error(400, "INVALID_REQUEST", str(exc))
    urn = body["urn"]
    existed = store.exists(urn)
    previous = store.get(urn) if existed else None
    kept_levels = {}
    if previous is not None:
        overridden = store.overrides(urn)
        kept_levels = {c["name"]: c.get("sensitivity") for c in previous["columns"] if c["name"] in overridden}
    columns = []
    for c in body["columns"]:
        level = kept_levels.get(c["name"]) or suggest_sensitivity(c["tags"])
        columns.append({"name": c["name"], "type": c["type"], "tags": list(c["tags"]), "sensitivity": level})
    dataset = {"urn": urn, "name": body["name"], "owner": body["owner"], "columns": columns}
    store.put(dataset)
    store.set_overrides(urn, {c["name"] for c in columns if c["name"] in kept_levels})
    events.dataset_changed(dataset, "UPDATED" if existed else "CREATED")
    return (200 if existed else 201), dataset


@route("GET", "/v1/datasets/{urn}")
def get_dataset(store: GraphStore, events: EventPublisher, params: dict, body, headers: dict):
    dataset = store.get(params["urn"])
    if dataset is None:
        return error(404, "NOT_FOUND", f"dataset {params['urn']} not found")
    return 200, dataset


@route("GET", "/v1/datasets/{urn}/columns")
def get_columns(store: GraphStore, events: EventPublisher, params: dict, body, headers: dict):
    dataset = store.get(params["urn"])
    if dataset is None:
        return error(404, "NOT_FOUND", f"dataset {params['urn']} not found")
    response = {"urn": dataset["urn"], "columns": [column_view(c) for c in dataset["columns"]]}
    validate("metadata.columns.response.v1", response)
    return 200, response


@route("PUT", "/v1/datasets/{urn}/owner")
def set_owner(store: GraphStore, events: EventPublisher, params: dict, body, headers: dict):
    if not _is_steward(headers):
        return error(403, "FORBIDDEN", "steward role required")
    dataset = store.get(params["urn"])
    if dataset is None:
        return error(404, "NOT_FOUND", f"dataset {params['urn']} not found")
    try:
        validate("metadata.dataset.owner.request.v1", body)
    except ContractError as exc:
        return error(400, "INVALID_REQUEST", str(exc))
    dataset["owner"] = body["owner"]
    store.put(dataset)
    events.dataset_changed(dataset, "UPDATED")
    return 200, dataset


@route("PUT", "/v1/datasets/{urn}/columns/{column}/sensitivity")
def set_sensitivity(store: GraphStore, events: EventPublisher, params: dict, body, headers: dict):
    if not _is_steward(headers):
        return error(403, "FORBIDDEN", "steward role required")
    dataset = store.get(params["urn"])
    if dataset is None:
        return error(404, "NOT_FOUND", f"dataset {params['urn']} not found")
    column = next((c for c in dataset["columns"] if c["name"] == params["column"]), None)
    if column is None:
        return error(404, "NOT_FOUND", f"column {params['column']} not found in dataset {params['urn']}")
    try:
        validate("metadata.column.sensitivity.request.v1", body)
    except ContractError as exc:
        return error(400, "INVALID_REQUEST", str(exc))
    column["sensitivity"] = body["sensitivity"]
    store.put(dataset)
    store.set_overrides(dataset["urn"], store.overrides(dataset["urn"]) | {column["name"]})
    events.dataset_changed(dataset, "UPDATED")
    return 200, column_view(column)
