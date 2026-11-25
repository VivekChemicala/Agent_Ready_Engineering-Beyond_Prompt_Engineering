import pytest

from metadata_graph.sensitivity import suggest


@pytest.mark.parametrize("tags, expected", [
    (["pii"], "PII"),
    (["confidential"], "CONFIDENTIAL"),
    (["public"], "PUBLIC"),
    (["key"], "INTERNAL"),
    ([], "INTERNAL"),
    (["pii", "public"], "PII"),
    (["public", "confidential"], "CONFIDENTIAL"),
    (["confidential", "pii"], "PII"),
    (["PII"], "PII"),
    (["Public"], "PUBLIC"),
])
def test_suggest(tags, expected):
    assert suggest(tags) == expected
