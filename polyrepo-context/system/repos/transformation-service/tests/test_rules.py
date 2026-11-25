from transformation.rules import RULES


def test_not_null():
    assert RULES["not_null"]([1, 2]) and not RULES["not_null"]([1, None])
