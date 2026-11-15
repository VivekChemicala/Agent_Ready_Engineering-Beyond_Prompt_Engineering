"""Ingest Kafka-style transaction events from JSON Lines files.

Each ``partition-<N>.jsonl`` file in the input directory is one partition;
each non-blank line is one event. Every event ends up in exactly one of
``valid.jsonl`` or ``rejects.jsonl``, and ``metrics.json`` summarises the run.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CURRENCIES_PATH = PROJECT_ROOT / "config" / "approved_currencies.json"

PARTITION_FILE = re.compile(r"^partition-(\d+)\.jsonl$")
EVENT_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")

VALID_FILE = "valid.jsonl"
REJECTS_FILE = "rejects.jsonl"
METRICS_FILE = "metrics.json"
METRICS_SCHEMA_VERSION = "1.0"

MALFORMED_EVENT = "MALFORMED_EVENT"
NULL_CUSTOMER_ID = "NULL_CUSTOMER_ID"
SCHEMA_VIOLATION = "SCHEMA_VIOLATION"
INVALID_CURRENCY = "INVALID_CURRENCY"
DUPLICATE_TRANSACTION = "DUPLICATE_TRANSACTION"

# Checks run in this order; the first failing one is the event's reason.
REASON_CODES = (
    MALFORMED_EVENT,
    NULL_CUSTOMER_ID,
    SCHEMA_VIOLATION,
    INVALID_CURRENCY,
    DUPLICATE_TRANSACTION,
)

VALUE_FIELDS = (
    "transaction_id",
    "customer_id",
    "amount",
    "currency",
    "event_time",
    "merchant_id",
)


class Rejection(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


def load_approved_currencies(path: str | Path) -> frozenset[str]:
    with open(path, encoding="utf-8") as fh:
        return frozenset(json.load(fh)["approved_currencies"])


def discover_partitions(input_dir: Path) -> list[tuple[int, Path]]:
    """Return ``(partition, path)`` pairs sorted by partition number."""
    if not input_dir.exists():
        raise FileNotFoundError(f"input directory not found: {input_dir}")
    if not input_dir.is_dir():
        raise NotADirectoryError(f"input path is not a directory: {input_dir}")
    found = []
    for path in input_dir.iterdir():
        match = PARTITION_FILE.match(path.name)
        if match and path.is_file():
            found.append((int(match.group(1)), path))
    return sorted(found)


def parse_event(raw: str | bytes) -> dict:
    """Parse one line as a JSON object, rejecting anything else as malformed."""
    if isinstance(raw, bytes):
        raise Rejection(MALFORMED_EVENT, "line is not valid UTF-8")
    try:
        event = json.loads(raw, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as exc:
        raise Rejection(MALFORMED_EVENT, f"line is not valid JSON: {exc}") from None
    if not isinstance(event, dict):
        raise Rejection(
            MALFORMED_EVENT,
            f"event must be a JSON object, got {_type_name(event)}",
        )
    if read_offset(event) is None:
        raise Rejection(MALFORMED_EVENT, "offset must be a non-negative integer")
    return event


def read_offset(event: Any) -> int | None:
    offset = event.get("offset") if isinstance(event, dict) else None
    return offset if _is_int(offset) and offset >= 0 else None


def check_customer_id(event: dict) -> None:
    value = event.get("value")
    if not isinstance(value, dict):
        return
    if "customer_id" not in value:
        raise Rejection(NULL_CUSTOMER_ID, "customer_id is missing")
    customer_id = value["customer_id"]
    if customer_id is None:
        raise Rejection(NULL_CUSTOMER_ID, "customer_id is null")
    if isinstance(customer_id, str) and not customer_id.strip():
        raise Rejection(NULL_CUSTOMER_ID, "customer_id is blank")


def check_schema(event: dict) -> None:
    if "key" in event and not (event["key"] is None or isinstance(event["key"], str)):
        _schema_error("key must be a string or null")
    if "timestamp" in event and not _is_int(event["timestamp"]):
        _schema_error("timestamp must be an integer")
    if "value" not in event:
        _schema_error("value is required")
    value = event["value"]
    if not isinstance(value, dict):
        _schema_error(f"value must be an object, got {_type_name(value)}")
    for name in VALUE_FIELDS:
        if name not in value:
            _schema_error(f"value.{name} is required")
    for name in ("transaction_id", "customer_id", "merchant_id"):
        if not isinstance(value[name], str) or not value[name]:
            _schema_error(f"value.{name} must be a non-empty string")
    amount = value["amount"]
    if not _is_number(amount):
        _schema_error(f"value.amount must be a number, got {_type_name(amount)}")
    if not _is_finite(amount):
        _schema_error("value.amount must be finite")
    if not amount > 0:
        _schema_error("value.amount must be greater than 0")
    if not isinstance(value["currency"], str):
        _schema_error("value.currency must be a string")
    if not is_valid_event_time(value["event_time"]):
        _schema_error(
            "value.event_time must be YYYY-MM-DDTHH:MM:SS[.ffffff]Z and a real date"
        )


def check_currency(event: dict, approved_currencies: frozenset[str]) -> None:
    currency = event["value"]["currency"]
    if currency not in approved_currencies:
        raise Rejection(
            INVALID_CURRENCY, f"currency {currency!r} is not in the approved set"
        )


def is_valid_event_time(value: Any) -> bool:
    if not isinstance(value, str) or not EVENT_TIME.match(value):
        return False
    try:
        datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return False
    return True


def run_pipeline(
    input_dir: str | Path,
    output_dir: str | Path,
    *,
    currencies_path: str | Path | None = None,
) -> dict:
    """Process every partition file in ``input_dir`` into ``output_dir``."""
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    approved_currencies = load_approved_currencies(
        DEFAULT_CURRENCIES_PATH if currencies_path is None else currencies_path
    )
    partitions = discover_partitions(input_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    accepted_ids: dict[str, tuple[int, int]] = {}
    rejects_by_reason = {code: 0 for code in REASON_CODES}
    partition_metrics: dict[str, dict] = {}

    with open(output_dir / VALID_FILE, "w", encoding="utf-8") as valid_out, open(
        output_dir / REJECTS_FILE, "w", encoding="utf-8"
    ) as rejects_out:
        for partition, path in partitions:
            counts = {"input_records": 0, "valid_records": 0, "rejected_records": 0}
            partition_metrics[str(partition)] = counts
            for raw in _read_events(path):
                counts["input_records"] += 1
                event = None
                try:
                    event = parse_event(raw)
                    check_customer_id(event)
                    check_schema(event)
                    check_currency(event, approved_currencies)
                    value = event["value"]
                    first = accepted_ids.get(value["transaction_id"])
                    if first is not None:
                        raise Rejection(
                            DUPLICATE_TRANSACTION,
                            f"transaction_id {value['transaction_id']!r} already "
                            f"accepted at partition {first[0]} offset {first[1]}",
                        )
                except Rejection as rejection:
                    counts["rejected_records"] += 1
                    rejects_by_reason[rejection.code] += 1
                    _write(
                        rejects_out,
                        {
                            "source_partition": partition,
                            "source_offset": read_offset(event),
                            "reason_code": rejection.code,
                            "reason_detail": rejection.detail,
                            "raw": _raw_text(raw),
                        },
                    )
                    continue

                accepted_ids[value["transaction_id"]] = (partition, event["offset"])
                counts["valid_records"] += 1
                _write(
                    valid_out,
                    {
                        **{name: value[name] for name in VALUE_FIELDS},
                        "source_partition": partition,
                        "source_offset": event["offset"],
                    },
                )

    metrics = {
        "schema_version": METRICS_SCHEMA_VERSION,
        "input_records": sum(p["input_records"] for p in partition_metrics.values()),
        "valid_records": sum(p["valid_records"] for p in partition_metrics.values()),
        "rejected_records": sum(
            p["rejected_records"] for p in partition_metrics.values()
        ),
        "rejects_by_reason": rejects_by_reason,
        "partitions": partition_metrics,
    }
    with open(output_dir / METRICS_FILE, "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=2)
        fh.write("\n")
    return metrics


def _read_events(path: Path) -> Iterator[str | bytes]:
    """Yield non-blank lines (without the terminator) in file order.

    Lines that are not valid UTF-8 are yielded as ``bytes`` so they can be
    rejected as malformed instead of aborting the run.
    """
    with open(path, "rb") as fh:
        for line in fh:
            data = line.rstrip(b"\r\n")
            try:
                raw = data.decode("utf-8")
            except UnicodeDecodeError:
                yield data
                continue
            if raw.strip():
                yield raw


def _raw_text(raw: str | bytes) -> str:
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return raw


def _reject_constant(name: str) -> None:
    raise ValueError(f"{name} is not a valid JSON value")


def _schema_error(detail: str) -> None:
    raise Rejection(SCHEMA_VIOLATION, detail)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_finite(value: int | float) -> bool:
    return isinstance(value, int) or math.isfinite(value)


def _type_name(value: Any) -> str:
    names = {dict: "object", list: "array", str: "string", bool: "boolean"}
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return names.get(type(value), type(value).__name__)


def _write(fh, record: dict) -> None:
    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
