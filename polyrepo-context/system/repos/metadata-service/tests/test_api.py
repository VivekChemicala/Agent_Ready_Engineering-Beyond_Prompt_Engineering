from metadata_service import api
from metadata_service.metadata_store import MetadataStore
from metadata_service.model import Column, Dataset


def test_get_columns():
    store = MetadataStore()
    store.upsert(Dataset("urn:ds:x", "x", "crm", "alice",
                         [Column("email", "string")]))
    status, body = api.get_columns(store, "urn:ds:x")
    assert status == 200 and body["columns"][0]["name"] == "email"
