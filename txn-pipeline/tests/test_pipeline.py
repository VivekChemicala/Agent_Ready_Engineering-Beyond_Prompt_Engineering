import json
from pathlib import Path

import pytest

from txn_pipeline.__main__ import main
from txn_pipeline.pipeline import REASON_CODES, run_pipeline

SAMPLE_INPUT = Path(__file__).resolve().parents[1] / "data" / "input"
CURRENCIES = {"USD", "EUR", "GBP", "CAD", "JPY"}
VALID_KEYS = [
    "transaction_id",
    "customer_id",
    "amount",
    "currency",
    "event_time",
    "merchant_id",
    "source_partition",
    "source_offset",
]
REJECT_KEYS = [
    "source_partition",
    "source_offset",
    "reason_code",
    "reason_detail",
    "raw",
]
METRICS_KEYS = [
    "schema_version",
    "input_records",
    "valid_records",
    "rejected_records",
    "rejects_by_reason",
    "partitions",
]


def make_message(offset=0, **overrides):
    value = {
        "transaction_id": f"txn-{offset:05d}",
        "customer_id": "cust-0001",
        "amount": 10.5,
        "currency": "USD",
        "event_time": "2026-11-01T00:00:00Z",
        "merchant_id": "merch-001",
    }
    value.update(overrides)
    return {"offset": offset, "key": "cust-0001", "timestamp": 1, "value": value}


def without(field, offset=0):
    message = make_message(offset)
    del message["value"][field]
    return message


def to_line(item):
    return item if isinstance(item, str) else json.dumps(item)


def write_partition(input_dir, partition, lines):
    input_dir.mkdir(parents=True, exist_ok=True)
    text = "".join(to_line(line) + "\n" for line in lines)
    (input_dir / f"partition-{partition}.jsonl").write_text(text, encoding="utf-8")


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def run(tmp_path, partitions):
    input_dir = tmp_path / "in"
    input_dir.mkdir(parents=True, exist_ok=True)
    for partition, lines in partitions.items():
        write_partition(input_dir, partition, lines)
    out = tmp_path / "out"
    metrics = run_pipeline(input_dir, out, approved_currencies=CURRENCIES)
    return metrics, read_jsonl(out / "valid.jsonl"), read_jsonl(out / "rejects.jsonl")


def reject_one(tmp_path, line):
    metrics, valid, rejects = run(tmp_path, {0: [line]})
    assert valid == []
    assert len(rejects) == 1
    assert list(rejects[0]) == REJECT_KEYS
    assert rejects[0]["raw"] == to_line(line)
    assert metrics["rejects_by_reason"][rejects[0]["reason_code"]] == 1
    return rejects[0]


def test_valid_row_has_exact_fields_and_drops_extras(tmp_path):
    message = make_message(3, channel="web", amount=7)
    _, valid, rejects = run(tmp_path, {4: [message]})
    assert rejects == []
    assert valid == [{
        "transaction_id": "txn-00003",
        "customer_id": "cust-0001",
        "amount": 7,
        "currency": "USD",
        "event_time": "2026-11-01T00:00:00Z",
        "merchant_id": "merch-001",
        "source_partition": 4,
        "source_offset": 3,
    }]
    assert list(valid[0]) == VALID_KEYS


@pytest.mark.parametrize(
    "line",
    [
        '{"offset": 1, "value": {"tran',
        "not json",
        "[1, 2]",
        '"a string"',
        "42",
        "null",
        '{"offset": NaN, "value": {}}',
        '{"offset": 0, "value": {"amount": Infinity}}',
        "1" * 5000,
        "[" * 100000,
        json.dumps({"value": make_message()["value"]}),
        json.dumps({**make_message(), "offset": -1}),
        json.dumps({**make_message(), "offset": 1.0}),
        json.dumps({**make_message(), "offset": "1"}),
        json.dumps({**make_message(), "offset": True}),
        json.dumps({**make_message(), "offset": None}),
    ],
)
def test_malformed_events(tmp_path, line):
    reject = reject_one(tmp_path, line)
    assert reject["reason_code"] == "MALFORMED_EVENT"
    assert reject["source_offset"] is None
    assert reject["source_partition"] == 0


def test_non_utf8_line_is_malformed(tmp_path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "partition-0.jsonl").write_bytes(b'{"offset": 0, "x": "\xff"}\n')
    metrics = run_pipeline(input_dir, tmp_path / "out", approved_currencies=CURRENCIES)
    assert metrics["rejects_by_reason"]["MALFORMED_EVENT"] == 1


@pytest.mark.parametrize("customer_id", [None, "", "   ", "\t\n"])
def test_null_customer_id(tmp_path, customer_id):
    reject = reject_one(tmp_path, make_message(5, customer_id=customer_id))
    assert reject["reason_code"] == "NULL_CUSTOMER_ID"
    assert reject["source_offset"] == 5


def test_missing_customer_id_is_null_customer_id(tmp_path):
    assert reject_one(tmp_path, without("customer_id"))["reason_code"] == (
        "NULL_CUSTOMER_ID"
    )


def test_null_customer_id_wins_over_schema_and_currency(tmp_path):
    line = make_message(customer_id=None, amount="1", currency="BTC")
    assert reject_one(tmp_path, line)["reason_code"] == "NULL_CUSTOMER_ID"


@pytest.mark.parametrize(
    "line",
    [
        make_message(customer_id=123),
        make_message(customer_id=["c"]),
        make_message(customer_id=True),
        make_message(amount="12.50"),
        make_message(amount=True),
        make_message(amount=0),
        make_message(amount=-3.2),
        make_message(amount=None),
        json.dumps(make_message(amount=1.5)).replace("1.5", "1e999"),
        make_message(transaction_id=""),
        make_message(transaction_id=7),
        make_message(merchant_id=None),
        make_message(currency=None),
        make_message(currency=1),
        make_message(event_time="2026-11-01"),
        make_message(event_time="2026-11-01T00:00:00"),
        make_message(event_time="2026-11-01T00:00:00+00:00"),
        make_message(event_time="2026-11-01T00:00:00.1234567Z"),
        make_message(event_time="2026-11-01 00:00:00Z"),
        make_message(event_time="2026-02-30T00:00:00Z"),
        make_message(event_time="2026-11-01T24:00:00Z"),
        make_message(event_time="２０２６-11-01T00:00:00Z"),
        make_message(event_time=1793836801000),
        {**make_message(), "key": 5},
        {**make_message(), "timestamp": "1"},
        {"offset": 0},
        {"offset": 0, "value": "x"},
        without("transaction_id"),
        without("amount"),
        without("currency"),
        without("event_time"),
        without("merchant_id"),
    ],
)
def test_schema_violations(tmp_path, line):
    reject = reject_one(tmp_path, line)
    assert reject["reason_code"] == "SCHEMA_VIOLATION"
    assert reject["source_offset"] == 0
    assert reject["reason_detail"]


def test_schema_violation_wins_over_currency(tmp_path):
    line = make_message(amount="1", currency="BTC")
    assert reject_one(tmp_path, line)["reason_code"] == "SCHEMA_VIOLATION"


@pytest.mark.parametrize(
    "event_time",
    ["2026-11-01T23:59:59Z", "2024-02-29T00:00:00.5Z", "2026-11-01T00:00:00.123456Z"],
)
def test_valid_event_times(tmp_path, event_time):
    _, valid, _ = run(tmp_path, {0: [make_message(event_time=event_time)]})
    assert valid[0]["event_time"] == event_time


def test_large_integer_amount_is_kept_unchanged(tmp_path):
    _, valid, _ = run(tmp_path, {0: [make_message(amount=10**30)]})
    assert valid[0]["amount"] == 10**30


@pytest.mark.parametrize("currency", ["XYZ", "BTC", "usd", "USD ", ""])
def test_invalid_currency(tmp_path, currency):
    reject = reject_one(tmp_path, make_message(currency=currency))
    assert reject["reason_code"] == "INVALID_CURRENCY"


def test_duplicates_within_and_across_partitions(tmp_path):
    metrics, valid, rejects = run(
        tmp_path,
        {
            0: [
                make_message(0, transaction_id="dup"),
                make_message(1, transaction_id="dup", amount=99.0),
            ],
            1: [make_message(0, transaction_id="dup")],
        },
    )
    assert [(r["source_partition"], r["source_offset"]) for r in valid] == [(0, 0)]
    assert [r["reason_code"] for r in rejects] == ["DUPLICATE_TRANSACTION"] * 2
    assert [(r["source_partition"], r["source_offset"]) for r in rejects] == [
        (0, 1),
        (1, 0),
    ]
    assert metrics["rejects_by_reason"]["DUPLICATE_TRANSACTION"] == 2


def test_only_accepted_events_reserve_transaction_id(tmp_path):
    _, valid, rejects = run(
        tmp_path,
        {
            0: [
                make_message(0, transaction_id="t", customer_id=None),
                make_message(1, transaction_id="t", currency="BTC"),
                make_message(2, transaction_id="t", amount="1"),
                make_message(3, transaction_id="t"),
            ]
        },
    )
    assert [r["source_offset"] for r in valid] == [3]
    assert [r["reason_code"] for r in rejects] == [
        "NULL_CUSTOMER_ID",
        "INVALID_CURRENCY",
        "SCHEMA_VIOLATION",
    ]


def test_partitions_processed_in_numeric_order(tmp_path):
    metrics, valid, rejects = run(
        tmp_path,
        {
            10: [make_message(0, transaction_id="t"), "bad"],
            2: [make_message(0, transaction_id="t"), "bad"],
            1: ["bad"],
        },
    )
    assert valid[0]["source_partition"] == 2
    assert [r["source_partition"] for r in rejects] == [1, 2, 10, 10]
    assert list(metrics["partitions"]) == ["1", "2", "10"]


def test_rows_are_in_line_order(tmp_path):
    lines = [make_message(i, currency="BTC" if i % 2 else "USD") for i in range(6)]
    _, valid, rejects = run(tmp_path, {0: list(reversed(lines))})
    assert [r["source_offset"] for r in valid] == [4, 2, 0]
    assert [r["source_offset"] for r in rejects] == [5, 3, 1]


def test_blank_lines_are_skipped_without_counting(tmp_path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    good = json.dumps(make_message())
    (input_dir / "partition-0.jsonl").write_text(f"\n   \n{good}\r\n\t\n")
    metrics = run_pipeline(input_dir, tmp_path / "out", approved_currencies=CURRENCIES)
    assert metrics["input_records"] == 1
    assert metrics["valid_records"] == 1
    assert metrics["rejected_records"] == 0


def test_raw_is_original_line(tmp_path):
    line = '{"offset": 0,   "value": {"customer_id": null, "note": "é"}}'
    assert reject_one(tmp_path, line)["raw"] == line


def test_non_partition_files_are_ignored(tmp_path):
    input_dir = tmp_path / "in"
    write_partition(input_dir, 0, [make_message()])
    (input_dir / "notes.txt").write_text("not json\n")
    (input_dir / "partition-x.jsonl").write_text("not json\n")
    metrics = run_pipeline(input_dir, tmp_path / "out", approved_currencies=CURRENCIES)
    assert list(metrics["partitions"]) == ["0"]
    assert metrics["input_records"] == 1


def test_empty_input_dir(tmp_path):
    metrics, valid, rejects = run(tmp_path, {})
    assert (valid, rejects) == ([], [])
    assert metrics == {
        "schema_version": "1.0",
        "input_records": 0,
        "valid_records": 0,
        "rejected_records": 0,
        "rejects_by_reason": {code: 0 for code in REASON_CODES},
        "partitions": {},
    }


def test_missing_input_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        run_pipeline(tmp_path / "missing", tmp_path / "out")


def test_sample_data(tmp_path):
    out = tmp_path / "out"
    metrics = run_pipeline(SAMPLE_INPUT, out)
    assert json.loads((out / "metrics.json").read_text()) == metrics
    assert list(metrics) == METRICS_KEYS
    assert metrics == {
        "schema_version": "1.0",
        "input_records": 43,
        "valid_records": 27,
        "rejected_records": 16,
        "rejects_by_reason": {
            "MALFORMED_EVENT": 1,
            "NULL_CUSTOMER_ID": 3,
            "SCHEMA_VIOLATION": 6,
            "INVALID_CURRENCY": 3,
            "DUPLICATE_TRANSACTION": 3,
        },
        "partitions": {
            "0": {"input_records": 14, "valid_records": 9, "rejected_records": 5},
            "1": {"input_records": 15, "valid_records": 9, "rejected_records": 6},
            "2": {"input_records": 14, "valid_records": 9, "rejected_records": 5},
        },
    }
    valid = read_jsonl(out / "valid.jsonl")
    rejects = read_jsonl(out / "rejects.jsonl")
    assert len(valid) == 27 and len(rejects) == 16
    assert all(list(r) == VALID_KEYS for r in valid)
    assert all(list(r) == REJECT_KEYS for r in rejects)
    ids = [r["transaction_id"] for r in valid]
    assert len(ids) == len(set(ids))
    order = [(r["source_partition"], r["source_offset"]) for r in valid]
    assert order == sorted(order)
    malformed = [r for r in rejects if r["reason_code"] == "MALFORMED_EVENT"]
    assert malformed[0]["source_partition"] == 1
    assert malformed[0]["source_offset"] is None
    sample_lines = (SAMPLE_INPUT / "partition-1.jsonl").read_text().splitlines()
    assert malformed[0]["raw"] == sample_lines[6]


def test_rerun_is_deterministic(tmp_path):
    run_pipeline(SAMPLE_INPUT, tmp_path / "a")
    run_pipeline(SAMPLE_INPUT, tmp_path / "b")
    for name in ("valid.jsonl", "rejects.jsonl", "metrics.json"):
        first = (tmp_path / "a" / name).read_bytes()
        assert first == (tmp_path / "b" / name).read_bytes()


def test_cli_writes_outputs(tmp_path, capsys):
    out = tmp_path / "out"
    assert main(["--input", str(SAMPLE_INPUT), "--output", str(out)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == json.loads((out / "metrics.json").read_text())
    assert (out / "valid.jsonl").exists() and (out / "rejects.jsonl").exists()


def test_cli_custom_currencies_and_missing_input(tmp_path, capsys):
    currencies = tmp_path / "currencies.json"
    currencies.write_text(json.dumps({"approved_currencies": ["USD", "BTC"]}))
    input_dir = tmp_path / "in"
    write_partition(
        input_dir, 0, [make_message(0, currency="BTC"), make_message(1, currency="EUR")]
    )
    out = tmp_path / "out"
    args = ["--input", str(input_dir), "--output", str(out)]
    assert main(args + ["--currencies", str(currencies)]) == 0
    assert [r["currency"] for r in read_jsonl(out / "valid.jsonl")] == ["BTC"]
    capsys.readouterr()
    assert main(["--input", str(tmp_path / "nope"), "--output", str(out)]) == 2
    assert "input directory not found" in capsys.readouterr().err
