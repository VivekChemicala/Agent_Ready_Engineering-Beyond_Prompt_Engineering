from metadata_graph import consumers
from metadata_graph.graph_store import GraphStore


def test_schema_discovered_creates_dataset(monkeypatch):
    sent = []
    monkeypatch.setattr(consumers, "publish_dataset_changed",
                        lambda ds, kind: sent.append(kind))
    store = GraphStore()
    consumers.on_schema_discovered(store, {
        "dataset_urn": "urn:ds:crm.customers", "dataset_name": "customers",
        "domain": "crm", "discovered_at": "2026-01-01T00:00:00Z",
        "columns": [{"name": "id", "type": "string", "nullable": False}],
    })
    assert store.get("urn:ds:crm.customers").columns[0].name == "id"
    assert sent == ["CREATED"]
