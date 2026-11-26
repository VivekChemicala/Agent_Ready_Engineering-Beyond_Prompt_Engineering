import pytest

from metadata_graph.sensitivity import LEVELS, column_out, suggest


def test_levels():
    assert LEVELS == ("PUBLIC", "INTERNAL", "CONFIDENTIAL", "PII")


@pytest.mark.parametrize("tags, level", [
    (["pii"], "PII"),
    (["confidential"], "CONFIDENTIAL"),
    (["public"], "PUBLIC"),
    ([], "INTERNAL"),
    (["key"], "INTERNAL"),
    (["key", "finance"], "INTERNAL"),
    (["public", "confidential"], "CONFIDENTIAL"),
    (["public", "pii"], "PII"),
    (["confidential", "pii"], "PII"),
    (["pii", "confidential", "public"], "PII"),
    (["public", "key"], "PUBLIC"),
    (["PII"], "PII"),
    (["Confidential", "PUBLIC"], "CONFIDENTIAL"),
    (["Public"], "PUBLIC"),
])
def test_suggest(tags, level):
    assert suggest(tags) == level


def test_column_out_defaults_missing_level_to_internal():
    assert column_out({"name": "a", "type": "string", "tags": []}) == {
        "name": "a", "type": "string", "tags": [], "sensitivity": "INTERNAL"}
