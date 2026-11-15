import json
import subprocess
import sys
from pathlib import Path

import pytest

import txn_pipeline.pipeline as pipeline_module
from txn_pipeline import run_pipeline
from txn_pipeline.pipeline import (
    DUPLICATE_TRANSACTION,
    INVALID_CURRENCY,
    MALFORMED_EVENT,
    NULL_CUSTOMER_ID,
    REASON_CODES,
    SCHEMA_VIOLATION,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_INPUT = PROJECT_ROOT / "data" / "input"

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


def make_value(**overrides):
    value = {
        "transaction_id": "txn-1",
        "customer_id": "cust-1",
        "amount": 10.5,
        "currency": "USD",
        "event_time": "2026-11-01T00:00:00Z",
        "merchant_id": "merch-1",
    }
    value.update(overrides)
    return value


def make_event(offset=0, **value_overrides):
    return {
        "offset": offset,
        "key": "cust-1",
        "timestamp": 1793836801000,
        "value": make_value(**value_overrides),
    }


def to_line(item):
    if isinstance(item, bytes):
        return item
    text = item if isinstance(item, str) else json.dumps(item)
    return text.encode("utf-8")


def write_partition(input_dir, partition, lines):
    input_dir.mkdir(parents=True, exist_ok=True)
    path = input_dir / f"partition-{partition}.jsonl"
    path.write_bytes(b"".join(to_line(ln) + b"\n" for ln in lines))


def read_jsonl(path):
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]


def run(tmp_path, partitions):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    for partition, lines in partitions.items():
        write_partition(input_dir, partition, lines)
    output_dir = tmp_path / "out"
    metrics = run_pipeline(input_dir, output_dir)
    return (
        metrics,
        read_jsonl(output_dir / "valid.jsonl"),
        read_jsonl(output_dir / "rejects.jsonl"),
    )


def reject_reason(tmp_path, line):
    _, valid, rejects = run(tmp_path, {0: [line]})
    assert valid == []
    assert len(rejects) == 1
    assert list(rejects[0]) == REJECT_KEYS
    return rejects[0]["reason_code"]


def test_valid_row_has_exact_fields_and_drops_extras(tmp_path):
    event = make_event(7, channel="web")
    _, valid, rejects = run(tmp_path, {3: [event]})
    assert rejects == []
    assert valid == [{**make_value(), "source_partition": 3, "source_offset": 7}]
    assert list(valid[0]) == VALID_KEYS


def test_valid_values_are_unchanged(tmp_path):
    event = make_event(amount=5, event_time="2026-02-28T23:59:59.123456Z")
    _, valid, _ = run(tmp_path, {0: [event]})
    assert valid[0]["amount"] == 5 and isinstance(valid[0]["amount"], int)
    assert valid[0]["event_time"] == "2026-02-28T23:59:59.123456Z"


def test_reject_row_has_exact_fields_and_raw_line(tmp_path):
    line = json.dumps(make_event(4, currency="BTC"))
    _, _, rejects = run(tmp_path, {2: [line]})
    assert rejects == [
        {
            "source_partition": 2,
            "source_offset": 4,
            "reason_code": INVALID_CURRENCY,
            "reason_detail": rejects[0]["reason_detail"],
            "raw": line,
        }
    ]
    assert "BTC" in rejects[0]["reason_detail"]


@pytest.mark.parametrize("customer_id", [None, "", " ", "\t \u00a0"])
def test_null_or_blank_customer_id(tmp_path, customer_id):
    assert reject_reason(tmp_path, make_event(customer_id=customer_id)) == (
        NULL_CUSTOMER_ID
    )


@pytest.mark.parametrize("customer_id", [42, 0, True, [], {}])
def test_non_string_customer_id_is_schema_violation(tmp_path, customer_id):
    assert reject_reason(tmp_path, make_event(customer_id=customer_id)) == (
        SCHEMA_VIOLATION
    )


def test_missing_customer_id_is_null_customer_id(tmp_path):
    event = make_event()
    del event["value"]["customer_id"]
    assert reject_reason(tmp_path, event) == NULL_CUSTOMER_ID


@pytest.mark.parametrize("currency", ["BTC", "usd", "Usd", " USD", "USD ", ""])
def test_invalid_currency(tmp_path, currency):
    assert reject_reason(tmp_path, make_event(currency=currency)) == INVALID_CURRENCY


@pytest.mark.parametrize("currency", ["USD", "EUR", "GBP", "CAD", "JPY"])
def test_approved_currencies_are_accepted(tmp_path, currency):
    _, valid, _ = run(tmp_path, {0: [make_event(currency=currency)]})
    assert len(valid) == 1


def test_currencies_are_read_from_config_each_run(tmp_path, monkeypatch):
    config = tmp_path / "currencies.json"
    config.write_text(json.dumps({"approved_currencies": ["CHF"]}))
    monkeypatch.setattr(pipeline_module, "DEFAULT_CURRENCIES_PATH", config)
    events = [make_event(0, currency="CHF", transaction_id="a"), make_event(1)]
    _, valid, rejects = run(tmp_path, {0: events})
    assert [v["currency"] for v in valid] == ["CHF"]
    assert [r["reason_code"] for r in rejects] == [INVALID_CURRENCY]


@pytest.mark.parametrize("amount", ["10.5", True, False, None, 0, -1, -0.01, []])
def test_bad_amount_is_schema_violation(tmp_path, amount):
    assert reject_reason(tmp_path, make_event(amount=amount)) == SCHEMA_VIOLATION


@pytest.mark.parametrize("literal", ["1e400", "-1e400", "1e-400"])
def test_out_of_range_amount_is_schema_violation(tmp_path, literal):
    line = json.dumps(make_event(amount=12345)).replace("12345", literal)
    assert reject_reason(tmp_path, line) == SCHEMA_VIOLATION


def test_huge_float_offset_is_malformed(tmp_path):
    line = json.dumps(make_event(offset=12345)).replace("12345", "1e400")
    assert reject_reason(tmp_path, line) == MALFORMED_EVENT


def test_huge_integer_offset_is_kept(tmp_path):
    _, valid, _ = run(tmp_path, {0: [make_event(offset=2**80)]})
    assert valid[0]["source_offset"] == 2**80


@pytest.mark.parametrize(
    "event_time",
    [
        "2026-11-01T00:00:00",
        "2026-11-01T00:00:00+00:00",
        "2026-11-01 00:00:00Z",
        "2026-11-01T00:00Z",
        "2026-11-01T00:00:00.Z",
        "2026-11-01T00:00:00.1234567Z",
        "2026-11-01t00:00:00z",
        "2026-02-30T00:00:00Z",
        "2026-13-01T00:00:00Z",
        "2026-11-01T24:00:00Z",
        "yesterday",
        "",
        1793836801000,
        None,
    ],
)
def test_bad_event_time_is_schema_violation(tmp_path, event_time):
    assert reject_reason(tmp_path, make_event(event_time=event_time)) == (
        SCHEMA_VIOLATION
    )


@pytest.mark.parametrize(
    "event_time",
    ["2024-02-29T12:00:00Z", "2026-11-01T00:00:00.5Z", "2026-11-01T23:59:59.999999Z"],
)
def test_good_event_time_is_accepted(tmp_path, event_time):
    _, valid, _ = run(tmp_path, {0: [make_event(event_time=event_time)]})
    assert len(valid) == 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e["value"].pop("event_time"),
        lambda e: e["value"].pop("transaction_id"),
        lambda e: e["value"].pop("merchant_id"),
        lambda e: e["value"].pop("amount"),
        lambda e: e["value"].pop("currency"),
        lambda e: e["value"].update(currency=None),
        lambda e: e["value"].update(currency=1),
        lambda e: e["value"].update(transaction_id=""),
        lambda e: e["value"].update(transaction_id=5),
        lambda e: e["value"].update(merchant_id=None),
        lambda e: e.update(key=5),
        lambda e: e.update(timestamp="now"),
        lambda e: e.pop("value"),
        lambda e: e.update(value=[]),
        lambda e: e.update(value=None),
    ],
)
def test_schema_violations(tmp_path, mutate):
    event = make_event()
    mutate(event)
    assert reject_reason(tmp_path, event) == SCHEMA_VIOLATION


@pytest.mark.parametrize(
    "line",
    [
        '{"offset": 1, "value": {"tran',
        "not json",
        "[]",
        "42",
        "null",
        '"text"',
        "true",
        '{"offset": 0, "value": {"amount": NaN}}',
        '{"offset": 0, "value": {"amount": Infinity}}',
        '{"offset": 0} trailing',
        "[" * 100000,
        '{"offset": 0, "value": {"amount": ' + "9" * 5000 + "}}",
        b'{"offset": 0, "value": "\xff\xfe"}',
    ],
)
def test_malformed_lines_are_rejected_with_null_offset(tmp_path, line):
    _, valid, rejects = run(tmp_path, {0: [line, make_event(1)]})
    assert len(valid) == 1
    assert rejects[0]["reason_code"] == MALFORMED_EVENT
    assert rejects[0]["source_offset"] is None
    if isinstance(line, str):
        assert rejects[0]["raw"] == line


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e.pop("offset"),
        lambda e: e.update(offset=None),
        lambda e: e.update(offset=-1),
        lambda e: e.update(offset="3"),
        lambda e: e.update(offset="five"),
        lambda e: e.update(offset=1.0),
        lambda e: e.update(offset=True),
        lambda e: e.update(offset=[0]),
    ],
)
def test_bad_offset_is_malformed_with_null_offset(tmp_path, mutate):
    event = make_event(customer_id=None, currency="BTC")
    mutate(event)
    _, valid, rejects = run(tmp_path, {0: [event]})
    assert valid == []
    assert rejects[0]["reason_code"] == MALFORMED_EVENT
    assert rejects[0]["source_offset"] is None


def test_offset_is_kept_when_readable(tmp_path):
    _, _, rejects = run(tmp_path, {0: [make_event(12, customer_id=None)]})
    assert rejects[0]["source_offset"] == 12


@pytest.mark.parametrize(
    "event, expected",
    [
        (make_event(customer_id=None, amount="1", currency="BTC"), NULL_CUSTOMER_ID),
        (make_event(customer_id=" ", event_time="bad"), NULL_CUSTOMER_ID),
        (make_event(customer_id=None, merchant_id=None), NULL_CUSTOMER_ID),
        (make_event(amount="1", currency="BTC"), SCHEMA_VIOLATION),
        (make_event(currency="usd"), INVALID_CURRENCY),
    ],
)
def test_first_failing_check_wins(tmp_path, event, expected):
    assert reject_reason(tmp_path, event) == expected


def test_duplicate_has_lower_priority_than_other_checks(tmp_path):
    events = [make_event(0), make_event(1, currency="BTC")]
    _, _, rejects = run(tmp_path, {0: events})
    assert [r["reason_code"] for r in rejects] == [INVALID_CURRENCY]


def test_duplicate_within_partition(tmp_path):
    _, valid, rejects = run(tmp_path, {0: [make_event(0), make_event(1)]})
    assert [v["source_offset"] for v in valid] == [0]
    assert [(r["source_offset"], r["reason_code"]) for r in rejects] == [
        (1, DUPLICATE_TRANSACTION)
    ]


def test_duplicate_across_partitions(tmp_path):
    _, valid, rejects = run(tmp_path, {0: [make_event(0)], 1: [make_event(0)]})
    assert [v["source_partition"] for v in valid] == [0]
    assert [(r["source_partition"], r["reason_code"]) for r in rejects] == [
        (1, DUPLICATE_TRANSACTION)
    ]


def test_only_accepted_events_reserve_transaction_id(tmp_path):
    events = [make_event(0, currency="BTC"), make_event(1, customer_id=None),
              make_event(2), make_event(3)]
    _, valid, rejects = run(tmp_path, {0: events})
    assert [v["source_offset"] for v in valid] == [2]
    assert [r["reason_code"] for r in rejects] == [
        INVALID_CURRENCY,
        NULL_CUSTOMER_ID,
        DUPLICATE_TRANSACTION,
    ]


def test_partitions_processed_in_numeric_order(tmp_path):
    metrics, valid, rejects = run(
        tmp_path, {10: [make_event(0)], 2: [make_event(0)], 1: []}
    )
    assert [v["source_partition"] for v in valid] == [2]
    assert [r["source_partition"] for r in rejects] == [10]
    assert list(metrics["partitions"]) == ["1", "2", "10"]


def test_rows_are_in_processing_order(tmp_path):
    p0 = [make_event(i, transaction_id=f"a{i}") for i in range(3)]
    p0[1]["value"]["currency"] = "BTC"
    p1 = [make_event(i, transaction_id=f"b{i}") for i in range(3)]
    p1[0]["value"]["customer_id"] = None
    _, valid, rejects = run(tmp_path, {1: p1, 0: p0})
    order = [(v["source_partition"], v["source_offset"]) for v in valid]
    assert order == [(0, 0), (0, 2), (1, 1), (1, 2)]
    assert [(r["source_partition"], r["source_offset"]) for r in rejects] == [
        (0, 1),
        (1, 0),
    ]


def test_blank_lines_are_skipped_without_counting(tmp_path):
    metrics, valid, rejects = run(
        tmp_path, {0: ["", make_event(), "   ", "\t", "\r"]}
    )
    assert len(valid) == 1 and rejects == []
    assert metrics["input_records"] == 1
    assert metrics["partitions"]["0"]["input_records"] == 1


def test_crlf_line_endings(tmp_path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "partition-0.jsonl").write_bytes(
        to_line(make_event()) + b"\r\n" + b"oops\r\n"
    )
    run_pipeline(input_dir, tmp_path / "out")
    rejects = read_jsonl(tmp_path / "out" / "rejects.jsonl")
    assert rejects[0]["raw"] == "oops"


def test_non_partition_files_are_ignored(tmp_path):
    input_dir = tmp_path / "in"
    write_partition(input_dir, 0, [make_event()])
    (input_dir / "notes.txt").write_text("ignore me")
    (input_dir / "partition-x.jsonl").write_text("not json\n")
    metrics = run_pipeline(input_dir, tmp_path / "out")
    assert list(metrics["partitions"]) == ["0"]
    assert metrics["input_records"] == 1


def test_metrics_exact_shape(tmp_path):
    events = [make_event(0), make_event(1, customer_id=None)]
    metrics, _, _ = run(tmp_path, {0: events})
    assert metrics == {
        "schema_version": "1.0",
        "input_records": 2,
        "valid_records": 1,
        "rejected_records": 1,
        "rejects_by_reason": {
            MALFORMED_EVENT: 0,
            NULL_CUSTOMER_ID: 1,
            SCHEMA_VIOLATION: 0,
            INVALID_CURRENCY: 0,
            DUPLICATE_TRANSACTION: 0,
        },
        "partitions": {
            "0": {"input_records": 2, "valid_records": 1, "rejected_records": 1}
        },
    }
    on_disk = json.loads((tmp_path / "out" / "metrics.json").read_text())
    assert on_disk == metrics


def test_empty_input_directory(tmp_path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    output_dir = tmp_path / "out"
    metrics = run_pipeline(input_dir, output_dir)
    assert metrics["input_records"] == 0
    assert metrics["partitions"] == {}
    assert metrics["rejects_by_reason"] == {code: 0 for code in REASON_CODES}
    assert (output_dir / "valid.jsonl").read_text() == ""
    assert (output_dir / "rejects.jsonl").read_text() == ""


def test_missing_input_directory_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        run_pipeline(tmp_path / "missing", tmp_path / "out")


def test_sample_data_end_to_end(tmp_path):
    metrics = run_pipeline(SAMPLE_INPUT, tmp_path)
    valid = read_jsonl(tmp_path / "valid.jsonl")
    rejects = read_jsonl(tmp_path / "rejects.jsonl")

    assert metrics == {
        "schema_version": "1.0",
        "input_records": 43,
        "valid_records": 27,
        "rejected_records": 16,
        "rejects_by_reason": {
            MALFORMED_EVENT: 1,
            NULL_CUSTOMER_ID: 3,
            SCHEMA_VIOLATION: 6,
            INVALID_CURRENCY: 3,
            DUPLICATE_TRANSACTION: 3,
        },
        "partitions": {
            "0": {"input_records": 14, "valid_records": 9, "rejected_records": 5},
            "1": {"input_records": 15, "valid_records": 9, "rejected_records": 6},
            "2": {"input_records": 14, "valid_records": 9, "rejected_records": 5},
        },
    }
    assert len(valid) == 27 and len(rejects) == 16
    assert all(list(v) == VALID_KEYS for v in valid)
    assert all(list(r) == REJECT_KEYS for r in rejects)

    raw_lines = [
        ln
        for p in sorted(SAMPLE_INPUT.glob("partition-*.jsonl"))
        for ln in p.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    assert all(r["raw"] in raw_lines for r in rejects)

    valid_ids = [v["transaction_id"] for v in valid]
    assert len(valid_ids) == len(set(valid_ids))
    duplicates = {
        json.loads(r["raw"])["value"]["transaction_id"]
        for r in rejects
        if r["reason_code"] == DUPLICATE_TRANSACTION
    }
    assert duplicates == {"txn-00003", "txn-00005", "txn-00007"}
    malformed = [r for r in rejects if r["reason_code"] == MALFORMED_EVENT]
    assert [(r["source_partition"], r["source_offset"]) for r in malformed] == [
        (1, None)
    ]


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "txn_pipeline", *args],
        cwd=PROJECT_ROOT,
        env={"PYTHONPATH": str(PROJECT_ROOT / "src")},
        capture_output=True,
        text=True,
    )


def test_cli_writes_outputs(tmp_path):
    result = run_cli("--input", str(SAMPLE_INPUT), "--output", str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["input_records"] == 43
    for name in ("valid.jsonl", "rejects.jsonl", "metrics.json"):
        assert (tmp_path / name).is_file()


def test_cli_missing_input_exits_nonzero(tmp_path):
    result = run_cli("--input", str(tmp_path / "missing"), "--output", str(tmp_path))
    assert result.returncode == 2
    assert "input directory not found" in result.stderr
