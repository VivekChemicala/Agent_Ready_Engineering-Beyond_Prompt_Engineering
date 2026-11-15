import json
import subprocess
import sys
from pathlib import Path

import pytest

from txn_pipeline import run_pipeline
from txn_pipeline.pipeline import APPROVED_CURRENCIES_PATH, load_approved_currencies

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REASONS = (
    "MALFORMED_EVENT",
    "NULL_CUSTOMER_ID",
    "SCHEMA_VIOLATION",
    "INVALID_CURRENCY",
    "DUPLICATE_TRANSACTION",
)
VALID_KEYS = [
    "transaction_id", "customer_id", "amount", "currency", "event_time",
    "merchant_id", "source_partition", "source_offset",
]
REJECT_KEYS = [
    "source_partition", "source_offset", "reason_code", "reason_detail", "raw",
]


def make_value(**overrides):
    value = {
        "transaction_id": "txn-1",
        "customer_id": "cust-1",
        "amount": 10.5,
        "currency": "USD",
        "event_time": "2026-11-01T10:00:00Z",
        "merchant_id": "merch-1",
    }
    for key, val in overrides.items():
        if val is _DROP:
            value.pop(key)
        else:
            value[key] = val
    return value


_DROP = object()


def message(offset, value, key="k"):
    return json.dumps(
        {"offset": offset, "key": key, "timestamp": 1, "value": value}
    )


def write_partition(input_dir, n, lines):
    input_dir.mkdir(parents=True, exist_ok=True)
    path = input_dir / f"partition-{n}.jsonl"
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return path


def read_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def run(tmp_path, partitions):
    input_dir = tmp_path / "input"
    input_dir.mkdir(exist_ok=True)
    for n, lines in partitions.items():
        write_partition(input_dir, n, lines)
    out = tmp_path / "out"
    metrics = run_pipeline(input_dir, out)
    return metrics, read_jsonl(out / "valid.jsonl"), read_jsonl(out / "rejects.jsonl")


def single_reject(tmp_path, line):
    metrics, valid, rejects = run(tmp_path, {0: [line]})
    assert valid == []
    assert len(rejects) == 1
    return rejects[0]


# --- happy path and output contract -----------------------------------------

def test_valid_event_is_accepted_with_exact_keys(tmp_path):
    value = make_value(channel="pos", extra={"x": 1})
    metrics, valid, rejects = run(tmp_path, {3: [message(7, value)]})
    assert rejects == []
    assert valid == [{
        "transaction_id": "txn-1",
        "customer_id": "cust-1",
        "amount": 10.5,
        "currency": "USD",
        "event_time": "2026-11-01T10:00:00Z",
        "merchant_id": "merch-1",
        "source_partition": 3,
        "source_offset": 7,
    }]
    assert list(valid[0]) == VALID_KEYS


def test_integer_amount_and_fractional_event_time_are_valid(tmp_path):
    value = make_value(amount=5, event_time="2024-02-29T23:59:59.123456Z")
    _, valid, rejects = run(tmp_path, {0: [message(0, value)]})
    assert rejects == []
    assert valid[0]["amount"] == 5
    assert isinstance(valid[0]["amount"], int)


def test_reject_record_has_exact_keys_and_raw_line(tmp_path):
    line = message(4, make_value(currency="XYZ"))
    reject = single_reject(tmp_path, line)
    assert list(reject) == REJECT_KEYS
    assert reject["source_partition"] == 0
    assert reject["source_offset"] == 4
    assert reject["reason_code"] == "INVALID_CURRENCY"
    assert isinstance(reject["reason_detail"], str) and reject["reason_detail"]
    assert reject["raw"] == line


# --- MALFORMED_EVENT -----------------------------------------------------------

@pytest.mark.parametrize("line", [
    '{"offset": 1, "value": {"transaction_id"',
    "not json",
    "[1, 2, 3]",
    '"a string"',
    "42",
    "null",
])
def test_unparseable_or_non_object_is_malformed_with_null_offset(tmp_path, line):
    reject = single_reject(tmp_path, line)
    assert reject["reason_code"] == "MALFORMED_EVENT"
    assert reject["source_offset"] is None
    assert reject["raw"] == line


@pytest.mark.parametrize("offset", [-1, "3", 1.5, True, None])
def test_bad_offset_is_malformed(tmp_path, offset):
    reject = single_reject(tmp_path, message(offset, make_value()))
    assert reject["reason_code"] == "MALFORMED_EVENT"
    assert reject["source_offset"] is None


def test_missing_offset_is_malformed(tmp_path):
    reject = single_reject(tmp_path, json.dumps({"value": make_value()}))
    assert reject["reason_code"] == "MALFORMED_EVENT"


@pytest.mark.parametrize("value", [None, "str", [1], 5])
def test_non_object_value_is_malformed_but_keeps_offset(tmp_path, value):
    reject = single_reject(tmp_path, message(9, value))
    assert reject["reason_code"] == "MALFORMED_EVENT"
    assert reject["source_offset"] == 9


def test_missing_value_is_malformed(tmp_path):
    reject = single_reject(tmp_path, json.dumps({"offset": 2}))
    assert reject["reason_code"] == "MALFORMED_EVENT"
    assert reject["source_offset"] == 2


def test_invalid_utf8_is_malformed_and_does_not_raise(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    good = message(1, make_value()).encode("utf-8")
    bad = b'{"offset": 0, \xff}'
    (input_dir / "partition-0.jsonl").write_bytes(bad + b"\n" + good + b"\n")
    metrics = run_pipeline(input_dir, tmp_path / "out")
    rejects = read_jsonl(tmp_path / "out" / "rejects.jsonl")
    assert rejects[0]["reason_code"] == "MALFORMED_EVENT"
    assert rejects[0]["source_offset"] is None
    assert metrics["valid_records"] == 1


def test_malformed_takes_precedence_over_null_customer(tmp_path):
    reject = single_reject(tmp_path, message(-1, make_value(customer_id=None)))
    assert reject["reason_code"] == "MALFORMED_EVENT"


# --- NULL_CUSTOMER_ID ----------------------------------------------------------

@pytest.mark.parametrize("customer_id", [None, "", "   ", "\t\n", _DROP])
def test_null_missing_or_blank_customer_id(tmp_path, customer_id):
    reject = single_reject(tmp_path, message(0, make_value(customer_id=customer_id)))
    assert reject["reason_code"] == "NULL_CUSTOMER_ID"
    assert reject["source_offset"] == 0


def test_null_customer_takes_precedence_over_schema_and_currency(tmp_path):
    value = make_value(customer_id=None, amount="bad", currency="XYZ")
    reject = single_reject(tmp_path, message(0, value))
    assert reject["reason_code"] == "NULL_CUSTOMER_ID"


# --- SCHEMA_VIOLATION ----------------------------------------------------------

@pytest.mark.parametrize("overrides", [
    {"customer_id": 123},
    {"customer_id": ["c"]},
    {"transaction_id": _DROP},
    {"transaction_id": ""},
    {"transaction_id": "  "},
    {"transaction_id": 17},
    {"merchant_id": _DROP},
    {"merchant_id": " "},
    {"merchant_id": None},
    {"amount": _DROP},
    {"amount": "10.5"},
    {"amount": True},
    {"amount": 0},
    {"amount": -3.2},
    {"amount": None},
    {"currency": _DROP},
    {"currency": 840},
    {"currency": None},
    {"event_time": _DROP},
    {"event_time": None},
    {"event_time": 1700000000},
    {"event_time": "2026-11-01 10:00:00Z"},
    {"event_time": "2026-11-01T10:00:00"},
    {"event_time": "2026-11-01T10:00:00+00:00"},
    {"event_time": "2026-11-01T10:00:00.1234567Z"},
    {"event_time": "2026-11-01T10:00:00.Z"},
    {"event_time": "2026-02-30T10:00:00Z"},
    {"event_time": "2025-02-29T10:00:00Z"},
    {"event_time": "2026-11-01T24:00:00Z"},
    {"event_time": "2026-11-01"},
])
def test_schema_violation(tmp_path, overrides):
    reject = single_reject(tmp_path, message(0, make_value(**overrides)))
    assert reject["reason_code"] == "SCHEMA_VIOLATION", reject["reason_detail"]


@pytest.mark.parametrize("amount_literal", ["NaN", "Infinity", "-Infinity", "1e400"])
def test_non_finite_amount_is_schema_violation(tmp_path, amount_literal):
    line = message(0, make_value(amount="PLACEHOLDER")).replace(
        '"PLACEHOLDER"', amount_literal
    )
    reject = single_reject(tmp_path, line)
    assert reject["reason_code"] == "SCHEMA_VIOLATION"


def test_huge_integer_amount_is_accepted(tmp_path):
    _, valid, _ = run(tmp_path, {0: [message(0, make_value(amount=10 ** 400))]})
    assert valid[0]["amount"] == 10 ** 400


def test_schema_takes_precedence_over_currency(tmp_path):
    value = make_value(amount="1", currency="XYZ")
    reject = single_reject(tmp_path, message(0, value))
    assert reject["reason_code"] == "SCHEMA_VIOLATION"


# --- INVALID_CURRENCY ----------------------------------------------------------

@pytest.mark.parametrize("currency", ["XYZ", "BTC", "usd", "Usd", " USD", ""])
def test_invalid_currency(tmp_path, currency):
    reject = single_reject(tmp_path, message(0, make_value(currency=currency)))
    assert reject["reason_code"] == "INVALID_CURRENCY"


def test_every_configured_currency_is_accepted(tmp_path):
    currencies = sorted(load_approved_currencies())
    lines = [
        message(i, make_value(transaction_id=f"t{i}", currency=c))
        for i, c in enumerate(currencies)
    ]
    metrics, valid, rejects = run(tmp_path, {0: lines})
    assert rejects == []
    assert [v["currency"] for v in valid] == currencies


def test_currencies_come_from_config_file():
    data = json.loads(APPROVED_CURRENCIES_PATH.read_text(encoding="utf-8"))
    assert load_approved_currencies() == frozenset(data["approved_currencies"])
    expected = PROJECT_ROOT / "config" / "approved_currencies.json"
    assert APPROVED_CURRENCIES_PATH == expected


def test_currency_config_resolved_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    metrics, valid, _ = run(tmp_path, {0: [message(0, make_value())]})
    assert len(valid) == 1


def test_invalid_currency_takes_precedence_over_duplicate(tmp_path):
    lines = [
        message(0, make_value(transaction_id="t1")),
        message(1, make_value(transaction_id="t1", currency="XYZ")),
    ]
    _, _, rejects = run(tmp_path, {0: lines})
    assert rejects[0]["reason_code"] == "INVALID_CURRENCY"


# --- DUPLICATE_TRANSACTION -----------------------------------------------------

def test_duplicate_within_partition(tmp_path):
    lines = [
        message(0, make_value(transaction_id="t1")),
        message(1, make_value(transaction_id="t1", amount=99)),
    ]
    _, valid, rejects = run(tmp_path, {0: lines})
    assert [v["source_offset"] for v in valid] == [0]
    assert valid[0]["amount"] == 10.5
    assert rejects[0]["reason_code"] == "DUPLICATE_TRANSACTION"
    assert rejects[0]["source_offset"] == 1


def test_duplicate_across_partitions(tmp_path):
    metrics, valid, rejects = run(tmp_path, {
        0: [message(0, make_value(transaction_id="t1"))],
        1: [message(0, make_value(transaction_id="t1"))],
    })
    assert [v["source_partition"] for v in valid] == [0]
    assert rejects[0]["reason_code"] == "DUPLICATE_TRANSACTION"
    assert rejects[0]["source_partition"] == 1


def test_duplicate_after_reject_is_accepted(tmp_path):
    lines = [
        message(0, make_value(transaction_id="t1", currency="XYZ")),
        message(1, make_value(transaction_id="t1", customer_id=None)),
        message(2, make_value(transaction_id="t1", amount="5")),
        message(3, make_value(transaction_id="t1")),
        message(4, make_value(transaction_id="t1")),
    ]
    metrics, valid, rejects = run(tmp_path, {0: lines})
    assert [v["source_offset"] for v in valid] == [3]
    assert [r["reason_code"] for r in rejects] == [
        "INVALID_CURRENCY", "NULL_CUSTOMER_ID", "SCHEMA_VIOLATION",
        "DUPLICATE_TRANSACTION",
    ]


def test_duplicate_detection_is_case_sensitive_exact_match(tmp_path):
    lines = [
        message(0, make_value(transaction_id="t1")),
        message(1, make_value(transaction_id="T1")),
    ]
    _, valid, rejects = run(tmp_path, {0: lines})
    assert len(valid) == 2 and rejects == []


# --- ordering and input discovery ---------------------------------------------

def test_partitions_processed_in_numeric_order(tmp_path):
    metrics, valid, _ = run(tmp_path, {
        10: [message(0, make_value(transaction_id="from-10"))],
        2: [message(0, make_value(transaction_id="from-2"))],
        1: [message(0, make_value(transaction_id="from-1"))],
    })
    assert [v["source_partition"] for v in valid] == [1, 2, 10]
    assert list(metrics["partitions"]) == ["1", "2", "10"]


def test_numeric_order_decides_which_duplicate_wins(tmp_path):
    _, valid, rejects = run(tmp_path, {
        10: [message(0, make_value(transaction_id="t1", merchant_id="m10"))],
        2: [message(0, make_value(transaction_id="t1", merchant_id="m2"))],
    })
    assert valid[0]["merchant_id"] == "m2"
    assert rejects[0]["source_partition"] == 10


def test_lines_keep_file_order_and_outputs_interleave_in_processing_order(tmp_path):
    lines = [
        message(5, make_value(transaction_id="a")),
        message(3, make_value(transaction_id="b", currency="XYZ")),
        message(1, make_value(transaction_id="c")),
        message(0, make_value(transaction_id="d", customer_id=None)),
    ]
    _, valid, rejects = run(tmp_path, {0: lines})
    assert [v["source_offset"] for v in valid] == [5, 1]
    assert [r["source_offset"] for r in rejects] == [3, 0]


def test_non_partition_files_are_ignored(tmp_path):
    input_dir = tmp_path / "input"
    write_partition(input_dir, 0, [message(0, make_value())])
    for name in ["notes.txt", "partition-1.json", "partition-x.jsonl",
                 "partition-2.jsonl.bak", "xpartition-3.jsonl"]:
        (input_dir / name).write_text("garbage\n", encoding="utf-8")
    (input_dir / "partition-4.jsonl").mkdir()
    metrics = run_pipeline(input_dir, tmp_path / "out")
    assert metrics["input_records"] == 1
    assert list(metrics["partitions"]) == ["0"]


def test_blank_lines_are_skipped_and_not_counted(tmp_path):
    lines = ["", "   ", message(0, make_value()), "\t", ""]
    metrics, valid, rejects = run(tmp_path, {0: lines})
    assert metrics["input_records"] == 1
    assert len(valid) == 1 and rejects == []


def test_crlf_line_endings(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    line = message(0, make_value())
    (input_dir / "partition-0.jsonl").write_bytes((line + "\r\n").encode("utf-8"))
    run_pipeline(input_dir, tmp_path / "out")
    assert len(read_jsonl(tmp_path / "out" / "valid.jsonl")) == 1


# --- metrics -------------------------------------------------------------------

def test_metrics_structure_and_counts(tmp_path):
    metrics, _, _ = run(tmp_path, {
        0: [
            message(0, make_value(transaction_id="t1")),
            "{bad json",
            message(2, make_value(transaction_id="t2", customer_id=None)),
            message(3, make_value(transaction_id="t3", amount=-1)),
        ],
        1: [
            message(0, make_value(transaction_id="t4", currency="usd")),
            message(1, make_value(transaction_id="t1")),
            message(2, make_value(transaction_id="t5")),
        ],
    })
    assert metrics == {
        "schema_version": "1.0",
        "input_records": 7,
        "valid_records": 2,
        "rejected_records": 5,
        "rejects_by_reason": {
            "MALFORMED_EVENT": 1,
            "NULL_CUSTOMER_ID": 1,
            "SCHEMA_VIOLATION": 1,
            "INVALID_CURRENCY": 1,
            "DUPLICATE_TRANSACTION": 1,
        },
        "partitions": {
            "0": {"input_records": 4, "valid_records": 1, "rejected_records": 3},
            "1": {"input_records": 3, "valid_records": 1, "rejected_records": 2},
        },
    }
    assert list(metrics["rejects_by_reason"]) == list(REASONS)


def test_metrics_file_matches_return_value(tmp_path):
    metrics, _, _ = run(tmp_path, {0: [message(0, make_value())]})
    on_disk = json.loads((tmp_path / "out" / "metrics.json").read_text("utf-8"))
    assert on_disk == metrics


def test_all_reason_codes_present_when_zero(tmp_path):
    metrics, _, _ = run(tmp_path, {0: [message(0, make_value())]})
    assert metrics["rejects_by_reason"] == {code: 0 for code in REASONS}


def test_empty_partition_appears_in_metrics(tmp_path):
    metrics, valid, rejects = run(tmp_path, {0: [], 1: [message(0, make_value())]})
    assert metrics["partitions"]["0"] == {
        "input_records": 0, "valid_records": 0, "rejected_records": 0,
    }
    assert metrics["input_records"] == 1


def test_empty_input_dir(tmp_path):
    (tmp_path / "input").mkdir()
    metrics = run_pipeline(tmp_path / "input", tmp_path / "out")
    assert metrics["input_records"] == 0
    assert metrics["partitions"] == {}
    assert (tmp_path / "out" / "valid.jsonl").read_text() == ""
    assert (tmp_path / "out" / "rejects.jsonl").read_text() == ""


def test_output_is_deterministic_and_overwritten(tmp_path):
    input_dir = tmp_path / "input"
    write_partition(input_dir, 0, [message(0, make_value()), "bad"])
    out = tmp_path / "nested" / "out"
    run_pipeline(input_dir, out)
    first = {p.name: p.read_bytes() for p in out.iterdir()}
    run_pipeline(input_dir, out)
    second = {p.name: p.read_bytes() for p in out.iterdir()}
    assert first == second
    assert sorted(first) == ["metrics.json", "rejects.jsonl", "valid.jsonl"]


def test_sample_data_invariants(tmp_path):
    metrics = run_pipeline(PROJECT_ROOT / "data" / "input", tmp_path / "out")
    assert metrics["input_records"] == (
        metrics["valid_records"] + metrics["rejected_records"]
    )
    assert metrics["rejected_records"] == sum(metrics["rejects_by_reason"].values())
    for counts in metrics["partitions"].values():
        assert counts["input_records"] == (
            counts["valid_records"] + counts["rejected_records"]
        )
    ids = [v["transaction_id"] for v in read_jsonl(tmp_path / "out" / "valid.jsonl")]
    assert len(ids) == len(set(ids))


def test_non_ascii_values_round_trip(tmp_path):
    value = make_value(customer_id="cüst-ñ", merchant_id="\ud800lone")
    line = message(0, value)
    _, valid, _ = run(tmp_path, {0: [line]})
    assert valid[0]["customer_id"] == "cüst-ñ"
    assert valid[0]["merchant_id"] == "\ud800lone"


# --- CLI -----------------------------------------------------------------------

def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "txn_pipeline", *args],
        cwd=PROJECT_ROOT, capture_output=True, text=True,
    )


def test_cli_success_with_rejects(tmp_path):
    input_dir = tmp_path / "input"
    write_partition(input_dir, 0, [message(0, make_value()), "bad"])
    out = tmp_path / "out"
    result = run_cli("--input", str(input_dir), "--output", str(out))
    assert result.returncode == 0, result.stderr
    metrics = json.loads((out / "metrics.json").read_text("utf-8"))
    assert metrics["valid_records"] == 1 and metrics["rejected_records"] == 1


def test_cli_missing_input_fails(tmp_path):
    result = run_cli("--input", str(tmp_path / "nope"), "--output", str(tmp_path / "o"))
    assert result.returncode != 0
    assert not (tmp_path / "o").exists()
