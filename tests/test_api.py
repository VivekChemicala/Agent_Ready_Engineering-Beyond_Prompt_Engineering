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


# DP-1501: column sensitivity

def _levels(columns):
    return {c["name"]: c["sensitivity"] for c in columns}


def _register(app, columns):
    return app.handle("POST", "/v1/datasets", {**BODY, "columns": columns})


@pytest.mark.parametrize("tags, level", [
    ([], "INTERNAL"),
    (["key"], "INTERNAL"),
    (["pii"], "PII"),
    (["confidential"], "CONFIDENTIAL"),
    (["public"], "PUBLIC"),
    (["public", "key"], "PUBLIC"),
    (["public", "confidential"], "CONFIDENTIAL"),
    (["confidential", "pii", "public"], "PII"),
    (["PII"], "PII"),
])
def test_register_suggests_level_from_tags(app, tags, level):
    status, body = _register(app, [{"name": "c", "type": "string", "tags": tags}])
    assert status == 201 and body["columns"][0]["sensitivity"] == level
    assert app.sink[-1]["columns"][0]["sensitivity"] == level


def test_levels_in_columns_response_and_events(app):
    app.handle("POST", "/v1/datasets", BODY)
    _, body = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert _levels(body["columns"]) == {"customer_id": "INTERNAL", "email": "PII"}
    assert _levels(app.sink[-1]["columns"]) == {"customer_id": "INTERNAL", "email": "PII"}
    _, body = app.handle("GET", f"/v1/datasets/{URN}")
    assert _levels(body["columns"]) == {"customer_id": "INTERNAL", "email": "PII"}


def test_set_sensitivity(app):
    app.handle("POST", "/v1/datasets", BODY)
    status, body = app.handle("PUT", f"/v1/datasets/{URN}/columns/customer_id/sensitivity",
                              {"sensitivity": "CONFIDENTIAL"}, STEWARD)
    assert status == 200
    assert body == {"name": "customer_id", "type": "string", "tags": ["key"], "sensitivity": "CONFIDENTIAL"}
    assert app.sink[-1]["change"] == "UPDATED"
    assert _levels(app.sink[-1]["columns"]) == {"customer_id": "CONFIDENTIAL", "email": "PII"}
    _, body = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert _levels(body["columns"]) == {"customer_id": "CONFIDENTIAL", "email": "PII"}


def test_set_sensitivity_can_lower_level(app):
    app.handle("POST", "/v1/datasets", BODY)
    status, body = app.handle("PUT", f"/v1/datasets/{URN}/columns/email/sensitivity",
                              {"sensitivity": "PUBLIC"}, STEWARD)
    assert status == 200 and body["sensitivity"] == "PUBLIC"


@pytest.mark.parametrize("headers", [{}, {"X-Roles": "reader"}, {"X-Roles": "stewards"}])
def test_set_sensitivity_requires_steward(app, headers):
    app.handle("POST", "/v1/datasets", BODY)
    events = len(app.sink)
    status, body = app.handle("PUT", f"/v1/datasets/{URN}/columns/email/sensitivity",
                              {"sensitivity": "PUBLIC"}, headers)
    assert status == 403 and body["error"]["code"] == "FORBIDDEN"
    assert len(app.sink) == events


def test_set_sensitivity_unknown_dataset(app):
    status, body = app.handle("PUT", "/v1/datasets/urn:ds:nope/columns/email/sensitivity",
                              {"sensitivity": "PII"}, STEWARD)
    assert status == 404 and body["error"]["code"] == "NOT_FOUND"


def test_set_sensitivity_unknown_column(app):
    app.handle("POST", "/v1/datasets", BODY)
    events = len(app.sink)
    status, body = app.handle("PUT", f"/v1/datasets/{URN}/columns/nope/sensitivity", {"sensitivity": "PII"}, STEWARD)
    assert status == 404 and body["error"]["code"] == "NOT_FOUND"
    assert len(app.sink) == events


@pytest.mark.parametrize("payload", [
    None, {}, [], {"sensitivity": "SECRET"}, {"sensitivity": "pii"}, {"sensitivity": None},
    {"sensitivity": "PII", "extra": 1}, {"level": "PII"},
])
def test_set_sensitivity_validates_body(app, payload):
    app.handle("POST", "/v1/datasets", BODY)
    events = len(app.sink)
    status, body = app.handle("PUT", f"/v1/datasets/{URN}/columns/email/sensitivity", payload, STEWARD)
    assert status == 400 and body["error"]["code"] == "INVALID_REQUEST"
    assert len(app.sink) == events
    _, body = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert _levels(body["columns"])["email"] == "PII"


def test_override_survives_reregistration(app):
    app.handle("POST", "/v1/datasets", BODY)
    app.handle("PUT", f"/v1/datasets/{URN}/columns/email/sensitivity", {"sensitivity": "CONFIDENTIAL"}, STEWARD)
    columns = [{"name": "email", "type": "string", "tags": ["pii"]},
               {"name": "phone", "type": "string", "tags": ["pii"]}]
    status, body = _register(app, columns)
    assert status == 200
    assert _levels(body["columns"]) == {"email": "CONFIDENTIAL", "phone": "PII"}
    assert _levels(app.sink[-1]["columns"]) == {"email": "CONFIDENTIAL", "phone": "PII"}


def test_override_dropped_when_column_removed(app):
    app.handle("POST", "/v1/datasets", BODY)
    app.handle("PUT", f"/v1/datasets/{URN}/columns/email/sensitivity", {"sensitivity": "PUBLIC"}, STEWARD)
    _register(app, [{"name": "customer_id", "type": "string", "tags": ["key"]}])
    status, body = app.handle("POST", "/v1/datasets", BODY)
    assert status == 200 and _levels(body["columns"])["email"] == "PII"


def test_column_without_level_is_internal(app):
    app.store.put({"urn": URN, "name": "customers", "owner": "team-crm",
                   "columns": [{"name": "legacy", "type": "string", "tags": ["pii"]}]})
    _, body = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert body["columns"][0]["sensitivity"] == "INTERNAL"
    status, _ = app.handle("PUT", f"/v1/datasets/{URN}/owner", {"owner": "team-x"}, STEWARD)
    assert status == 200 and app.sink[-1]["columns"][0]["sensitivity"] == "INTERNAL"


def test_register_request_without_levels_stays_valid(app):
    status, body = app.handle("POST", "/v1/datasets", BODY)
    assert status == 201 and all("sensitivity" in c for c in body["columns"])
