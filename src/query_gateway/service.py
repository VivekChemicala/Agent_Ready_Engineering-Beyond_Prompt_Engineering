"""Query execution with access enforcement."""
from query_gateway.metadata_client import MetadataClient, UpstreamContractError, UpstreamError

READ_PERMISSION = "dataset:read"
PII_PERMISSION = "pii:read"
PII_LEVEL = "PII"
MASK = "***"


class QueryService:
    def __init__(self, metadata: MetadataClient):
        self.metadata = metadata

    def run(self, principal: str, permissions: set[str], urn: str, rows: list[dict]) -> dict:
        """Return the rows `principal` may see. `rows` stands in for the warehouse result.

        Without `pii:read`, non-null values of `PII` columns are replaced by "***".
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
        if PII_PERMISSION in permissions:
            masked = []
        else:
            masked = [c.name for c in columns if c.sensitivity == PII_LEVEL]
        masked_set = set(masked)
        out_rows = []
        for row in rows:
            out = {}
            for n in names:
                value = row.get(n)
                out[n] = MASK if n in masked_set and value is not None else value
            out_rows.append(out)
        return {"status": 200, "rows": out_rows, "masked_columns": masked}
