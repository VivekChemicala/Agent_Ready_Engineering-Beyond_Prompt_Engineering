"""Wire contracts for the synthetic data platform."""
from platform_contracts.validator import ContractError, load_schema, validate

__version__ = "2.4.0"

# Column sensitivity levels, least to most restrictive.
SENSITIVITY_LEVELS = ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII")
# Level of a column that carries no `sensitivity` field.
DEFAULT_SENSITIVITY = "INTERNAL"


def column_sensitivity(column: dict) -> str:
    """Level of `column`: DEFAULT_SENSITIVITY when absent, ContractError unless one of SENSITIVITY_LEVELS."""
    if "sensitivity" not in column:
        return DEFAULT_SENSITIVITY
    level = column["sensitivity"]
    if type(level) is not str or level not in SENSITIVITY_LEVELS:
        raise ContractError(f"sensitivity {level!r} not in {list(SENSITIVITY_LEVELS)}")
    return level


__all__ = [
    "ContractError",
    "DEFAULT_SENSITIVITY",
    "SENSITIVITY_LEVELS",
    "column_sensitivity",
    "load_schema",
    "validate",
    "__version__",
]
