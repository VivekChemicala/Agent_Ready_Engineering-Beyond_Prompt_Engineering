import pytest

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
STEWARD = {"X-Roles": "reader,steward"}
COLUMN_KEYS = {"name", "type", "tags", "sensitivity"}


def sens_path(column, urn=URN):
    return f"/v1/datasets/{urn}/columns/{column}/sensitivity"


@pytest.fixture
def app():
    a = App()
    a.handle("POST", "/v1/datasets", BODY)
    return a


def levels(app, urn=URN):
    _, body = app.handle("GET", f"/v1/datasets/{urn}/columns")
    return {c["name"]: c["sensitivity"] for c in body["columns"]}


@pytest.mark.parametrize("tags,expected", [
    (["key"], "INTERNAL"),
    (["pii"], "PII"),
    (["confidential"], "CONFIDENTIAL"),
    (["public"], "PUBLIC"),
    ([], "INTERNAL"),
    (["public", "pii"], "PII"),
    (["public", "confidential"], "CONFIDENTIAL"),
    (["confidential", "pii"], "PII"),
    (["PII"], "PII"),
    (["Public"], "PUBLIC"),
    (["piii", "non-public", "confidential-ish"], "INTERNAL"),
])
def test_suggest_sensitivity(tags, expected):
    assert suggest_sensitivity(tags) == expected


def test_get_columns_returns_levels(app):
    assert levels(app) == {"customer_id": "INTERNAL", "email": "PII", "country": "PUBLIC"}


def test_created_event_carries_levels(app):
    event = app.sink[0]
    assert event["change"] == "CREATED"
    assert [c["sensitivity"] for c in event["columns"]] == ["INTERNAL", "PII", "PUBLIC"]


def test_put_sensitivity_success(app):
    status, body = app.handle("PUT", sens_path("customer_id"), {"sensitivity": "CONFIDENTIAL"}, STEWARD)
    assert status == 200
    assert body == {"name": "customer_id", "type": "string", "tags": ["key"], "sensitivity": "CONFIDENTIAL"}
    assert len(app.sink) == 2 and app.sink[-1]["change"] == "UPDATED"
    assert {c["name"]: c["sensitivity"] for c in app.sink[-1]["columns"]}["customer_id"] == "CONFIDENTIAL"
    assert levels(app)["customer_id"] == "CONFIDENTIAL"


def test_put_same_level_still_emits(app):
    status, body = app.handle("PUT", sens_path("email"), {"sensitivity": "PII"}, STEWARD)
    assert status == 200 and body["sensitivity"] == "PII"
    assert [e["change"] for e in app.sink] == ["CREATED", "UPDATED"]


def test_put_requires_steward(app):
    status, body = app.handle("PUT", sens_path("email"), {"sensitivity": "PUBLIC"}, {"X-Roles": "reader"})
    assert status == 403 and body["error"]["code"] == "FORBIDDEN"
    status, _ = app.handle("PUT", sens_path("email"), {"sensitivity": "PUBLIC"})
    assert status == 403
    assert len(app.sink) == 1 and levels(app)["email"] == "PII"


def test_put_forbidden_before_not_found(app):
    status, body = app.handle("PUT", sens_path("email", "urn:ds:nope"), {"sensitivity": "PUBLIC"}, {})
    assert status == 403 and body["error"]["code"] == "FORBIDDEN"


def test_put_unknown_dataset(app):
    status, body = app.handle("PUT", sens_path("email", "urn:ds:nope"), {"sensitivity": "PUBLIC"}, STEWARD)
    assert status == 404 and body["error"]["code"] == "NOT_FOUND"


def test_put_unknown_column(app):
    status, body = app.handle("PUT", sens_path("phone"), {"sensitivity": "PUBLIC"}, STEWARD)
    assert status == 404 and body["error"]["code"] == "NOT_FOUND"
    status, _ = app.handle("PUT", sens_path("Email"), {"sensitivity": "PUBLIC"}, STEWARD)
    assert status == 404
    assert len(app.sink) == 1


def test_put_unknown_column_before_invalid_body(app):
    status, body = app.handle("PUT", sens_path("phone"), {"sensitivity": "nope"}, STEWARD)
    assert status == 404 and body["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("bad", [
    {}, {"sensitivity": "SECRET"}, {"sensitivity": "pii"}, {"sensitivity": 1}, {"sensitivity": None},
    {"sensitivity": "PII", "extra": True}, None, [], "PII",
])
def test_put_invalid_body(app, bad):
    status, body = app.handle("PUT", sens_path("email"), bad, STEWARD)
    assert status == 400 and body["error"]["code"] == "INVALID_REQUEST"
    assert len(app.sink) == 1 and levels(app)["email"] == "PII"


def test_override_survives_reregistration(app):
    app.handle("PUT", sens_path("email"), {"sensitivity": "CONFIDENTIAL"}, STEWARD)
    changed = {**BODY, "columns": [
        {"name": "customer_id", "type": "string", "tags": ["key"]},
        {"name": "email", "type": "text", "tags": ["pii", "contact"]},
        {"name": "country", "type": "string", "tags": ["public"]},
    ]}
    status, _ = app.handle("POST", "/v1/datasets", changed)
    assert status == 200 and app.sink[-1]["change"] == "UPDATED"
    assert levels(app)["email"] == "CONFIDENTIAL"
    assert {c["name"]: c["sensitivity"] for c in app.sink[-1]["columns"]}["email"] == "CONFIDENTIAL"
    app.handle("POST", "/v1/datasets", BODY)
    assert levels(app)["email"] == "CONFIDENTIAL"


def test_override_discarded_when_column_removed(app):
    app.handle("PUT", sens_path("email"), {"sensitivity": "PUBLIC"}, STEWARD)
    without = {**BODY, "columns": [c for c in BODY["columns"] if c["name"] != "email"]}
    app.handle("POST", "/v1/datasets", without)
    assert "email" not in levels(app)
    app.handle("POST", "/v1/datasets", BODY)
    assert levels(app)["email"] == "PII"


def test_new_column_on_reregistration_gets_suggestion(app):
    more = {**BODY, "columns": BODY["columns"] + [
        {"name": "ssn", "type": "string", "tags": ["confidential", "pii"]},
        {"name": "notes", "type": "string", "tags": []},
    ]}
    app.handle("POST", "/v1/datasets", more)
    assert levels(app)["ssn"] == "PII" and levels(app)["notes"] == "INTERNAL"


def test_non_overridden_level_follows_tags(app):
    app.handle("PUT", sens_path("email"), {"sensitivity": "INTERNAL"}, STEWARD)
    retagged = {**BODY, "columns": [
        {"name": "customer_id", "type": "string", "tags": ["key", "confidential"]},
        {"name": "email", "type": "string", "tags": ["public"]},
        {"name": "country", "type": "string", "tags": []},
    ]}
    app.handle("POST", "/v1/datasets", retagged)
    assert levels(app) == {"customer_id": "CONFIDENTIAL", "email": "INTERNAL", "country": "INTERNAL"}


def test_owner_put_keeps_levels(app):
    app.handle("PUT", sens_path("customer_id"), {"sensitivity": "PUBLIC"}, STEWARD)
    status, body = app.handle("PUT", f"/v1/datasets/{URN}/owner", {"owner": "team-x"}, STEWARD)
    assert status == 200
    assert [c["sensitivity"] for c in body["columns"]] == ["PUBLIC", "PII", "PUBLIC"]
    assert [c["sensitivity"] for c in app.sink[-1]["columns"]] == ["PUBLIC", "PII", "PUBLIC"]
    app.handle("POST", "/v1/datasets", BODY)
    assert levels(app)["customer_id"] == "PUBLIC"


def test_register_rejects_sensitivity_in_body():
    a = App()
    body = {**BODY, "columns": [{"name": "x", "type": "string", "tags": [], "sensitivity": "PII"}]}
    status, resp = a.handle("POST", "/v1/datasets", body)
    assert status == 400 and resp["error"]["code"] == "INVALID_REQUEST"
    assert a.sink == []


def test_outward_payloads_have_exactly_four_column_keys():
    a = App()
    payloads = []
    payloads.append(a.handle("POST", "/v1/datasets", BODY)[1]["columns"])
    payloads.append([a.handle("PUT", sens_path("email"), {"sensitivity": "CONFIDENTIAL"}, STEWARD)[1]])
    payloads.append(a.handle("POST", "/v1/datasets", BODY)[1]["columns"])
    payloads.append(a.handle("GET", f"/v1/datasets/{URN}")[1]["columns"])
    payloads.append(a.handle("GET", f"/v1/datasets/{URN}/columns")[1]["columns"])
    payloads.append(a.handle("PUT", f"/v1/datasets/{URN}/owner", {"owner": "team-x"}, STEWARD)[1]["columns"])
    payloads.extend(e["columns"] for e in a.sink)
    assert len(a.sink) == 4
    for columns in payloads:
        for c in columns:
            assert set(c) == COLUMN_KEYS
