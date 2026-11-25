import json
from pathlib import Path

import pytest

import platform_contracts
from platform_contracts import ContractError, load_schema, validate

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


FIXTURE_DIR = Path(__file__).parent / "fixtures"
LEVEL_SCHEMAS = [
    "metadata.columns.response.v1",
    "metadata.dataset.changed.v1",
    "metadata.column.sensitivity.request.v1",
]


def _fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text())


def _with_level(schema, level):
    if schema == "metadata.columns.response.v1":
        payload = _fixture("columns_response_with_sensitivity.json")["payload"]
        payload["columns"][1]["sensitivity"] = level
    elif schema == "metadata.dataset.changed.v1":
        payload = _fixture("dataset_changed_with_sensitivity.json")["payload"]
        payload["columns"][1]["sensitivity"] = level
    else:
        payload = {"sensitivity": level}
    return payload


def _enum(schema):
    s = load_schema(schema)
    if schema == "metadata.column.sensitivity.request.v1":
        return s["properties"]["sensitivity"]["enum"]
    return s["properties"]["columns"]["items"]["properties"]["sensitivity"]["enum"]


def test_sensitivity_constants():
    assert platform_contracts.SENSITIVITY_LEVELS == ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII")
    assert platform_contracts.DEFAULT_SENSITIVITY == "INTERNAL"
    assert platform_contracts.DEFAULT_SENSITIVITY in platform_contracts.SENSITIVITY_LEVELS
    assert "SENSITIVITY_LEVELS" in platform_contracts.__all__
    assert "DEFAULT_SENSITIVITY" in platform_contracts.__all__


@pytest.mark.parametrize("schema", LEVEL_SCHEMAS)
def test_schema_enum_matches_sensitivity_levels(schema):
    assert tuple(_enum(schema)) == platform_contracts.SENSITIVITY_LEVELS


@pytest.mark.parametrize("schema", LEVEL_SCHEMAS)
@pytest.mark.parametrize("level", ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII"])
def test_every_level_accepted(schema, level):
    validate(schema, _with_level(schema, level))


@pytest.mark.parametrize("schema", LEVEL_SCHEMAS)
@pytest.mark.parametrize("level", ["SECRET", "pii", "Internal", "", None, 1, ["PII"]])
def test_invalid_level_rejected(schema, level):
    with pytest.raises(ContractError):
        validate(schema, _with_level(schema, level))


@pytest.mark.parametrize("payload", [
    {},
    {"sensitivity": "PII", "reason": "gdpr"},
    {"sensitivity": 3},
    {"sensitivity": True},
    {"level": "PII"},
])
def test_sensitivity_request_rejects_bad_bodies(payload):
    with pytest.raises(ContractError):
        validate("metadata.column.sensitivity.request.v1", payload)


@pytest.mark.parametrize("payload", ["PII", ["PII"], None])
def test_sensitivity_request_must_be_object(payload):
    with pytest.raises(ContractError):
        validate("metadata.column.sensitivity.request.v1", payload)


def test_sensitivity_is_optional_in_columns_and_event():
    for name in ("columns_response.json", "dataset_changed.json"):
        doc = _fixture(name)
        assert all("sensitivity" not in c for c in doc["payload"]["columns"])
        validate(doc["schema"], doc["payload"])
    for schema in LEVEL_SCHEMAS[:2]:
        assert "sensitivity" not in load_schema(schema)["properties"]["columns"]["items"]["required"]


def test_mixed_columns_with_and_without_sensitivity_valid():
    doc = _fixture("dataset_changed_with_sensitivity.json")
    del doc["payload"]["columns"][0]["sensitivity"]
    validate(doc["schema"], doc["payload"])


def test_register_request_rejects_column_sensitivity():
    doc = _fixture("register_request.json")
    doc["payload"]["columns"][1]["sensitivity"] = "PII"
    with pytest.raises(ContractError):
        validate(doc["schema"], doc["payload"])


def test_new_fixtures_carry_expected_levels():
    for name in ("columns_response_with_sensitivity.json", "dataset_changed_with_sensitivity.json"):
        cols = _fixture(name)["payload"]["columns"]
        assert [(c["name"], c["sensitivity"]) for c in cols] == [("customer_id", "INTERNAL"), ("email", "PII")]
    assert _fixture("sensitivity_request.json")["payload"] == {"sensitivity": "PII"}


def test_sensitivity_schema_metadata():
    s = load_schema("metadata.column.sensitivity.request.v1")
    assert s["$id"] == "metadata.column.sensitivity.request.v1"
    assert s["$comment"] == "Synthetic contract for a controlled experiment."
    assert s["additionalProperties"] is False
    assert s["required"] == ["sensitivity"]
