from query_gateway.models import Column


def test_column_defaults_to_internal_when_level_missing():
    assert Column.from_dict({"name": "x", "type": "string", "tags": []}).sensitivity == "INTERNAL"


def test_column_keeps_level():
    assert Column.from_dict({"name": "x", "type": "string", "tags": [], "sensitivity": "PII"}).sensitivity == "PII"


def test_column_drops_unknown_fields():
    col = Column.from_dict({"name": "x", "type": "string", "tags": ["pii"], "extra": 1})
    assert col == Column(name="x", type="string", tags=("pii",), sensitivity="INTERNAL")
