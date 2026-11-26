from query_gateway.metadata_client import MetadataClient
from query_gateway.models import Column
from query_gateway.service import PII_READ_PERMISSION, QueryService

URN = "urn:ds:crm.customers"
COLUMNS = {"urn": URN, "columns": [
    {"name": "customer_id", "type": "string", "tags": ["key"]},
    {"name": "email", "type": "string", "tags": ["pii"]},
]}
ROWS = [{"customer_id": "c1", "email": "a@example.test"}, {"customer_id": "c2", "email": None}]
LEVELLED = {"urn": URN, "columns": [
    {"name": "customer_id", "type": "string", "tags": ["key"], "sensitivity": "INTERNAL"},
    {"name": "email", "type": "string", "tags": ["pii"], "sensitivity": "PII"},
]}
READ = {"dataset:read"}


def service(body=COLUMNS, status=200):
    return QueryService(MetadataClient(lambda method, path: (status, body)))


def cols(*specs):
    return {"urn": URN, "columns": [{"name": n, "type": "string", "tags": [], "sensitivity": s} for n, s in specs]}


def test_requires_read_permission():
    assert service().run("u1", set(), URN, ROWS) == {"status": 403, "error": "FORBIDDEN"}


def test_requires_read_permission_even_with_pii_read():
    assert service(LEVELLED).run("u1", {PII_READ_PERMISSION}, URN, ROWS) == {"status": 403, "error": "FORBIDDEN"}


def test_returns_rows_for_known_columns():
    out = service().run("u1", READ, URN, ROWS)
    assert out == {"status": 200, "rows": ROWS, "masked_columns": []}


def test_pii_column_masked_without_pii_read():
    rows = ROWS + [{"customer_id": "c3"}]
    out = service(LEVELLED).run("u1", READ, URN, rows)
    assert out == {"status": 200, "masked_columns": ["email"], "rows": [
        {"customer_id": "c1", "email": "***"},
        {"customer_id": "c2", "email": None},
        {"customer_id": "c3", "email": None},
    ]}


def test_pii_read_sees_raw_values():
    out = service(LEVELLED).run("u1", READ | {PII_READ_PERMISSION}, URN, ROWS)
    assert out == {"status": 200, "rows": ROWS, "masked_columns": []}


def test_columns_without_sensitivity_are_internal_and_not_masked():
    out = service(COLUMNS).run("u1", READ, URN, ROWS)
    assert out["rows"] == ROWS and out["masked_columns"] == []


def test_other_levels_not_masked():
    body = cols(("a", "PUBLIC"), ("b", "INTERNAL"), ("c", "CONFIDENTIAL"))
    rows = [{"a": "x", "b": "y", "c": "z"}]
    assert service(body).run("u1", READ, URN, rows) == {"status": 200, "rows": rows, "masked_columns": []}


def test_multiple_pii_columns_listed_in_dataset_order():
    body = cols(("phone", "PII"), ("id", "INTERNAL"), ("email", "PII"))
    rows = [{"email": "e", "id": "1", "phone": "p"}]
    out = service(body).run("u1", READ, URN, rows)
    assert out["masked_columns"] == ["phone", "email"]
    assert out["rows"] == [{"phone": "***", "id": "1", "email": "***"}]


def test_empty_rows_still_list_masked_columns():
    assert service(LEVELLED).run("u1", READ, URN, []) == {"status": 200, "rows": [], "masked_columns": ["email"]}


def test_all_null_rows_still_list_masked_columns():
    out = service(LEVELLED).run("u1", READ, URN, [{"customer_id": "c1", "email": None}])
    assert out["masked_columns"] == ["email"] and out["rows"] == [{"customer_id": "c1", "email": None}]


def test_non_string_values_are_masked():
    body = cols(("v", "PII"))
    rows = [{"v": 0}, {"v": False}, {"v": ""}, {"v": [1]}, {"v": 12.5}]
    out = service(body).run("u1", READ, URN, rows)
    assert out["rows"] == [{"v": "***"}] * 5


def test_out_of_enum_sensitivity_is_upstream_contract():
    for level in ("SECRET", "pii", ""):
        body = cols(("email", level))
        assert service(body).run("u1", READ, URN, ROWS) == {"status": 502, "error": "UPSTREAM_CONTRACT"}


def test_upstream_contract_violation_is_502():
    bad = {"urn": URN, "columns": [{"name": "x", "type": "string", "tags": [], "colour": "blue"}]}
    assert service(bad).run("u1", READ, URN, ROWS) == {"status": 502, "error": "UPSTREAM_CONTRACT"}


def test_upstream_error_is_502():
    assert service({}, status=500).run("u1", READ, URN, ROWS) == {"status": 502, "error": "UPSTREAM"}


def test_column_from_dict_defaults_to_internal():
    assert Column.from_dict({"name": "a", "type": "string"}).sensitivity == "INTERNAL"
    assert Column.from_dict({"name": "a", "type": "string", "sensitivity": None}).sensitivity == "INTERNAL"
    assert Column.from_dict({"name": "a", "type": "string", "sensitivity": "PII"}).sensitivity == "PII"


def test_column_from_dict_drops_unknown_fields():
    assert Column.from_dict({"name": "a", "type": "string", "tags": ["t"], "x": 1}) == Column("a", "string", ("t",))
