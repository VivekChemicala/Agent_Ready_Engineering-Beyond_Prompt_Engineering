from types import SimpleNamespace

from gateway import query
from gateway.query import QueryService


def test_denied_returns_403(monkeypatch):
    ent = SimpleNamespace(decide=lambda *a: SimpleNamespace(allow=False, reason="NO_GRANT"))
    status, body = QueryService(ent, None).run("bob", "urn:ds:x", "select 1")
    assert status == 403
