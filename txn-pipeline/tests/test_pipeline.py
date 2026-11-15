import json
import subprocess
import sys
from pathlib import Path

import pytest

from txn_pipeline import pipeline
from txn_pipeline.pipeline import REASON_CODES, run_pipeline

PROJECT_ROOT = Path(__file__).resolve().parents[1]

VALID_KEYS = {
    "transaction_id", "customer_id", "amount", "currency", "event_time",
    "merchant_id", "source_partition", "source_offset",
}
REJECT_KEYS = {
    "source_partition", "source_offset", "reason_code", "reason_detail", "raw",
}


def make_value(txn="txn-1", **overrides):
    value = {
        "transaction_id": txn,
        "customer_id": "cust-1",
        "amount": 10.5,
        "currency": "USD",
        "event_time": "2026-11-01T10:00:00Z",
        "merchant_id": "merch-1",
    }
    value.update(overrides)
    return value


def drop(value, field):
    value = dict(value)
    del value[field]
    return value


def msg(offset, value):
    return json.dumps(
        {"offset": offset, "key": "k", "timestamp": 0, "value": value})


def write_partition(input_dir, n, lines):
    input_dir.mkdir(parents=True, exist_ok=True)
    path = input_dir / f"partition-{n}.jsonl"
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return path


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def run(tmp_path, partitions):
    input_dir = tmp_path / "in"
    input_dir.mkdir(exist_ok=True)
    for n, lines in partitions.items():
        write_partition(input_dir, n, lines)
    out = tmp_path / "out"
    metrics = run_pipeline(input_dir, out)
    return metrics, read_jsonl(out / "valid.jsonl"), read_jsonl(
        out / "rejects.jsonl")


def single_reject(tmp_path, line):
    metrics, valid, rejects = run(tmp_path, {0: [line]})
    assert valid == []
    assert len(rejects) == 1
    assert metrics["rejected_records"] == 1
    return rejects[0]


# --- happy path and output contracts -------------------------------------

def test_valid_event_is_accepted_with_exact_keys(tmp_path):
    value = make_value(channel="web", extra={"nested": 1})
    metrics, valid, rejects = run(tmp_path, {3: [msg(7, value)]})
    assert rejects == []
    assert valid == [{
        "transaction_id": "txn-1", "customer_id": "cust-1", "amount": 10.5,
        "currency": "USD", "event_time": "2026-11-01T10:00:00Z",
        "merchant_id": "merch-1", "source_partition": 3, "source_offset": 7,
    }]
    assert set(valid[0]) == VALID_KEYS
    assert metrics["valid_records"] == 1


def test_valid_values_are_unchanged(tmp_path):
    value = make_value(amount=5, event_time="2026-02-28T23:59:59.123456Z",
                       customer_id=" cust ")
    _, valid, _ = run(tmp_path, {0: [msg(0, value)]})
    assert valid[0]["amount"] == 5 and isinstance(valid[0]["amount"], int)
    assert valid[0]["event_time"] == "2026-02-28T23:59:59.123456Z"
    assert valid[0]["customer_id"] == " cust "


def test_reject_record_shape_and_raw(tmp_path):
    line = msg(4, make_value(currency="XYZ"))
    reject = single_reject(tmp_path, line)
    assert set(reject) == REJECT_KEYS
    assert reject["source_partition"] == 0
    assert reject["source_offset"] == 4
    assert reject["reason_code"] == "INVALID_CURRENCY"
    assert isinstance(reject["reason_detail"], str) and reject["reason_detail"]
    assert reject["raw"] == line


# --- MALFORMED_EVENT ------------------------------------------------------

@pytest.mark.parametrize("line", [
    '{"offset": 1, "value": {',
    "not json",
    "[1, 2, 3]",
    '"a string"',
    "42",
    "null",
])
def test_malformed_unreadable_offset_is_null(tmp_path, line):
    reject = single_reject(tmp_path, line)
    assert reject["reason_code"] == "MALFORMED_EVENT"
    assert reject["source_offset"] is None
    assert reject["raw"] == line


@pytest.mark.parametrize("offset", [-1, "3", 1.0, True, None])
def test_malformed_bad_offset(tmp_path, offset):
    reject = single_reject(tmp_path, msg(offset, make_value()))
    assert reject["reason_code"] == "MALFORMED_EVENT"
    assert reject["source_offset"] is None


def test_malformed_missing_offset(tmp_path):
    line = json.dumps({"value": make_value()})
    reject = single_reject(tmp_path, line)
    assert reject["reason_code"] == "MALFORMED_EVENT"


@pytest.mark.parametrize("value", [None, "x", [make_value()], 5])
def test_malformed_value_not_object_keeps_offset(tmp_path, value):
    reject = single_reject(tmp_path, msg(2, value))
    assert reject["reason_code"] == "MALFORMED_EVENT"
    assert reject["source_offset"] == 2


def test_malformed_missing_value(tmp_path):
    reject = single_reject(tmp_path, json.dumps({"offset": 0}))
    assert reject["reason_code"] == "MALFORMED_EVENT"
    assert reject["source_offset"] == 0


def test_malformed_invalid_utf8_does_not_raise(tmp_path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "partition-0.jsonl").write_bytes(
        b'{"offset": 0, "value": "\xff"}\n' + msg(1, make_value()).encode() +
        b"\n")
    metrics = run_pipeline(input_dir, tmp_path / "out")
    rejects = read_jsonl(tmp_path / "out" / "rejects.jsonl")
    assert rejects[0]["reason_code"] == "MALFORMED_EVENT"
    assert metrics["valid_records"] == 1


def test_malformed_takes_priority_over_null_customer(tmp_path):
    reject = single_reject(tmp_path, msg(-5, make_value(customer_id=None)))
    assert reject["reason_code"] == "MALFORMED_EVENT"


# --- NULL_CUSTOMER_ID -----------------------------------------------------

@pytest.mark.parametrize("value", [
    make_value(customer_id=None),
    make_value(customer_id=""),
    make_value(customer_id="   \t"),
    drop(make_value(), "customer_id"),
])
def test_null_customer_id(tmp_path, value):
    reject = single_reject(tmp_path, msg(0, value))
    assert reject["reason_code"] == "NULL_CUSTOMER_ID"
    assert reject["source_offset"] == 0


def test_null_customer_takes_priority_over_schema_and_currency(tmp_path):
    value = make_value(customer_id=None, amount="bad", currency="usd")
    reject = single_reject(tmp_path, msg(0, value))
    assert reject["reason_code"] == "NULL_CUSTOMER_ID"


# --- SCHEMA_VIOLATION -----------------------------------------------------

@pytest.mark.parametrize("value", [
    make_value(customer_id=123),
    make_value(customer_id=["c"]),
    drop(make_value(), "transaction_id"),
    make_value(transaction_id=""),
    make_value(transaction_id="  "),
    make_value(transaction_id=7),
    drop(make_value(), "merchant_id"),
    make_value(merchant_id=" "),
    make_value(merchant_id=None),
    drop(make_value(), "amount"),
    make_value(amount="10.5"),
    make_value(amount=True),
    make_value(amount=0),
    make_value(amount=-1.5),
    make_value(amount=None),
    make_value(amount=float("nan")),
    make_value(amount=float("inf")),
    drop(make_value(), "currency"),
    make_value(currency=None),
    make_value(currency=840),
    drop(make_value(), "event_time"),
    make_value(event_time=None),
    make_value(event_time=1700000000),
    make_value(event_time="2026-11-01T10:00:00"),
    make_value(event_time="2026-11-01T10:00:00+00:00"),
    make_value(event_time="2026-11-01 10:00:00Z"),
    make_value(event_time="2026-11-01T10:00:00.Z"),
    make_value(event_time="2026-11-01T10:00:00.1234567Z"),
    make_value(event_time="2026-11-01T10:00Z"),
    make_value(event_time="2026-02-30T10:00:00Z"),
    make_value(event_time="2026-13-01T10:00:00Z"),
    make_value(event_time="2026-11-01T24:00:00Z"),
    make_value(event_time="2026-11-01T10:00:00z"),
    make_value(event_time="2026-11-01T10:00:00Z\n"),
])
def test_schema_violation(tmp_path, value):
    reject = single_reject(tmp_path, msg(0, value))
    assert reject["reason_code"] == "SCHEMA_VIOLATION", value


def test_huge_amount_does_not_raise(tmp_path):
    line = msg(0, make_value(amount=10 ** 400))
    _, valid, _ = run(tmp_path, {0: [line]})
    assert valid[0]["amount"] == 10 ** 400


def test_accepted_event_time_variants(tmp_path):
    times = ["2024-02-29T00:00:00Z", "2026-11-01T10:00:00.1Z",
             "2026-11-01T10:00:00.123456Z"]
    lines = [msg(i, make_value(txn=f"t{i}", event_time=t))
             for i, t in enumerate(times)]
    metrics, valid, _ = run(tmp_path, {0: lines})
    assert metrics["valid_records"] == 3


def test_schema_takes_priority_over_currency(tmp_path):
    value = make_value(amount=-1, currency="XYZ")
    reject = single_reject(tmp_path, msg(0, value))
    assert reject["reason_code"] == "SCHEMA_VIOLATION"


# --- INVALID_CURRENCY -----------------------------------------------------

@pytest.mark.parametrize("currency", ["usd", "XYZ", "BTC", "", " USD", "USD "])
def test_invalid_currency(tmp_path, currency):
    reject = single_reject(tmp_path, msg(0, make_value(currency=currency)))
    assert reject["reason_code"] == "INVALID_CURRENCY"


def test_currency_list_comes_from_config(tmp_path, monkeypatch):
    config = tmp_path / "currencies.json"
    config.write_text(json.dumps({"approved_currencies": ["CHF"]}))
    monkeypatch.setattr(pipeline, "CURRENCIES_PATH", config)
    lines = [msg(0, make_value(txn="a", currency="CHF")),
             msg(1, make_value(txn="b", currency="USD"))]
    metrics, valid, rejects = run(tmp_path, {0: lines})
    assert [v["currency"] for v in valid] == ["CHF"]
    assert rejects[0]["reason_code"] == "INVALID_CURRENCY"


def test_default_config_resolved_from_project_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert pipeline.CURRENCIES_PATH == (
        PROJECT_ROOT / "config" / "approved_currencies.json")
    expected = json.loads(pipeline.CURRENCIES_PATH.read_text())
    assert pipeline.load_approved_currencies() == frozenset(
        expected["approved_currencies"])


# --- DUPLICATE_TRANSACTION ------------------------------------------------

def test_duplicate_transaction_rejected(tmp_path):
    lines = [msg(0, make_value(txn="t1")), msg(1, make_value(txn="t1"))]
    metrics, valid, rejects = run(tmp_path, {0: lines})
    assert [v["source_offset"] for v in valid] == [0]
    assert rejects[0]["reason_code"] == "DUPLICATE_TRANSACTION"
    assert rejects[0]["source_offset"] == 1


def test_duplicate_detection_spans_partitions(tmp_path):
    metrics, valid, rejects = run(tmp_path, {
        0: [msg(0, make_value(txn="t1"))],
        1: [msg(0, make_value(txn="t1"))],
    })
    assert len(valid) == 1 and valid[0]["source_partition"] == 0
    assert rejects[0]["source_partition"] == 1
    assert rejects[0]["reason_code"] == "DUPLICATE_TRANSACTION"


def test_duplicate_after_reject_is_accepted(tmp_path):
    lines = [
        msg(0, make_value(txn="t1", currency="XYZ")),
        msg(1, make_value(txn="t1", customer_id=None)),
        msg(2, make_value(txn="t1", amount="1")),
        msg(3, make_value(txn="t1")),
        msg(4, make_value(txn="t1")),
    ]
    metrics, valid, rejects = run(tmp_path, {0: lines})
    assert [v["source_offset"] for v in valid] == [3]
    assert [r["reason_code"] for r in rejects] == [
        "INVALID_CURRENCY", "NULL_CUSTOMER_ID", "SCHEMA_VIOLATION",
        "DUPLICATE_TRANSACTION"]


def test_invalid_duplicate_gets_its_own_reason(tmp_path):
    lines = [msg(0, make_value(txn="t1")),
             msg(1, make_value(txn="t1", currency="usd"))]
    _, _, rejects = run(tmp_path, {0: lines})
    assert rejects[0]["reason_code"] == "INVALID_CURRENCY"


def test_duplicate_ids_are_case_sensitive(tmp_path):
    lines = [msg(0, make_value(txn="T1")), msg(1, make_value(txn="t1"))]
    metrics, _, _ = run(tmp_path, {0: lines})
    assert metrics["valid_records"] == 2


# --- input handling and ordering ------------------------------------------

def test_partitions_processed_in_numeric_order(tmp_path):
    partitions = {
        n: [msg(0, make_value(txn=f"p{n}"))] for n in (10, 2, 1, 0)
    }
    metrics, valid, _ = run(tmp_path, partitions)
    assert [v["source_partition"] for v in valid] == [0, 1, 2, 10]
    assert list(metrics["partitions"]) == ["0", "1", "2", "10"]


def test_numeric_order_decides_duplicate_winner(tmp_path):
    _, valid, rejects = run(tmp_path, {
        10: [msg(0, make_value(txn="t1"))],
        2: [msg(0, make_value(txn="t1"))],
    })
    assert valid[0]["source_partition"] == 2
    assert rejects[0]["source_partition"] == 10


def test_lines_processed_in_file_order(tmp_path):
    lines = [msg(o, make_value(txn=f"t{o}")) for o in (5, 1, 3)]
    _, valid, _ = run(tmp_path, {0: lines})
    assert [v["source_offset"] for v in valid] == [5, 1, 3]


def test_mixed_output_preserves_processing_order(tmp_path):
    _, valid, rejects = run(tmp_path, {
        0: [msg(0, make_value(txn="a")), "bad", msg(2, make_value(txn="b"))],
        1: ["bad", msg(1, make_value(txn="a"))],
    })
    assert [(v["source_partition"], v["source_offset"]) for v in valid] == [
        (0, 0), (0, 2)]
    assert [(r["source_partition"], r["reason_code"]) for r in rejects] == [
        (0, "MALFORMED_EVENT"), (1, "MALFORMED_EVENT"),
        (1, "DUPLICATE_TRANSACTION")]


def test_non_partition_files_ignored(tmp_path):
    input_dir = tmp_path / "in"
    write_partition(input_dir, 0, [msg(0, make_value())])
    for name in ("partition-1.json", "partition-x.jsonl", "notes.txt",
                 "partition-1.jsonl.bak", "Partition-1.jsonl"):
        (input_dir / name).write_text(msg(0, make_value(txn="other")) + "\n")
    (input_dir / "partition-5.jsonl").mkdir()
    metrics = run_pipeline(input_dir, tmp_path / "out")
    assert metrics["input_records"] == 1
    assert list(metrics["partitions"]) == ["0"]


def test_blank_lines_skipped_and_not_counted(tmp_path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "partition-0.jsonl").write_text(
        "\n   \n" + msg(0, make_value()) + "\r\n\t\n\n", encoding="utf-8")
    metrics = run_pipeline(input_dir, tmp_path / "out")
    assert metrics["input_records"] == 1
    assert metrics["valid_records"] == 1
    assert metrics["rejected_records"] == 0


def test_raw_excludes_line_terminator(tmp_path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "partition-0.jsonl").write_bytes(b"oops\r\nlast-no-newline")
    run_pipeline(input_dir, tmp_path / "out")
    rejects = read_jsonl(tmp_path / "out" / "rejects.jsonl")
    assert [r["raw"] for r in rejects] == ["oops", "last-no-newline"]


def test_non_ascii_round_trips(tmp_path):
    line = msg(0, make_value(customer_id="cüst-☃", currency="€"))
    reject = single_reject(tmp_path, line)
    assert reject["raw"] == line
    raw_bytes = (tmp_path / "out" / "rejects.jsonl").read_bytes()
    raw_bytes.decode("utf-8")


def test_missing_input_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        run_pipeline(tmp_path / "missing", tmp_path / "out")


# --- metrics ---------------------------------------------------------------

def test_metrics_structure_and_counts(tmp_path):
    metrics, _, _ = run(tmp_path, {
        0: [msg(0, make_value(txn="a")), "garbage",
            msg(2, make_value(txn="b", customer_id=None))],
        1: [msg(0, make_value(txn="c", amount=-1)),
            msg(1, make_value(txn="d", currency="usd")),
            msg(2, make_value(txn="a")),
            msg(3, make_value(txn="e"))],
    })
    assert metrics == {
        "schema_version": "1.0",
        "input_records": 7,
        "valid_records": 2,
        "rejected_records": 5,
        "rejects_by_reason": {
            "MALFORMED_EVENT": 1, "NULL_CUSTOMER_ID": 1,
            "SCHEMA_VIOLATION": 1, "INVALID_CURRENCY": 1,
            "DUPLICATE_TRANSACTION": 1,
        },
        "partitions": {
            "0": {"input_records": 3, "valid_records": 1,
                  "rejected_records": 2},
            "1": {"input_records": 4, "valid_records": 1,
                  "rejected_records": 3},
        },
    }
    on_disk = json.loads((tmp_path / "out" / "metrics.json").read_text())
    assert on_disk == metrics


def test_metrics_all_reason_codes_present_when_empty(tmp_path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "partition-4.jsonl").write_text("")
    metrics = run_pipeline(input_dir, tmp_path / "out")
    assert list(metrics["rejects_by_reason"]) == list(REASON_CODES)
    assert all(v == 0 for v in metrics["rejects_by_reason"].values())
    assert metrics["partitions"] == {
        "4": {"input_records": 0, "valid_records": 0, "rejected_records": 0}}
    assert (tmp_path / "out" / "valid.jsonl").read_text() == ""
    assert (tmp_path / "out" / "rejects.jsonl").read_text() == ""


def test_metrics_totals_are_consistent(tmp_path):
    metrics = run_pipeline(PROJECT_ROOT / "data" / "input", tmp_path / "out")
    assert metrics["input_records"] == (
        metrics["valid_records"] + metrics["rejected_records"])
    assert metrics["rejected_records"] == sum(
        metrics["rejects_by_reason"].values())
    for counts in metrics["partitions"].values():
        assert counts["input_records"] == (
            counts["valid_records"] + counts["rejected_records"])
    assert len(read_jsonl(tmp_path / "out" / "valid.jsonl")) == (
        metrics["valid_records"])
    assert len(read_jsonl(tmp_path / "out" / "rejects.jsonl")) == (
        metrics["rejected_records"])


def test_output_is_deterministic_and_overwritten(tmp_path):
    input_dir = PROJECT_ROOT / "data" / "input"
    out = tmp_path / "nested" / "out"
    out.mkdir(parents=True)
    (out / "valid.jsonl").write_text("stale\n" * 100)
    run_pipeline(input_dir, out)
    first = {p.name: p.read_bytes() for p in out.iterdir()}
    run_pipeline(input_dir, out)
    second = {p.name: p.read_bytes() for p in out.iterdir()}
    assert first == second
    assert b"stale" not in first["valid.jsonl"]
    assert set(first) == {"valid.jsonl", "rejects.jsonl", "metrics.json"}


# --- CLI --------------------------------------------------------------------

def run_cli(*args, cwd=PROJECT_ROOT):
    return subprocess.run(
        [sys.executable, "-m", "txn_pipeline", *args],
        cwd=cwd, capture_output=True, text=True)


def test_cli_success_with_rejects(tmp_path):
    out = tmp_path / "out"
    result = run_cli("--input", str(PROJECT_ROOT / "data" / "input"),
                     "--output", str(out))
    assert result.returncode == 0, result.stderr
    metrics = json.loads((out / "metrics.json").read_text())
    assert metrics["rejected_records"] > 0
    assert json.loads(result.stdout) == metrics


def test_cli_missing_input_exits_non_zero(tmp_path):
    result = run_cli("--input", str(tmp_path / "missing"),
                     "--output", str(tmp_path / "out"))
    assert result.returncode != 0
    assert "not found" in result.stderr
    assert not (tmp_path / "out").exists()
