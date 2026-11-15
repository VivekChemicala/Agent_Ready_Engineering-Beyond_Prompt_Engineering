"""Minimal validator for the JSON Schema subset used by the event schema.

Supports ``type``, ``required``, ``properties``, ``minLength``, ``minimum``,
``exclusiveMinimum`` and ``format: date-time``; that is everything
``schemas/transaction_event.schema.json`` uses, so no third-party dependency
is needed.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Iterator

_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: (
        isinstance(v, (int, float))
        and not isinstance(v, bool)
        and math.isfinite(v)
    ),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def is_rfc3339_datetime(value: str) -> bool:
    """Return True for an RFC 3339 date-time with an explicit UTC offset."""
    if "T" not in value.upper():
        return False
    candidate = value[:-1] + "+00:00" if value[-1:] in ("Z", "z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def iter_errors(
    instance: Any, schema: dict, path: str = ""
) -> Iterator[tuple[str, str]]:
    """Yield ``(path, message)`` for every violation of ``schema``."""
    where = path or "<root>"
    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_TYPE_CHECKS[t](instance) for t in types):
            yield where, (
                f"expected type {' or '.join(types)}, "
                f"got {type(instance).__name__}"
            )
            return

    if isinstance(instance, dict):
        for name in schema.get("required", []):
            if name not in instance:
                yield _join(path, name), "required field is missing"
        for name, subschema in schema.get("properties", {}).items():
            if name in instance:
                yield from iter_errors(instance[name], subschema, _join(path, name))

    if isinstance(instance, str):
        min_length = schema.get("minLength")
        if min_length is not None and len(instance) < min_length:
            yield where, f"must be at least {min_length} character(s) long"
        if schema.get("format") == "date-time" and not is_rfc3339_datetime(instance):
            yield where, "must be an RFC 3339 date-time with a UTC offset"

    if _TYPE_CHECKS["number"](instance):
        minimum = schema.get("minimum")
        if minimum is not None and instance < minimum:
            yield where, f"must be >= {minimum}"
        exclusive = schema.get("exclusiveMinimum")
        if exclusive is not None and instance <= exclusive:
            yield where, f"must be > {exclusive}"


def _join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name
