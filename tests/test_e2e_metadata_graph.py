"""End-to-end check against a metadata-graph checkout (set METADATA_GRAPH_PATH to enable)."""
import os
import sys
from pathlib import Path

import pytest

from query_gateway.metadata_client import MetadataClient
from query_gateway.service import QueryService

MG_PATH = os.environ.get("METADATA_GRAPH_PATH")
pytestmark = pytest.mark.skipif(not MG_PATH, reason="METADATA_GRAPH_PATH not set")

URN = "urn:ds:crm.customers"
DATASET = {
    "urn": URN, "name": "customers", "owner": "team-crm",
    "columns": [
        {"name": "customer_id", "type": "string", "tags": ["key"]},
        {"name": "email", "type": "string", "tags": ["pii"]},
    ],
}
ROWS = [{"customer_id": "c1", "email": "a@example.test"}, {"customer_id": "c2", "email": None}]
READ = {"dataset:read"}
STEWARD = {"X-Roles": "steward"}


@pytest.fixture
def app():
    src = str(Path(MG_PATH) / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from metadata_graph.app import App
    app = App()
    status, _ = app.handle("POST", "/v1/datasets", DATASET)
    assert status == 201
    return app


@pytest.fixture
def gateway(app):
    return QueryService(MetadataClient(lambda method, path: app.handle(method, path)))


def set_level(app, column, level):
    path = f"/v1/datasets/{URN}/columns/{column}/sensitivity"
    status, body = app.handle("PUT", path, {"sensitivity": level}, STEWARD)
    assert status == 200 and body["sensitivity"] == level
    return body


def test_pii_masked_without_pii_read(gateway):
    out = gateway.run("u1", READ, URN, ROWS)
    assert out == {"status": 200, "masked_columns": ["email"], "rows": [
        {"customer_id": "c1", "email": "***"}, {"customer_id": "c2", "email": None}]}


def test_pii_read_sees_raw(gateway):
    assert gateway.run("u1", READ | {"pii:read"}, URN, ROWS) == {"status": 200, "rows": ROWS, "masked_columns": []}


def test_steward_overrides_drive_masking(app, gateway):
    set_level(app, "email", "INTERNAL")
    assert gateway.run("u1", READ, URN, ROWS) == {"status": 200, "rows": ROWS, "masked_columns": []}

    set_level(app, "customer_id", "PII")
    expected = {"status": 200, "masked_columns": ["customer_id"], "rows": [
        {"customer_id": "***", "email": "a@example.test"}, {"customer_id": "***", "email": None}]}
    assert gateway.run("u1", READ, URN, ROWS) == expected

    status, _ = app.handle("POST", "/v1/datasets", DATASET)
    assert status == 200
    assert gateway.run("u1", READ, URN, ROWS) == expected
