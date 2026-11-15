import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from txn_pipeline import pipeline, run_pipeline
from txn_pipeline.__main__ import main
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
    "source_partition", "source_offset", "reason_code", "reason_detail", "raw"
]
METRICS_KEYS = [
    "schema_version",
    "input_records",
    "valid_records",
    "rejected_records",
    "rejects_by_reason",
    "partitions",
]


def make_event(offset, txn_id="txn-1", **overrides):
    value = {
        "transaction_id": txn_id,
        "customer_id": "cust-1",
        "amount": 10.5,
        "currency": "USD",
        "event_time": "2026-11-01T00:00:00Z",
        "merchant_id": "merch-1",
    }
    value.update(overrides)
    return {"offset": offset, "key": "k", "timestamp": 1, "value": value}


def as_line(item):
    return item if isinstance(item, str) else json.dumps(item)


def write_partition(directory, number, lines):
    directory.mkdir(parents=True, exist_ok=True)
    text = "".join(as_line(line) + "\n" for line in lines)
    (directory / f"partition-{number}.jsonl").write_text(text, encoding="utf-8")


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def run(tmp_path, partitions):
    input_dir = tmp_path / "in"
    for number, lines in partitions.items():
        write_partition(input_dir, number, lines)
    out = tmp_path / "out"
    metrics = run_pipeline(input_dir, out)
    return metrics, read_jsonl(out / "valid.jsonl"), read_jsonl(out / "rejects.jsonl")


def reject_codes(tmp_path, *lines):
    _, valid, rejects = run(tmp_path, {0: list(lines)})
    assert valid == []
    return [r["reason_code"] for r in rejects]


def test_valid_row_shape_drops_extra_fields(tmp_path):
    event = make_event(3, channel="web")
    _, valid, rejects = run(tmp_path, {7: [event]})
    assert rejects == []
    assert list(valid[0]) == VALID_KEYS
    assert valid[0] == {
        **{k: v for k, v in event["value"].items() if k != "channel"},
        "source_partition": 7,
        "source_offset": 3,
    }


def test_reject_row_shape_and_raw_is_original_line(tmp_path):
    line = '{"offset": 4,  "value": {"customer_id": null}}'
    _, _, rejects = run(tmp_path, {2: [line]})
    assert list(rejects[0]) == REJECT_KEYS
    assert rejects[0]["raw"] == line
    assert rejects[0]["source_partition"] == 2
    assert rejects[0]["source_offset"] == 4
    assert rejects[0]["reason_code"] == NULL_CUSTOMER_ID
    assert isinstance(rejects[0]["reason_detail"], str) and rejects[0]["reason_detail"]


@pytest.mark.parametrize("customer_id", [None, "", "   ", "\t\n"])
def test_null_or_blank_customer_id(tmp_path, customer_id):
    assert reject_codes(tmp_path, make_event(0, customer_id=customer_id)) == [
        NULL_CUSTOMER_ID
    ]


@pytest.mark.parametrize("customer_id", [123, 1.5, True, [], {}])
def test_non_string_customer_id_is_schema_violation(tmp_path, customer_id):
    assert reject_codes(tmp_path, make_event(0, customer_id=customer_id)) == [
        SCHEMA_VIOLATION
    ]


@pytest.mark.parametrize("currency", ["XYZ", "BTC", "usd", "Usd", " USD", ""])
def test_invalid_currency(tmp_path, currency):
    assert reject_codes(tmp_path, make_event(0, currency=currency)) == [
        INVALID_CURRENCY
    ]


def test_currencies_read_from_config_each_run(tmp_path, monkeypatch):
    config = tmp_path / "root" / "config" / "approved_currencies.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"approved_currencies": ["XYZ"]}))
    monkeypatch.setattr(pipeline, "PROJECT_ROOT", tmp_path / "root")
    _, valid, rejects = run(
        tmp_path, {0: [make_event(0, "a", currency="XYZ"), make_event(1, "b")]}
    )
    assert [v["currency"] for v in valid] == ["XYZ"]
    assert [r["reason_code"] for r in rejects] == [INVALID_CURRENCY]


def test_duplicate_across_partitions_first_accepted_wins(tmp_path):
    metrics, valid, rejects = run(
        tmp_path,
        {
            0: [make_event(0, "txn-a"), make_event(1, "txn-a")],
            1: [make_event(0, "txn-a"), make_event(1, "txn-b")],
        },
    )
    assert [(v["transaction_id"], v["source_partition"]) for v in valid] == [
        ("txn-a", 0),
        ("txn-b", 1),
    ]
    assert [(r["reason_code"], r["source_partition"], r["source_offset"])
            for r in rejects] == [
        (DUPLICATE_TRANSACTION, 0, 1),
        (DUPLICATE_TRANSACTION, 1, 0),
    ]


def test_only_accepted_events_reserve_transaction_id(tmp_path):
    _, valid, rejects = run(
        tmp_path,
        {0: [
            make_event(0, "txn-a", currency="BTC"),
            make_event(1, "txn-a", customer_id=None),
            make_event(2, "txn-a", amount="1"),
            make_event(3, "txn-a"),
        ]},
    )
    assert [r["reason_code"] for r in rejects] == [
        INVALID_CURRENCY, NULL_CUSTOMER_ID, SCHEMA_VIOLATION
    ]
    assert [v["source_offset"] for v in valid] == [3]


@pytest.mark.parametrize("amount", ["10.5", True, False, None, 0, 0.0, -1, [], {}])
def test_bad_amount(tmp_path, amount):
    assert reject_codes(tmp_path, make_event(0, amount=amount)) == [SCHEMA_VIOLATION]


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_non_finite_amount(tmp_path, token):
    line = json.dumps(make_event(0, amount=12345)).replace("12345", token)
    assert reject_codes(tmp_path, line) == [SCHEMA_VIOLATION]


def test_integer_and_huge_amounts_accepted(tmp_path):
    _, valid, _ = run(
        tmp_path, {0: [make_event(0, "a", amount=5), make_event(1, "b", amount=10**30)]}
    )
    assert [v["amount"] for v in valid] == [5, 10**30]


@pytest.mark.parametrize(
    "event_time",
    [
        "2026-11-01T00:00:00.1Z",
        "2026-11-01T23:59:59.123456Z",
        "2024-02-29T12:00:00Z",
    ],
)
def test_good_event_time(tmp_path, event_time):
    _, valid, _ = run(tmp_path, {0: [make_event(0, event_time=event_time)]})
    assert valid[0]["event_time"] == event_time


@pytest.mark.parametrize(
    "event_time",
    [
        "2026-11-01T00:00:00",
        "2026-11-01T00:00:00+00:00",
        "2026-11-01 00:00:00Z",
        "2026-11-01T00:00:00z",
        "2026-11-01T00:00:00.1234567Z",
        "2026-11-01T00:00:00.Z",
        "2026-02-30T00:00:00Z",
        "2025-02-29T00:00:00Z",
        "2026-13-01T00:00:00Z",
        "2026-11-01T24:00:00Z",
        "2026-11-01T00:60:00Z",
        "2026-11-01",
        "not-a-date",
        "",
        1793836801000,
        None,
    ],
)
def test_bad_event_time(tmp_path, event_time):
    assert reject_codes(tmp_path, make_event(0, event_time=event_time)) == [
        SCHEMA_VIOLATION
    ]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e["value"].pop("event_time"),
        lambda e: e["value"].pop("transaction_id"),
        lambda e: e["value"].pop("customer_id"),
        lambda e: e["value"].update(merchant_id=""),
        lambda e: e["value"].update(transaction_id=123),
        lambda e: e["value"].update(currency=None),
        lambda e: e.update(offset=-1),
        lambda e: e.update(offset="3"),
        lambda e: e.update(offset=True),
        lambda e: e.pop("offset"),
        lambda e: e.update(key=5),
        lambda e: e.update(timestamp="now"),
        lambda e: e.update(value="oops"),
        lambda e: e.update(value=None),
        lambda e: e.pop("value"),
    ],
)
def test_schema_violations(tmp_path, mutate):
    event = make_event(0)
    mutate(event)
    assert reject_codes(tmp_path, event) == [SCHEMA_VIOLATION]


@pytest.mark.parametrize(
    "line",
    [
        '{"offset": 1, "val',
        "not json",
        "[1, 2]",
        "null",
        '"a string"',
        "42",
        "{" * 100000,
        '{"offset": 1, "x": ' + "9" * 5000 + "}",
    ],
)
def test_malformed_events(tmp_path, line):
    _, valid, rejects = run(tmp_path, {0: [line]})
    assert valid == []
    assert rejects[0]["reason_code"] == MALFORMED_EVENT
    assert rejects[0]["source_offset"] is None
    assert rejects[0]["raw"] == line


def test_invalid_utf8_line_is_malformed(tmp_path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "partition-0.jsonl").write_bytes(b'{"offset": 0, "v": "\xff"}\n')
    run_pipeline(input_dir, tmp_path / "out")
    rejects = read_jsonl(tmp_path / "out" / "rejects.jsonl")
    assert rejects[0]["reason_code"] == MALFORMED_EVENT
    assert rejects[0]["source_offset"] is None


@pytest.mark.parametrize("offset", ["3", None, 1.5, True])
def test_unreadable_offset_is_null(tmp_path, offset):
    event = make_event(0, customer_id=None)
    event["offset"] = offset
    _, _, rejects = run(tmp_path, {0: [event]})
    assert rejects[0]["source_offset"] is None


def test_precedence(tmp_path):
    null_and_bad = make_event(0, customer_id=None, amount="x", currency="BTC")
    schema_and_currency = make_event(1, "b", amount="x", currency="BTC")
    _, _, rejects = run(
        tmp_path,
        {0: [null_and_bad, schema_and_currency, make_event(2, "c"),
             make_event(3, "c", currency="BTC")]},
    )
    assert [r["reason_code"] for r in rejects] == [
        NULL_CUSTOMER_ID, SCHEMA_VIOLATION, INVALID_CURRENCY
    ]


def test_blank_lines_skipped_without_counting(tmp_path):
    metrics, valid, rejects = run(tmp_path, {0: ["", "   ", make_event(0), "\t"]})
    assert len(valid) == 1 and rejects == []
    assert metrics["input_records"] == 1
    assert metrics["partitions"]["0"]["input_records"] == 1


def test_crlf_line_endings(tmp_path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    line = json.dumps(make_event(0))
    (input_dir / "partition-0.jsonl").write_text(line + "\r\n\r\n", encoding="utf-8")
    metrics = run_pipeline(input_dir, tmp_path / "out")
    assert metrics["valid_records"] == 1 and metrics["input_records"] == 1


def test_partitions_processed_in_numeric_order(tmp_path):
    _, valid, rejects = run(
        tmp_path,
        {
            10: [make_event(0, "x"), make_event(1, "dup")],
            2: [make_event(0, "dup"), "bad"],
            1: [make_event(0, "y"), "bad"],
        },
    )
    assert [(v["source_partition"], v["source_offset"]) for v in valid] == [
        (1, 0), (2, 0), (10, 0)
    ]
    assert [r["source_partition"] for r in rejects] == [1, 2, 10]
    assert rejects[-1]["reason_code"] == DUPLICATE_TRANSACTION


def test_non_partition_files_ignored(tmp_path):
    input_dir = tmp_path / "in"
    write_partition(input_dir, 0, [make_event(0)])
    (input_dir / "notes.txt").write_text("ignore me")
    (input_dir / "partition-x.jsonl").write_text("garbage\n")
    metrics = run_pipeline(input_dir, tmp_path / "out")
    assert metrics["input_records"] == 1
    assert list(metrics["partitions"]) == ["0"]


def test_metrics_shape(tmp_path):
    metrics, _, _ = run(tmp_path, {0: [make_event(0), "bad"], 1: []})
    assert list(metrics) == METRICS_KEYS
    assert metrics["schema_version"] == "1.0"
    assert metrics["rejects_by_reason"] == {
        MALFORMED_EVENT: 1,
        NULL_CUSTOMER_ID: 0,
        SCHEMA_VIOLATION: 0,
        INVALID_CURRENCY: 0,
        DUPLICATE_TRANSACTION: 0,
    }
    assert metrics["partitions"] == {
        "0": {"input_records": 2, "valid_records": 1, "rejected_records": 1},
        "1": {"input_records": 0, "valid_records": 0, "rejected_records": 0},
    }
    assert json.loads((tmp_path / "out" / "metrics.json").read_text()) == metrics


def test_missing_input_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        run_pipeline(tmp_path / "missing", tmp_path / "out")


def test_empty_input_dir(tmp_path):
    (tmp_path / "in").mkdir()
    metrics = run_pipeline(tmp_path / "in", tmp_path / "out")
    assert metrics["input_records"] == 0
    assert metrics["partitions"] == {}
    assert set(metrics["rejects_by_reason"]) == set(REASON_CODES)
    assert (tmp_path / "out" / "valid.jsonl").read_text() == ""


def test_sample_data_end_to_end(tmp_path):
    out = tmp_path / "out"
    metrics = run_pipeline(SAMPLE_INPUT, out)
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
    valid = read_jsonl(out / "valid.jsonl")
    rejects = read_jsonl(out / "rejects.jsonl")
    assert all(list(v) == VALID_KEYS for v in valid)
    assert all(list(r) == REJECT_KEYS for r in rejects)
    ids = [v["transaction_id"] for v in valid]
    assert len(ids) == len(set(ids))
    positions = [(v["source_partition"], v["source_offset"]) for v in valid]
    assert positions == sorted(positions)

    raw_lines = {}
    for number in range(3):
        path = SAMPLE_INPUT / f"partition-{number}.jsonl"
        raw_lines[number] = path.read_text().splitlines()
    for r in rejects:
        assert r["raw"] in raw_lines[r["source_partition"]]
    duplicates = [r for r in rejects if r["reason_code"] == DUPLICATE_TRANSACTION]
    assert sorted(json.loads(r["raw"])["value"]["transaction_id"]
                  for r in duplicates) == ["txn-00003", "txn-00005", "txn-00007"]


def test_cli_main(tmp_path, capsys):
    assert main(["--input", str(SAMPLE_INPUT), "--output", str(tmp_path)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["valid_records"] == 27
    assert (tmp_path / "metrics.json").exists()


def test_cli_missing_input(tmp_path, capsys):
    assert main(["--input", str(tmp_path / "nope"), "--output", str(tmp_path)]) == 2
    assert "input directory not found" in capsys.readouterr().err


def test_cli_module_invocation(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(PROJECT_ROOT / "src"))
    result = subprocess.run(
        [sys.executable, "-m", "txn_pipeline", "--input", str(SAMPLE_INPUT),
         "--output", str(tmp_path / "out")],
        capture_output=True, text=True, env=env, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["rejected_records"] == 16
    for name in ("valid.jsonl", "rejects.jsonl", "metrics.json"):
        assert (tmp_path / "out" / name).exists()
