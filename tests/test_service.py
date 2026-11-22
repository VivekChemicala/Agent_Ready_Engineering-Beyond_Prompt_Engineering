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


def _cols(*specs):
    out = []
    for name, sensitivity in specs:
        col = {"name": name, "type": "string", "tags": []}
        if sensitivity is not None:
            col["sensitivity"] = sensitivity
        out.append(col)
    return {"urn": URN, "columns": out}


CLASSIFIED = _cols(("customer_id", "PUBLIC"), ("email", "PII"), ("segment", "CONFIDENTIAL"), ("phone", "PII"))
CLASSIFIED_ROWS = [
    {"customer_id": "c1", "email": "a@example.test", "segment": "gold", "phone": "555-0100"},
    {"customer_id": "c2", "email": None, "segment": None, "phone": ""},
]


def test_pii_columns_masked_without_pii_read():
    out = service(CLASSIFIED).run("u1", {"dataset:read"}, URN, CLASSIFIED_ROWS)
    assert out["status"] == 200
    assert out["masked_columns"] == ["email", "phone"]
    assert out["rows"] == [
        {"customer_id": "c1", "email": "***", "segment": "gold", "phone": "***"},
        {"customer_id": "c2", "email": None, "segment": None, "phone": "***"},
    ]


def test_pii_read_permission_sees_raw_values():
    out = service(CLASSIFIED).run("u1", {"dataset:read", "pii:read"}, URN, CLASSIFIED_ROWS)
    assert out["masked_columns"] == []
    assert out["rows"] == CLASSIFIED_ROWS


def test_masked_columns_follow_dataset_column_order():
    body = _cols(("phone", "PII"), ("customer_id", "PUBLIC"), ("email", "PII"))
    out = service(body).run("u1", {"dataset:read"}, URN, CLASSIFIED_ROWS)
    assert out["masked_columns"] == ["phone", "email"]
    assert list(out["rows"][0]) == ["phone", "customer_id", "email"]


def test_non_pii_levels_are_not_masked():
    body = _cols(("a", "PUBLIC"), ("b", "INTERNAL"), ("c", "CONFIDENTIAL"))
    rows = [{"a": 1, "b": 2, "c": 3}]
    out = service(body).run("u1", {"dataset:read"}, URN, rows)
    assert out["rows"] == rows
    assert out["masked_columns"] == []


def test_column_without_level_is_internal_and_not_masked():
    # Pre-DP-1501 payload: pii tag but no sensitivity -> INTERNAL, tags alone never mask.
    out = service(COLUMNS).run("u1", {"dataset:read"}, URN, ROWS)
    assert out["rows"] == ROWS
    assert out["masked_columns"] == []


def test_masked_columns_empty_when_no_rows():
    out = service(CLASSIFIED).run("u1", {"dataset:read"}, URN, [])
    assert out == {"status": 200, "rows": [], "masked_columns": ["email", "phone"]}


def test_unknown_sensitivity_level_is_upstream_contract_error():
    body = _cols(("email", "SECRET"))
    assert service(body).run("u1", {"dataset:read"}, URN, ROWS) == {"status": 502, "error": "UPSTREAM_CONTRACT"}
