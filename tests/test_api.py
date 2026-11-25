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


TAGGED = {
    "urn": URN, "name": "customers", "owner": "team-crm",
    "columns": [
        {"name": "customer_id", "type": "string", "tags": ["key"]},
        {"name": "email", "type": "string", "tags": ["pii"]},
        {"name": "salary", "type": "number", "tags": ["confidential"]},
        {"name": "country", "type": "string", "tags": ["public"]},
        {"name": "phone", "type": "string", "tags": ["public", "pii", "confidential"]},
        {"name": "notes", "type": "string", "tags": ["public", "confidential"]},
        {"name": "untagged", "type": "string", "tags": []},
    ],
}
SUGGESTED = {
    "customer_id": "INTERNAL", "email": "PII", "salary": "CONFIDENTIAL", "country": "PUBLIC",
    "phone": "PII", "notes": "CONFIDENTIAL", "untagged": "INTERNAL",
}


def levels(columns):
    return {c["name"]: c["sensitivity"] for c in columns}


def test_register_suggests_sensitivity_from_tags(app):
    status, body = app.handle("POST", "/v1/datasets", TAGGED)
    assert status == 201 and levels(body["columns"]) == SUGGESTED
    assert levels(app.sink[-1]["columns"]) == SUGGESTED


def test_get_columns_returns_sensitivity(app):
    app.handle("POST", "/v1/datasets", TAGGED)
    status, body = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert status == 200 and levels(body["columns"]) == SUGGESTED


def test_set_sensitivity(app):
    app.handle("POST", "/v1/datasets", BODY)
    path = f"/v1/datasets/{URN}/columns/customer_id/sensitivity"
    status, body = app.handle("PUT", path, {"sensitivity": "PII"}, STEWARD)
    assert status == 200
    assert body == {"name": "customer_id", "type": "string", "tags": ["key"], "sensitivity": "PII"}
    assert app.sink[-1]["change"] == "UPDATED"
    assert levels(app.sink[-1]["columns"]) == {"customer_id": "PII", "email": "PII"}
    _, cols = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert levels(cols["columns"]) == {"customer_id": "PII", "email": "PII"}


def test_set_sensitivity_requires_steward(app):
    app.handle("POST", "/v1/datasets", BODY)
    status, body = app.handle("PUT", f"/v1/datasets/{URN}/columns/email/sensitivity",
                              {"sensitivity": "PUBLIC"}, {"X-Roles": "reader"})
    assert status == 403 and body["error"]["code"] == "FORBIDDEN"
    assert len(app.sink) == 1


def test_set_sensitivity_unknown_dataset(app):
    status, body = app.handle("PUT", "/v1/datasets/urn:ds:nope/columns/email/sensitivity",
                              {"sensitivity": "PII"}, STEWARD)
    assert status == 404 and body["error"]["code"] == "NOT_FOUND"


def test_set_sensitivity_unknown_column(app):
    app.handle("POST", "/v1/datasets", BODY)
    status, body = app.handle("PUT", f"/v1/datasets/{URN}/columns/nope/sensitivity",
                              {"sensitivity": "PII"}, STEWARD)
    assert status == 404 and body["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("bad", [{}, {"sensitivity": "SECRET"}, {"sensitivity": "pii"},
                                 {"sensitivity": "PII", "extra": 1}, None, "PII"])
def test_set_sensitivity_validates_body(app, bad):
    app.handle("POST", "/v1/datasets", BODY)
    status, body = app.handle("PUT", f"/v1/datasets/{URN}/columns/email/sensitivity", bad, STEWARD)
    assert status == 400 and body["error"]["code"] == "INVALID_REQUEST"
    assert len(app.sink) == 1


def test_override_kept_on_reregister_and_new_columns_suggested(app):
    app.handle("POST", "/v1/datasets", BODY)
    app.handle("PUT", f"/v1/datasets/{URN}/columns/email/sensitivity", {"sensitivity": "CONFIDENTIAL"}, STEWARD)
    again = dict(BODY, columns=BODY["columns"] + [{"name": "ssn", "type": "string", "tags": ["pii"]}])
    status, body = app.handle("POST", "/v1/datasets", again)
    assert status == 200
    assert levels(body["columns"]) == {"customer_id": "INTERNAL", "email": "CONFIDENTIAL", "ssn": "PII"}
    assert levels(app.sink[-1]["columns"]) == levels(body["columns"])


def test_override_dropped_when_column_removed(app):
    app.handle("POST", "/v1/datasets", BODY)
    app.handle("PUT", f"/v1/datasets/{URN}/columns/email/sensitivity", {"sensitivity": "PUBLIC"}, STEWARD)
    app.handle("POST", "/v1/datasets", dict(BODY, columns=BODY["columns"][:1]))
    _, body = app.handle("POST", "/v1/datasets", BODY)
    assert levels(body["columns"])["email"] == "PII"


def test_set_owner_keeps_sensitivity(app):
    app.handle("POST", "/v1/datasets", BODY)
    app.handle("PUT", f"/v1/datasets/{URN}/columns/customer_id/sensitivity", {"sensitivity": "PUBLIC"}, STEWARD)
    app.handle("PUT", f"/v1/datasets/{URN}/owner", {"owner": "team-x"}, STEWARD)
    assert levels(app.sink[-1]["columns"]) == {"customer_id": "PUBLIC", "email": "PII"}
