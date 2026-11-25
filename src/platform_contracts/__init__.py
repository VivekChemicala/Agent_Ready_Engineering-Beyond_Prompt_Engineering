"""Wire contracts for the synthetic data platform."""
from platform_contracts.validator import ContractError, load_schema, validate

__version__ = "2.4.0"

# Column sensitivity levels, ordered least to most restrictive.
SENSITIVITY_LEVELS = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII")
DEFAULT_SENSITIVITY = "INTERNAL"

__all__ = [
    "ContractError",
    "DEFAULT_SENSITIVITY",
    "SENSITIVITY_LEVELS",
    "load_schema",
    "validate",
    "__version__",
]
