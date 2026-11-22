"""Query execution with access enforcement."""
from query_gateway.metadata_client import MetadataClient, UpstreamContractError, UpstreamError
from query_gateway.models import PII

READ_PERMISSION = "dataset:read"
PII_READ_PERMISSION = "pii:read"
MASK = "***"


class QueryService:
    def __init__(self, metadata: MetadataClient):
        self.metadata = metadata

    def run(self, principal: str, permissions: set[str], urn: str, rows: list[dict]) -> dict:
        """Return the rows `principal` may see. `rows` stands in for the warehouse result.

        Non-null values of `PII` columns are replaced by `MASK` unless the caller has
        `pii:read`; `masked_columns` lists those columns in dataset column order.
        """
        if READ_PERMISSION not in permissions:
            return {"status": 403, "error": "FORBIDDEN"}
        try:
            columns = self.metadata.get_columns(urn)
        except UpstreamContractError:
            return {"status": 502, "error": "UPSTREAM_CONTRACT"}
        except UpstreamError:
            return {"status": 502, "error": "UPSTREAM"}
        names = [c.name for c in columns]
        if PII_READ_PERMISSION in permissions:
            masked = []
        else:
            masked = [c.name for c in columns if c.sensitivity == PII]
        masked_set = set(masked)
        return {
            "status": 200,
            "rows": [{n: _visible(n, row.get(n), masked_set) for n in names} for row in rows],
            "masked_columns": masked,
        }


def _visible(name: str, value, masked: set[str]):
    if value is None or name not in masked:
        return value
    return MASK
