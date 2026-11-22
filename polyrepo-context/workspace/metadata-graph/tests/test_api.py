from metadata_graph import api
from metadata_graph.graph_store import GraphStore
from metadata_graph.model import Column, Dataset


def test_get_columns():
    store = GraphStore()
    store.upsert(Dataset("urn:ds:x", "x", "crm", "alice",
                         [Column("email", "string")]))
    status, body = api.get_columns(store, "urn:ds:x")
    assert status == 200 and body["columns"][0]["name"] == "email"
