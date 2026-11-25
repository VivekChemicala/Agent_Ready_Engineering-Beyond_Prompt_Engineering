"""Column sensitivity levels and their suggestion from source tags (DP-1501)."""
PUBLIC = "PUBLIC"
INTERNAL = "INTERNAL"
CONFIDENTIAL = "CONFIDENTIAL"
PII = "PII"
LEVELS = (PUBLIC, INTERNAL, CONFIDENTIAL, PII)
DEFAULT = INTERNAL


def suggest(tags) -> str:
    """Most restrictive level implied by the tags: pii > confidential > (none) INTERNAL > public."""
    lowered = {t.lower() for t in tags or []}
    if "pii" in lowered:
        return PII
    if "confidential" in lowered:
        return CONFIDENTIAL
    if "public" in lowered:
        return PUBLIC
    return INTERNAL
