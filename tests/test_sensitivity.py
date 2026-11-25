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
        {"name": "country", "type": "string", "tags": ["public"]},
    ],
}
STEWARD = {"X-Roles": "reader, steward"}
KEYS = {"name", "type", "tags", "sensitivity"}


def path(column, urn=URN):
    return f"/v1/datasets/{urn}/columns/{column}/sensitivity"


def levels(columns):
    return {c["name"]: c["sensitivity"] for c in columns}


@pytest.fixture
def app():
    a = App()
    a.handle("POST", "/v1/datasets", BODY)
    return a


@pytest.mark.parametrize("tags, expected", [
    ([], "INTERNAL"),
    (["key"], "INTERNAL"),
    (["pii"], "PII"),
    (["confidential"], "CONFIDENTIAL"),
    (["public"], "PUBLIC"),
    (["public", "pii"], "PII"),
    (["public", "confidential"], "CONFIDENTIAL"),
    (["confidential", "pii"], "PII"),
    (["public", "internal"], "PUBLIC"),
    ([" PII "], "PII"),
    (["Confidential"], "CONFIDENTIAL"),
    (["PUBLIC"], "PUBLIC"),
    (["pii_hash"], "INTERNAL"),
    (["non-pii"], "INTERNAL"),
    (["publicly"], "INTERNAL"),
    (["key", "pii_hash", "public"], "PUBLIC"),
])
def test_suggest_sensitivity(tags, expected):
    assert suggest_sensitivity(tags) == expected


def test_register_returns_and_emits_sensitivity():
    a = App()
    status, body = a.handle("POST", "/v1/datasets", BODY)
    assert status == 201
    assert all(set(c) == KEYS for c in body["columns"])
    expected = {"customer_id": "INTERNAL", "email": "PII", "country": "PUBLIC"}
    assert levels(body["columns"]) == expected
    assert levels(a.sink[-1]["columns"]) == expected
    assert [c["name"] for c in a.sink[-1]["columns"]] == ["customer_id", "email", "country"]


def test_register_rejects_sensitivity_field():
    a = App()
    body = {**BODY, "columns": [{"name": "x", "type": "string", "tags": [], "sensitivity": "PII"}]}
    status, resp = a.handle("POST", "/v1/datasets", body)
    assert status == 400 and resp["error"]["code"] == "INVALID_REQUEST"
    assert a.sink == []


def test_get_columns_includes_sensitivity(app):
    status, body = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert status == 200
    validate("metadata.columns.response.v1", body)
    assert all(set(c) == KEYS for c in body["columns"])
    assert levels(body["columns"]) == {"customer_id": "INTERNAL", "email": "PII", "country": "PUBLIC"}


def test_get_dataset_includes_sensitivity(app):
    status, body = app.handle("GET", f"/v1/datasets/{URN}")
    assert status == 200
    assert all(set(c) == KEYS for c in body["columns"])


def test_override_happy_path(app):
    status, body = app.handle("PUT", path("customer_id"), {"sensitivity": "CONFIDENTIAL"}, STEWARD)
    assert status == 200
    assert body == {"name": "customer_id", "type": "string", "tags": ["key"], "sensitivity": "CONFIDENTIAL"}
    event = app.sink[-1]
    assert event["change"] == "UPDATED" and event["owner"] == "team-crm"
    assert levels(event["columns"]) == {"customer_id": "CONFIDENTIAL", "email": "PII", "country": "PUBLIC"}
    assert len(app.sink) == 2
    _, cols = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert levels(cols["columns"])["customer_id"] == "CONFIDENTIAL"


def test_override_same_level_still_emits(app):
    status, _ = app.handle("PUT", path("email"), {"sensitivity": "PII"}, STEWARD)
    assert status == 200
    assert [e["change"] for e in app.sink] == ["CREATED", "UPDATED"]


def test_override_requires_steward(app):
    for headers in ({}, {"X-Roles": "reader"}, {"X-Roles": "stewards"}):
        status, body = app.handle("PUT", path("email"), {"sensitivity": "PUBLIC"}, headers)
        assert status == 403 and body["error"]["code"] == "FORBIDDEN"
    assert len(app.sink) == 1


def test_override_forbidden_checked_before_not_found(app):
    status, body = app.handle("PUT", path("email", "urn:ds:nope"), {"bad": 1}, {})
    assert status == 403 and body["error"]["code"] == "FORBIDDEN"


def test_override_unknown_dataset(app):
    status, body = app.handle("PUT", path("email", "urn:ds:nope"), {"sensitivity": "PII"}, STEWARD)
    assert status == 404 and body["error"]["code"] == "NOT_FOUND"


def test_override_unknown_column(app):
    for column in ("nope", "Email"):
        status, body = app.handle("PUT", path(column), {"sensitivity": "PII"}, STEWARD)
        assert status == 404 and body["error"]["code"] == "NOT_FOUND"
    assert len(app.sink) == 1


def test_override_unknown_column_checked_before_body(app):
    status, body = app.handle("PUT", path("nope"), {"sensitivity": "bogus"}, STEWARD)
    assert status == 404 and body["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("payload", [
    {"sensitivity": "SECRET"},
    {"sensitivity": "pii"},
    {"sensitivity": None},
    {},
    {"sensitivity": "PII", "reason": "x"},
    None,
    "PII",
    ["PII"],
])
def test_override_invalid_body(app, payload):
    status, body = app.handle("PUT", path("email"), payload, STEWARD)
    assert status == 400 and body["error"]["code"] == "INVALID_REQUEST"
    assert len(app.sink) == 1
    _, cols = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert levels(cols["columns"])["email"] == "PII"


def test_override_survives_reregister_with_changed_tags(app):
    app.handle("PUT", path("email"), {"sensitivity": "PUBLIC"}, STEWARD)
    changed = {**BODY, "columns": [
        {"name": "customer_id", "type": "string", "tags": ["pii"]},
        {"name": "email", "type": "text", "tags": ["pii", "confidential"]},
        {"name": "country", "type": "string", "tags": ["public"]},
    ]}
    status, body = app.handle("POST", "/v1/datasets", changed)
    assert status == 200
    assert levels(body["columns"]) == {"customer_id": "PII", "email": "PUBLIC", "country": "PUBLIC"}
    assert levels(app.sink[-1]["columns"]) == levels(body["columns"])
    assert app.sink[-1]["change"] == "UPDATED"


def test_new_column_on_reregister_gets_suggestion(app):
    app.handle("PUT", path("email"), {"sensitivity": "INTERNAL"}, STEWARD)
    extended = {**BODY, "columns": BODY["columns"] + [{"name": "ssn", "type": "string", "tags": ["PII"]}]}
    _, body = app.handle("POST", "/v1/datasets", extended)
    assert [c["name"] for c in body["columns"]] == ["customer_id", "email", "country", "ssn"]
    assert levels(body["columns"]) == {"customer_id": "INTERNAL", "email": "INTERNAL", "country": "PUBLIC",
                                       "ssn": "PII"}


def test_dropped_and_readded_column_loses_override(app):
    app.handle("PUT", path("email"), {"sensitivity": "PUBLIC"}, STEWARD)
    dropped = {**BODY, "columns": [c for c in BODY["columns"] if c["name"] != "email"]}
    _, body = app.handle("POST", "/v1/datasets", dropped)
    assert "email" not in levels(body["columns"])
    _, body = app.handle("POST", "/v1/datasets", BODY)
    assert levels(body["columns"])["email"] == "PII"


def test_owner_change_keeps_sensitivity(app):
    app.handle("PUT", path("country"), {"sensitivity": "CONFIDENTIAL"}, STEWARD)
    status, body = app.handle("PUT", f"/v1/datasets/{URN}/owner", {"owner": "team-x"}, STEWARD)
    assert status == 200
    expected = {"customer_id": "INTERNAL", "email": "PII", "country": "CONFIDENTIAL"}
    assert levels(body["columns"]) == expected
    assert app.sink[-1]["owner"] == "team-x" and levels(app.sink[-1]["columns"]) == expected


def test_every_event_validates(app):
    app.handle("PUT", path("email"), {"sensitivity": "CONFIDENTIAL"}, STEWARD)
    app.handle("PUT", f"/v1/datasets/{URN}/owner", {"owner": "team-x"}, STEWARD)
    app.handle("POST", "/v1/datasets", BODY)
    assert [e["change"] for e in app.sink] == ["CREATED", "UPDATED", "UPDATED", "UPDATED"]
    for event in app.sink:
        validate("metadata.dataset.changed.v1", event)
        assert all(set(c) == KEYS for c in event["columns"])


def test_overrides_never_leak(app):
    app.handle("PUT", path("email"), {"sensitivity": "PUBLIC"}, STEWARD)
    _, ds = app.handle("GET", f"/v1/datasets/{URN}")
    assert set(ds) == {"urn", "name", "owner", "columns"}
    assert all(set(c) == KEYS for c in ds["columns"])
