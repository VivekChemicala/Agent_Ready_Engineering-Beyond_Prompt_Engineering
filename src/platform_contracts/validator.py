"""Minimal JSON Schema subset validator (type, required, properties,
additionalProperties, enum, items, minLength), so services need no third-party deps."""
import json
from pathlib import Path

SCHEMA_DIR = Path(__file__).parent / "schemas"

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


class ContractError(ValueError):
    """Raised when a payload does not match its contract."""


def load_schema(name: str) -> dict:
    path = SCHEMA_DIR / f"{name}.json"
    if not path.exists():
        raise ContractError(f"unknown schema {name}")
    return json.loads(path.read_text())


def _type_ok(value, expected) -> bool:
    if isinstance(expected, list):
        return any(_type_ok(value, e) for e in expected)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, _TYPES[expected])


def _check(value, schema: dict, path: str) -> None:
    if "type" in schema and not _type_ok(value, schema["type"]):
        raise ContractError(f"{path}: expected {schema['type']}")
    if "enum" in schema and value not in schema["enum"]:
        raise ContractError(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        raise ContractError(f"{path}: shorter than {schema['minLength']}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                raise ContractError(f"{path}: missing {key}")
        for key, item in value.items():
            if key in props:
                _check(item, props[key], f"{path}.{key}")
            elif schema.get("additionalProperties", True) is False:
                raise ContractError(f"{path}: unexpected field {key}")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            _check(item, schema["items"], f"{path}[{i}]")


def validate(name: str, payload) -> None:
    """Raise ContractError unless payload matches schema `name`."""
    _check(payload, load_schema(name), "$")
