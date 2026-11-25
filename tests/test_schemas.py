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


LEVELS = ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII"]
COLUMN_SCHEMAS = {
    "metadata.columns.response.v1": "columns_response.json",
    "metadata.dataset.changed.v1": "dataset_changed.json",
}


def _fixture(name):
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


@pytest.mark.parametrize("schema", sorted(COLUMN_SCHEMAS))
@pytest.mark.parametrize("level", LEVELS)
def test_column_sensitivity_accepts_each_level(schema, level):
    doc = _fixture(COLUMN_SCHEMAS[schema])
    doc["payload"]["columns"][0]["sensitivity"] = level
    validate(schema, doc["payload"])


@pytest.mark.parametrize("schema", sorted(COLUMN_SCHEMAS))
@pytest.mark.parametrize("bad", ["SECRET", "pii", "Public", "", None, 1])
def test_column_sensitivity_rejects_unknown_level(schema, bad):
    doc = _fixture(COLUMN_SCHEMAS[schema])
    doc["payload"]["columns"][0]["sensitivity"] = bad
    with pytest.raises(ContractError):
        validate(schema, doc["payload"])


@pytest.mark.parametrize("schema", sorted(COLUMN_SCHEMAS))
def test_column_sensitivity_is_optional(schema):
    doc = _fixture(COLUMN_SCHEMAS[schema])
    for col in doc["payload"]["columns"]:
        assert "sensitivity" not in col
    validate(schema, doc["payload"])


@pytest.mark.parametrize("schema", sorted(COLUMN_SCHEMAS))
def test_column_items_stay_closed_with_sensitivity(schema):
    doc = _fixture(COLUMN_SCHEMAS[schema])
    doc["payload"]["columns"][0]["sensitivity"] = "PII"
    doc["payload"]["columns"][0]["masked"] = True
    with pytest.raises(ContractError):
        validate(schema, doc["payload"])


@pytest.mark.parametrize("level", LEVELS)
def test_sensitivity_request_accepts_each_level(level):
    validate("metadata.column.sensitivity.request.v1", {"sensitivity": level})


@pytest.mark.parametrize("payload", [
    {},
    {"sensitivity": "SECRET"},
    {"sensitivity": "pii"},
    {"sensitivity": None},
    {"sensitivity": "PII", "column": "email"},
    [],
    "PII",
])
def test_sensitivity_request_rejects_invalid(payload):
    with pytest.raises(ContractError):
        validate("metadata.column.sensitivity.request.v1", payload)


def test_register_request_still_rejects_column_sensitivity():
    doc = _fixture("register_request.json")
    doc["payload"]["columns"][1]["sensitivity"] = "PII"
    with pytest.raises(ContractError):
        validate(doc["schema"], doc["payload"])


def test_owner_request_still_rejects_sensitivity():
    with pytest.raises(ContractError):
        validate("metadata.dataset.owner.request.v1", {"owner": "team-sales", "sensitivity": "PII"})
