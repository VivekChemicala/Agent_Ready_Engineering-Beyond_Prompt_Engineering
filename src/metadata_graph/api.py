"""Metadata API handlers. Each returns (status, body)."""
from platform_contracts import ContractError, validate

from metadata_graph import sensitivity
from metadata_graph.events import EventPublisher
from metadata_graph.store import GraphStore

SENSITIVITY_REQUEST = "metadata.column.sensitivity.request.v1"

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


def _column(source: dict, override: str | None) -> dict:
    return {
        "name": source["name"],
        "type": source["type"],
        "tags": list(source["tags"]),
        "sensitivity": override or sensitivity.suggest(source["tags"]),
    }


@route("POST", "/v1/datasets")
def register_dataset(store: GraphStore, events: EventPublisher, params: dict, body, headers: dict):
    try:
        validate("metadata.dataset.register.request.v1", body)
    except ContractError as exc:
        return error(400, "INVALID_REQUEST", str(exc))
    existed = store.exists(body["urn"])
    overrides = store.get_overrides(body["urn"])
    columns = [_column(c, overrides.get(c["name"])) for c in body["columns"]]
    dataset = {"urn": body["urn"], "name": body["name"], "owner": body["owner"], "columns": columns}
    store.put(dataset)
    store.set_overrides(body["urn"], {c["name"]: overrides[c["name"]] for c in columns if c["name"] in overrides})
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
    response = {"urn": dataset["urn"], "columns": [sensitivity.with_level(c) for c in dataset["columns"]]}
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
def set_column_sensitivity(store: GraphStore, events: EventPublisher, params: dict, body, headers: dict):
    if not _is_steward(headers):
        return error(403, "FORBIDDEN", "steward role required")
    dataset = store.get(params["urn"])
    if dataset is None:
        return error(404, "NOT_FOUND", f"dataset {params['urn']} not found")
    column = next((c for c in dataset["columns"] if c["name"] == params["column"]), None)
    if column is None:
        return error(404, "NOT_FOUND", f"column {params['column']} not found in dataset {params['urn']}")
    try:
        validate(SENSITIVITY_REQUEST, body)
    except ContractError as exc:
        return error(400, "INVALID_REQUEST", str(exc))
    column["sensitivity"] = body["sensitivity"]
    store.put(dataset)
    store.set_override(dataset["urn"], column["name"], body["sensitivity"])
    events.dataset_changed(dataset, "UPDATED")
    return 200, column
