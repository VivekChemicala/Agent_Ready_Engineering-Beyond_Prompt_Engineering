from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CURRENCY_FILE = PROJECT_ROOT / "config" / "approved_currencies.json"
PARTITION_FILE = re.compile(r"partition-(\d+)\.jsonl")
EVENT_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z")
REASONS = ("MALFORMED_EVENT", "NULL_CUSTOMER_ID", "SCHEMA_VIOLATION",
           "INVALID_CURRENCY", "DUPLICATE_TRANSACTION")
FIELDS = ("transaction_id", "customer_id", "amount", "currency", "event_time",
          "merchant_id")


class Reject(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code, self.detail = code, detail


def _approved() -> frozenset:
    return frozenset(json.loads(CURRENCY_FILE.read_text())["approved_currencies"])


def _partitions(input_dir: Path) -> list[tuple[int, Path]]:
    found = []
    for path in input_dir.iterdir():
        m = PARTITION_FILE.fullmatch(path.name)
        if m and path.is_file():
            found.append((int(m.group(1)), path))
    return sorted(found)


def _nonblank(v) -> bool:
    return isinstance(v, str) and v.strip() != ""


def _valid_time(v) -> bool:
    if not isinstance(v, str) or not EVENT_TIME.fullmatch(v):
        return False
    try:
        datetime.strptime(v[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return False
    return True


def _parse(line: str) -> tuple[int | None, dict]:
    try:
        msg = json.loads(line)
    except ValueError:
        raise Reject("MALFORMED_EVENT", "line is not valid JSON")
    if not isinstance(msg, dict):
        raise Reject("MALFORMED_EVENT", "message is not a JSON object")
    offset = msg.get("offset")
    ok_offset = isinstance(offset, int) and not isinstance(offset, bool)
    if not ok_offset or offset < 0:
        raise Reject("MALFORMED_EVENT", "offset is not a non-negative integer")
    if not isinstance(msg.get("value"), dict):
        raise Reject("MALFORMED_EVENT", "value is not an object")
    return offset, msg["value"]


def _check(value: dict, approved: frozenset) -> None:
    cust = value.get("customer_id")
    if cust is None or (isinstance(cust, str) and not cust.strip()):
        raise Reject("NULL_CUSTOMER_ID", "customer_id is missing, null or blank")
    if not isinstance(cust, str):
        raise Reject("SCHEMA_VIOLATION", "customer_id must be a string")
    for name in ("transaction_id", "merchant_id"):
        if not _nonblank(value.get(name)):
            raise Reject("SCHEMA_VIOLATION", f"{name} must be a non-blank string")
    amount = value.get("amount")
    if (isinstance(amount, bool) or not isinstance(amount, (int, float))
            or (isinstance(amount, float) and not math.isfinite(amount))
            or amount <= 0):
        raise Reject("SCHEMA_VIOLATION", "amount must be a finite number > 0")
    if not isinstance(value.get("currency"), str):
        raise Reject("SCHEMA_VIOLATION", "currency must be a string")
    if not _valid_time(value.get("event_time")):
        raise Reject("SCHEMA_VIOLATION", "event_time must be YYYY-MM-DDTHH:MM:SSZ")
    if value["currency"] not in approved:
        raise Reject("INVALID_CURRENCY", f"currency {value['currency']!r} "
                     "is not approved")


def _offset_of(line: str):
    try:
        msg = json.loads(line)
    except ValueError:
        return None
    off = msg.get("offset") if isinstance(msg, dict) else None
    if isinstance(off, int) and not isinstance(off, bool) and off >= 0:
        return off
    return None


def run_pipeline(input_dir, output_dir) -> dict:
    input_dir, output_dir = Path(input_dir), Path(output_dir)
    approved = _approved()
    metrics = {"schema_version": "1.0", "input_records": 0, "valid_records": 0,
               "rejected_records": 0,
               "rejects_by_reason": {r: 0 for r in REASONS}, "partitions": {}}
    valid, rejects, accepted_ids = [], [], set()
    for partition, path in _partitions(input_dir):
        part = metrics["partitions"].setdefault(
            str(partition),
            {"input_records": 0, "valid_records": 0, "rejected_records": 0})
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            metrics["input_records"] += 1
            part["input_records"] += 1
            try:
                offset, value = _parse(line)
                _check(value, approved)
                if value["transaction_id"] in accepted_ids:
                    raise Reject("DUPLICATE_TRANSACTION",
                                 "transaction_id already accepted")
            except Reject as rej:
                rejects.append({"source_partition": partition,
                                "source_offset": _offset_of(line),
                                "reason_code": rej.code,
                                "reason_detail": rej.detail, "raw": line})
                metrics["rejected_records"] += 1
                metrics["rejects_by_reason"][rej.code] += 1
                part["rejected_records"] += 1
                continue
            accepted_ids.add(value["transaction_id"])
            valid.append({**{f: value[f] for f in FIELDS},
                          "source_partition": partition, "source_offset": offset})
            metrics["valid_records"] += 1
            part["valid_records"] += 1
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, rows in (("valid.jsonl", valid), ("rejects.jsonl", rejects)):
        with open(output_dir / name, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")
    (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    return metrics
