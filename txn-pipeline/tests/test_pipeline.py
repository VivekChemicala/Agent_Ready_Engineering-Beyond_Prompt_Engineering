import json
from pathlib import Path

import pytest

from txn_pipeline.__main__ import main
from txn_pipeline.pipeline import (
    load_approved_currencies,
    run_pipeline,
    schema_errors,
)

SAMPLE_INPUT = Path(__file__).resolve().parents[1] / "data" / "input"
CURRENCIES = {"USD", "EUR", "GBP", "CAD", "JPY"}
AMOUNT_ERR = "value.amount: expected finite number > 0"
NON_EMPTY = "expected non-empty string"
TIME_ERR = "value.event_time: expected RFC 3339 date-time"


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
    key = value["customer_id"]
    return {"offset": offset, "key": key, "timestamp": 1, "value": value}


def write_partition(input_dir, partition, lines):
    input_dir.mkdir(parents=True, exist_ok=True)
    text = "".join(
        (line if isinstance(line, str) else json.dumps(line)) + "\n" for line in lines
    )
    (input_dir / f"partition-{partition}.jsonl").write_text(text, encoding="utf-8")


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def run(tmp_path, partitions):
    input_dir = tmp_path / "in"
    for partition, lines in partitions.items():
        write_partition(input_dir, partition, lines)
    out = tmp_path / "out"
    metrics = run_pipeline(input_dir, out, approved_currencies=CURRENCIES)
    return metrics, read_jsonl(out / "valid.jsonl"), read_jsonl(out / "rejects.jsonl")


def test_valid_event_is_accepted_with_source_metadata(tmp_path):
    metrics, valid, rejects = run(tmp_path, {0: [make_message(3, channel="web")]})
    assert rejects == []
    assert len(valid) == 1
    record = valid[0]
    assert record["transaction_id"] == "txn-00003"
    assert record["channel"] == "web"
    assert record["_source"] == {
        "partition": 0,
        "file": "partition-0.jsonl",
        "line": 1,
        "offset": 3,
        "key": "cust-0001",
        "timestamp": 1,
    }
    assert metrics["valid"] == 1 and metrics["rejected"] == 0


@pytest.mark.parametrize(
    "message, error",
    [
        ({"value": make_message()["value"]}, "offset: required"),
        ({**make_message(), "offset": -1}, "offset: expected integer >= 0"),
        ({**make_message(), "offset": True}, "offset: expected integer >= 0"),
        ({**make_message(), "key": 5}, "key: expected string or null"),
        ({**make_message(), "timestamp": "1"}, "timestamp: expected integer"),
        ({"offset": 0}, "value: required"),
        ({"offset": 0, "value": []}, "value: expected object"),
        ([1, 2], "message: expected object"),
        (make_message(amount="12.50"), AMOUNT_ERR),
        (make_message(amount=0), AMOUNT_ERR),
        (make_message(amount=-3), AMOUNT_ERR),
        (make_message(amount=True), AMOUNT_ERR),
        (make_message(transaction_id=""), "value.transaction_id: " + NON_EMPTY),
        (make_message(transaction_id=7), "value.transaction_id: " + NON_EMPTY),
        (make_message(customer_id=""), "value.customer_id: " + NON_EMPTY),
        (make_message(merchant_id=None), "value.merchant_id: " + NON_EMPTY),
        (make_message(currency=None), "value.currency: expected string"),
        (make_message(event_time="yesterday"), TIME_ERR),
        (make_message(event_time="2026-11-01"), TIME_ERR),
        (
            make_message(event_time="2026-11-01T00:00:00"),
            TIME_ERR,
        ),
    ],
)
def test_schema_violations_are_rejected(tmp_path, message, error):
    metrics, valid, rejects = run(tmp_path, {0: [message]})
    assert valid == []
    assert len(rejects) == 1
    assert rejects[0]["reason"] == "schema_violation"
    assert error in rejects[0]["errors"]
    assert rejects[0]["message"] == message
    assert metrics["rejects_by_reason"]["schema_violation"] == 1


@pytest.mark.parametrize(
    "field",
    [
        "transaction_id",
        "customer_id",
        "amount",
        "currency",
        "event_time",
        "merchant_id",
    ],
)
def test_missing_required_value_field_is_schema_violation(field):
    message = make_message()
    del message["value"][field]
    assert schema_errors(message) == [f"value.{field}: required"]


def test_event_time_with_offset_is_accepted():
    assert schema_errors(make_message(event_time="2026-11-01T08:00:00.123+05:30")) == []


def test_null_customer_id_is_rejected(tmp_path):
    metrics, valid, rejects = run(tmp_path, {0: [make_message(customer_id=None)]})
    assert valid == []
    assert rejects[0]["reason"] == "null_customer_id"
    assert metrics["rejects_by_reason"]["null_customer_id"] == 1


def test_null_customer_id_with_other_schema_errors_is_schema_violation(tmp_path):
    _, _, rejects = run(tmp_path, {0: [make_message(customer_id=None, amount="1")]})
    assert rejects[0]["reason"] == "schema_violation"


@pytest.mark.parametrize("currency", ["XYZ", "BTC", "usd", ""])
def test_unapproved_currency_is_rejected(tmp_path, currency):
    metrics, valid, rejects = run(tmp_path, {0: [make_message(currency=currency)]})
    assert valid == []
    assert rejects[0]["reason"] == "unapproved_currency"
    assert metrics["rejects_by_reason"]["unapproved_currency"] == 1


def test_duplicate_transaction_ids_rejected_within_and_across_partitions(tmp_path):
    first = make_message(0, transaction_id="txn-dup")
    metrics, valid, rejects = run(
        tmp_path,
        {
            0: [first, make_message(1, transaction_id="txn-dup", amount=99.0)],
            1: [make_message(0, transaction_id="txn-dup")],
        },
    )
    assert [r["_source"]["offset"] for r in valid] == [0]
    assert valid[0]["amount"] == 10.5
    assert [r["reason"] for r in rejects] == ["duplicate_transaction_id"] * 2
    assert [r["source"]["partition"] for r in rejects] == [0, 1]
    assert metrics["rejects_by_reason"]["duplicate_transaction_id"] == 2


def test_invalid_first_occurrence_does_not_block_later_valid_event(tmp_path):
    _, valid, rejects = run(
        tmp_path,
        {0: [make_message(0, transaction_id="t", customer_id=None),
             make_message(1, transaction_id="t")]},
    )
    assert [r["_source"]["offset"] for r in valid] == [1]
    assert [r["reason"] for r in rejects] == ["null_customer_id"]


def test_partitions_processed_in_numeric_order(tmp_path):
    _, valid, rejects = run(
        tmp_path,
        {
            10: [make_message(0, transaction_id="t")],
            2: [make_message(0, transaction_id="t")],
        },
    )
    assert valid[0]["_source"]["partition"] == 2
    assert rejects[0]["source"]["partition"] == 10


def test_malformed_lines_rejected_and_blank_lines_skipped(tmp_path):
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    good = json.dumps(make_message()).encode()
    (input_dir / "partition-0.jsonl").write_bytes(
        b'{"offset": 1, "value": {"tran\n\n   \n\xff\xfe\n{"offset": NaN}\n' + good
    )
    metrics = run_pipeline(input_dir, tmp_path / "out", approved_currencies=CURRENCIES)
    rejects = read_jsonl(tmp_path / "out" / "rejects.jsonl")
    assert [r["reason"] for r in rejects] == ["malformed_json"] * 3
    assert [r["source"]["line"] for r in rejects] == [1, 4, 5]
    assert rejects[0]["raw"] == '{"offset": 1, "value": {"tran'
    assert "message" not in rejects[0]
    assert metrics["blank_lines_skipped"] == 2
    assert metrics["records_read"] == 4
    assert metrics["valid"] == 1


def test_non_partition_files_are_ignored(tmp_path):
    input_dir = tmp_path / "in"
    write_partition(input_dir, 0, [make_message()])
    (input_dir / "notes.txt").write_text("not json\n")
    (input_dir / "partition-x.jsonl").write_text("not json\n")
    metrics = run_pipeline(input_dir, tmp_path / "out", approved_currencies=CURRENCIES)
    assert metrics["partitions_processed"] == 1
    assert metrics["records_read"] == 1


def test_empty_input_dir_produces_empty_outputs(tmp_path):
    (tmp_path / "in").mkdir()
    metrics = run_pipeline(
        tmp_path / "in", tmp_path / "out", approved_currencies=CURRENCIES
    )
    assert metrics["records_read"] == 0
    assert (tmp_path / "out" / "valid.jsonl").read_text() == ""
    assert (tmp_path / "out" / "rejects.jsonl").read_text() == ""


def test_missing_input_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        run_pipeline(tmp_path / "missing", tmp_path / "out")


def test_metrics_file_matches_return_value_and_is_consistent(tmp_path):
    out = tmp_path / "out"
    metrics = run_pipeline(SAMPLE_INPUT, out)
    assert json.loads((out / "metrics.json").read_text()) == metrics
    assert metrics["records_read"] == metrics["valid"] + metrics["rejected"]
    assert sum(metrics["rejects_by_reason"].values()) == metrics["rejected"]
    for key in ("records_read", "valid", "rejected", "blank_lines_skipped"):
        assert sum(p[key] for p in metrics["per_partition"].values()) == metrics[key]
    assert len(read_jsonl(out / "valid.jsonl")) == metrics["valid"]
    assert len(read_jsonl(out / "rejects.jsonl")) == metrics["rejected"]


def test_sample_data_expected_counts(tmp_path):
    out = tmp_path / "out"
    metrics = run_pipeline(SAMPLE_INPUT, out)
    assert metrics["partitions_processed"] == 3
    assert metrics["records_read"] == 43
    assert metrics["blank_lines_skipped"] == 1
    assert metrics["valid"] == 27
    assert metrics["rejected"] == 16
    assert metrics["rejects_by_reason"] == {
        "malformed_json": 1,
        "schema_violation": 6,
        "null_customer_id": 3,
        "unapproved_currency": 3,
        "duplicate_transaction_id": 3,
    }
    valid = read_jsonl(out / "valid.jsonl")
    ids = [r["transaction_id"] for r in valid]
    assert len(ids) == len(set(ids))
    assert all(r["customer_id"] for r in valid)
    assert {r["currency"] for r in valid} <= load_approved_currencies()


def test_rerun_is_deterministic(tmp_path):
    run_pipeline(SAMPLE_INPUT, tmp_path / "a")
    run_pipeline(SAMPLE_INPUT, tmp_path / "b")
    for name in ("valid.jsonl", "rejects.jsonl"):
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
    write_partition(input_dir, 0, [make_message(0, currency="BTC"),
                                   make_message(1, currency="EUR")])
    out = tmp_path / "out"
    args = ["--input", str(input_dir), "--output", str(out)]
    args += ["--currencies", str(currencies)]
    assert main(args) == 0
    assert [r["currency"] for r in read_jsonl(out / "valid.jsonl")] == ["BTC"]
    capsys.readouterr()
    assert main(["--input", str(tmp_path / "nope"), "--output", str(out)]) == 2
    assert "input directory not found" in capsys.readouterr().err
