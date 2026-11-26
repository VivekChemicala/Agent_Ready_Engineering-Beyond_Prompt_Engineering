"""Column sensitivity suggestion from source tags."""
from platform_contracts import DEFAULT_SENSITIVITY, SENSITIVITY_LEVELS

TAG_LEVELS = {"pii": "PII", "confidential": "CONFIDENTIAL", "public": "PUBLIC"}


def suggest_sensitivity(tags) -> str:
    """Most restrictive level implied by the tags (exact, case-insensitive); INTERNAL if none apply."""
    levels = {TAG_LEVELS[t.lower()] for t in tags if isinstance(t, str) and t.lower() in TAG_LEVELS}
    if not levels:
        return DEFAULT_SENSITIVITY
    return max(levels, key=SENSITIVITY_LEVELS.index)
