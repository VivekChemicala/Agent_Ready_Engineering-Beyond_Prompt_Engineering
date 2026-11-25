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
INVALID_LEVELS = ["SECRET", "pii", "", None, 1]
COLUMN_SCHEMAS = ["columns_response", "dataset_changed"]
SENSITIVITY_REQUEST = "metadata.dataset.column.sensitivity.request.v1"


def _fixture(name):
    return json.loads((Path(__file__).parent / "fixtures" / f"{name}.json").read_text())


@pytest.mark.parametrize("fixture", COLUMN_SCHEMAS)
@pytest.mark.parametrize("level", LEVELS)
def test_column_sensitivity_accepts_every_level(fixture, level):
    doc = _fixture(fixture)
    doc["payload"]["columns"][0]["sensitivity"] = level
    validate(doc["schema"], doc["payload"])


@pytest.mark.parametrize("fixture", COLUMN_SCHEMAS)
@pytest.mark.parametrize("level", INVALID_LEVELS, ids=repr)
def test_column_sensitivity_rejects_invalid_values(fixture, level):
    doc = _fixture(fixture)
    doc["payload"]["columns"][0]["sensitivity"] = level
    with pytest.raises(ContractError):
        validate(doc["schema"], doc["payload"])


@pytest.mark.parametrize("fixture", COLUMN_SCHEMAS)
def test_column_without_sensitivity_is_valid(fixture):
    doc = _fixture(f"{fixture}_sensitivity")
    del doc["payload"]["columns"][1]["sensitivity"]
    validate(doc["schema"], doc["payload"])


@pytest.mark.parametrize("fixture", COLUMN_SCHEMAS)
def test_column_sensitivity_columns_stay_closed(fixture):
    doc = _fixture(f"{fixture}_sensitivity")
    doc["payload"]["columns"][0]["sensitivity_overridden"] = True
    with pytest.raises(ContractError):
        validate(doc["schema"], doc["payload"])


@pytest.mark.parametrize("level", LEVELS)
def test_sensitivity_request_accepts_every_level(level):
    validate(SENSITIVITY_REQUEST, {"sensitivity": level})


@pytest.mark.parametrize("level", INVALID_LEVELS, ids=repr)
def test_sensitivity_request_rejects_invalid_values(level):
    with pytest.raises(ContractError):
        validate(SENSITIVITY_REQUEST, {"sensitivity": level})


@pytest.mark.parametrize("payload", [{}, {"level": "PII"}, None, [], "PII"], ids=repr)
def test_sensitivity_request_requires_sensitivity_object(payload):
    with pytest.raises(ContractError):
        validate(SENSITIVITY_REQUEST, payload)


def test_sensitivity_request_is_closed():
    with pytest.raises(ContractError):
        validate(SENSITIVITY_REQUEST, {"sensitivity": "PII", "reason": "gdpr"})


def test_register_request_rejects_column_sensitivity():
    doc = _fixture("register_request")
    doc["payload"]["columns"][0]["sensitivity"] = "PII"
    with pytest.raises(ContractError):
        validate(doc["schema"], doc["payload"])


def test_sensitivity_request_schema_id_matches_file():
    from platform_contracts import load_schema
    assert load_schema(SENSITIVITY_REQUEST)["$id"] == SENSITIVITY_REQUEST
