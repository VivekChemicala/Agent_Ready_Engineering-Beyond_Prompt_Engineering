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


SCHEMA_COLUMN_KEYS = {"name", "type", "tags", "sensitivity"}


def _levels(columns):
    return {c["name"]: c["sensitivity"] for c in columns}


def _put_level(app, column, level, headers=STEWARD, urn=URN):
    return app.handle("PUT", f"/v1/datasets/{urn}/columns/{column}/sensitivity", {"sensitivity": level}, headers)


def _register(app, columns):
    return app.handle("POST", "/v1/datasets", dict(BODY, columns=columns))


def test_register_suggests_sensitivity(app):
    status, body = _register(app, [
        {"name": "id", "type": "string", "tags": ["key"]},
        {"name": "email", "type": "string", "tags": ["public", "PII"]},
        {"name": "salary", "type": "int", "tags": ["confidential", "public"]},
        {"name": "country", "type": "string", "tags": ["public"]},
        {"name": "note", "type": "string", "tags": []},
    ])
    assert status == 201
    expected = {"id": "INTERNAL", "email": "PII", "salary": "CONFIDENTIAL", "country": "PUBLIC", "note": "INTERNAL"}
    assert _levels(body["columns"]) == expected
    assert _levels(app.sink[-1]["columns"]) == expected


def test_get_columns_returns_sensitivity(app):
    app.handle("POST", "/v1/datasets", BODY)
    status, body = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert status == 200
    assert body["columns"] == [
        {"name": "customer_id", "type": "string", "tags": ["key"], "sensitivity": "INTERNAL"},
        {"name": "email", "type": "string", "tags": ["pii"], "sensitivity": "PII"},
    ]


def test_events_carry_sensitivity(app):
    app.handle("POST", "/v1/datasets", BODY)
    app.handle("POST", "/v1/datasets", BODY)
    app.handle("PUT", f"/v1/datasets/{URN}/owner", {"owner": "team-x"}, STEWARD)
    assert [e["change"] for e in app.sink] == ["CREATED", "UPDATED", "UPDATED"]
    for event in app.sink:
        assert _levels(event["columns"]) == {"customer_id": "INTERNAL", "email": "PII"}


def test_set_sensitivity(app):
    app.handle("POST", "/v1/datasets", BODY)
    status, body = _put_level(app, "customer_id", "CONFIDENTIAL")
    assert status == 200
    assert body == {"name": "customer_id", "type": "string", "tags": ["key"], "sensitivity": "CONFIDENTIAL"}
    assert app.sink[-1]["change"] == "UPDATED"
    assert _levels(app.sink[-1]["columns"]) == {"customer_id": "CONFIDENTIAL", "email": "PII"}
    _, cols = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert _levels(cols["columns"]) == {"customer_id": "CONFIDENTIAL", "email": "PII"}


def test_set_sensitivity_unchanged_still_emits(app):
    app.handle("POST", "/v1/datasets", BODY)
    status, _ = _put_level(app, "email", "PII")
    assert status == 200
    assert [e["change"] for e in app.sink] == ["CREATED", "UPDATED"]


def test_set_sensitivity_requires_steward(app):
    app.handle("POST", "/v1/datasets", BODY)
    for headers in ({"X-Roles": "reader"}, {}):
        status, body = _put_level(app, "email", "PUBLIC", headers)
        assert status == 403 and body["error"]["code"] == "FORBIDDEN"
    assert len(app.sink) == 1


def test_set_sensitivity_forbidden_before_not_found(app):
    status, body = _put_level(app, "email", "PUBLIC", {"X-Roles": "reader"}, urn="urn:ds:nope")
    assert status == 403 and body["error"]["code"] == "FORBIDDEN"


def test_set_sensitivity_unknown_dataset(app):
    status, body = _put_level(app, "email", "PUBLIC", urn="urn:ds:nope")
    assert status == 404 and body["error"]["code"] == "NOT_FOUND"


def test_set_sensitivity_unknown_column(app):
    app.handle("POST", "/v1/datasets", BODY)
    for column in ("nope", "Email"):
        status, body = _put_level(app, column, "PUBLIC")
        assert status == 404 and body["error"]["code"] == "NOT_FOUND"
    assert len(app.sink) == 1


@pytest.mark.parametrize("payload", [
    {},
    None,
    "PII",
    {"sensitivity": "SECRET"},
    {"sensitivity": "pii"},
    {"sensitivity": 1},
    {"sensitivity": "PII", "reason": "x"},
])
def test_set_sensitivity_validates_body(app, payload):
    app.handle("POST", "/v1/datasets", BODY)
    status, body = app.handle("PUT", f"/v1/datasets/{URN}/columns/email/sensitivity", payload, STEWARD)
    assert status == 400 and body["error"]["code"] == "INVALID_REQUEST"
    assert len(app.sink) == 1
    _, cols = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert _levels(cols["columns"])["email"] == "PII"


def test_override_survives_reregister_with_changed_tags(app):
    app.handle("POST", "/v1/datasets", BODY)
    _put_level(app, "email", "PUBLIC")
    status, body = _register(app, [
        {"name": "customer_id", "type": "string", "tags": ["key"]},
        {"name": "email", "type": "string", "tags": ["pii", "confidential"]},
    ])
    assert status == 200
    assert _levels(body["columns"]) == {"customer_id": "INTERNAL", "email": "PUBLIC"}
    assert _levels(app.sink[-1]["columns"]) == {"customer_id": "INTERNAL", "email": "PUBLIC"}


def test_reregister_new_column_gets_suggestion(app):
    app.handle("POST", "/v1/datasets", BODY)
    _put_level(app, "email", "PUBLIC")
    _, body = _register(app, BODY["columns"] + [{"name": "phone", "type": "string", "tags": ["PII"]}])
    assert _levels(body["columns"]) == {"customer_id": "INTERNAL", "email": "PUBLIC", "phone": "PII"}


def test_reregister_resuggests_non_overridden_column(app):
    app.handle("POST", "/v1/datasets", BODY)
    _put_level(app, "email", "PUBLIC")
    _, body = _register(app, [
        {"name": "customer_id", "type": "string", "tags": ["confidential"]},
        {"name": "email", "type": "string", "tags": ["pii"]},
    ])
    assert _levels(body["columns"]) == {"customer_id": "CONFIDENTIAL", "email": "PUBLIC"}


def test_removed_column_loses_override(app):
    app.handle("POST", "/v1/datasets", BODY)
    _put_level(app, "email", "PUBLIC")
    _register(app, [BODY["columns"][0]])
    _, body = _register(app, BODY["columns"])
    assert _levels(body["columns"]) == {"customer_id": "INTERNAL", "email": "PII"}


def test_no_internal_keys_leak(app):
    app.handle("POST", "/v1/datasets", BODY)
    _, put_body = _put_level(app, "email", "PUBLIC")
    _, post_body = app.handle("POST", "/v1/datasets", BODY)
    _, get_body = app.handle("GET", f"/v1/datasets/{URN}")
    _, cols_body = app.handle("GET", f"/v1/datasets/{URN}/columns")
    _, owner_body = app.handle("PUT", f"/v1/datasets/{URN}/owner", {"owner": "team-x"}, STEWARD)
    assert set(put_body) == SCHEMA_COLUMN_KEYS
    assert set(post_body) == set(get_body) == set(owner_body) == {"urn", "name", "owner", "columns"}
    assert set(cols_body) == {"urn", "columns"}
    for columns in [post_body["columns"], get_body["columns"], cols_body["columns"], owner_body["columns"]]:
        assert all(set(c) == SCHEMA_COLUMN_KEYS for c in columns)
    for event in app.sink:
        assert set(event) == {"event_type", "urn", "change", "owner", "columns"}
        assert all(set(c) == SCHEMA_COLUMN_KEYS for c in event["columns"])


def test_register_body_with_sensitivity_still_rejected(app):
    columns = [dict(BODY["columns"][0], sensitivity="PUBLIC")]
    status, body = _register(app, columns)
    assert status == 400 and body["error"]["code"] == "INVALID_REQUEST"
