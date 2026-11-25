"""Column sensitivity levels (DP-1501)."""

LEVELS = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII")
DEFAULT = "INTERNAL"
_RANK = {level: i for i, level in enumerate(LEVELS)}
_TAG_LEVELS = {"pii": "PII", "confidential": "CONFIDENTIAL", "public": "PUBLIC"}


def most_restrictive(levels) -> str:
    return max(levels, key=_RANK.__getitem__)


def suggest(tags) -> str:
    """Level suggested from source tags; the most restrictive matching tag wins, else INTERNAL."""
    matched = {_TAG_LEVELS[t.strip().lower()] for t in tags if t.strip().lower() in _TAG_LEVELS}
    return most_restrictive(matched) if matched else DEFAULT


def level_of(column: dict) -> str:
    """Level of a column; a column without one is treated as INTERNAL."""
    return column.get("sensitivity") or DEFAULT
