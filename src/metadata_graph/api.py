"""Metadata API handlers. Each returns (status, body)."""
from platform_contracts import ContractError, validate

from metadata_graph.events import EventPublisher
from metadata_graph.sensitivity import column_out, dataset_out, suggest
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
    names = {c["name"] for c in body["columns"]}
    overrides = {name: level for name, level in store.get_overrides(urn).items() if name in names}
    dataset = {
        "urn": urn,
        "name": body["name"],
        "owner": body["owner"],
        "columns": [
            {
                "name": c["name"],
                "type": c["type"],
                "tags": list(c["tags"]),
                "sensitivity": overrides.get(c["name"]) or suggest(c["tags"]),
            }
            for c in body["columns"]
        ],
    }
    store.put(dataset)
    store.put_overrides(urn, overrides)
    events.dataset_changed(dataset, "UPDATED" if existed else "CREATED")
    return (200 if existed else 201), dataset_out(dataset)


@route("GET", "/v1/datasets/{urn}")
def get_dataset(store: GraphStore, events: EventPublisher, params: dict, body, headers: dict):
    dataset = store.get(params["urn"])
    if dataset is None:
        return error(404, "NOT_FOUND", f"dataset {params['urn']} not found")
    return 200, dataset_out(dataset)


@route("GET", "/v1/datasets/{urn}/columns")
def get_columns(store: GraphStore, events: EventPublisher, params: dict, body, headers: dict):
    dataset = store.get(params["urn"])
    if dataset is None:
        return error(404, "NOT_FOUND", f"dataset {params['urn']} not found")
    response = {"urn": dataset["urn"], "columns": [column_out(c) for c in dataset["columns"]]}
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
    return 200, dataset_out(dataset)


@route("PUT", "/v1/datasets/{urn}/columns/{column}/sensitivity")
def set_column_sensitivity(store: GraphStore, events: EventPublisher, params: dict, body, headers: dict):
    if not _is_steward(headers):
        return error(403, "FORBIDDEN", "steward role required")
    urn, name = params["urn"], params["column"]
    dataset = store.get(urn)
    if dataset is None:
        return error(404, "NOT_FOUND", f"dataset {urn} not found")
    column = next((c for c in dataset["columns"] if c["name"] == name), None)
    if column is None:
        return error(404, "NOT_FOUND", f"column {name} not found in dataset {urn}")
    try:
        validate("metadata.dataset.column.sensitivity.request.v1", body)
    except ContractError as exc:
        return error(400, "INVALID_REQUEST", str(exc))
    column["sensitivity"] = body["sensitivity"]
    overrides = store.get_overrides(urn)
    overrides[name] = body["sensitivity"]
    store.put(dataset)
    store.put_overrides(urn, overrides)
    events.dataset_changed(dataset, "UPDATED")
    return 200, column_out(column)
