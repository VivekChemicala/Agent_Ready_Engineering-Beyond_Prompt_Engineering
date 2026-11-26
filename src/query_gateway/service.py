"""Query execution with access enforcement."""
from query_gateway.metadata_client import MetadataClient, UpstreamContractError, UpstreamError

READ_PERMISSION = "dataset:read"
PII_READ_PERMISSION = "pii:read"
PII = "PII"
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
        masked = [] if PII_READ_PERMISSION in permissions else [c.name for c in columns if c.sensitivity == PII]
        out = []
        for row in rows:
            projected = {n: row.get(n) for n in names}
            for n in masked:
                if projected[n] is not None:
                    projected[n] = MASK
            out.append(projected)
        return {"status": 200, "rows": out, "masked_columns": masked}
