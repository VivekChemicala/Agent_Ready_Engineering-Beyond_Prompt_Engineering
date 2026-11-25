import pytest

from metadata_graph.app import App

URN = "urn:ds:crm.customers"
BODY = {
    "urn": URN, "name": "customers", "owner": "team-crm",
    "columns": [
        {"name": "customer_id", "type": "string", "tags": ["key"]},
        {"name": "email", "type": "string", "tags": ["pii"]},
    ],
}
STEWARD = {"X-Roles": "reader,steward"}


@pytest.fixture
def app():
    return App()


def test_register_creates_and_emits(app):
    status, body = app.handle("POST", "/v1/datasets", BODY)
    assert status == 201 and body["urn"] == URN
    assert [e["change"] for e in app.sink] == ["CREATED"]


def test_reregister_is_update(app):
    app.handle("POST", "/v1/datasets", BODY)
    status, _ = app.handle("POST", "/v1/datasets", BODY)
    assert status == 200
    assert [e["change"] for e in app.sink] == ["CREATED", "UPDATED"]


def test_register_rejects_invalid(app):
    status, body = app.handle("POST", "/v1/datasets", {"urn": URN})
    assert status == 400 and body["error"]["code"] == "INVALID_REQUEST"


def test_get_columns(app):
    app.handle("POST", "/v1/datasets", BODY)
    status, body = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert status == 200
    assert [c["name"] for c in body["columns"]] == ["customer_id", "email"]


def test_get_columns_unknown(app):
    status, body = app.handle("GET", "/v1/datasets/urn:ds:nope/columns")
    assert status == 404 and body["error"]["code"] == "NOT_FOUND"


def test_set_owner_requires_steward(app):
    app.handle("POST", "/v1/datasets", BODY)
    status, body = app.handle("PUT", f"/v1/datasets/{URN}/owner", {"owner": "team-x"}, {"X-Roles": "reader"})
    assert status == 403 and body["error"]["code"] == "FORBIDDEN"


def test_set_owner(app):
    app.handle("POST", "/v1/datasets", BODY)
    status, body = app.handle("PUT", f"/v1/datasets/{URN}/owner", {"owner": "team-x"}, STEWARD)
    assert status == 200 and body["owner"] == "team-x"
    assert app.sink[-1]["owner"] == "team-x"


def test_set_owner_validates_body(app):
    app.handle("POST", "/v1/datasets", BODY)
    status, body = app.handle("PUT", f"/v1/datasets/{URN}/owner", {"owner": ""}, STEWARD)
    assert status == 400 and body["error"]["code"] == "INVALID_REQUEST"


def _levels(columns):
    return {c["name"]: c["sensitivity"] for c in columns}


@pytest.mark.parametrize("tags, level", [
    ([], "INTERNAL"),
    (["key"], "INTERNAL"),
    (["public"], "PUBLIC"),
    (["confidential"], "CONFIDENTIAL"),
    (["pii"], "PII"),
    (["public", "confidential"], "CONFIDENTIAL"),
    (["public", "pii", "confidential"], "PII"),
    (["PII"], "PII"),
])
def test_register_suggests_sensitivity_from_tags(app, tags, level):
    body = {**BODY, "columns": [{"name": "c", "type": "string", "tags": tags}]}
    status, ds = app.handle("POST", "/v1/datasets", body)
    assert status == 201 and ds["columns"][0]["sensitivity"] == level
    assert app.sink[-1]["columns"][0]["sensitivity"] == level


def test_get_columns_includes_sensitivity(app):
    app.handle("POST", "/v1/datasets", BODY)
    _, body = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert _levels(body["columns"]) == {"customer_id": "INTERNAL", "email": "PII"}


def test_override_sensitivity(app):
    app.handle("POST", "/v1/datasets", BODY)
    status, body = app.handle("PUT", f"/v1/datasets/{URN}/columns/customer_id/sensitivity",
                              {"sensitivity": "CONFIDENTIAL"}, STEWARD)
    assert status == 200
    assert body == {"name": "customer_id", "type": "string", "tags": ["key"], "sensitivity": "CONFIDENTIAL"}
    assert [e["change"] for e in app.sink] == ["CREATED", "UPDATED"]
    assert _levels(app.sink[-1]["columns"]) == {"customer_id": "CONFIDENTIAL", "email": "PII"}
    _, cols = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert _levels(cols["columns"]) == {"customer_id": "CONFIDENTIAL", "email": "PII"}


def test_override_requires_steward(app):
    app.handle("POST", "/v1/datasets", BODY)
    status, body = app.handle("PUT", f"/v1/datasets/{URN}/columns/email/sensitivity",
                              {"sensitivity": "PUBLIC"}, {"X-Roles": "reader"})
    assert status == 403 and body["error"]["code"] == "FORBIDDEN"
    status, _ = app.handle("PUT", f"/v1/datasets/{URN}/columns/email/sensitivity", {"sensitivity": "PUBLIC"})
    assert status == 403
    assert len(app.sink) == 1


def test_override_unknown_dataset_or_column(app):
    status, body = app.handle("PUT", "/v1/datasets/urn:ds:nope/columns/email/sensitivity",
                              {"sensitivity": "PII"}, STEWARD)
    assert status == 404 and body["error"]["code"] == "NOT_FOUND"
    app.handle("POST", "/v1/datasets", BODY)
    status, body = app.handle("PUT", f"/v1/datasets/{URN}/columns/nope/sensitivity", {"sensitivity": "PII"}, STEWARD)
    assert status == 404 and body["error"]["code"] == "NOT_FOUND"
    assert len(app.sink) == 1


@pytest.mark.parametrize("bad", [None, {}, {"sensitivity": "SECRET"}, {"sensitivity": "pii"},
                                 {"sensitivity": 1}, {"sensitivity": "PII", "extra": 1}, "PII"])
def test_override_validates_body(app, bad):
    app.handle("POST", "/v1/datasets", BODY)
    status, body = app.handle("PUT", f"/v1/datasets/{URN}/columns/email/sensitivity", bad, STEWARD)
    assert status == 400 and body["error"]["code"] == "INVALID_REQUEST"
    assert len(app.sink) == 1


def test_override_kept_on_reregister_and_new_columns_suggested(app):
    app.handle("POST", "/v1/datasets", BODY)
    app.handle("PUT", f"/v1/datasets/{URN}/columns/email/sensitivity", {"sensitivity": "PUBLIC"}, STEWARD)
    body = {**BODY, "columns": BODY["columns"] + [{"name": "ssn", "type": "string", "tags": ["pii"]}]}
    status, ds = app.handle("POST", "/v1/datasets", body)
    assert status == 200
    assert _levels(ds["columns"]) == {"customer_id": "INTERNAL", "email": "PUBLIC", "ssn": "PII"}
    assert _levels(app.sink[-1]["columns"]) == {"customer_id": "INTERNAL", "email": "PUBLIC", "ssn": "PII"}


def test_override_dropped_when_column_removed(app):
    app.handle("POST", "/v1/datasets", BODY)
    app.handle("PUT", f"/v1/datasets/{URN}/columns/email/sensitivity", {"sensitivity": "PUBLIC"}, STEWARD)
    app.handle("POST", "/v1/datasets", {**BODY, "columns": BODY["columns"][:1]})
    _, ds = app.handle("POST", "/v1/datasets", BODY)
    assert _levels(ds["columns"])["email"] == "PII"


def test_column_stored_without_level_is_internal():
    from metadata_graph.store import GraphStore
    store = GraphStore()
    store.put({"urn": URN, "name": "customers", "owner": "team-crm",
               "columns": [{"name": "legacy", "type": "string", "tags": []}]})
    app = App(store=store)
    _, body = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert body["columns"][0]["sensitivity"] == "INTERNAL"
    app.handle("PUT", f"/v1/datasets/{URN}/owner", {"owner": "team-x"}, STEWARD)
    assert app.sink[-1]["columns"][0]["sensitivity"] == "INTERNAL"


def test_every_event_validates_and_carries_levels(app):
    from platform_contracts import validate
    app.handle("POST", "/v1/datasets", BODY)
    app.handle("PUT", f"/v1/datasets/{URN}/columns/email/sensitivity", {"sensitivity": "CONFIDENTIAL"}, STEWARD)
    app.handle("PUT", f"/v1/datasets/{URN}/owner", {"owner": "team-x"}, STEWARD)
    app.handle("POST", "/v1/datasets", BODY)
    assert [e["change"] for e in app.sink] == ["CREATED", "UPDATED", "UPDATED", "UPDATED"]
    for event in app.sink:
        validate("metadata.dataset.changed.v1", event)
        assert all("sensitivity" in c for c in event["columns"])
    assert _levels(app.sink[-1]["columns"]) == {"customer_id": "INTERNAL", "email": "CONFIDENTIAL"}
