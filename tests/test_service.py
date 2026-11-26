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
    assert out["masked_columns"] == []


def test_upstream_contract_violation_is_502():
    bad = {"urn": URN, "columns": [{"name": "x", "type": "string", "tags": [], "colour": "blue"}]}
    assert service(bad).run("u1", {"dataset:read"}, URN, ROWS) == {"status": 502, "error": "UPSTREAM_CONTRACT"}


def test_upstream_error_is_502():
    assert service({}, status=500).run("u1", {"dataset:read"}, URN, ROWS)["status"] == 502


def cols(*specs):
    return {"urn": URN, "columns": [
        {"name": n, "type": "string", "tags": [], "sensitivity": lvl} for n, lvl in specs]}


PII_COLUMNS = cols(("customer_id", "INTERNAL"), ("email", "PII"), ("phone", "PII"))
PII_ROWS = [
    {"customer_id": "c1", "email": "a@example.test", "phone": "555-0100"},
    {"customer_id": "c2", "email": None, "phone": ""},
    {"customer_id": "c3", "email": 0, "phone": False},
]


def test_pii_masked_without_pii_read_and_nulls_kept():
    out = service(PII_COLUMNS).run("u1", {"dataset:read"}, URN, PII_ROWS)
    assert out == {"status": 200, "masked_columns": ["email", "phone"], "rows": [
        {"customer_id": "c1", "email": "***", "phone": "***"},
        {"customer_id": "c2", "email": None, "phone": "***"},
        {"customer_id": "c3", "email": "***", "phone": "***"},
    ]}


def test_masked_columns_follow_dataset_column_order():
    body = cols(("phone", "PII"), ("customer_id", "PUBLIC"), ("email", "PII"))
    out = service(body).run("u1", {"dataset:read"}, URN, PII_ROWS)
    assert out["masked_columns"] == ["phone", "email"]
    assert list(out["rows"][0]) == ["phone", "customer_id", "email"]


def test_masked_columns_listed_even_without_rows_or_values():
    out = service(PII_COLUMNS).run("u1", {"dataset:read"}, URN, [])
    assert out == {"status": 200, "rows": [], "masked_columns": ["email", "phone"]}
    out = service(PII_COLUMNS).run("u1", {"dataset:read"}, URN, [{"customer_id": "c1"}])
    assert out["rows"] == [{"customer_id": "c1", "email": None, "phone": None}]
    assert out["masked_columns"] == ["email", "phone"]


def test_pii_read_sees_everything():
    out = service(PII_COLUMNS).run("u1", {"dataset:read", "pii:read"}, URN, PII_ROWS)
    assert out == {"status": 200, "rows": PII_ROWS, "masked_columns": []}


def test_pii_read_alone_does_not_grant_access():
    assert service(PII_COLUMNS).run("u1", {"pii:read"}, URN, PII_ROWS) == {"status": 403, "error": "FORBIDDEN"}


def test_other_levels_never_masked():
    body = cols(("a", "PUBLIC"), ("b", "INTERNAL"), ("c", "CONFIDENTIAL"))
    rows = [{"a": "x", "b": "y", "c": "z"}]
    out = service(body).run("u1", {"dataset:read"}, URN, rows)
    assert out == {"status": 200, "rows": rows, "masked_columns": []}


def test_missing_sensitivity_is_internal_and_not_masked():
    out = service(COLUMNS).run("u1", {"dataset:read"}, URN, ROWS)
    assert out == {"status": 200, "rows": ROWS, "masked_columns": []}
    client = MetadataClient(lambda method, path: (200, COLUMNS))
    assert [c.sensitivity for c in client.get_columns(URN)] == ["INTERNAL", "INTERNAL"]


def test_column_model_reads_sensitivity():
    client = MetadataClient(lambda method, path: (200, PII_COLUMNS))
    assert [c.sensitivity for c in client.get_columns(URN)] == ["INTERNAL", "PII", "PII"]


def test_invalid_sensitivity_is_upstream_contract_error():
    for level in ("SECRET", "pii", "", None):
        body = {"urn": URN, "columns": [{"name": "email", "type": "string", "tags": [], "sensitivity": level}]}
        assert service(body).run("u1", {"dataset:read"}, URN, ROWS) == {"status": 502, "error": "UPSTREAM_CONTRACT"}


def test_errors_have_no_masked_columns():
    assert "masked_columns" not in service({}, status=500).run("u1", {"dataset:read"}, URN, ROWS)
    assert "masked_columns" not in service().run("u1", set(), URN, ROWS)
