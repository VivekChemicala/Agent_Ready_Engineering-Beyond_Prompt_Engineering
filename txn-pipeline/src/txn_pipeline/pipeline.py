"""Ingest Kafka-style transaction events from JSON Lines files."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CURRENCIES_PATH = PROJECT_ROOT / "config" / "approved_currencies.json"

SCHEMA_VERSION = "1.0"

MALFORMED_EVENT = "MALFORMED_EVENT"
NULL_CUSTOMER_ID = "NULL_CUSTOMER_ID"
SCHEMA_VIOLATION = "SCHEMA_VIOLATION"
INVALID_CURRENCY = "INVALID_CURRENCY"
DUPLICATE_TRANSACTION = "DUPLICATE_TRANSACTION"
REASON_CODES = (
    MALFORMED_EVENT,
    NULL_CUSTOMER_ID,
    SCHEMA_VIOLATION,
    INVALID_CURRENCY,
    DUPLICATE_TRANSACTION,
)

VALID_FIELDS = (
    "transaction_id",
    "customer_id",
    "amount",
    "currency",
    "event_time",
    "merchant_id",
)

_PARTITION_RE = re.compile(r"partition-([0-9]+)\.jsonl")
_EVENT_TIME_RE = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})"
    r"(?:\.[0-9]{1,6})?Z"
)


class Rejection(Exception):
    """Raised by validation to reject an event with a reason code."""

    def __init__(self, reason_code: str, reason_detail: str) -> None:
        super().__init__(reason_detail)
        self.reason_code = reason_code
        self.reason_detail = reason_detail


def load_approved_currencies(path: Path = CURRENCIES_PATH) -> frozenset[str]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    currencies = data["approved_currencies"]
    if not isinstance(currencies, list) or not all(
        isinstance(c, str) for c in currencies
    ):
        raise ValueError(f"{path}: approved_currencies must be a list of strings")
    return frozenset(currencies)


def discover_partitions(input_dir: Path) -> list[tuple[int, Path]]:
    """Return ``(partition, path)`` pairs in ascending numeric order."""
    found = []
    for path in input_dir.iterdir():
        match = _PARTITION_RE.fullmatch(path.name)
        if match and path.is_file():
            found.append((int(match.group(1)), path))
    found.sort(key=lambda item: (item[0], item[1].name))
    return found


def iter_lines(path: Path) -> Iterator[str]:
    """Yield non-blank lines of ``path`` without their line terminator."""
    with open(path, "rb") as fh:
        for raw in fh:
            line = raw.decode("utf-8", errors="replace")
            if line.endswith("\n"):
                line = line[:-1]
            if line.endswith("\r"):
                line = line[:-1]
            if line.strip():
                yield line


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_non_blank_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_valid_amount(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(value, float) and not math.isfinite(value):
        return False
    return value > 0


def _is_valid_event_time(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    match = _EVENT_TIME_RE.fullmatch(value)
    if not match:
        return False
    try:
        datetime(*(int(part) for part in match.groups()))
    except ValueError:
        return False
    return True


def parse_message(line: str) -> tuple[int | None, dict | None, Rejection | None]:
    """Parse a message line into ``(offset, value, rejection)``."""
    try:
        message = json.loads(line)
    except (ValueError, RecursionError):
        return None, None, Rejection(MALFORMED_EVENT, "line is not valid JSON")
    if not isinstance(message, dict):
        return None, None, Rejection(MALFORMED_EVENT, "message is not a JSON object")
    offset = message.get("offset")
    if not _is_int(offset) or offset < 0:
        return None, None, Rejection(
            MALFORMED_EVENT, "offset is missing or not a non-negative integer"
        )
    value = message.get("value")
    if not isinstance(value, dict):
        return offset, None, Rejection(
            MALFORMED_EVENT, "value is missing or not a JSON object"
        )
    return offset, value, None


def validate_value(value: dict, approved_currencies: frozenset[str]) -> None:
    """Apply checks 2-4; raise :class:`Rejection` on the first failure."""
    customer_id = value.get("customer_id")
    blank = isinstance(customer_id, str) and not customer_id.strip()
    if customer_id is None or blank:
        raise Rejection(NULL_CUSTOMER_ID, "customer_id is missing, null or blank")

    problems = []
    if not isinstance(customer_id, str):
        problems.append("customer_id must be a string")
    for field in ("transaction_id", "merchant_id"):
        if field not in value:
            problems.append(f"{field} is missing")
        elif not _is_non_blank_str(value[field]):
            problems.append(f"{field} must be a non-blank string")
    if "amount" not in value:
        problems.append("amount is missing")
    elif not _is_valid_amount(value["amount"]):
        problems.append("amount must be a finite number > 0")
    if "currency" not in value:
        problems.append("currency is missing")
    elif not isinstance(value["currency"], str):
        problems.append("currency must be a string")
    if "event_time" not in value:
        problems.append("event_time is missing")
    elif not _is_valid_event_time(value["event_time"]):
        problems.append("event_time must be a UTC datetime YYYY-MM-DDTHH:MM:SS[.f]Z")
    if problems:
        raise Rejection(SCHEMA_VIOLATION, "; ".join(problems))

    if value["currency"] not in approved_currencies:
        raise Rejection(
            INVALID_CURRENCY, f"currency {value['currency']!r} is not approved"
        )


def _empty_counts() -> dict:
    return {"input_records": 0, "valid_records": 0, "rejected_records": 0}


def _dump(record: dict) -> str:
    return json.dumps(record) + "\n"


def run_pipeline(input_dir: str | Path, output_dir: str | Path) -> dict:
    """Process every partition file in ``input_dir`` into ``output_dir``."""
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    if not input_dir.is_dir():
        raise FileNotFoundError(f"input directory not found: {input_dir}")
    approved_currencies = load_approved_currencies()
    partitions = discover_partitions(input_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    metrics = {
        "schema_version": SCHEMA_VERSION,
        "input_records": 0,
        "valid_records": 0,
        "rejected_records": 0,
        "rejects_by_reason": {code: 0 for code in REASON_CODES},
        "partitions": {},
    }
    accepted_ids: set[str] = set()

    with open(output_dir / "valid.jsonl", "w", encoding="utf-8") as valid_fh, open(
        output_dir / "rejects.jsonl", "w", encoding="utf-8"
    ) as rejects_fh:
        for partition, path in partitions:
            counts = metrics["partitions"].setdefault(str(partition), _empty_counts())
            for line in iter_lines(path):
                counts["input_records"] += 1
                metrics["input_records"] += 1
                offset, value, rejection = parse_message(line)
                if rejection is None:
                    try:
                        validate_value(value, approved_currencies)
                        if value["transaction_id"] in accepted_ids:
                            raise Rejection(
                                DUPLICATE_TRANSACTION,
                                f"transaction_id {value['transaction_id']!r} "
                                "was already accepted",
                            )
                    except Rejection as exc:
                        rejection = exc

                if rejection is None:
                    accepted_ids.add(value["transaction_id"])
                    record = {field: value[field] for field in VALID_FIELDS}
                    record["source_partition"] = partition
                    record["source_offset"] = offset
                    valid_fh.write(_dump(record))
                    counts["valid_records"] += 1
                    metrics["valid_records"] += 1
                else:
                    rejects_fh.write(
                        _dump(
                            {
                                "source_partition": partition,
                                "source_offset": offset,
                                "reason_code": rejection.reason_code,
                                "reason_detail": rejection.reason_detail,
                                "raw": line,
                            }
                        )
                    )
                    counts["rejected_records"] += 1
                    metrics["rejected_records"] += 1
                    metrics["rejects_by_reason"][rejection.reason_code] += 1

    with open(output_dir / "metrics.json", "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=2)
        fh.write("\n")
    return metrics
