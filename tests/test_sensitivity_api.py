import copy

import pytest

from metadata_graph.app import App

URN = "urn:ds:crm.customers"
BODY = {
    "urn": URN, "name": "customers", "owner": "team-crm",
    "columns": [
        {"name": "customer_id", "type": "string", "tags": ["key"]},
        {"name": "email", "type": "string", "tags": ["pii"]},
        {"name": "country", "type": "string", "tags": ["public"]},
        {"name": "revenue", "type": "number", "tags": ["public", "Confidential"]},
    ],
}
LEVELS = {"customer_id": "INTERNAL", "email": "PII", "country": "PUBLIC", "revenue": "CONFIDENTIAL"}
STEWARD = {"X-Roles": "reader,steward"}
PATH = f"/v1/datasets/{URN}/columns/{{}}/sensitivity"


def levels(columns):
    return {c["name"]: c["sensitivity"] for c in columns}


@pytest.fixture
def app():
    a = App()
    a.handle("POST", "/v1/datasets", BODY)
    return a


def test_register_suggests_levels_and_event_carries_them(app):
    assert levels(app.sink[0]["columns"]) == LEVELS
    assert app.sink[0]["change"] == "CREATED"
    status, body = app.handle("GET", f"/v1/datasets/{URN}")
    assert status == 200 and levels(body["columns"]) == LEVELS


def test_register_response_has_levels():
    status, body = App().handle("POST", "/v1/datasets", BODY)
    assert status == 201 and levels(body["columns"]) == LEVELS
    assert set(body["columns"][0]) == {"name", "type", "tags", "sensitivity"}


def test_register_rejects_column_sensitivity():
    body = copy.deepcopy(BODY)
    body["columns"][0]["sensitivity"] = "PII"
    a = App()
    status, resp = a.handle("POST", "/v1/datasets", body)
    assert status == 400 and resp["error"]["code"] == "INVALID_REQUEST"
    assert a.sink == []


def test_get_columns_returns_levels(app):
    status, body = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert status == 200 and body["urn"] == URN
    assert [c["name"] for c in body["columns"]] == list(LEVELS)
    assert levels(body["columns"]) == LEVELS


def test_put_sensitivity_success(app):
    status, body = app.handle("PUT", PATH.format("customer_id"), {"sensitivity": "PII"}, STEWARD)
    assert status == 200
    assert body == {"name": "customer_id", "type": "string", "tags": ["key"], "sensitivity": "PII"}
    _, cols = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert levels(cols["columns"])["customer_id"] == "PII"
    assert len(app.sink) == 2
    event = app.sink[-1]
    assert event["change"] == "UPDATED" and event["owner"] == "team-crm"
    assert levels(event["columns"]) == {**LEVELS, "customer_id": "PII"}


def test_put_sensitivity_same_level_still_emits(app):
    status, _ = app.handle("PUT", PATH.format("email"), {"sensitivity": "PII"}, STEWARD)
    assert status == 200 and [e["change"] for e in app.sink] == ["CREATED", "UPDATED"]


def test_put_sensitivity_requires_steward(app):
    status, body = app.handle("PUT", PATH.format("email"), {"sensitivity": "PUBLIC"}, {"X-Roles": "reader"})
    assert status == 403 and body == {"error": {"code": "FORBIDDEN", "message": "steward role required"}}
    status, _ = app.handle("PUT", PATH.format("email"), {"sensitivity": "PUBLIC"})
    assert status == 403
    assert len(app.sink) == 1


def test_put_sensitivity_role_checked_before_dataset(app):
    status, body = app.handle("PUT", "/v1/datasets/urn:ds:nope/columns/x/sensitivity", {}, {"X-Roles": "reader"})
    assert status == 403 and body["error"]["code"] == "FORBIDDEN"


def test_put_sensitivity_unknown_dataset(app):
    status, body = app.handle("PUT", "/v1/datasets/urn:ds:nope/columns/email/sensitivity",
                              {"sensitivity": "PII"}, STEWARD)
    assert status == 404
    assert body == {"error": {"code": "NOT_FOUND", "message": "dataset urn:ds:nope not found"}}


def test_put_sensitivity_unknown_column(app):
    status, body = app.handle("PUT", PATH.format("Email"), {"sensitivity": "PII"}, STEWARD)
    assert status == 404
    assert body == {"error": {"code": "NOT_FOUND", "message": f"column Email not found in dataset {URN}"}}
    assert len(app.sink) == 1


def test_put_sensitivity_column_checked_before_body(app):
    status, body = app.handle("PUT", PATH.format("nope"), {"sensitivity": "bad"}, STEWARD)
    assert status == 404 and body["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("payload", [
    {},
    {"sensitivity": "PII", "reason": "x"},
    {"sensitivity": "SECRET"},
    {"sensitivity": "pii"},
    {"sensitivity": None},
    "PII",
    None,
])
def test_put_sensitivity_invalid_body(app, payload):
    status, body = app.handle("PUT", PATH.format("email"), payload, STEWARD)
    assert status == 400 and body["error"]["code"] == "INVALID_REQUEST"
    assert len(app.sink) == 1
    _, cols = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert levels(cols["columns"])["email"] == "PII"


def test_override_survives_reregister_and_new_columns_get_suggestion(app):
    app.handle("PUT", PATH.format("email"), {"sensitivity": "CONFIDENTIAL"}, STEWARD)
    body = copy.deepcopy(BODY)
    body["columns"][1]["tags"] = ["public"]
    body["columns"].append({"name": "phone", "type": "string", "tags": ["pii"]})
    status, resp = app.handle("POST", "/v1/datasets", body)
    assert status == 200
    expected = {**LEVELS, "email": "CONFIDENTIAL", "phone": "PII"}
    assert levels(resp["columns"]) == expected
    assert app.sink[-1]["change"] == "UPDATED" and levels(app.sink[-1]["columns"]) == expected
    _, cols = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert levels(cols["columns"]) == expected


def test_removed_then_readded_column_loses_override(app):
    app.handle("PUT", PATH.format("email"), {"sensitivity": "PUBLIC"}, STEWARD)
    without = copy.deepcopy(BODY)
    without["columns"] = [c for c in without["columns"] if c["name"] != "email"]
    app.handle("POST", "/v1/datasets", without)
    status, resp = app.handle("POST", "/v1/datasets", BODY)
    assert status == 200 and levels(resp["columns"]) == LEVELS


def test_owner_change_keeps_levels(app):
    app.handle("PUT", PATH.format("country"), {"sensitivity": "CONFIDENTIAL"}, STEWARD)
    status, body = app.handle("PUT", f"/v1/datasets/{URN}/owner", {"owner": "team-x"}, STEWARD)
    expected = {**LEVELS, "country": "CONFIDENTIAL"}
    assert status == 200 and levels(body["columns"]) == expected
    assert app.sink[-1]["owner"] == "team-x" and levels(app.sink[-1]["columns"]) == expected
    status, resp = app.handle("POST", "/v1/datasets", BODY)
    assert levels(resp["columns"]) == expected


def test_overrides_are_isolated_per_dataset(app):
    other = {**copy.deepcopy(BODY), "urn": "urn:ds:crm.other"}
    app.handle("PUT", PATH.format("email"), {"sensitivity": "PUBLIC"}, STEWARD)
    status, resp = app.handle("POST", "/v1/datasets", other)
    assert status == 201 and levels(resp["columns"]) == LEVELS


def test_stored_column_without_level_is_served_as_internal(app):
    ds = app.store.get(URN)
    for c in ds["columns"]:
        c.pop("sensitivity")
    app.store.put(ds)
    _, cols = app.handle("GET", f"/v1/datasets/{URN}/columns")
    assert set(levels(cols["columns"]).values()) == {"INTERNAL"}
    app.handle("PUT", f"/v1/datasets/{URN}/owner", {"owner": "team-x"}, STEWARD)
    assert set(levels(app.sink[-1]["columns"]).values()) == {"INTERNAL"}
