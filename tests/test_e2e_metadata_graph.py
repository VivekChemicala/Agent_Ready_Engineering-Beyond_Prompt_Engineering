"""Cross-repo end-to-end check against a metadata-graph checkout (DP-1501).

Skipped unless METADATA_GRAPH_PATH points to a metadata-graph checkout.
"""
import os
import sys
from pathlib import Path

import pytest

MG_PATH = os.environ.get("METADATA_GRAPH_PATH")
if not MG_PATH or not (Path(MG_PATH) / "src" / "metadata_graph").is_dir():
    pytest.skip("METADATA_GRAPH_PATH not set to a metadata-graph checkout", allow_module_level=True)
sys.path.insert(0, str(Path(MG_PATH) / "src"))

from metadata_graph.app import App  # noqa: E402

from query_gateway.metadata_client import MetadataClient  # noqa: E402
from query_gateway.service import QueryService  # noqa: E402

URN = "urn:ds:crm.customers"
REGISTER = {"urn": URN, "name": "customers", "owner": "team-crm", "columns": [
    {"name": "customer_id", "type": "string", "tags": ["key"]},
    {"name": "email", "type": "string", "tags": ["pii"]},
]}
ROWS = [{"customer_id": "c1", "email": "a@example.test"}, {"customer_id": "c2", "email": None}]
READ = {"dataset:read"}


def test_pii_masking_end_to_end():
    app = App()
    gateway = QueryService(MetadataClient(lambda m, p: app.handle(m, p)))

    status, _ = app.handle("POST", "/v1/datasets", REGISTER)
    assert status == 201
    out = gateway.run("u1", READ, URN, ROWS)
    assert out == {"status": 200, "masked_columns": ["email"], "rows": [
        {"customer_id": "c1", "email": "***"}, {"customer_id": "c2", "email": None}]}

    status, column = app.handle("PUT", f"/v1/datasets/{URN}/columns/customer_id/sensitivity",
                                {"sensitivity": "PII"}, {"X-Roles": "steward"})
    assert (status, column["sensitivity"]) == (200, "PII")
    out = gateway.run("u1", READ, URN, ROWS)
    assert out["masked_columns"] == ["customer_id", "email"]
    assert out["rows"] == [{"customer_id": "***", "email": "***"}, {"customer_id": "***", "email": None}]

    status, _ = app.handle("POST", "/v1/datasets", REGISTER)
    assert status == 200
    out = gateway.run("u1", READ, URN, ROWS)
    assert out["masked_columns"] == ["customer_id", "email"]
    assert out["rows"][0] == {"customer_id": "***", "email": "***"}

    out = gateway.run("u1", READ | {"pii:read"}, URN, ROWS)
    assert out == {"status": 200, "rows": ROWS, "masked_columns": []}
