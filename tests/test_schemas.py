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


@pytest.mark.parametrize("schema", COLUMN_SCHEMAS)
def test_column_sensitivity_is_optional(schema):
    payload = _column_payload(schema)
    payload["columns"][0]["sensitivity"] = "PII"
    assert "sensitivity" not in payload["columns"][1]
    validate(schema, payload)


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
