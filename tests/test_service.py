import copy
import dataclasses

import pytest

from query_gateway.metadata_client import MetadataClient
from query_gateway.models import Column
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
        {"name": n, "type": t, "tags": [], **({"sensitivity": lvl} if lvl else {})} for n, t, lvl in specs
    ]}


PII_COLUMNS = cols(("customer_id", "string", "INTERNAL"), ("email", "string", "PII"))


def test_pii_column_masked_without_pii_read_and_nulls_kept():
    out = service(PII_COLUMNS).run("u1", {"dataset:read"}, URN, ROWS)
    assert out == {"status": 200, "masked_columns": ["email"], "rows": [
        {"customer_id": "c1", "email": "***"}, {"customer_id": "c2", "email": None}]}


def test_missing_key_in_pii_column_stays_none():
    out = service(PII_COLUMNS).run("u1", {"dataset:read"}, URN, [{"customer_id": "c3"}])
    assert out["rows"] == [{"customer_id": "c3", "email": None}]


def test_non_string_and_falsy_values_masked():
    body = cols(("v", "string", "PII"))
    rows = [{"v": ""}, {"v": 0}, {"v": False}, {"v": 42}, {"v": 1.5}, {"v": True}, {"v": None}]
    out = service(body).run("u1", {"dataset:read"}, URN, rows)
    assert [r["v"] for r in out["rows"]] == ["***"] * 6 + [None]


def test_pii_read_sees_raw_values():
    out = service(PII_COLUMNS).run("u1", {"dataset:read", "pii:read"}, URN, ROWS)
    assert out == {"status": 200, "rows": ROWS, "masked_columns": []}


def test_masked_columns_in_dataset_column_order():
    body = cols(("b", "string", "PII"), ("a", "string", "INTERNAL"), ("c", "string", "PII"))
    rows = [{"c": "z", "a": "y", "b": "x"}]
    out = service(body).run("u1", {"dataset:read"}, URN, rows)
    assert out["masked_columns"] == ["b", "c"]
    assert out["rows"] == [{"b": "***", "a": "y", "c": "***"}]


def test_masked_columns_listed_with_zero_rows():
    out = service(PII_COLUMNS).run("u1", {"dataset:read"}, URN, [])
    assert out == {"status": 200, "rows": [], "masked_columns": ["email"]}


def test_other_levels_not_masked():
    body = cols(("c", "string", "CONFIDENTIAL"), ("i", "string", "INTERNAL"), ("p", "string", "PUBLIC"))
    rows = [{"c": "1", "i": "2", "p": "3"}]
    out = service(body).run("u1", {"dataset:read"}, URN, rows)
    assert out == {"status": 200, "rows": rows, "masked_columns": []}


def test_column_without_sensitivity_is_internal():
    client = MetadataClient(lambda method, path: (200, cols(("x", "string", None))))
    assert client.get_columns(URN)[0].sensitivity == "INTERNAL"
    out = QueryService(client).run("u1", {"dataset:read"}, URN, [{"x": "v"}])
    assert out == {"status": 200, "rows": [{"x": "v"}], "masked_columns": []}


@pytest.mark.parametrize("level", ["SECRET", "pii", None, ""])
def test_invalid_upstream_sensitivity_is_502(level):
    body = {"urn": URN, "columns": [{"name": "x", "type": "string", "tags": [], "sensitivity": level}]}
    assert service(body).run("u1", {"dataset:read"}, URN, ROWS) == {"status": 502, "error": "UPSTREAM_CONTRACT"}


def test_missing_dataset_read_takes_precedence():
    out = service(PII_COLUMNS).run("u1", {"pii:read"}, URN, ROWS)
    assert out == {"status": 403, "error": "FORBIDDEN"}


def test_input_rows_not_mutated():
    rows = [{"customer_id": "c1", "email": "a@example.test", "extra": 1}]
    snapshot = copy.deepcopy(rows)
    service(PII_COLUMNS).run("u1", {"dataset:read"}, URN, rows)
    assert rows == snapshot


def test_column_model_is_frozen_and_drops_unknown_fields():
    c = Column.from_dict({"name": "x", "type": "string", "tags": [], "sensitivity": "PII", "colour": "blue"})
    assert c == Column(name="x", type="string", tags=(), sensitivity="PII")
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.sensitivity = "PUBLIC"
