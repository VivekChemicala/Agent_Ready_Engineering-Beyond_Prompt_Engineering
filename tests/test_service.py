from query_gateway.metadata_client import MetadataClient
from query_gateway.service import QueryService

URN = "urn:ds:crm.customers"
COLUMNS = {"urn": URN, "columns": [
    {"name": "customer_id", "type": "string", "tags": ["key"]},
    {"name": "email", "type": "string", "tags": ["pii"]},
]}
ROWS = [{"customer_id": "c1", "email": "a@example.test"}, {"customer_id": "c2", "email": None}]


def service(body=COLUMNS, status=200):
    return QueryService(MetadataClient(lambda method, path: (status, body)))


def test_requires_read_permission():
    assert service().run("u1", set(), URN, ROWS)["status"] == 403


def test_returns_rows_for_known_columns():
    out = service().run("u1", {"dataset:read"}, URN, ROWS)
    assert out["status"] == 200
    assert out["rows"] == ROWS


def test_upstream_contract_violation_is_502():
    bad = {"urn": URN, "columns": [{"name": "x", "type": "string", "tags": [], "colour": "blue"}]}
    assert service(bad).run("u1", {"dataset:read"}, URN, ROWS) == {"status": 502, "error": "UPSTREAM_CONTRACT"}


def test_upstream_error_is_502():
    assert service({}, status=500).run("u1", {"dataset:read"}, URN, ROWS)["status"] == 502


SENSITIVE = {"urn": URN, "columns": [
    {"name": "customer_id", "type": "string", "tags": ["key"], "sensitivity": "INTERNAL"},
    {"name": "email", "type": "string", "tags": ["pii"], "sensitivity": "PII"},
    {"name": "segment", "type": "string", "tags": ["confidential"], "sensitivity": "CONFIDENTIAL"},
    {"name": "country", "type": "string", "tags": ["public"], "sensitivity": "PUBLIC"},
    {"name": "phone", "type": "string", "tags": [], "sensitivity": "PII"},
]}
SENSITIVE_ROWS = [
    {"customer_id": "c1", "email": "a@example.test", "segment": "gold", "country": "NL", "phone": "+31 0"},
    {"customer_id": "c2", "email": None, "segment": None, "country": "DE", "phone": ""},
]


def test_pii_columns_are_masked_without_pii_read():
    out = service(SENSITIVE).run("u1", {"dataset:read"}, URN, SENSITIVE_ROWS)
    assert out["status"] == 200
    assert out["rows"] == [
        {"customer_id": "c1", "email": "***", "segment": "gold", "country": "NL", "phone": "***"},
        {"customer_id": "c2", "email": None, "segment": None, "country": "DE", "phone": "***"},
    ]
    assert out["masked_columns"] == ["email", "phone"]


def test_masked_columns_follow_dataset_column_order():
    body = {"urn": URN, "columns": list(reversed(SENSITIVE["columns"]))}
    out = service(body).run("u1", {"dataset:read"}, URN, SENSITIVE_ROWS)
    assert out["masked_columns"] == ["phone", "email"]


def test_pii_read_sees_clear_values():
    out = service(SENSITIVE).run("u1", {"dataset:read", "pii:read"}, URN, SENSITIVE_ROWS)
    assert out["rows"] == SENSITIVE_ROWS
    assert out["masked_columns"] == []


def test_pii_read_alone_does_not_grant_query():
    assert service(SENSITIVE).run("u1", {"pii:read"}, URN, SENSITIVE_ROWS) == {"status": 403, "error": "FORBIDDEN"}


def test_column_without_sensitivity_is_internal_and_not_masked():
    out = service().run("u1", {"dataset:read"}, URN, ROWS)
    assert out["rows"] == ROWS
    assert out["masked_columns"] == []
    assert all(c.sensitivity == "INTERNAL" for c in service().metadata.get_columns(URN))


def test_unknown_sensitivity_is_upstream_contract_violation():
    bad = {"urn": URN, "columns": [{"name": "x", "type": "string", "tags": [], "sensitivity": "SECRET"}]}
    assert service(bad).run("u1", {"dataset:read"}, URN, ROWS) == {"status": 502, "error": "UPSTREAM_CONTRACT"}


def test_tags_do_not_drive_masking():
    body = {"urn": URN, "columns": [{"name": "email", "type": "string", "tags": ["pii"], "sensitivity": "INTERNAL"}]}
    out = service(body).run("u1", {"dataset:read"}, URN, [{"email": "a@example.test"}])
    assert out["rows"] == [{"email": "a@example.test"}]
    assert out["masked_columns"] == []


def test_masking_with_no_rows():
    out = service(SENSITIVE).run("u1", {"dataset:read"}, URN, [])
    assert out == {"status": 200, "rows": [], "masked_columns": ["email", "phone"]}
