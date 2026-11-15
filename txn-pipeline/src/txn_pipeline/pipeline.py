"""Ingest Kafka-style transaction events from JSON Lines files."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import IO, Iterator

from txn_pipeline.validation import REASON_CODES, Accepted, validate_line

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APPROVED_CURRENCIES_PATH = PROJECT_ROOT / "config" / "approved_currencies.json"
SCHEMA_VERSION = "1.0"

_PARTITION_RE = re.compile(r"partition-([0-9]+)\.jsonl")


def load_approved_currencies(path: Path = APPROVED_CURRENCIES_PATH) -> frozenset:
    with open(path, encoding="utf-8") as fh:
        return frozenset(json.load(fh)["approved_currencies"])


def discover_partitions(input_dir: Path) -> list[tuple[int, Path]]:
    """Return ``(N, path)`` for each partition file, in ascending numeric order."""
    partitions = []
    for path in input_dir.iterdir():
        match = _PARTITION_RE.fullmatch(path.name)
        if match and path.is_file():
            partitions.append((int(match.group(1)), path))
    partitions.sort(key=lambda item: (item[0], item[1].name))
    return partitions


def _read_lines(path: Path) -> Iterator[tuple[str, bool]]:
    """Yield ``(line, decoded_ok)`` for every non-blank line of ``path``."""
    data = path.read_bytes()
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    for raw in data.split(b"\n"):
        if raw.endswith(b"\r"):
            raw = raw[:-1]
        try:
            line, ok = raw.decode("utf-8"), True
        except UnicodeDecodeError:
            line, ok = raw.decode("utf-8", errors="replace"), False
        if line.strip() == "":
            continue
        yield line, ok


def _write_jsonl(fh: IO[str], record: dict) -> None:
    text = json.dumps(record, ensure_ascii=False)
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        text = json.dumps(record, ensure_ascii=True)
    fh.write(text + "\n")


def _empty_counts() -> dict:
    return {"input_records": 0, "valid_records": 0, "rejected_records": 0}


def run_pipeline(input_dir: str | Path, output_dir: str | Path) -> dict:
    """Process every partition file in ``input_dir`` into ``output_dir``."""
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    if not input_dir.is_dir():
        raise FileNotFoundError(f"input directory not found: {input_dir}")
    approved_currencies = load_approved_currencies()
    output_dir.mkdir(parents=True, exist_ok=True)

    metrics = {
        "schema_version": SCHEMA_VERSION,
        "input_records": 0,
        "valid_records": 0,
        "rejected_records": 0,
        "rejects_by_reason": {code: 0 for code in REASON_CODES},
        "partitions": {},
    }
    accepted_ids: set = set()

    with open(output_dir / "valid.jsonl", "w", encoding="utf-8") as valid_fh, \
            open(output_dir / "rejects.jsonl", "w", encoding="utf-8") as reject_fh:
        for partition, path in discover_partitions(input_dir):
            counts = metrics["partitions"].setdefault(str(partition), _empty_counts())
            for line, decoded_ok in _read_lines(path):
                counts["input_records"] += 1
                metrics["input_records"] += 1
                if decoded_ok:
                    result = validate_line(line, approved_currencies, accepted_ids)
                else:
                    result = None

                if isinstance(result, Accepted):
                    accepted_ids.add(result.value["transaction_id"])
                    record = dict(result.value)
                    record["source_partition"] = partition
                    record["source_offset"] = result.offset
                    _write_jsonl(valid_fh, record)
                    counts["valid_records"] += 1
                    metrics["valid_records"] += 1
                    continue

                if result is None:
                    reason_code, detail, offset = (
                        "MALFORMED_EVENT", "line is not valid UTF-8", None
                    )
                else:
                    reason_code = result.reason_code
                    detail = result.reason_detail
                    offset = result.offset
                _write_jsonl(reject_fh, {
                    "source_partition": partition,
                    "source_offset": offset,
                    "reason_code": reason_code,
                    "reason_detail": detail,
                    "raw": line,
                })
                counts["rejected_records"] += 1
                metrics["rejected_records"] += 1
                metrics["rejects_by_reason"][reason_code] += 1

    with open(output_dir / "metrics.json", "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=2)
        fh.write("\n")
    return metrics
