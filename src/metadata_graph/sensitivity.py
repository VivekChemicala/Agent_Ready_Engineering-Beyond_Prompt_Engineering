"""Column sensitivity levels (DP-1501)."""
PUBLIC = "PUBLIC"
INTERNAL = "INTERNAL"
CONFIDENTIAL = "CONFIDENTIAL"
PII = "PII"

# Least to most restrictive.
LEVELS = (PUBLIC, INTERNAL, CONFIDENTIAL, PII)
DEFAULT = INTERNAL

_TAG_LEVELS = {"pii": PII, "confidential": CONFIDENTIAL, "public": PUBLIC}


def suggest(tags) -> str:
    """Suggest a level from source tags; the most restrictive matching level wins, INTERNAL if none match."""
    matched = {_TAG_LEVELS[t.lower()] for t in tags if t.lower() in _TAG_LEVELS}
    if not matched:
        return DEFAULT
    return max(matched, key=LEVELS.index)


def with_level(column: dict) -> dict:
    """Copy of `column` with a sensitivity level; a column stored without one is INTERNAL."""
    return {**column, "sensitivity": column.get("sensitivity") or DEFAULT}
