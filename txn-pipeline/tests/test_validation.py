import json
import math

import pytest

from tests.helpers import MISSING, event, message, reasons, run


def run_one(tmp_path, line):
    _, valid, rejects = run(tmp_path, {0: [line]})
    return valid, rejects


def test_valid_event_is_accepted_with_exact_keys(tmp_path):
    value = event(channel="pos", extra={"x": 1})
    valid, rejects = run_one(tmp_path, message(7, value))
    assert rejects == []
    assert valid == [{
        "transaction_id": "txn-1",
        "customer_id": "cust-1",
        "amount": 10.5,
        "currency": "USD",
        "event_time": "2026-11-01T10:00:00Z",
        "merchant_id": "merch-1",
        "source_partition": 0,
        "source_offset": 7,
    }]


@pytest.mark.parametrize("line, expected_offset", [
    ('{"offset": 1, "value": {"transaction_id"', None),
    ("not json", None),
    ("[1, 2, 3]", None),
    ('"a string"', None),
    ("null", None),
    (json.dumps({"value": event()}), None),
    (json.dumps({"offset": -1, "value": event()}), None),
    (json.dumps({"offset": "3", "value": event()}), None),
    (json.dumps({"offset": 1.0, "value": event()}), None),
    (json.dumps({"offset": True, "value": event()}), None),
    (json.dumps({"offset": 4}), 4),
    (json.dumps({"offset": 4, "value": None}), 4),
    (json.dumps({"offset": 4, "value": [event()]}), 4),
    (json.dumps({"offset": 4, "value": json.dumps(event())}), 4),
])
def test_malformed_event(tmp_path, line, expected_offset):
    valid, rejects = run_one(tmp_path, line)
    assert valid == []
    assert reasons(rejects) == ["MALFORMED_EVENT"]
    assert rejects[0]["source_offset"] == expected_offset
    assert rejects[0]["raw"] == line


def test_invalid_utf8_is_malformed_not_an_error(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "partition-0.jsonl").write_bytes(b'{"offset": 0, \xff}\n')
    from txn_pipeline import run_pipeline
    metrics = run_pipeline(input_dir, tmp_path / "out")
    assert metrics["rejects_by_reason"]["MALFORMED_EVENT"] == 1


@pytest.mark.parametrize("customer_id", [None, MISSING, "", "   ", "\t\n"])
def test_null_customer_id(tmp_path, customer_id):
    valid, rejects = run_one(tmp_path, message(0, event(customer_id=customer_id)))
    assert valid == []
    assert reasons(rejects) == ["NULL_CUSTOMER_ID"]


def test_null_customer_id_wins_over_schema_and_currency(tmp_path):
    value = event(customer_id=None, amount="bad", currency="XYZ")
    _, rejects = run_one(tmp_path, message(0, value))
    assert reasons(rejects) == ["NULL_CUSTOMER_ID"]


@pytest.mark.parametrize("overrides", [
    {"customer_id": 123},
    {"customer_id": ["cust-1"]},
    {"transaction_id": MISSING},
    {"transaction_id": ""},
    {"transaction_id": "  "},
    {"transaction_id": 42},
    {"merchant_id": MISSING},
    {"merchant_id": " "},
    {"merchant_id": None},
    {"amount": MISSING},
    {"amount": "10.5"},
    {"amount": True},
    {"amount": 0},
    {"amount": -1.5},
    {"amount": None},
    {"currency": MISSING},
    {"currency": 840},
    {"currency": None},
    {"event_time": MISSING},
    {"event_time": None},
    {"event_time": "2026-11-01 10:00:00Z"},
    {"event_time": "2026-11-01T10:00:00"},
    {"event_time": "2026-11-01T10:00:00+00:00"},
    {"event_time": "2026-11-01T10:00:00.1234567Z"},
    {"event_time": "2026-11-01T10:00:00.Z"},
    {"event_time": "2026-02-30T10:00:00Z"},
    {"event_time": "2026-11-01T24:00:00Z"},
    {"event_time": "2026-11-01T10:00:00Z\n"},
    {"event_time": "2026-11-01"},
    {"event_time": 1793836801000},
])
def test_schema_violation(tmp_path, overrides):
    valid, rejects = run_one(tmp_path, message(0, event(**overrides)))
    assert valid == []
    assert reasons(rejects) == ["SCHEMA_VIOLATION"]
    assert rejects[0]["reason_detail"]


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_amount_is_schema_violation(tmp_path, token):
    line = message(0, event()).replace('"amount": 10.5', f'"amount": {token}')
    assert token in line
    valid, rejects = run_one(tmp_path, line)
    assert valid == []
    assert reasons(rejects) == ["SCHEMA_VIOLATION"]


def test_schema_violation_wins_over_invalid_currency(tmp_path):
    _, rejects = run_one(tmp_path, message(0, event(amount="1", currency="XYZ")))
    assert reasons(rejects) == ["SCHEMA_VIOLATION"]


@pytest.mark.parametrize("event_time", [
    "2026-11-01T10:00:00.1Z",
    "2026-11-01T10:00:00.123456Z",
    "2024-02-29T23:59:59Z",
])
def test_valid_event_time_variants(tmp_path, event_time):
    valid, rejects = run_one(tmp_path, message(0, event(event_time=event_time)))
    assert rejects == []
    assert valid[0]["event_time"] == event_time


@pytest.mark.parametrize("amount", [1, 0.01, 10 ** 30])
def test_valid_amount_variants(tmp_path, amount):
    valid, _ = run_one(tmp_path, message(0, event(amount=amount)))
    assert valid[0]["amount"] == amount
    assert math.isfinite(valid[0]["amount"])


@pytest.mark.parametrize("currency", ["XYZ", "usd", "Usd", " USD", "", "BTC"])
def test_invalid_currency(tmp_path, currency):
    valid, rejects = run_one(tmp_path, message(0, event(currency=currency)))
    assert valid == []
    assert reasons(rejects) == ["INVALID_CURRENCY"]


def test_currencies_come_from_config(tmp_path, monkeypatch):
    from txn_pipeline import pipeline

    config = tmp_path / "currencies.json"
    config.write_text(json.dumps({"approved_currencies": ["XYZ"]}))
    original = pipeline.load_approved_currencies
    monkeypatch.setattr(
        pipeline, "load_approved_currencies", lambda: original(config)
    )
    _, valid, rejects = run(
        tmp_path, {0: [message(0, event(currency="XYZ")),
                       message(1, event(transaction_id="t2", currency="USD"))]}
    )
    assert [v["currency"] for v in valid] == ["XYZ"]
    assert reasons(rejects) == ["INVALID_CURRENCY"]


def test_default_config_is_resolved_from_project_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    valid, _ = run_one(tmp_path, message(0, event(currency="JPY")))
    assert len(valid) == 1


def test_duplicate_transaction_within_partition(tmp_path):
    _, valid, rejects = run(tmp_path, {0: [
        message(0, event(amount=1)),
        message(1, event(amount=2)),
    ]})
    assert [v["amount"] for v in valid] == [1]
    assert reasons(rejects) == ["DUPLICATE_TRANSACTION"]
    assert rejects[0]["source_offset"] == 1


def test_duplicate_transaction_across_partitions(tmp_path):
    _, valid, rejects = run(tmp_path, {
        0: [message(0, event())],
        3: [message(0, event(customer_id="cust-2"))],
    })
    assert [(v["source_partition"], v["customer_id"]) for v in valid] == [
        (0, "cust-1")
    ]
    assert reasons(rejects) == ["DUPLICATE_TRANSACTION"]
    assert rejects[0]["source_partition"] == 3


@pytest.mark.parametrize("bad", [
    {"customer_id": None},
    {"amount": "10"},
    {"currency": "XYZ"},
])
def test_rejected_event_does_not_reserve_transaction_id(tmp_path, bad):
    _, valid, rejects = run(tmp_path, {0: [
        message(0, event(**bad)),
        message(1, event()),
        message(2, event()),
    ]})
    assert [v["source_offset"] for v in valid] == [1]
    assert reasons(rejects)[1:] == ["DUPLICATE_TRANSACTION"]
    assert [r["source_offset"] for r in rejects] == [0, 2]


def test_malformed_then_valid_same_id_is_accepted(tmp_path):
    malformed = json.dumps({"offset": 0, "value": "txn-1"})
    _, valid, rejects = run(tmp_path, {0: [malformed, message(1, event())]})
    assert [v["transaction_id"] for v in valid] == ["txn-1"]
    assert reasons(rejects) == ["MALFORMED_EVENT"]


def test_duplicate_is_last_check(tmp_path):
    _, valid, rejects = run(tmp_path, {0: [
        message(0, event()),
        message(1, event(currency="XYZ")),
        message(2, event(amount=-1)),
    ]})
    assert len(valid) == 1
    assert reasons(rejects) == ["INVALID_CURRENCY", "SCHEMA_VIOLATION"]
