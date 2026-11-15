"""Ingest Kafka-style transaction events from JSON Lines files.

Each ``partition-<N>.jsonl`` file in the input directory is one partition and
each line is one message.  Partitions are processed in ascending ``N`` and
lines in file order; every event is routed to ``valid.jsonl`` or
``rejects.jsonl`` and ``metrics.json`` summarises the run.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

DEFAULT_CURRENCIES_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "approved_currencies.json"
)
PARTITION_FILE_RE = re.compile(r"partition-([0-9]+)\.jsonl")
EVENT_TIME_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
                           r"(\.[0-9]{1,6})?Z")

VALID_FILE = "valid.jsonl"
REJECTS_FILE = "rejects.jsonl"
METRICS_FILE = "metrics.json"
METRICS_SCHEMA_VERSION = "1.0"

# Reject reason codes, in precedence order (the first failing check wins).
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


class Rejected(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def load_approved_currencies(path: str | Path = DEFAULT_CURRENCIES_PATH) -> frozenset:
    with open(path, encoding="utf-8") as fh:
        return frozenset(json.load(fh)["approved_currencies"])


def discover_partitions(input_dir: Path) -> list[tuple[int, Path]]:
    """Return ``(partition, path)`` pairs sorted by partition number."""
    found = []
    for path in input_dir.iterdir():
        match = PARTITION_FILE_RE.fullmatch(path.name)
        if match and path.is_file():
            found.append((int(match.group(1)), path))
    return sorted(found)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_valid_amount(value: Any) -> bool:
    if _is_int(value):
        return value > 0
    return isinstance(value, float) and math.isfinite(value) and value > 0


def _is_valid_event_time(value: Any) -> bool:
    if not isinstance(value, str) or not EVENT_TIME_RE.fullmatch(value):
        return False
    try:
        datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return False
    return True


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0


def _reject_constant(name: str) -> None:
    raise ValueError(f"non-standard JSON constant {name}")


def parse_event(raw: bytes) -> tuple[dict, int]:
    """Decode one line into ``(message, offset)`` or raise MALFORMED_EVENT."""
    try:
        message = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise Rejected(MALFORMED_EVENT, f"invalid JSON: {exc}") from None
    if not isinstance(message, dict):
        raise Rejected(MALFORMED_EVENT, "message is not a JSON object")
    offset = message.get("offset")
    if not _is_int(offset) or offset < 0:
        raise Rejected(MALFORMED_EVENT, "offset is not a non-negative integer")
    return message, offset


def check_event(message: dict, approved_currencies: frozenset,
                accepted_ids: set) -> dict:
    """Validate a parsed message and return its transaction fields."""
    value = message.get("value")
    if not isinstance(value, dict):
        raise Rejected(SCHEMA_VIOLATION, "value is not a JSON object")

    customer_id = value.get("customer_id")
    blank = isinstance(customer_id, str) and not customer_id.strip()
    if customer_id is None or blank:
        raise Rejected(NULL_CUSTOMER_ID, "customer_id is missing, null or blank")

    errors = [f"{f} is required" for f in TRANSACTION_FIELDS if f not in value]
    key = message.get("key")
    if key is not None and not isinstance(key, str):
        errors.append("key must be a string or null")
    if "timestamp" in message and not _is_int(message["timestamp"]):
        errors.append("timestamp must be an integer")
    for field in ("transaction_id", "customer_id", "merchant_id"):
        if field in value and not _non_empty_string(value[field]):
            errors.append(f"{field} must be a non-empty string")
    if "amount" in value and not _is_valid_amount(value["amount"]):
        errors.append("amount must be a finite number > 0")
    if "currency" in value and not isinstance(value["currency"], str):
        errors.append("currency must be a string")
    if "event_time" in value and not _is_valid_event_time(value["event_time"]):
        errors.append("event_time must be YYYY-MM-DDTHH:MM:SS[.ffffff]Z")
    if errors:
        raise Rejected(SCHEMA_VIOLATION, "; ".join(errors))

    if value["currency"] not in approved_currencies:
        raise Rejected(INVALID_CURRENCY, f"currency {value['currency']!r} not approved")
    if value["transaction_id"] in accepted_ids:
        raise Rejected(
            DUPLICATE_TRANSACTION,
            f"transaction_id {value['transaction_id']!r} already accepted",
        )
    return {field: value[field] for field in TRANSACTION_FIELDS}


def _counts() -> dict:
    return {"input_records": 0, "valid_records": 0, "rejected_records": 0}


def _strip_newline(raw: bytes) -> bytes:
    if raw.endswith(b"\n"):
        raw = raw[:-1]
    if raw.endswith(b"\r"):
        raw = raw[:-1]
    return raw


def _dump(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False) + "\n"


def run_pipeline(
    input_dir: str | Path,
    output_dir: str | Path,
    approved_currencies: Iterable[str] | None = None,
) -> dict:
    """Process every partition file in ``input_dir`` into ``output_dir``."""
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    if not input_dir.is_dir():
        raise FileNotFoundError(f"input directory not found: {input_dir}")
    if approved_currencies is None:
        approved_currencies = load_approved_currencies()
    approved = frozenset(approved_currencies)
    accepted_ids: set = set()

    totals = _counts()
    reasons = {code: 0 for code in REASON_CODES}
    partitions: dict[str, dict] = {}

    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_dir / VALID_FILE, "w", encoding="utf-8") as valid_out, open(
        output_dir / REJECTS_FILE, "w", encoding="utf-8"
    ) as rejects_out:
        for partition, path in discover_partitions(input_dir):
            counts = partitions[str(partition)] = _counts()
            with open(path, "rb") as fh:
                for raw in fh:
                    raw = _strip_newline(raw)
                    if not raw.strip():
                        continue
                    counts["input_records"] += 1
                    offset = None
                    try:
                        message, offset = parse_event(raw)
                        row = check_event(message, approved, accepted_ids)
                    except Rejected as rejected:
                        counts["rejected_records"] += 1
                        reasons[rejected.code] += 1
                        rejects_out.write(_dump({
                            "source_partition": partition,
                            "source_offset": offset,
                            "reason_code": rejected.code,
                            "reason_detail": rejected.detail,
                            "raw": raw.decode("utf-8", errors="replace"),
                        }))
                        continue
                    accepted_ids.add(row["transaction_id"])
                    counts["valid_records"] += 1
                    row["source_partition"] = partition
                    row["source_offset"] = offset
                    valid_out.write(_dump(row))
            for key in totals:
                totals[key] += counts[key]

    metrics = {
        "schema_version": METRICS_SCHEMA_VERSION,
        **totals,
        "rejects_by_reason": reasons,
        "partitions": partitions,
    }
    with open(output_dir / METRICS_FILE, "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=2)
        fh.write("\n")
    return metrics
