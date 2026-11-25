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
INVALID_LEVELS = ["pii", "SECRET", None, 1]
COLUMN_SCHEMAS = [
    ("columns_response.json", "metadata.columns.response.v1"),
    ("dataset_changed.json", "metadata.dataset.changed.v1"),
]
SENSITIVITY_REQUEST = "metadata.dataset.column.sensitivity.request.v1"


def _fixture(name):
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


@pytest.mark.parametrize("fixture,schema", COLUMN_SCHEMAS)
@pytest.mark.parametrize("level", LEVELS)
def test_column_sensitivity_levels_accepted(fixture, schema, level):
    doc = _fixture(fixture)
    for column in doc["payload"]["columns"]:
        column["sensitivity"] = level
    validate(schema, doc["payload"])


@pytest.mark.parametrize("fixture,schema", COLUMN_SCHEMAS)
@pytest.mark.parametrize("level", INVALID_LEVELS)
def test_column_sensitivity_invalid_values_rejected(fixture, schema, level):
    doc = _fixture(fixture)
    doc["payload"]["columns"][0]["sensitivity"] = level
    with pytest.raises(ContractError):
        validate(schema, doc["payload"])


@pytest.mark.parametrize("fixture,schema", COLUMN_SCHEMAS)
def test_columns_without_sensitivity_stay_valid(fixture, schema):
    doc = _fixture(fixture)
    assert all("sensitivity" not in c for c in doc["payload"]["columns"])
    validate(schema, doc["payload"])


@pytest.mark.parametrize("fixture,schema", COLUMN_SCHEMAS)
def test_sensitivity_is_optional_per_column(fixture, schema):
    doc = _fixture(fixture)
    doc["payload"]["columns"][1]["sensitivity"] = "PII"
    validate(schema, doc["payload"])


@pytest.mark.parametrize("level", LEVELS)
def test_sensitivity_request_levels_accepted(level):
    validate(SENSITIVITY_REQUEST, {"sensitivity": level})


@pytest.mark.parametrize("level", INVALID_LEVELS)
def test_sensitivity_request_invalid_values_rejected(level):
    with pytest.raises(ContractError):
        validate(SENSITIVITY_REQUEST, {"sensitivity": level})


@pytest.mark.parametrize("payload", [{}, {"sensitivity": "PII", "reason": "x"}, ["PII"], "PII"])
def test_sensitivity_request_shape_rejected(payload):
    with pytest.raises(ContractError):
        validate(SENSITIVITY_REQUEST, payload)


def test_register_request_rejects_column_sensitivity():
    doc = _fixture("register_request.json")
    doc["payload"]["columns"][1]["sensitivity"] = "PII"
    with pytest.raises(ContractError):
        validate(doc["schema"], doc["payload"])
