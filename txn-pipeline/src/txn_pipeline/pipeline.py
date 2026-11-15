"""Ingest Kafka-style transaction events from JSON Lines files."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CURRENCIES_RELATIVE_PATH = Path("config") / "approved_currencies.json"

PARTITION_FILE_RE = re.compile(r"^partition-(\d+)\.jsonl$")
EVENT_TIME_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?Z$"
)

VALID_FILE = "valid.jsonl"
REJECTS_FILE = "rejects.jsonl"
METRICS_FILE = "metrics.json"
METRICS_SCHEMA_VERSION = "1.0"

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

TRANSACTION_FIELDS = (
    "transaction_id",
    "customer_id",
    "amount",
    "currency",
    "event_time",
    "merchant_id",
)


class RejectedEvent(Exception):
    def __init__(self, reason_code: str, reason_detail: str):
        super().__init__(reason_detail)
        self.reason_code = reason_code
        self.reason_detail = reason_detail


def load_approved_currencies(path: str | Path | None = None) -> frozenset:
    """Read the approved set; defaults to the project-root config file."""
    if path is None:
        path = PROJECT_ROOT / CURRENCIES_RELATIVE_PATH
    with open(path, encoding="utf-8") as fh:
        currencies = json.load(fh)["approved_currencies"]
    return frozenset(c for c in currencies if isinstance(c, str))


def discover_partitions(input_dir: Path) -> list[tuple[int, Path]]:
    """Return ``(partition, path)`` pairs sorted by numeric partition."""
    found = []
    for path in input_dir.iterdir():
        match = PARTITION_FILE_RE.match(path.name)
        if match and path.is_file():
            found.append((int(match.group(1)), path))
    return sorted(found, key=lambda item: (item[0], item[1].name))


def _read_lines(path: Path) -> Iterator[str | bytes]:
    """Yield lines without their line terminator; undecodable lines as bytes."""
    with open(path, "rb") as fh:
        for raw in fh:
            raw = raw.rstrip(b"\r\n")
            try:
                yield raw.decode("utf-8")
            except UnicodeDecodeError:
                yield raw


def parse_message(line: str) -> dict:
    try:
        message = json.loads(line)
    except (ValueError, RecursionError) as exc:
        raise RejectedEvent(MALFORMED_EVENT, f"invalid JSON: {exc}") from None
    if not isinstance(message, dict):
        raise RejectedEvent(
            MALFORMED_EVENT, f"message is a JSON {_type_name(message)}, not an object"
        )
    return message


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def read_offset(message: Any) -> int | None:
    if isinstance(message, dict) and _is_int(message.get("offset")):
        return message["offset"]
    return None


def _is_valid_event_time(value: str) -> bool:
    match = EVENT_TIME_RE.match(value)
    if not match:
        return False
    try:
        datetime(*(int(part) for part in match.groups()[:6]))
    except ValueError:
        return False
    return True


def _is_positive_finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if _is_int(value):
        return value > 0
    return isinstance(value, float) and math.isfinite(value) and value > 0


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0


def check_customer_id(message: dict) -> None:
    value = message.get("value")
    if not isinstance(value, dict) or "customer_id" not in value:
        return
    customer_id = value["customer_id"]
    if customer_id is None:
        raise RejectedEvent(NULL_CUSTOMER_ID, "value.customer_id is null")
    if isinstance(customer_id, str) and not customer_id.strip():
        raise RejectedEvent(NULL_CUSTOMER_ID, "value.customer_id is blank")


def schema_errors(message: dict) -> list[str]:
    """Check ``message`` against schemas/transaction_event.schema.json rules."""
    errors = []
    if "offset" not in message:
        errors.append("offset: required field missing")
    elif not _is_int(message["offset"]) or message["offset"] < 0:
        errors.append("offset: must be a non-negative integer")
    if "key" in message and not (
        message["key"] is None or isinstance(message["key"], str)
    ):
        errors.append("key: must be a string or null")
    if "timestamp" in message and not _is_int(message["timestamp"]):
        errors.append("timestamp: must be an integer")

    if "value" not in message:
        errors.append("value: required field missing")
        return errors
    value = message["value"]
    if not isinstance(value, dict):
        errors.append(f"value: must be an object, got {_type_name(value)}")
        return errors

    checks = {
        "transaction_id": (_non_empty_string, "must be a non-empty string"),
        "customer_id": (_non_empty_string, "must be a non-empty string"),
        "amount": (_is_positive_finite_number, "must be a finite number > 0"),
        "currency": (lambda v: isinstance(v, str), "must be a string"),
        "event_time": (
            lambda v: isinstance(v, str) and _is_valid_event_time(v),
            "must be a real date-time formatted YYYY-MM-DDTHH:MM:SS[.ffffff]Z",
        ),
        "merchant_id": (_non_empty_string, "must be a non-empty string"),
    }
    for name, (is_valid, message_text) in checks.items():
        if name not in value:
            errors.append(f"value.{name}: required field missing")
        elif not is_valid(value[name]):
            errors.append(f"value.{name}: {message_text}")
    return errors


def validate(
    line: str | bytes, approved_currencies: frozenset, accepted_ids: set
) -> dict:
    """Return the parsed message or raise ``RejectedEvent``.

    The first failing check wins: MALFORMED_EVENT > NULL_CUSTOMER_ID >
    SCHEMA_VIOLATION > INVALID_CURRENCY > DUPLICATE_TRANSACTION.
    """
    if isinstance(line, bytes):
        raise RejectedEvent(MALFORMED_EVENT, "line is not valid UTF-8")
    message = parse_message(line)
    check_customer_id(message)
    errors = schema_errors(message)
    if errors:
        raise RejectedEvent(SCHEMA_VIOLATION, "; ".join(errors))
    value = message["value"]
    if value["currency"] not in approved_currencies:
        raise RejectedEvent(
            INVALID_CURRENCY, f"currency {value['currency']!r} is not approved"
        )
    if value["transaction_id"] in accepted_ids:
        raise RejectedEvent(
            DUPLICATE_TRANSACTION,
            f"transaction_id {value['transaction_id']!r} was already accepted",
        )
    return message


def _try_parse(line: str | bytes) -> Any:
    if isinstance(line, bytes):
        return None
    try:
        return json.loads(line)
    except (ValueError, RecursionError):
        return None


def run_pipeline(input_dir: str | Path, output_dir: str | Path) -> dict:
    """Process every partition file in ``input_dir`` into ``output_dir``.

    Writes ``valid.jsonl``, ``rejects.jsonl`` and ``metrics.json`` and returns
    the metrics dict.
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    if not input_dir.is_dir():
        raise FileNotFoundError(f"input directory not found: {input_dir}")

    approved = load_approved_currencies()
    partitions = discover_partitions(input_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    accepted_ids: set = set()
    rejects_by_reason = {code: 0 for code in REASON_CODES}
    per_partition: dict[str, dict] = {}

    with open(output_dir / VALID_FILE, "w", encoding="utf-8") as valid_fh, open(
        output_dir / REJECTS_FILE, "w", encoding="utf-8"
    ) as rejects_fh:
        for partition, path in partitions:
            stats = per_partition.setdefault(
                str(partition),
                {"input_records": 0, "valid_records": 0, "rejected_records": 0},
            )
            for line in _read_lines(path):
                if not line.strip():
                    continue
                stats["input_records"] += 1
                try:
                    message = validate(line, approved, accepted_ids)
                except RejectedEvent as rejected:
                    raw = line
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", "replace")
                    reject = {
                        "source_partition": partition,
                        "source_offset": read_offset(_try_parse(line)),
                        "reason_code": rejected.reason_code,
                        "reason_detail": rejected.reason_detail,
                        "raw": raw,
                    }
                    rejects_fh.write(json.dumps(reject) + "\n")
                    stats["rejected_records"] += 1
                    rejects_by_reason[rejected.reason_code] += 1
                    continue

                value = message["value"]
                accepted_ids.add(value["transaction_id"])
                row = {name: value[name] for name in TRANSACTION_FIELDS}
                row["source_partition"] = partition
                row["source_offset"] = message["offset"]
                valid_fh.write(json.dumps(row) + "\n")
                stats["valid_records"] += 1

    metrics = {
        "schema_version": METRICS_SCHEMA_VERSION,
        "input_records": sum(p["input_records"] for p in per_partition.values()),
        "valid_records": sum(p["valid_records"] for p in per_partition.values()),
        "rejected_records": sum(
            p["rejected_records"] for p in per_partition.values()
        ),
        "rejects_by_reason": rejects_by_reason,
        "partitions": per_partition,
    }
    with open(output_dir / METRICS_FILE, "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=2)
        fh.write("\n")
    return metrics
