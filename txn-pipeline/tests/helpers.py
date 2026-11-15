import json
from pathlib import Path

from txn_pipeline import run_pipeline


def event(**overrides):
    value = {
        "transaction_id": "txn-1",
        "customer_id": "cust-1",
        "amount": 10.5,
        "currency": "USD",
        "event_time": "2026-11-01T10:00:00Z",
        "merchant_id": "merch-1",
    }
    value.update(overrides)
    return {k: v for k, v in value.items() if v is not _MISSING}


class _Missing:
    pass


_MISSING = _Missing()
MISSING = _MISSING


def message(offset, value, key="k"):
    return json.dumps(
        {"offset": offset, "key": key, "timestamp": 1, "value": value}
    )


def write_partition(input_dir: Path, n, lines):
    input_dir.mkdir(parents=True, exist_ok=True)
    path = input_dir / f"partition-{n}.jsonl"
    path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return path


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def run(tmp_path, partitions):
    """``partitions`` maps partition number to a list of raw lines."""
    input_dir = tmp_path / "input"
    input_dir.mkdir(exist_ok=True)
    for n, lines in partitions.items():
        write_partition(input_dir, n, lines)
    out = tmp_path / "out"
    metrics = run_pipeline(input_dir, out)
    return metrics, read_jsonl(out / "valid.jsonl"), read_jsonl(out / "rejects.jsonl")


def reasons(rejects):
    return [r["reason_code"] for r in rejects]
