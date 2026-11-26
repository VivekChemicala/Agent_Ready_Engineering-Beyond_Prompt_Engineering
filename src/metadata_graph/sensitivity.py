"""Column sensitivity levels and their suggestion from source tags (DP-1501)."""

LEVELS = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII")
DEFAULT_LEVEL = "INTERNAL"

_TAG_LEVELS = {"pii": "PII", "confidential": "CONFIDENTIAL", "public": "PUBLIC"}
_RESTRICTIVENESS = {"PUBLIC": 0, "INTERNAL": 1, "CONFIDENTIAL": 2, "PII": 3}


def suggest(tags) -> str:
    """Suggest a level from tags (case-insensitive); the most restrictive match wins, else INTERNAL."""
    matched = {_TAG_LEVELS[t.lower()] for t in tags if isinstance(t, str) and t.lower() in _TAG_LEVELS}
    if not matched:
        return DEFAULT_LEVEL
    return max(matched, key=_RESTRICTIVENESS.__getitem__)


def column_out(column: dict) -> dict:
    """The column as served/emitted: name, type, tags and sensitivity (INTERNAL when missing)."""
    return {
        "name": column["name"],
        "type": column["type"],
        "tags": list(column["tags"]),
        "sensitivity": column.get("sensitivity") or DEFAULT_LEVEL,
    }


def dataset_out(dataset: dict) -> dict:
    return {**dataset, "columns": [column_out(c) for c in dataset["columns"]]}
