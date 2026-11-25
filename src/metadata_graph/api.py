"""Metadata API handlers. Each returns (status, body)."""
from platform_contracts import ContractError, validate

from metadata_graph.events import EventPublisher
from metadata_graph.sensitivity import LEVELS, level_of, suggest
from metadata_graph.store import GraphStore

# Contract schema for the sensitivity override body; validated locally as well, see _validate_sensitivity_body.
SENSITIVITY_REQUEST_SCHEMA = "metadata.column.sensitivity.request.v1"

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


def _with_levels(columns: list[dict]) -> list[dict]:
    return [{**c, "sensitivity": level_of(c)} for c in columns]


def _validate_sensitivity_body(body) -> None:
    try:
        validate(SENSITIVITY_REQUEST_SCHEMA, body)
    except ContractError as exc:
        if not str(exc).startswith("unknown schema"):
            raise
    if not isinstance(body, dict) or set(body) != {"sensitivity"}:
        raise ContractError('$: body must be {"sensitivity": "<LEVEL>"}')
    if body["sensitivity"] not in LEVELS:
        raise ContractError(f"$.sensitivity: {body['sensitivity']!r} not in {list(LEVELS)}")


@route("POST", "/v1/datasets")
def register_dataset(store: GraphStore, events: EventPublisher, params: dict, body, headers: dict):
    try:
        validate("metadata.dataset.register.request.v1", body)
    except ContractError as exc:
        return error(400, "INVALID_REQUEST", str(exc))
    existed = store.exists(body["urn"])
    names = {c["name"] for c in body["columns"]}
    overrides = {n: level for n, level in store.overrides(body["urn"]).items() if n in names}
    dataset = {
        "urn": body["urn"],
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
    store.set_overrides(body["urn"], overrides)
    events.dataset_changed(dataset, "UPDATED" if existed else "CREATED")
    return (200 if existed else 201), dataset


@route("GET", "/v1/datasets/{urn}")
def get_dataset(store: GraphStore, events: EventPublisher, params: dict, body, headers: dict):
    dataset = store.get(params["urn"])
    if dataset is None:
        return error(404, "NOT_FOUND", f"dataset {params['urn']} not found")
    dataset["columns"] = _with_levels(dataset["columns"])
    return 200, dataset


@route("GET", "/v1/datasets/{urn}/columns")
def get_columns(store: GraphStore, events: EventPublisher, params: dict, body, headers: dict):
    dataset = store.get(params["urn"])
    if dataset is None:
        return error(404, "NOT_FOUND", f"dataset {params['urn']} not found")
    response = {"urn": dataset["urn"], "columns": _with_levels(dataset["columns"])}
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
    dataset["columns"] = _with_levels(dataset["columns"])
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
        _validate_sensitivity_body(body)
    except ContractError as exc:
        return error(400, "INVALID_REQUEST", str(exc))
    column["sensitivity"] = body["sensitivity"]
    overrides = store.overrides(dataset["urn"])
    overrides[column["name"]] = body["sensitivity"]
    events.dataset_changed(dataset, "UPDATED")
    store.put(dataset)
    store.set_overrides(dataset["urn"], overrides)
    return 200, dict(column)
