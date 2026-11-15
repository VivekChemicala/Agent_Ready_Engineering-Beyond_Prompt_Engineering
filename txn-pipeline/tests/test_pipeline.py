import json
import subprocess
import sys
from pathlib import Path

import pytest

from txn_pipeline import run_pipeline
from txn_pipeline.pipeline import (
    DUPLICATE_TRANSACTION_ID,
    MALFORMED_JSON,
    NULL_CUSTOMER_ID,
    SCHEMA_VIOLATION,
    UNAPPROVED_CURRENCY,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_INPUT = PROJECT_ROOT / "data" / "input"


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


def make_message(offset=0, **value_overrides):
    return {
        "offset": offset,
        "key": "cust-1",
        "timestamp": 1793836801000,
        "value": make_value(**value_overrides),
    }


def write_partition(input_dir, partition, lines):
    input_dir.mkdir(parents=True, exist_ok=True)
    path = input_dir / f"partition-{partition}.jsonl"
    path.write_text(
        "".join((ln if isinstance(ln, str) else json.dumps(ln)) + "\n" for ln in lines),
        encoding="utf-8",
    )


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


def test_valid_event_is_accepted(tmp_path):
    metrics, valid, rejects = run(tmp_path, {0: [make_message()]})
    assert rejects == []
    assert valid == [
        {
            "partition": 0,
            "offset": 0,
            "key": "cust-1",
            "timestamp": 1793836801000,
            "value": make_value(),
        }
    ]
    assert metrics["valid"] == 1 and metrics["rejected"] == 0


def test_extra_value_fields_are_allowed_and_preserved(tmp_path):
    _, valid, rejects = run(tmp_path, {0: [make_message(channel="web")]})
    assert rejects == []
    assert valid[0]["value"]["channel"] == "web"


def test_null_customer_id_is_rejected(tmp_path):
    _, valid, rejects = run(tmp_path, {0: [make_message(customer_id=None)]})
    assert valid == []
    assert rejects[0]["reason"] == NULL_CUSTOMER_ID
    assert [e["code"] for e in rejects[0]["errors"]] == [NULL_CUSTOMER_ID]


def test_null_customer_reason_wins_over_other_violations(tmp_path):
    msg = make_message(customer_id=None, currency="BTC", amount="1")
    _, _, rejects = run(tmp_path, {0: [msg]})
    assert rejects[0]["reason"] == NULL_CUSTOMER_ID
    codes = {e["code"] for e in rejects[0]["errors"]}
    assert codes == {NULL_CUSTOMER_ID, SCHEMA_VIOLATION, UNAPPROVED_CURRENCY}


@pytest.mark.parametrize("currency", ["BTC", "usd", "", "XYZ"])
def test_unapproved_currency_is_rejected(tmp_path, currency):
    _, valid, rejects = run(tmp_path, {0: [make_message(currency=currency)]})
    assert valid == []
    assert rejects[0]["reason"] == UNAPPROVED_CURRENCY


@pytest.mark.parametrize("currency", ["USD", "EUR", "GBP", "CAD", "JPY"])
def test_approved_currencies_are_accepted(tmp_path, currency):
    _, valid, _ = run(tmp_path, {0: [make_message(currency=currency)]})
    assert len(valid) == 1


def test_duplicate_transaction_id_within_partition(tmp_path):
    msgs = [make_message(0), make_message(1)]
    _, valid, rejects = run(tmp_path, {0: msgs})
    assert [v["offset"] for v in valid] == [0]
    assert rejects[0]["offset"] == 1
    assert rejects[0]["reason"] == DUPLICATE_TRANSACTION_ID
    assert "partition 0 offset 0" in rejects[0]["errors"][0]["message"]


def test_duplicate_transaction_id_across_partitions(tmp_path):
    _, valid, rejects = run(tmp_path, {0: [make_message(0)], 1: [make_message(0)]})
    assert [v["partition"] for v in valid] == [0]
    assert [(r["partition"], r["reason"]) for r in rejects] == [
        (1, DUPLICATE_TRANSACTION_ID)
    ]


def test_rejected_event_does_not_claim_its_transaction_id(tmp_path):
    msgs = [make_message(0, currency="BTC"), make_message(1)]
    _, valid, rejects = run(tmp_path, {0: msgs})
    assert [v["offset"] for v in valid] == [1]
    assert [r["reason"] for r in rejects] == [UNAPPROVED_CURRENCY]


def test_partitions_are_processed_in_numeric_order(tmp_path):
    _, valid, rejects = run(
        tmp_path, {10: [make_message(0)], 2: [make_message(0)]}
    )
    assert [v["partition"] for v in valid] == [2]
    assert [r["partition"] for r in rejects] == [10]


@pytest.mark.parametrize(
    "mutate, field",
    [
        (lambda m: m["value"].pop("event_time"), "value.event_time"),
        (lambda m: m["value"].pop("transaction_id"), "value.transaction_id"),
        (lambda m: m["value"].pop("merchant_id"), "value.merchant_id"),
        (lambda m: m["value"].pop("customer_id"), "value.customer_id"),
        (lambda m: m["value"].update(amount="10.50"), "value.amount"),
        (lambda m: m["value"].update(amount=0), "value.amount"),
        (lambda m: m["value"].update(amount=-1), "value.amount"),
        (lambda m: m["value"].update(amount=True), "value.amount"),
        (lambda m: m["value"].update(currency=None), "value.currency"),
        (lambda m: m["value"].update(transaction_id=""), "value.transaction_id"),
        (lambda m: m["value"].update(customer_id=""), "value.customer_id"),
        (lambda m: m["value"].update(customer_id=42), "value.customer_id"),
        (lambda m: m["value"].update(event_time="yesterday"), "value.event_time"),
        (
            lambda m: m["value"].update(event_time="2026-11-01T00:00:00"),
            "value.event_time",
        ),
        (lambda m: m.pop("offset"), "offset"),
        (lambda m: m.update(offset=-1), "offset"),
        (lambda m: m.update(offset="3"), "offset"),
        (lambda m: m.update(key=5), "key"),
        (lambda m: m.update(timestamp="now"), "timestamp"),
        (lambda m: m.pop("value"), "value"),
        (lambda m: m.update(value=[]), "value"),
    ],
)
def test_schema_violations_are_rejected(tmp_path, mutate, field):
    msg = make_message()
    mutate(msg)
    _, valid, rejects = run(tmp_path, {0: [msg]})
    assert valid == []
    assert rejects[0]["reason"] == SCHEMA_VIOLATION
    assert field in {e["field"] for e in rejects[0]["errors"]}


@pytest.mark.parametrize("line", ['{"offset": 1, "value": {"tran', "not json"])
def test_malformed_json_is_rejected_with_raw_line(tmp_path, line):
    _, valid, rejects = run(tmp_path, {0: [line, make_message(1)]})
    assert len(valid) == 1
    assert rejects[0]["reason"] == MALFORMED_JSON
    assert rejects[0]["raw"] == line
    assert rejects[0]["line_number"] == 1
    assert rejects[0]["offset"] is None


@pytest.mark.parametrize("line", ["[]", "42", "null", '"text"'])
def test_non_object_json_is_a_schema_violation(tmp_path, line):
    _, _, rejects = run(tmp_path, {0: [line]})
    assert rejects[0]["reason"] == SCHEMA_VIOLATION
    assert rejects[0]["offset"] is None


def test_blank_lines_are_skipped_not_rejected(tmp_path):
    metrics, valid, rejects = run(tmp_path, {0: ["", make_message(), "   "]})
    assert len(valid) == 1 and rejects == []
    assert metrics["lines_read"] == 3
    assert metrics["blank_lines_skipped"] == 2
    assert metrics["messages_read"] == 1


def test_non_partition_files_are_ignored(tmp_path):
    input_dir = tmp_path / "in"
    write_partition(input_dir, 0, [make_message()])
    (input_dir / "notes.txt").write_text("ignore me")
    (input_dir / "partition-x.jsonl").write_text("not json\n")
    metrics = run_pipeline(input_dir, tmp_path / "out")
    assert metrics["partitions_processed"] == 1
    assert metrics["messages_read"] == 1


def test_empty_input_directory_produces_empty_outputs(tmp_path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    output_dir = tmp_path / "out"
    metrics = run_pipeline(input_dir, output_dir)
    assert metrics["messages_read"] == 0
    assert metrics["valid_rate"] is None
    assert (output_dir / "valid.jsonl").read_text() == ""
    assert (output_dir / "rejects.jsonl").read_text() == ""


def test_missing_input_directory_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        run_pipeline(tmp_path / "missing", tmp_path / "out")


def test_metrics_file_matches_return_value(tmp_path):
    metrics, _, _ = run(tmp_path, {0: [make_message()]})
    on_disk = json.loads((tmp_path / "out" / "metrics.json").read_text())
    assert on_disk == metrics


def test_sample_data_end_to_end(tmp_path):
    metrics = run_pipeline(SAMPLE_INPUT, tmp_path)
    valid = read_jsonl(tmp_path / "valid.jsonl")
    rejects = read_jsonl(tmp_path / "rejects.jsonl")

    assert metrics["partitions_processed"] == 3
    assert metrics["lines_read"] == 44
    assert metrics["blank_lines_skipped"] == 1
    assert metrics["messages_read"] == 43
    assert metrics["valid"] == len(valid) == 27
    assert metrics["rejected"] == len(rejects) == 16
    assert metrics["valid"] + metrics["rejected"] == metrics["messages_read"]
    assert metrics["rejects_by_reason"] == {
        MALFORMED_JSON: 1,
        NULL_CUSTOMER_ID: 3,
        SCHEMA_VIOLATION: 6,
        UNAPPROVED_CURRENCY: 3,
        DUPLICATE_TRANSACTION_ID: 3,
    }
    assert sum(p["messages_read"] for p in metrics["partitions"]) == 43

    valid_ids = [v["value"]["transaction_id"] for v in valid]
    assert len(valid_ids) == len(set(valid_ids))
    assert all(v["value"]["customer_id"] for v in valid)
    approved = set(metrics["approved_currencies"])
    assert all(v["value"]["currency"] in approved for v in valid)

    duplicates = {
        r["transaction_id"]
        for r in rejects
        if r["reason"] == DUPLICATE_TRANSACTION_ID
    }
    assert duplicates == {"txn-00003", "txn-00005", "txn-00007"}
    assert duplicates <= set(valid_ids)


def test_cli_writes_outputs(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "txn_pipeline",
            "--input",
            str(SAMPLE_INPUT),
            "--output",
            str(tmp_path),
        ],
        cwd=PROJECT_ROOT,
        env={"PYTHONPATH": str(PROJECT_ROOT / "src")},
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)["messages_read"] == 43
    for name in ("valid.jsonl", "rejects.jsonl", "metrics.json"):
        assert (tmp_path / name).is_file()


def test_cli_missing_input_exits_nonzero(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "txn_pipeline",
            "--input",
            str(tmp_path / "missing"),
            "--output",
            str(tmp_path / "out"),
        ],
        env={"PYTHONPATH": str(PROJECT_ROOT / "src")},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "input directory not found" in result.stderr
