import json
from pathlib import Path

import pytest

import platform_contracts
from platform_contracts import ContractError, validate

FIXTURES = sorted((Path(__file__).parent / "fixtures").glob("*.json"))
VERSION_FILE = Path(__file__).parent.parent / "VERSION"


def test_version_file_matches_package():
    assert VERSION_FILE.read_text().strip() == platform_contracts.__version__


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
def test_previous_release_payloads_stay_valid(fixture):
    doc = json.loads(fixture.read_text())
    validate(doc["schema"], doc["payload"])


def test_schemas_are_closed():
    doc = json.loads((Path(__file__).parent / "fixtures" / "dataset_changed.json").read_text())
    doc["payload"]["unexpected"] = 1
    with pytest.raises(ContractError):
        validate(doc["schema"], doc["payload"])


def test_column_fields_are_closed():
    doc = json.loads((Path(__file__).parent / "fixtures" / "columns_response.json").read_text())
    doc["payload"]["columns"][0]["colour"] = "blue"
    with pytest.raises(ContractError):
        validate(doc["schema"], doc["payload"])


COLUMN_SCHEMAS = ["metadata.columns.response.v1", "metadata.dataset.changed.v1"]
SENSITIVITY_REQUEST = "metadata.dataset.column.sensitivity.request.v1"


def _fixture(name):
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


def _column_payload(schema):
    name = {"metadata.columns.response.v1": "columns_response.json",
            "metadata.dataset.changed.v1": "dataset_changed.json"}[schema]
    return _fixture(name)["payload"]


def test_sensitivity_levels_are_ordered_least_to_most_restrictive():
    assert platform_contracts.SENSITIVITY_LEVELS == ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII")
    assert platform_contracts.DEFAULT_SENSITIVITY == "INTERNAL"


@pytest.mark.parametrize("schema", COLUMN_SCHEMAS)
@pytest.mark.parametrize("level", ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII"])
def test_columns_accept_every_sensitivity_level(schema, level):
    payload = _column_payload(schema)
    for column in payload["columns"]:
        column["sensitivity"] = level
    validate(schema, payload)


def test_column_sensitivity_is_optional_per_column_in_columns_response():
    payload = _column_payload("metadata.columns.response.v1")
    payload["columns"][0]["sensitivity"] = "PII"
    assert "sensitivity" not in payload["columns"][1]
    validate("metadata.columns.response.v1", payload)


@pytest.mark.parametrize("schema", COLUMN_SCHEMAS)
@pytest.mark.parametrize("bad", ["pii", "SECRET", "", None, 1])
def test_columns_reject_unknown_sensitivity(schema, bad):
    payload = _column_payload(schema)
    payload["columns"][0]["sensitivity"] = bad
    with pytest.raises(ContractError):
        validate(schema, payload)


def test_schema_enums_match_package_levels():
    from platform_contracts import load_schema
    for schema in COLUMN_SCHEMAS:
        enum = load_schema(schema)["properties"]["columns"]["items"]["properties"]["sensitivity"]["enum"]
        assert tuple(enum) == platform_contracts.SENSITIVITY_LEVELS
    enum = load_schema(SENSITIVITY_REQUEST)["properties"]["sensitivity"]["enum"]
    assert tuple(enum) == platform_contracts.SENSITIVITY_LEVELS


def test_register_request_is_unchanged():
    payload = _fixture("register_request.json")["payload"]
    payload["columns"][0]["sensitivity"] = "PII"
    with pytest.raises(ContractError):
        validate("metadata.dataset.register.request.v1", payload)


@pytest.mark.parametrize("level", ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII"])
def test_sensitivity_request_accepts_every_level(level):
    validate(SENSITIVITY_REQUEST, {"sensitivity": level})


@pytest.mark.parametrize("body", [
    {},
    {"sensitivity": "pii"},
    {"sensitivity": "SECRET"},
    {"sensitivity": None},
    {"sensitivity": 3},
    {"sensitivity": "PII", "reason": "x"},
    ["PII"],
    "PII",
    None,
])
def test_sensitivity_request_rejects_invalid_bodies(body):
    with pytest.raises(ContractError):
        validate(SENSITIVITY_REQUEST, body)


def _event(change, owner, columns):
    return {"event_type": "metadata.dataset.changed", "urn": "urn:ds:crm.customers",
            "change": change, "owner": owner, "columns": columns}


def _col(name, tags, level):
    return {"name": name, "type": "string", "tags": tags, "sensitivity": level}


EMITTED_EVENTS = {
    "create": _event("CREATED", "team-crm", [
        _col("customer_id", ["key"], "INTERNAL"), _col("email", ["pii"], "PII")]),
    "override": _event("UPDATED", "team-crm", [
        _col("customer_id", ["key"], "PUBLIC"), _col("email", ["pii"], "PII")]),
    "owner_change": _event("UPDATED", "team-sales", [
        _col("customer_id", ["key"], "PUBLIC"), _col("email", ["pii"], "PII")]),
    "re_register_with_new_column": _event("UPDATED", "team-crm", [
        _col("customer_id", ["key"], "PUBLIC"), _col("email", ["pii"], "PII"),
        _col("vip_notes", ["confidential", "public"], "CONFIDENTIAL")]),
}


@pytest.mark.parametrize("path", sorted(EMITTED_EVENTS))
def test_every_emitted_event_with_levels_is_valid(path):
    validate("metadata.dataset.changed.v1", EMITTED_EVENTS[path])


@pytest.mark.parametrize("path", sorted(EMITTED_EVENTS))
@pytest.mark.parametrize("missing", [0, -1])
def test_event_with_a_level_missing_on_some_column_is_rejected(path, missing):
    event = json.loads(json.dumps(EMITTED_EVENTS[path]))
    del event["columns"][missing]["sensitivity"]
    with pytest.raises(ContractError, match="missing sensitivity"):
        validate("metadata.dataset.changed.v1", event)


def test_event_without_any_level_stays_valid():
    payload = _fixture("dataset_changed.json")["payload"]
    assert all("sensitivity" not in c for c in payload["columns"])
    validate("metadata.dataset.changed.v1", payload)


def test_columns_response_tolerates_columns_without_level():
    payload = _column_payload("metadata.columns.response.v1")
    payload["columns"][1]["sensitivity"] = "PII"
    validate("metadata.columns.response.v1", payload)


def test_all_or_none_keyword():
    schema = {"type": "array", "items": {"type": "object"}, "x-itemsAllOrNone": ["a"]}
    from platform_contracts.validator import _check
    _check([], schema, "$")
    _check([{}, {}], schema, "$")
    _check([{"a": 1}, {"a": 2}], schema, "$")
    with pytest.raises(ContractError, match=r"\$\[1\]: missing a"):
        _check([{"a": 1}, {}], schema, "$")


INVALID_LEVELS = ["pii", "Pii", "public", "PII ", " PII", "P II", "", "SECRET", "RESTRICTED", "UNKNOWN",
                  None, 0, 1, 3, True, False, 1.0, [], ["PII"], {}, {"level": "PII"}]


def _level_payloads(level):
    column = {"name": "email", "type": "string", "tags": ["pii"], "sensitivity": level}
    return [
        (SENSITIVITY_REQUEST, {"sensitivity": level}),
        ("metadata.columns.response.v1", {"urn": "urn:ds:x", "columns": [dict(column)]}),
        ("metadata.dataset.changed.v1", _event("UPDATED", "team-crm", [dict(column)])),
    ]


@pytest.mark.parametrize("level", INVALID_LEVELS, ids=repr)
def test_every_contract_rejects_levels_outside_the_four(level):
    for schema, payload in _level_payloads(level):
        with pytest.raises(ContractError):
            validate(schema, payload)


@pytest.mark.parametrize("level", ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII"])
def test_every_contract_accepts_the_four_levels(level):
    for schema, payload in _level_payloads(level):
        validate(schema, payload)


def test_every_sensitivity_property_is_restricted_to_the_four_levels():
    from platform_contracts import load_schema
    from platform_contracts.validator import SCHEMA_DIR

    found = []

    def walk(node, where):
        if isinstance(node, dict):
            props = node.get("properties", {})
            if "sensitivity" in props:
                found.append(where)
                assert props["sensitivity"] == {"type": "string", "enum": list(platform_contracts.SENSITIVITY_LEVELS)}
            for key, child in node.items():
                walk(child, f"{where}.{key}")
        elif isinstance(node, list):
            for child in node:
                walk(child, where)

    for path in SCHEMA_DIR.glob("*.json"):
        walk(load_schema(path.stem), path.stem)
    assert len(found) == 3


def test_enum_is_type_exact():
    from platform_contracts.validator import _check
    with pytest.raises(ContractError):
        _check(True, {"enum": [1]}, "$")
    with pytest.raises(ContractError):
        _check(1.0, {"enum": [1]}, "$")
    _check(1, {"enum": [1]}, "$")


def test_column_sensitivity_helper():
    from platform_contracts import column_sensitivity
    assert column_sensitivity({"name": "a"}) == "INTERNAL"
    for level in platform_contracts.SENSITIVITY_LEVELS:
        assert column_sensitivity({"sensitivity": level}) == level
    for level in INVALID_LEVELS:
        with pytest.raises(ContractError):
            column_sensitivity({"sensitivity": level})
