"""Column sensitivity: suggestion from source tags (DP-1501)."""
from platform_contracts import DEFAULT_SENSITIVITY, SENSITIVITY_LEVELS

TAG_LEVELS = {"pii": "PII", "confidential": "CONFIDENTIAL", "public": "PUBLIC"}


def suggest_sensitivity(tags) -> str:
    """Most restrictive level whose tag appears exactly (case-insensitive) in tags, else the default."""
    levels = {TAG_LEVELS[t] for t in (str(tag).strip().lower() for tag in tags or []) if t in TAG_LEVELS}
    if not levels:
        return DEFAULT_SENSITIVITY
    return max(levels, key=SENSITIVITY_LEVELS.index)


def with_sensitivity(column: dict) -> dict:
    """Column object with exactly name, type, tags and sensitivity (missing level -> default)."""
    return {
        "name": column["name"],
        "type": column["type"],
        "tags": list(column["tags"]),
        "sensitivity": column.get("sensitivity") or DEFAULT_SENSITIVITY,
    }
