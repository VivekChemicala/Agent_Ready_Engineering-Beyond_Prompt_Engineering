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


def _fixture(name):
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


COLUMN_SCHEMA_FIXTURES = ["columns_response.json", "dataset_changed.json"]


def test_sensitivity_levels_ordered_least_to_most_restrictive():
    assert platform_contracts.SENSITIVITY_LEVELS == ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII")
    assert platform_contracts.DEFAULT_SENSITIVITY == "INTERNAL"


@pytest.mark.parametrize("fixture", COLUMN_SCHEMA_FIXTURES)
@pytest.mark.parametrize("level", platform_contracts.SENSITIVITY_LEVELS)
def test_columns_accept_every_sensitivity_level(fixture, level):
    doc = _fixture(fixture)
    for column in doc["payload"]["columns"]:
        column["sensitivity"] = level
    validate(doc["schema"], doc["payload"])


@pytest.mark.parametrize("fixture", COLUMN_SCHEMA_FIXTURES)
def test_sensitivity_is_optional_per_column(fixture):
    doc = _fixture(fixture)
    doc["payload"]["columns"][1]["sensitivity"] = "PII"
    validate(doc["schema"], doc["payload"])


@pytest.mark.parametrize("fixture", COLUMN_SCHEMA_FIXTURES)
@pytest.mark.parametrize("bad", ["SECRET", "pii", "", None, 3])
def test_columns_reject_unknown_sensitivity(fixture, bad):
    doc = _fixture(fixture)
    doc["payload"]["columns"][0]["sensitivity"] = bad
    with pytest.raises(ContractError):
        validate(doc["schema"], doc["payload"])


def test_register_request_does_not_carry_sensitivity():
    doc = _fixture("register_request.json")
    doc["payload"]["columns"][0]["sensitivity"] = "PUBLIC"
    with pytest.raises(ContractError):
        validate(doc["schema"], doc["payload"])


@pytest.mark.parametrize("level", platform_contracts.SENSITIVITY_LEVELS)
def test_sensitivity_request_accepts_every_level(level):
    validate("metadata.column.sensitivity.request.v1", {"sensitivity": level})


@pytest.mark.parametrize("body", [
    {},
    {"sensitivity": "SECRET"},
    {"sensitivity": "pii"},
    {"sensitivity": None},
    {"sensitivity": "PII", "reason": "x"},
    ["PII"],
    "PII",
    None,
])
def test_sensitivity_request_rejects_invalid_bodies(body):
    with pytest.raises(ContractError):
        validate("metadata.column.sensitivity.request.v1", body)
