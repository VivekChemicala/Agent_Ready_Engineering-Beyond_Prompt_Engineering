"""Wire contracts for the synthetic data platform."""
from platform_contracts.validator import ContractError, load_schema, validate

__version__ = "2.4.0"

# Column sensitivity levels, least to most restrictive (DP-1501).
SENSITIVITY_LEVELS = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII")
# Level to assume for a column that carries no `sensitivity` (payloads from contracts < 2.4.0).
DEFAULT_SENSITIVITY = "INTERNAL"

__all__ = [
    "ContractError",
    "DEFAULT_SENSITIVITY",
    "SENSITIVITY_LEVELS",
    "load_schema",
    "validate",
    "__version__",
]
