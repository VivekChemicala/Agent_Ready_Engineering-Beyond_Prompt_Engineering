"""Event helpers. Validation uses the platform-contracts version pinned in pyproject."""

from __future__ import annotations

import uuid

from platform_contracts import load_schema, validate  # noqa: F401

_HANDLERS: dict[str, list] = {}


def new_event_id() -> str:
    return str(uuid.uuid4())


def publish(topic: str, payload: dict, schema_ref: str) -> None:
    validate(payload, load_schema(schema_ref))
    for handler in _HANDLERS.get(topic, []):
        handler(payload)


def subscribe(topic: str, handler) -> None:
    _HANDLERS.setdefault(topic, []).append(handler)
