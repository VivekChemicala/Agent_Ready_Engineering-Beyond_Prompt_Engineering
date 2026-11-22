"""Client for the metadata-graph API.

`transport(method, path)` returns (status, body); production wires it to HTTP, tests to fakes.
"""
from platform_contracts import ContractError, validate

from query_gateway.models import Column


class UpstreamError(RuntimeError):
    pass


class UpstreamContractError(UpstreamError):
    pass


class MetadataClient:
    def __init__(self, transport):
        self.transport = transport

    def get_columns(self, urn: str) -> list[Column]:
        status, body = self.transport("GET", f"/v1/datasets/{urn}/columns")
        if status != 200:
            raise UpstreamError(f"metadata-graph returned {status}")
        try:
            validate("metadata.columns.response.v1", body)
        except ContractError as exc:
            raise UpstreamContractError(str(exc)) from exc
        return [Column.from_dict(c) for c in body["columns"]]
