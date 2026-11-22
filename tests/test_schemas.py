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
COLUMN_SCHEMAS = ["columns_response.json", "dataset_changed.json"]


def _fixture(name):
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


@pytest.mark.parametrize("fixture", COLUMN_SCHEMAS)
@pytest.mark.parametrize("level", LEVELS)
def test_column_sensitivity_levels_are_accepted(fixture, level):
    doc = _fixture(fixture)
    for column in doc["payload"]["columns"]:
        column["sensitivity"] = level
    validate(doc["schema"], doc["payload"])


@pytest.mark.parametrize("fixture", COLUMN_SCHEMAS)
def test_column_sensitivity_is_optional(fixture):
    doc = _fixture(fixture)
    doc["payload"]["columns"][0]["sensitivity"] = "PII"
    assert "sensitivity" not in doc["payload"]["columns"][1]
    validate(doc["schema"], doc["payload"])


@pytest.mark.parametrize("fixture", COLUMN_SCHEMAS)
@pytest.mark.parametrize("bad", ["pii", "SECRET", "", None, 3])
def test_column_sensitivity_rejects_unknown_values(fixture, bad):
    doc = _fixture(fixture)
    doc["payload"]["columns"][0]["sensitivity"] = bad
    with pytest.raises(ContractError):
        validate(doc["schema"], doc["payload"])


def test_register_request_is_unchanged_by_sensitivity():
    doc = _fixture("register_request.json")
    doc["payload"]["columns"][0]["sensitivity"] = "PII"
    with pytest.raises(ContractError):
        validate(doc["schema"], doc["payload"])


@pytest.mark.parametrize("level", LEVELS)
def test_sensitivity_request_accepts_levels(level):
    validate("metadata.column.sensitivity.request.v1", {"sensitivity": level})


@pytest.mark.parametrize("body", [
    {},
    {"sensitivity": "SECRET"},
    {"sensitivity": "pii"},
    {"sensitivity": None},
    {"sensitivity": "PII", "reason": "x"},
    [],
    "PII",
])
def test_sensitivity_request_rejects_invalid_bodies(body):
    with pytest.raises(ContractError):
        validate("metadata.column.sensitivity.request.v1", body)
