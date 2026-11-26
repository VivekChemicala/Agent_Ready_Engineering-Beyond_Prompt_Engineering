import pytest
from platform_contracts import validate

from metadata_graph.app import App
from metadata_graph.sensitivity import suggest_sensitivity

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


# --- DP-1501: column sensitivity ---------------------------------------------------------------

COLUMN_KEYS = {"name", "type", "tags", "sensitivity"}
DATASET_KEYS = {"urn", "name", "owner", "columns"}
EVENT_KEYS = {"event_type", "urn", "change", "owner", "columns"}


def levels(columns):
    return {c["name"]: c["sensitivity"] for c in columns}


def put_level(app, column, body, headers=STEWARD, urn=URN):
    return app.handle("PUT", f"/v1/datasets/{urn}/columns/{column}/sensitivity", body, headers)


def assert_closed(app):
    _, ds = app.handle("GET", f"/v1/datasets/{URN}")
    assert set(ds) == DATASET_KEYS and all(set(c) == COLUMN_KEYS for c in ds["columns"])
    for event in app.sink:
        assert set(event) == EVENT_KEYS and all(set(c) == COLUMN_KEYS for c in event["columns"])
        validate("metadata.dataset.changed.v1", event)


@pytest.mark.parametrize("tags,level", [
    ([], "INTERNAL"),
    (["key"], "INTERNAL"),
    (["pii"], "PII"),
    (["confidential"], "CONFIDENTIAL"),
    (["public"], "PUBLIC"),
    (["public", "key"], "PUBLIC"),
    (["public", "pii"], "PII"),
    (["pii", "public"], "PII"),
    (["public", "confidential"], "CONFIDENTIAL"),
    (["confidential", "pii"], "PII"),
    (["public", "confidential", "pii"], "PII"),
    (["PII"], "PII"),
    ([" Public "], "PUBLIC"),
    (["piiish", "secret"], "INTERNAL"),
])
def test_suggest_sensitivity(tags, level):
    assert suggest_sensitivity(tags) == level


def test_register_suggests_levels(app):
    body = dict(BODY, columns=BODY["columns"] + [
        {"name": "country", "type": "string", "tags": ["public"]},
        {"name": "salary", "type": "int", "tags": ["confidential", "public"]},
    ])
    status, resp = app.handle("POST", "/v1/datasets", body)
    expected = {"customer_id": "INTERNAL", "email": "PII", "country": "PUBLIC", "salary": "CONFIDENTIAL"}
    assert status == 201 and levels(resp["columns"]) == expected
    _, cols = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert levels(cols["columns"]) == expected
    validate("metadata.columns.response.v1", cols)
    assert app.sink[0]["change"] == "CREATED" and levels(app.sink[0]["columns"]) == expected
    assert_closed(app)


def test_register_rejects_sensitivity_in_body(app):
    body = dict(BODY, columns=[{"name": "email", "type": "string", "tags": [], "sensitivity": "PII"}])
    status, resp = app.handle("POST", "/v1/datasets", body)
    assert status == 400 and resp["error"]["code"] == "INVALID_REQUEST"
    assert app.sink == []


def test_override_sensitivity(app):
    app.handle("POST", "/v1/datasets", BODY)
    status, resp = put_level(app, "customer_id", {"sensitivity": "CONFIDENTIAL"})
    assert status == 200
    assert resp == {"name": "customer_id", "type": "string", "tags": ["key"], "sensitivity": "CONFIDENTIAL"}
    assert [e["change"] for e in app.sink] == ["CREATED", "UPDATED"]
    assert levels(app.sink[-1]["columns"]) == {"customer_id": "CONFIDENTIAL", "email": "PII"}
    _, cols = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert levels(cols["columns"]) == {"customer_id": "CONFIDENTIAL", "email": "PII"}
    assert_closed(app)


def test_override_same_level_still_emits_update(app):
    app.handle("POST", "/v1/datasets", BODY)
    status, _ = put_level(app, "email", {"sensitivity": "PII"})
    assert status == 200 and [e["change"] for e in app.sink] == ["CREATED", "UPDATED"]


def test_override_requires_steward(app):
    app.handle("POST", "/v1/datasets", BODY)
    for headers in ({"X-Roles": "reader"}, {}):
        status, resp = put_level(app, "email", {"sensitivity": "PUBLIC"}, headers)
        assert status == 403 and resp["error"]["code"] == "FORBIDDEN"
    assert len(app.sink) == 1
    _, cols = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert levels(cols["columns"])["email"] == "PII"


def test_override_forbidden_before_not_found(app):
    status, resp = put_level(app, "email", {"sensitivity": "bad"}, {"X-Roles": "reader"}, urn="urn:ds:nope")
    assert status == 403 and resp["error"]["code"] == "FORBIDDEN"


def test_override_unknown_dataset(app):
    status, resp = put_level(app, "email", {"sensitivity": "PII"}, urn="urn:ds:nope")
    assert status == 404 and resp["error"]["code"] == "NOT_FOUND"
    assert app.sink == []


def test_override_unknown_column(app):
    app.handle("POST", "/v1/datasets", BODY)
    for column in ("phone", "Email"):
        status, resp = put_level(app, column, {"sensitivity": "PII"})
        assert status == 404 and resp["error"]["code"] == "NOT_FOUND"
    status, _ = put_level(app, "phone", {"sensitivity": "bad"})
    assert status == 404
    assert len(app.sink) == 1


@pytest.mark.parametrize("body", [
    {}, {"sensitivity": "pii"}, {"sensitivity": "SECRET"}, {"sensitivity": "PII", "extra": 1},
    {"sensitivity": None}, None, "PII", ["PII"],
])
def test_override_invalid_body(app, body):
    app.handle("POST", "/v1/datasets", BODY)
    status, resp = put_level(app, "email", body)
    assert status == 400 and resp["error"]["code"] == "INVALID_REQUEST"
    assert len(app.sink) == 1
    _, cols = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert levels(cols["columns"])["email"] == "PII"


def test_override_survives_reregister(app):
    app.handle("POST", "/v1/datasets", BODY)
    put_level(app, "email", {"sensitivity": "CONFIDENTIAL"})
    body = dict(BODY, columns=[
        {"name": "customer_id", "type": "string", "tags": ["public"]},
        {"name": "email", "type": "string", "tags": ["pii", "contact"]},
        {"name": "phone", "type": "string", "tags": ["pii"]},
    ])
    status, resp = app.handle("POST", "/v1/datasets", body)
    expected = {"customer_id": "PUBLIC", "email": "CONFIDENTIAL", "phone": "PII"}
    assert status == 200 and levels(resp["columns"]) == expected
    assert app.sink[-1]["change"] == "UPDATED" and levels(app.sink[-1]["columns"]) == expected
    _, cols = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert levels(cols["columns"]) == expected
    assert_closed(app)


def test_removed_column_loses_override(app):
    app.handle("POST", "/v1/datasets", BODY)
    put_level(app, "email", {"sensitivity": "PUBLIC"})
    app.handle("POST", "/v1/datasets", dict(BODY, columns=BODY["columns"][:1]))
    status, resp = app.handle("POST", "/v1/datasets", BODY)
    assert status == 200 and levels(resp["columns"]) == {"customer_id": "INTERNAL", "email": "PII"}


def test_owner_change_event_carries_levels(app):
    app.handle("POST", "/v1/datasets", BODY)
    put_level(app, "customer_id", {"sensitivity": "PUBLIC"})
    status, resp = app.handle("PUT", f"/v1/datasets/{URN}/owner", {"owner": "team-x"}, STEWARD)
    assert status == 200 and levels(resp["columns"]) == {"customer_id": "PUBLIC", "email": "PII"}
    assert levels(app.sink[-1]["columns"]) == {"customer_id": "PUBLIC", "email": "PII"}
    assert_closed(app)


def test_legacy_column_without_level_reads_internal(app):
    app.store.put({"urn": URN, "name": "customers", "owner": "team-crm",
                   "columns": [{"name": "email", "type": "string", "tags": ["pii"]}]})
    _, cols = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert cols["columns"] == [{"name": "email", "type": "string", "tags": ["pii"], "sensitivity": "INTERNAL"}]
    _, ds = app.handle("GET", f"/v1/datasets/{URN}")
    assert ds["columns"][0]["sensitivity"] == "INTERNAL"
    app.handle("PUT", f"/v1/datasets/{URN}/owner", {"owner": "team-x"}, STEWARD)
    assert app.sink[-1]["columns"][0]["sensitivity"] == "INTERNAL"
    status, resp = put_level(app, "email", {"sensitivity": "PII"})
    assert status == 200 and resp["sensitivity"] == "PII"
    assert_closed(app)
