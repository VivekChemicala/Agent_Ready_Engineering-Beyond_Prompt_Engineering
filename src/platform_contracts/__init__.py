"""Wire contracts for the synthetic data platform."""
from platform_contracts.validator import ContractError, load_schema, validate

__version__ = "2.3.0"

__all__ = ["ContractError", "load_schema", "validate", "__version__"]
