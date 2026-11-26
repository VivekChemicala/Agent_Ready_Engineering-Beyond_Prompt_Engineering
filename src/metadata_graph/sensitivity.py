"""Column sensitivity levels (DP-1501): suggestion from source tags."""
from platform_contracts import DEFAULT_SENSITIVITY, SENSITIVITY_LEVELS

TAG_LEVELS = {"pii": "PII", "confidential": "CONFIDENTIAL", "public": "PUBLIC"}


def restrictiveness(level: str) -> int:
    return SENSITIVITY_LEVELS.index(level)


def suggest_sensitivity(tags) -> str:
    """Most restrictive level among tags pii/confidential/public (case-insensitive), else INTERNAL."""
    levels = {TAG_LEVELS[t.strip().lower()] for t in tags or () if t.strip().lower() in TAG_LEVELS}
    if not levels:
        return DEFAULT_SENSITIVITY
    return max(levels, key=restrictiveness)
