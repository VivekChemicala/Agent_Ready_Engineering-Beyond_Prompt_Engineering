import json
import subprocess
import sys
from pathlib import Path

from tests.helpers import event, message, read_jsonl, reasons, run, write_partition
from txn_pipeline import run_pipeline

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REASON_CODES = [
    "MALFORMED_EVENT", "NULL_CUSTOMER_ID", "SCHEMA_VIOLATION",
    "INVALID_CURRENCY", "DUPLICATE_TRANSACTION",
]


def mixed_input():
    return {
        0: [
            message(0, event(transaction_id="a")),
            message(1, event(transaction_id="b", customer_id=None)),
            "{broken",
            message(3, event(transaction_id="c", amount="1")),
        ],
        1: [
            message(0, event(transaction_id="d", currency="usd")),
            message(1, event(transaction_id="a")),
            message(2, event(transaction_id="e")),
        ],
    }


def test_metrics_structure_and_counts(tmp_path):
    metrics, valid, rejects = run(tmp_path, mixed_input())
    assert metrics == {
        "schema_version": "1.0",
        "input_records": 7,
        "valid_records": 2,
        "rejected_records": 5,
        "rejects_by_reason": {code: 1 for code in REASON_CODES},
        "partitions": {
            "0": {"input_records": 4, "valid_records": 1, "rejected_records": 3},
            "1": {"input_records": 3, "valid_records": 1, "rejected_records": 2},
        },
    }
    assert list(metrics["rejects_by_reason"]) == REASON_CODES
    assert len(valid) == metrics["valid_records"]
    assert len(rejects) == metrics["rejected_records"]
    on_disk = json.loads((tmp_path / "out" / "metrics.json").read_text("utf-8"))
    assert on_disk == metrics


def test_metrics_always_has_all_reason_codes(tmp_path):
    metrics, _, rejects = run(tmp_path, {0: [message(0, event())]})
    assert rejects == []
    assert metrics["rejects_by_reason"] == {code: 0 for code in REASON_CODES}
    assert metrics["input_records"] == 1
    assert metrics["valid_records"] == 1


def test_empty_input_dir(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    metrics = run_pipeline(input_dir, tmp_path / "out")
    assert metrics["input_records"] == 0
    assert metrics["partitions"] == {}
    assert (tmp_path / "out" / "valid.jsonl").read_text() == ""
    assert (tmp_path / "out" / "rejects.jsonl").read_text() == ""


def test_reject_record_shape(tmp_path):
    line = message(5, event(currency="XYZ"))
    _, _, rejects = run(tmp_path, {2: [line]})
    assert rejects == [{
        "source_partition": 2,
        "source_offset": 5,
        "reason_code": "INVALID_CURRENCY",
        "reason_detail": rejects[0]["reason_detail"],
        "raw": line,
    }]
    assert isinstance(rejects[0]["reason_detail"], str)
    assert rejects[0]["reason_detail"]


def test_partitions_processed_in_numeric_order(tmp_path):
    parts = {n: [message(0, event(transaction_id=f"t{n}"))] for n in (10, 2, 1)}
    parts[10].append(message(1, event(transaction_id="dup")))
    parts[2].append(message(1, event(transaction_id="dup")))
    metrics, valid, rejects = run(tmp_path, parts)
    assert [v["source_partition"] for v in valid] == [1, 2, 2, 10]
    assert [v["transaction_id"] for v in valid] == ["t1", "t2", "dup", "t10"]
    assert [(r["source_partition"], r["reason_code"]) for r in rejects] == [
        (10, "DUPLICATE_TRANSACTION")
    ]
    assert list(metrics["partitions"]) == ["1", "2", "10"]


def test_lines_processed_in_file_order_not_offset_order(tmp_path):
    _, valid, _ = run(tmp_path, {0: [
        message(9, event(transaction_id="x")),
        message(3, event(transaction_id="y")),
    ]})
    assert [v["source_offset"] for v in valid] == [9, 3]


def test_non_partition_files_are_ignored(tmp_path):
    input_dir = tmp_path / "input"
    write_partition(input_dir, 0, [message(0, event())])
    (input_dir / "README.md").write_text("not data\n")
    (input_dir / "partition-1.json").write_text("garbage\n")
    (input_dir / "partition-x.jsonl").write_text("garbage\n")
    (input_dir / "partition-2.jsonl.bak").write_text("garbage\n")
    (input_dir / "other-3.jsonl").write_text("garbage\n")
    (input_dir / "partition-4.jsonl").mkdir()
    metrics = run_pipeline(input_dir, tmp_path / "out")
    assert metrics["input_records"] == 1
    assert list(metrics["partitions"]) == ["0"]


def test_blank_lines_are_skipped_and_not_counted(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "partition-0.jsonl").write_text(
        "\n   \n" + message(0, event()) + "\n\t\n\n"
        + message(1, event(transaction_id="t2")),
        encoding="utf-8",
    )
    metrics = run_pipeline(input_dir, tmp_path / "out")
    assert metrics["input_records"] == 2
    assert metrics["valid_records"] == 2
    assert metrics["rejected_records"] == 0


def test_crlf_line_endings(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    line = "{bad json"
    (input_dir / "partition-0.jsonl").write_bytes(
        (message(0, event()) + "\r\n" + line + "\r\n").encode()
    )
    run_pipeline(input_dir, tmp_path / "out")
    rejects = read_jsonl(tmp_path / "out" / "rejects.jsonl")
    assert [r["raw"] for r in rejects] == [line]


def test_outputs_are_overwritten_and_deterministic(tmp_path):
    out = tmp_path / "nested" / "out"
    input_dir = tmp_path / "input"
    for n, lines in mixed_input().items():
        write_partition(input_dir, n, lines)
    run_pipeline(input_dir, out)
    first = {p.name: p.read_bytes() for p in out.iterdir()}
    run_pipeline(input_dir, out)
    second = {p.name: p.read_bytes() for p in out.iterdir()}
    assert first == second
    assert set(first) == {"valid.jsonl", "rejects.jsonl", "metrics.json"}

    write_partition(input_dir, 0, [message(0, event())])
    (input_dir / "partition-1.jsonl").unlink()
    run_pipeline(input_dir, out)
    assert len(read_jsonl(out / "valid.jsonl")) == 1
    assert read_jsonl(out / "rejects.jsonl") == []


def test_never_raises_on_bad_content(tmp_path):
    lines = [
        "[]", "1", '""', "{}", '{"offset": 0}', '{"offset": 0, "value": 1}',
        '{"offset": 0, "value": {}}', "[" * 100000,
        '{"offset": 0, "value": {"customer_id": {"a": 1}}}',
        '{"offset": 0, "value": {"customer_id": "c", "transaction_id": ["x"]}}',
        '{"offset": 0, "value": {"customer_id": "\\ud800", "transaction_id":'
        ' "t", "amount": 1, "currency": "USD", "event_time": '
        '"2026-01-01T00:00:00Z", "merchant_id": "m"}}',
    ]
    metrics, valid, rejects = run(tmp_path, {0: lines})
    assert metrics["input_records"] == len(lines)
    assert metrics["input_records"] == (
        metrics["valid_records"] + metrics["rejected_records"]
    )
    assert len(valid) == 1
    assert all(r["reason_code"] in REASON_CODES for r in rejects)
    assert reasons(rejects).count("MALFORMED_EVENT") == 7


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "txn_pipeline", *args],
        cwd=PROJECT_ROOT, capture_output=True, text=True,
    )


def test_cli_success_with_rejects(tmp_path):
    input_dir = tmp_path / "input"
    for n, lines in mixed_input().items():
        write_partition(input_dir, n, lines)
    out = tmp_path / "out"
    result = run_cli("--input", str(input_dir), "--output", str(out))
    assert result.returncode == 0, result.stderr
    metrics = json.loads((out / "metrics.json").read_text("utf-8"))
    assert metrics["rejected_records"] == 5
    assert json.loads(result.stdout) == metrics


def test_cli_missing_input_dir_fails(tmp_path):
    out = tmp_path / "out"
    result = run_cli("--input", str(tmp_path / "nope"), "--output", str(out))
    assert result.returncode != 0
    assert "not found" in result.stderr
    assert not out.exists()


def test_cli_requires_arguments():
    assert run_cli().returncode != 0
