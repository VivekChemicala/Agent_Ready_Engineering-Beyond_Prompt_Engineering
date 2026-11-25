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


SENSITIVITY_SCHEMAS = ["metadata.columns.response.v1", "metadata.dataset.changed.v1"]
SENSITIVITY_REQUEST = "metadata.dataset.column.sensitivity.request.v1"


def _fixture(name):
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text())


def _payload_with_sensitivity(schema, value):
    name = "columns_response.json" if schema == "metadata.columns.response.v1" else "dataset_changed.json"
    payload = _fixture(name)["payload"]
    payload["columns"][0]["sensitivity"] = value
    return payload


def test_sensitivity_constants():
    assert platform_contracts.SENSITIVITY_LEVELS == ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII")
    assert platform_contracts.DEFAULT_SENSITIVITY == "INTERNAL"
    assert platform_contracts.DEFAULT_SENSITIVITY in platform_contracts.SENSITIVITY_LEVELS
    assert "SENSITIVITY_LEVELS" in platform_contracts.__all__
    assert "DEFAULT_SENSITIVITY" in platform_contracts.__all__


def test_every_sensitivity_enum_matches_levels():
    for schema in SENSITIVITY_SCHEMAS:
        item = load_schema(schema)["properties"]["columns"]["items"]
        assert item["properties"]["sensitivity"]["enum"] == list(platform_contracts.SENSITIVITY_LEVELS)
        assert item["required"] == ["name", "type", "tags"]
        assert item["additionalProperties"] is False
    request = load_schema(SENSITIVITY_REQUEST)
    assert request["properties"]["sensitivity"]["enum"] == list(platform_contracts.SENSITIVITY_LEVELS)


@pytest.mark.parametrize("schema", SENSITIVITY_SCHEMAS)
@pytest.mark.parametrize("level", ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII"])
def test_column_accepts_every_level(schema, level):
    validate(schema, _payload_with_sensitivity(schema, level))


@pytest.mark.parametrize("schema", SENSITIVITY_SCHEMAS)
@pytest.mark.parametrize("value", ["SECRET", "pii", "Pii", "", None, 1, ["PII"]])
def test_column_rejects_invalid_sensitivity(schema, value):
    with pytest.raises(ContractError):
        validate(schema, _payload_with_sensitivity(schema, value))


@pytest.mark.parametrize("level", ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII"])
def test_sensitivity_request_accepts_every_level(level):
    validate(SENSITIVITY_REQUEST, {"sensitivity": level})


@pytest.mark.parametrize("payload", [
    {"sensitivity": "SECRET"},
    {"sensitivity": "pii"},
    {"sensitivity": None},
    {"sensitivity": ""},
    {},
    {"sensitivity": "PII", "reason": "gdpr"},
    "PII",
    None,
    ["PII"],
])
def test_sensitivity_request_rejects_invalid(payload):
    with pytest.raises(ContractError):
        validate(SENSITIVITY_REQUEST, payload)


@pytest.mark.parametrize("value", ["PII", "INTERNAL"])
def test_register_request_rejects_column_sensitivity(value):
    payload = _fixture("register_request.json")["payload"]
    payload["columns"][1]["sensitivity"] = value
    with pytest.raises(ContractError):
        validate("metadata.dataset.register.request.v1", payload)


def test_owner_request_rejects_sensitivity():
    with pytest.raises(ContractError):
        validate("metadata.dataset.owner.request.v1", {"owner": "team-sales", "sensitivity": "PII"})


def test_2_4_0_fixtures_mix_columns_with_and_without_sensitivity():
    for name in ["columns_response_2_4_0.json", "dataset_changed_2_4_0.json"]:
        columns = _fixture(name)["payload"]["columns"]
        assert any("sensitivity" in c for c in columns)
        assert any("sensitivity" not in c for c in columns)
