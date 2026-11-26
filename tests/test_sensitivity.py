import pytest
from platform_contracts import SENSITIVITY_LEVELS, validate

from metadata_graph.app import App
from metadata_graph.sensitivity import suggest_sensitivity

URN = "urn:ds:crm.customers"
STEWARD = {"X-Roles": "reader,steward"}
COLUMNS = [
    {"name": "customer_id", "type": "string", "tags": ["key"]},
    {"name": "email", "type": "string", "tags": ["pii"]},
    {"name": "country", "type": "string", "tags": ["public"]},
    {"name": "revenue", "type": "number", "tags": ["confidential", "public"]},
]


def body(columns=COLUMNS):
    return {"urn": URN, "name": "customers", "owner": "team-crm", "columns": [dict(c) for c in columns]}


def put(app, column, payload, headers=STEWARD, urn=URN):
    return app.handle("PUT", f"/v1/datasets/{urn}/columns/{column}/sensitivity", payload, headers)


def levels(app):
    _, resp = app.handle("GET", f"/v1/datasets/{URN}/columns")
    return {c["name"]: c["sensitivity"] for c in resp["columns"]}


@pytest.fixture
def app():
    a = App()
    a.handle("POST", "/v1/datasets", body())
    return a


@pytest.mark.parametrize("tags,expected", [
    ([], "INTERNAL"),
    (["key", "other"], "INTERNAL"),
    (["pii"], "PII"),
    (["confidential"], "CONFIDENTIAL"),
    (["public"], "PUBLIC"),
    (["public", "confidential"], "CONFIDENTIAL"),
    (["confidential", "pii", "public"], "PII"),
    (["PII"], "PII"),
    ([" Confidential "], "CONFIDENTIAL"),
    (["Public"], "PUBLIC"),
    (["personal"], "INTERNAL"),
])
def test_suggest_sensitivity(tags, expected):
    assert suggest_sensitivity(tags) == expected


def test_levels_match_contracts():
    assert SENSITIVITY_LEVELS == ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII")


def test_register_suggests_levels(app):
    expected = {"customer_id": "INTERNAL", "email": "PII", "country": "PUBLIC", "revenue": "CONFIDENTIAL"}
    assert levels(app) == expected
    event = app.sink[-1]
    assert {c["name"]: c["sensitivity"] for c in event["columns"]} == expected
    validate("metadata.dataset.changed.v1", event)


def test_register_response_and_get_dataset_carry_levels():
    a = App()
    status, resp = a.handle("POST", "/v1/datasets", body())
    assert status == 201
    for col in resp["columns"]:
        assert set(col) == {"name", "type", "tags", "sensitivity"}
    assert resp["columns"][1]["tags"] == ["pii"]
    _, ds = a.handle("GET", f"/v1/datasets/{URN}")
    assert [c["sensitivity"] for c in ds["columns"]] == ["INTERNAL", "PII", "PUBLIC", "CONFIDENTIAL"]


def test_register_rejects_sensitivity_in_column():
    a = App()
    cols = [{"name": "email", "type": "string", "tags": [], "sensitivity": "PII"}]
    status, resp = a.handle("POST", "/v1/datasets", body(cols))
    assert status == 400 and resp["error"]["code"] == "INVALID_REQUEST"
    assert a.sink == []


def test_get_columns_validated_shape(app):
    _, resp = app.handle("GET", f"/v1/datasets/{URN}/columns")
    validate("metadata.columns.response.v1", resp)
    assert all(set(c) == {"name", "type", "tags", "sensitivity"} for c in resp["columns"])


def test_put_sensitivity_success(app):
    status, resp = put(app, "customer_id", {"sensitivity": "PII"})
    assert status == 200
    assert resp == {"name": "customer_id", "type": "string", "tags": ["key"], "sensitivity": "PII"}
    assert levels(app)["customer_id"] == "PII"
    event = app.sink[-1]
    assert event["change"] == "UPDATED" and len(app.sink) == 2
    assert {c["name"]: c["sensitivity"] for c in event["columns"]}["customer_id"] == "PII"
    assert all(set(c) == {"name", "type", "tags", "sensitivity"} for c in event["columns"])
    validate("metadata.dataset.changed.v1", event)
    _, ds = app.handle("GET", f"/v1/datasets/{URN}")
    assert set(ds) == {"urn", "name", "owner", "columns"}
    assert all(set(c) == {"name", "type", "tags", "sensitivity"} for c in ds["columns"])


def test_put_sensitivity_unchanged_level_still_emits(app):
    status, _ = put(app, "email", {"sensitivity": "PII"})
    assert status == 200
    assert [e["change"] for e in app.sink] == ["CREATED", "UPDATED"]


def test_put_sensitivity_requires_steward(app):
    for headers in ({}, {"X-Roles": "reader"}, {"X-Roles": "stewards"}):
        status, resp = put(app, "email", {"sensitivity": "PUBLIC"}, headers)
        assert status == 403 and resp["error"]["code"] == "FORBIDDEN"
    assert levels(app)["email"] == "PII" and len(app.sink) == 1


def test_put_sensitivity_forbidden_before_not_found(app):
    status, resp = put(app, "email", None, {"X-Roles": "reader"}, urn="urn:ds:nope")
    assert status == 403 and resp["error"]["code"] == "FORBIDDEN"


def test_put_sensitivity_unknown_dataset(app):
    status, resp = put(app, "email", {"sensitivity": "PII"}, urn="urn:ds:nope")
    assert status == 404 and resp["error"]["code"] == "NOT_FOUND"


def test_put_sensitivity_unknown_column(app):
    for column in ("nope", "Email"):
        status, resp = put(app, column, {"sensitivity": "PII"})
        assert status == 404 and resp["error"]["code"] == "NOT_FOUND"
    assert len(app.sink) == 1


def test_put_sensitivity_not_found_before_invalid_body(app):
    status, resp = put(app, "nope", {"sensitivity": "bad"})
    assert status == 404 and resp["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize("payload", [
    None, {}, [], "PII", {"sensitivity": "pii"}, {"sensitivity": "SECRET"}, {"sensitivity": None},
    {"sensitivity": "PII", "reason": "x"}, {"level": "PII"},
])
def test_put_sensitivity_invalid_body(app, payload):
    status, resp = put(app, "email", payload)
    assert status == 400 and resp["error"]["code"] == "INVALID_REQUEST"
    assert levels(app)["email"] == "PII" and len(app.sink) == 1


def test_override_survives_reregistration(app):
    put(app, "email", {"sensitivity": "CONFIDENTIAL"})
    cols = [dict(c) for c in COLUMNS]
    cols[1]["tags"] = ["pii", "contact"]
    status, resp = app.handle("POST", "/v1/datasets", body(cols))
    assert status == 200
    assert levels(app)["email"] == "CONFIDENTIAL"
    assert {c["name"]: c["sensitivity"] for c in app.sink[-1]["columns"]}["email"] == "CONFIDENTIAL"
    assert app.sink[-1]["change"] == "UPDATED"
    # and again on a second re-registration
    app.handle("POST", "/v1/datasets", body(cols))
    assert levels(app)["email"] == "CONFIDENTIAL"


def test_non_overridden_column_resuggested(app):
    put(app, "email", {"sensitivity": "INTERNAL"})
    cols = [dict(c) for c in COLUMNS]
    cols[0]["tags"] = ["key", "pii"]
    cols[2]["tags"] = []
    app.handle("POST", "/v1/datasets", body(cols))
    assert levels(app) == {"customer_id": "PII", "email": "INTERNAL", "country": "INTERNAL",
                           "revenue": "CONFIDENTIAL"}


def test_new_column_gets_suggestion(app):
    put(app, "email", {"sensitivity": "PUBLIC"})
    cols = COLUMNS + [{"name": "phone", "type": "string", "tags": ["PII"]}]
    app.handle("POST", "/v1/datasets", body(cols))
    assert levels(app)["phone"] == "PII"
    assert levels(app)["email"] == "PUBLIC"


def test_removed_then_readded_column_loses_override(app):
    put(app, "email", {"sensitivity": "PUBLIC"})
    app.handle("POST", "/v1/datasets", body([c for c in COLUMNS if c["name"] != "email"]))
    assert "email" not in levels(app)
    app.handle("POST", "/v1/datasets", body())
    assert levels(app)["email"] == "PII"


def test_owner_change_keeps_levels(app):
    put(app, "country", {"sensitivity": "CONFIDENTIAL"})
    status, resp = app.handle("PUT", f"/v1/datasets/{URN}/owner", {"owner": "team-x"}, STEWARD)
    assert status == 200
    assert {c["name"]: c["sensitivity"] for c in resp["columns"]}["country"] == "CONFIDENTIAL"
    assert {c["name"]: c["sensitivity"] for c in app.sink[-1]["columns"]}["country"] == "CONFIDENTIAL"


def test_column_without_level_defaults_to_internal():
    a = App()
    a.store.put({"urn": URN, "name": "customers", "owner": "team-crm",
                 "columns": [{"name": "legacy", "type": "string", "tags": ["pii"]}]})
    _, resp = a.handle("GET", f"/v1/datasets/{URN}/columns")
    assert resp["columns"][0]["sensitivity"] == "INTERNAL"
