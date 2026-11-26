"""Column sensitivity levels (DP-1501)."""
PUBLIC = "PUBLIC"
INTERNAL = "INTERNAL"
CONFIDENTIAL = "CONFIDENTIAL"
PII = "PII"
DEFAULT = INTERNAL

# Most restrictive first.
RESTRICTIVENESS = (PII, CONFIDENTIAL, INTERNAL, PUBLIC)
_TAG_LEVELS = {"pii": PII, "confidential": CONFIDENTIAL, "public": PUBLIC}


def suggest_sensitivity(tags) -> str:
    """Suggest a level from source tags; the most restrictive matching level wins, INTERNAL if none match."""
    matched = {_TAG_LEVELS[t.strip().lower()] for t in tags or [] if t.strip().lower() in _TAG_LEVELS}
    if not matched:
        return DEFAULT
    return min(matched, key=RESTRICTIVENESS.index)


def column_view(column: dict) -> dict:
    """Wire form of a stored column; a column without a level (legacy data) is INTERNAL."""
    return {
        "name": column["name"],
        "type": column["type"],
        "tags": list(column["tags"]),
        "sensitivity": column.get("sensitivity") or DEFAULT,
    }
