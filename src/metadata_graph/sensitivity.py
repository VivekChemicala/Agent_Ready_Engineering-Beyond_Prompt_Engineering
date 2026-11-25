"""Column sensitivity levels (DP-1501)."""

LEVELS = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII")
DEFAULT = "INTERNAL"
_TAG_LEVELS = {"pii": "PII", "confidential": "CONFIDENTIAL", "public": "PUBLIC"}
_RANK = {"PII": 3, "CONFIDENTIAL": 2, "INTERNAL": 1, "PUBLIC": 0}


def suggest(tags) -> str:
    """Most restrictive level implied by source tags; INTERNAL when no tag applies."""
    levels = {_TAG_LEVELS[t.lower()] for t in tags if t.lower() in _TAG_LEVELS}
    if "PII" in levels or "CONFIDENTIAL" in levels or not levels:
        levels.add(DEFAULT)
    return max(levels, key=_RANK.__getitem__)
