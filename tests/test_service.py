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


def test_upstream_contract_violation_is_502():
    bad = {"urn": URN, "columns": [{"name": "x", "type": "string", "tags": [], "colour": "blue"}]}
    assert service(bad).run("u1", {"dataset:read"}, URN, ROWS) == {"status": 502, "error": "UPSTREAM_CONTRACT"}


def test_upstream_error_is_502():
    assert service({}, status=500).run("u1", {"dataset:read"}, URN, ROWS)["status"] == 502


PII_COLUMNS = {"urn": URN, "columns": [
    {"name": "customer_id", "type": "string", "tags": ["key"], "sensitivity": "INTERNAL"},
    {"name": "phone", "type": "string", "tags": ["pii"], "sensitivity": "PII"},
    {"name": "segment", "type": "string", "tags": ["confidential"], "sensitivity": "CONFIDENTIAL"},
    {"name": "email", "type": "string", "tags": ["pii"], "sensitivity": "PII"},
    {"name": "country", "type": "string", "tags": ["public"], "sensitivity": "PUBLIC"},
]}
PII_ROWS = [
    {"customer_id": "c1", "phone": "555-0100", "segment": "gold", "email": "a@example.test", "country": "NL"},
    {"customer_id": "c2", "phone": None, "segment": None, "email": "", "country": None},
]


def test_no_masking_reports_empty_masked_columns():
    assert service().run("u1", {"dataset:read"}, URN, ROWS)["masked_columns"] == []


def test_pii_columns_are_masked_without_pii_read():
    out = service(PII_COLUMNS).run("u1", {"dataset:read"}, URN, PII_ROWS)
    assert out["status"] == 200
    assert out["masked_columns"] == ["phone", "email"]
    assert out["rows"] == [
        {"customer_id": "c1", "phone": "***", "segment": "gold", "email": "***", "country": "NL"},
        {"customer_id": "c2", "phone": None, "segment": None, "email": "***", "country": None},
    ]


def test_pii_read_permission_sees_raw_values():
    out = service(PII_COLUMNS).run("u1", {"dataset:read", "pii:read"}, URN, PII_ROWS)
    assert out == {"status": 200, "rows": PII_ROWS, "masked_columns": []}


def test_pii_read_alone_is_not_enough_to_query():
    assert service(PII_COLUMNS).run("u1", {"pii:read"}, URN, PII_ROWS) == {"status": 403, "error": "FORBIDDEN"}


def test_column_without_sensitivity_is_internal_and_not_masked():
    body = {"urn": URN, "columns": [{"name": "email", "type": "string", "tags": ["pii"]}]}
    client = MetadataClient(lambda method, path: (200, body))
    assert client.get_columns(URN)[0].sensitivity == "INTERNAL"
    out = service(body).run("u1", {"dataset:read"}, URN, [{"email": "a@example.test"}])
    assert out == {"status": 200, "rows": [{"email": "a@example.test"}], "masked_columns": []}


def test_masking_follows_level_not_tags():
    body = {"urn": URN, "columns": [
        {"name": "email", "type": "string", "tags": ["pii"], "sensitivity": "INTERNAL"},
        {"name": "note", "type": "string", "tags": [], "sensitivity": "PII"},
    ]}
    out = service(body).run("u1", {"dataset:read"}, URN, [{"email": "a@example.test", "note": "x"}])
    assert out["rows"] == [{"email": "a@example.test", "note": "***"}]
    assert out["masked_columns"] == ["note"]


def test_unknown_sensitivity_level_is_upstream_contract_violation():
    body = {"urn": URN, "columns": [{"name": "x", "type": "string", "tags": [], "sensitivity": "SECRET"}]}
    assert service(body).run("u1", {"dataset:read"}, URN, ROWS) == {"status": 502, "error": "UPSTREAM_CONTRACT"}


class FakeMetadataGraph:
    """Stands in for metadata-graph: steward overrides change what GET .../columns returns."""

    def __init__(self, columns):
        self.columns = [dict(c) for c in columns]

    def override(self, column, level):
        next(c for c in self.columns if c["name"] == column)["sensitivity"] = level

    def transport(self, method, path):
        assert (method, path) == ("GET", f"/v1/datasets/{URN}/columns")
        return 200, {"urn": URN, "columns": [dict(c) for c in self.columns]}


def test_steward_override_changes_what_is_masked_on_next_query():
    graph = FakeMetadataGraph(PII_COLUMNS["columns"])
    svc = QueryService(MetadataClient(graph.transport))
    assert svc.run("u1", {"dataset:read"}, URN, PII_ROWS)["masked_columns"] == ["phone", "email"]

    graph.override("email", "INTERNAL")
    graph.override("customer_id", "PII")
    out = svc.run("u1", {"dataset:read"}, URN, PII_ROWS)
    assert out["masked_columns"] == ["customer_id", "phone"]
    assert out["rows"][0] == {"customer_id": "***", "phone": "***", "segment": "gold",
                              "email": "a@example.test", "country": "NL"}


@pytest.mark.parametrize("column, expected", [
    ({"name": "e", "type": "string", "tags": ["pii"], "sensitivity": "PII"}, "PII"),
    ({"name": "e", "type": "string", "tags": ["pii"]}, "INTERNAL"),
    ({"name": "e", "type": "string", "tags": ["pii"], "sensitivity": None}, "INTERNAL"),
    ({"name": "e", "type": "string", "tags": [], "sensitivity": "PII", "sensitivity_override": "PUBLIC"}, "PUBLIC"),
    ({"name": "e", "type": "string", "tags": [], "sensitivity": "INTERNAL", "steward_sensitivity": "PII"}, "PII"),
    ({"name": "e", "type": "string", "tags": [], "suggested_sensitivity": "PII", "sensitivity": "PUBLIC"}, "PUBLIC"),
    ({"name": "e", "type": "string", "tags": [], "suggested_sensitivity": "PII"}, "PII"),
    ({"name": "e", "type": "string", "tags": [], "sensitivity": {"level": "PII", "source": "STEWARD"}}, "PII"),
    ({"name": "e", "type": "string", "tags": [], "sensitivity": {"suggested": "PII", "override": "INTERNAL"}},
     "INTERNAL"),
])
def test_column_effective_sensitivity(column, expected):
    assert Column.from_dict(column).sensitivity == expected
