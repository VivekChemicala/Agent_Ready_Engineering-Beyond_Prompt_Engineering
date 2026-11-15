import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from txn_pipeline import run_pipeline
from txn_pipeline.__main__ import main
from txn_pipeline.pipeline import (
    REASON_CURRENCY,
    REASON_DUPLICATE,
    REASON_MALFORMED_JSON,
    REASON_NULL_CUSTOMER,
    REASON_SCHEMA,
    load_schema,
    validate_schema,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_INPUT = PROJECT_ROOT / "data" / "input"


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
    key = value["customer_id"]
    return {"offset": offset, "key": key, "timestamp": 1, "value": value}


def write_partition(directory, number, lines):
    directory.mkdir(parents=True, exist_ok=True)
    text = "".join(
        (line if isinstance(line, str) else json.dumps(line)) + "\n" for line in lines
    )
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


def test_valid_event_is_accepted(tmp_path):
    metrics, valid, rejects = run(tmp_path, {0: [make_event(0)]})
    assert rejects == []
    assert len(valid) == 1
    assert valid[0]["partition"] == 0
    assert valid[0]["value"]["transaction_id"] == "txn-1"
    assert metrics["valid"] == 1 and metrics["rejected"] == 0


def test_null_customer_id_rejected(tmp_path):
    _, valid, rejects = run(tmp_path, {0: [make_event(0, customer_id=None)]})
    assert valid == []
    assert rejects[0]["reason"] == REASON_NULL_CUSTOMER


@pytest.mark.parametrize("currency", ["XYZ", "BTC", "usd", ""])
def test_unapproved_currency_rejected(tmp_path, currency):
    _, valid, rejects = run(tmp_path, {0: [make_event(0, currency=currency)]})
    assert valid == []
    assert rejects[0]["reason"] == REASON_CURRENCY


def test_duplicate_transaction_id_rejected_across_partitions(tmp_path):
    metrics, valid, rejects = run(
        tmp_path,
        {
            0: [make_event(0, "txn-a"), make_event(1, "txn-a")],
            1: [make_event(0, "txn-a"), make_event(1, "txn-b")],
        },
    )
    assert [v["value"]["transaction_id"] for v in valid] == ["txn-a", "txn-b"]
    assert [r["reason"] for r in rejects] == [REASON_DUPLICATE, REASON_DUPLICATE]
    assert [(r["partition"], r["offset"]) for r in rejects] == [(0, 1), (1, 0)]
    assert metrics["unique_valid_transaction_ids"] == 2


def test_rejected_event_does_not_block_later_valid_duplicate(tmp_path):
    _, valid, rejects = run(
        tmp_path,
        {0: [make_event(0, "txn-a", currency="BTC"), make_event(1, "txn-a")]},
    )
    assert [r["reason"] for r in rejects] == [REASON_CURRENCY]
    assert len(valid) == 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda e: e["value"].pop("event_time"),
        lambda e: e["value"].pop("transaction_id"),
        lambda e: e["value"].update(amount="10.5"),
        lambda e: e["value"].update(amount=0),
        lambda e: e["value"].update(amount=-1),
        lambda e: e["value"].update(amount=True),
        lambda e: e["value"].update(event_time="not-a-date"),
        lambda e: e["value"].update(event_time="2026-11-01T00:00:00"),
        lambda e: e["value"].update(merchant_id=""),
        lambda e: e["value"].update(transaction_id=123),
        lambda e: e.update(offset=-1),
        lambda e: e.update(offset="3"),
        lambda e: e.pop("offset"),
        lambda e: e.update(value="oops"),
    ],
)
def test_schema_violations_rejected(tmp_path, mutate):
    event = make_event(0)
    mutate(event)
    _, valid, rejects = run(tmp_path, {0: [event]})
    assert valid == []
    assert rejects[0]["reason"] == REASON_SCHEMA
    assert rejects[0]["errors"]


def test_non_object_message_rejected(tmp_path):
    _, valid, rejects = run(tmp_path, {0: ["[1, 2]", "null"]})
    assert valid == []
    assert [r["reason"] for r in rejects] == [REASON_SCHEMA, REASON_SCHEMA]


def test_malformed_json_rejected_and_blank_lines_skipped(tmp_path):
    metrics, valid, rejects = run(
        tmp_path, {0: ['{"offset": 1, "val', "", "   ", make_event(2)]}
    )
    assert len(valid) == 1
    assert rejects[0]["reason"] == REASON_MALFORMED_JSON
    assert rejects[0]["offset"] is None
    assert rejects[0]["line_number"] == 1
    assert rejects[0]["raw"] == '{"offset": 1, "val'
    assert metrics["blank_lines_skipped"] == 2
    assert metrics["messages_read"] == 2


def test_extra_fields_allowed_and_preserved(tmp_path):
    _, valid, _ = run(tmp_path, {0: [make_event(0, channel="web")]})
    assert valid[0]["value"]["channel"] == "web"


def test_partitions_processed_in_numeric_order(tmp_path):
    _, valid, _ = run(
        tmp_path,
        {10: [make_event(0, "txn-10")], 2: [make_event(0, "txn-2")]},
    )
    assert [v["partition"] for v in valid] == [2, 10]


def test_non_partition_files_ignored(tmp_path):
    input_dir = tmp_path / "in"
    write_partition(input_dir, 0, [make_event(0)])
    (input_dir / "notes.txt").write_text("ignore me")
    (input_dir / "partition-x.jsonl").write_text("garbage\n")
    metrics = run_pipeline(input_dir, tmp_path / "out")
    assert metrics["partitions_processed"] == 1
    assert metrics["messages_read"] == 1


def test_missing_input_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        run_pipeline(tmp_path / "missing", tmp_path / "out")


def test_empty_input_dir(tmp_path):
    (tmp_path / "in").mkdir()
    metrics = run_pipeline(tmp_path / "in", tmp_path / "out")
    assert metrics["messages_read"] == 0
    assert metrics["reject_rate"] == 0.0
    assert (tmp_path / "out" / "valid.jsonl").read_text() == ""


def test_rerun_overwrites_outputs(tmp_path):
    run(tmp_path, {0: [make_event(0)]})
    _, valid, _ = run(tmp_path, {0: [make_event(0)]})
    assert len(valid) == 1


def test_sample_data_end_to_end(tmp_path):
    out = tmp_path / "out"
    metrics = run_pipeline(SAMPLE_INPUT, out)

    assert metrics["partitions_processed"] == 3
    assert metrics["messages_read"] == 43
    assert metrics["blank_lines_skipped"] == 1
    assert metrics["valid"] == 27
    assert metrics["rejected"] == 16
    assert metrics["rejects_by_reason"] == {
        REASON_DUPLICATE: 3,
        REASON_MALFORMED_JSON: 1,
        REASON_NULL_CUSTOMER: 3,
        REASON_SCHEMA: 6,
        REASON_CURRENCY: 3,
    }
    assert json.loads((out / "metrics.json").read_text()) == metrics

    valid = read_jsonl(out / "valid.jsonl")
    rejects = read_jsonl(out / "rejects.jsonl")
    assert len(valid) == metrics["valid"]
    assert len(rejects) == metrics["rejected"]

    ids = [v["value"]["transaction_id"] for v in valid]
    assert len(ids) == len(set(ids))
    schema = load_schema()
    for record in valid:
        record = dict(record)
        record.pop("partition")
        assert validate_schema(record, schema) == []
        assert record["value"]["customer_id"] is not None
        assert record["value"]["currency"] in {"USD", "EUR", "GBP", "CAD", "JPY"}

    duplicate_ids = sorted(
        r["errors"][0].split("'")[1] for r in rejects if r["reason"] == REASON_DUPLICATE
    )
    assert duplicate_ids == ["txn-00003", "txn-00005", "txn-00007"]

    for key, part in metrics["partitions"].items():
        assert part["messages_read"] == part["valid"] + part["rejected"]


def test_cli_main(tmp_path, capsys):
    assert main(["--input", str(SAMPLE_INPUT), "--output", str(tmp_path)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["valid"] == 27
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
    assert json.loads(result.stdout)["rejected"] == 16
    for name in ("valid.jsonl", "rejects.jsonl", "metrics.json"):
        assert (tmp_path / "out" / name).exists()
