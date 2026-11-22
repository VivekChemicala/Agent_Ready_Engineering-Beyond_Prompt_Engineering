"""Query execution with access enforcement."""
from query_gateway.metadata_client import MetadataClient, UpstreamContractError, UpstreamError

READ_PERMISSION = "dataset:read"
PII_READ_PERMISSION = "pii:read"
MASK = "***"


class QueryService:
    def __init__(self, metadata: MetadataClient):
        self.metadata = metadata

    def run(self, principal: str, permissions: set[str], urn: str, rows: list[dict]) -> dict:
        """Return the rows `principal` may see. `rows` stands in for the warehouse result."""
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
            masked = [c.name for c in columns if c.sensitivity == "PII"]
        masked_set = set(masked)
        out_rows = [
            {n: (MASK if n in masked_set and row.get(n) is not None else row.get(n)) for n in names}
            for row in rows
        ]
        return {"status": 200, "rows": out_rows, "masked_columns": masked}
