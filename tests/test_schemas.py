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


FIXTURE_DIR = Path(__file__).parent / "fixtures"
COLUMN_SCHEMAS = ["metadata.columns.response.v1", "metadata.dataset.changed.v1"]
SENSITIVITY_REQUEST = "metadata.column.sensitivity.request.v1"


def _fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text())


def _column_payload(schema):
    name = "columns_response.json" if schema == "metadata.columns.response.v1" else "dataset_changed.json"
    doc = _fixture(name)
    assert doc["schema"] == schema
    return doc["payload"]


@pytest.mark.parametrize("name", ["columns_response.json", "dataset_changed.json",
                                  "owner_request.json", "register_request.json"])
def test_previous_release_fixtures_present_and_valid(name):
    doc = _fixture(name)
    validate(doc["schema"], doc["payload"])
    for column in doc["payload"].get("columns", []):
        assert "sensitivity" not in column


@pytest.mark.parametrize("schema", COLUMN_SCHEMAS)
@pytest.mark.parametrize("level", ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII"])
def test_column_sensitivity_accepted(schema, level):
    payload = _column_payload(schema)
    for column in payload["columns"]:
        column["sensitivity"] = level
    validate(schema, payload)


@pytest.mark.parametrize("schema", COLUMN_SCHEMAS)
@pytest.mark.parametrize("level", ["pii", "Internal", "SECRET", "", 1, None, True, ["PII"]])
def test_column_sensitivity_invalid_level_rejected(schema, level):
    payload = _column_payload(schema)
    payload["columns"][0]["sensitivity"] = level
    with pytest.raises(ContractError):
        validate(schema, payload)


@pytest.mark.parametrize("schema", COLUMN_SCHEMAS)
def test_column_without_sensitivity_accepted(schema):
    payload = _column_payload(schema)
    payload["columns"][0]["sensitivity"] = "PII"
    validate(schema, payload)
    assert "sensitivity" not in payload["columns"][1]


@pytest.mark.parametrize("schema", COLUMN_SCHEMAS)
def test_sensitivity_is_optional_in_column_schemas(schema):
    items = platform_contracts.load_schema(schema)["properties"]["columns"]["items"]
    assert "sensitivity" not in items["required"]
    assert items["additionalProperties"] is False


def test_mixed_sensitivity_fixtures_valid():
    for name in ["columns_response_sensitivity.json", "dataset_changed_sensitivity.json"]:
        doc = _fixture(name)
        validate(doc["schema"], doc["payload"])
        columns = doc["payload"]["columns"]
        assert any("sensitivity" in c for c in columns)
        assert any("sensitivity" not in c for c in columns)


@pytest.mark.parametrize("level", ["PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII"])
def test_sensitivity_request_accepts_levels(level):
    validate(SENSITIVITY_REQUEST, {"sensitivity": level})


@pytest.mark.parametrize("payload", [
    {},
    {"sensitivity": "PII", "reason": "gdpr"},
    {"sensitivity": "pii"},
    {"sensitivity": "SECRET"},
    {"sensitivity": 1},
    {"sensitivity": None},
    None,
    "PII",
    ["PII"],
])
def test_sensitivity_request_rejects_invalid(payload):
    with pytest.raises(ContractError):
        validate(SENSITIVITY_REQUEST, payload)


def test_register_request_rejects_column_sensitivity():
    doc = _fixture("register_request.json")
    doc["payload"]["columns"][0]["sensitivity"] = "PII"
    with pytest.raises(ContractError):
        validate(doc["schema"], doc["payload"])


def test_unchanged_request_schemas_have_no_sensitivity():
    register = platform_contracts.load_schema("metadata.dataset.register.request.v1")
    assert "sensitivity" not in register["properties"]["columns"]["items"]["properties"]
    owner = platform_contracts.load_schema("metadata.dataset.owner.request.v1")
    assert set(owner["properties"]) == {"owner"}


def test_sensitivity_levels_match_schema_enums():
    assert platform_contracts.SENSITIVITY_LEVELS == ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII")
    assert platform_contracts.DEFAULT_SENSITIVITY == "INTERNAL"
    assert platform_contracts.DEFAULT_SENSITIVITY in platform_contracts.SENSITIVITY_LEVELS
    enums = [
        platform_contracts.load_schema(s)["properties"]["columns"]["items"]["properties"]["sensitivity"]["enum"]
        for s in COLUMN_SCHEMAS
    ]
    enums.append(platform_contracts.load_schema(SENSITIVITY_REQUEST)["properties"]["sensitivity"]["enum"])
    for enum in enums:
        assert tuple(enum) == platform_contracts.SENSITIVITY_LEVELS


def test_public_exports():
    for name in ["SENSITIVITY_LEVELS", "DEFAULT_SENSITIVITY"]:
        assert name in platform_contracts.__all__
    assert platform_contracts.__version__ == "2.4.0"
