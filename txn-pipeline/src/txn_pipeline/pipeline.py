"""Ingest Kafka-style transaction events from JSON Lines files.

Each ``partition-<N>.jsonl`` file in the input directory is one partition and
each line is one message.  Messages are validated in a deterministic order
(partitions by ascending ``N``, then by line) and routed either to
``valid.jsonl`` or ``rejects.jsonl``; ``metrics.json`` summarises the run.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

DEFAULT_CURRENCIES_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "approved_currencies.json"
)
PARTITION_FILE_RE = re.compile(r"^partition-(\d+)\.jsonl$")

VALID_FILE = "valid.jsonl"
REJECTS_FILE = "rejects.jsonl"
METRICS_FILE = "metrics.json"

# Reject reason codes (the first failing check determines a record's reason).
MALFORMED_JSON = "malformed_json"
SCHEMA_VIOLATION = "schema_violation"
NULL_CUSTOMER_ID = "null_customer_id"
UNAPPROVED_CURRENCY = "unapproved_currency"
DUPLICATE_TRANSACTION_ID = "duplicate_transaction_id"
REJECT_REASONS = (
    MALFORMED_JSON,
    SCHEMA_VIOLATION,
    NULL_CUSTOMER_ID,
    UNAPPROVED_CURRENCY,
    DUPLICATE_TRANSACTION_ID,
)

VALUE_REQUIRED_FIELDS = (
    "transaction_id",
    "customer_id",
    "amount",
    "currency",
    "event_time",
    "merchant_id",
)
NON_EMPTY_STRING_FIELDS = ("transaction_id", "customer_id", "merchant_id")


def load_approved_currencies(path: str | Path = DEFAULT_CURRENCIES_PATH) -> frozenset:
    with open(path, encoding="utf-8") as fh:
        return frozenset(json.load(fh)["approved_currencies"])


def discover_partitions(input_dir: Path) -> list[tuple[int, Path]]:
    """Return ``(partition, path)`` pairs sorted by partition number."""
    found = []
    for path in input_dir.iterdir():
        match = PARTITION_FILE_RE.match(path.name)
        if match and path.is_file():
            found.append((int(match.group(1)), path))
    return sorted(found)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_rfc3339(value: str) -> bool:
    if "T" not in value and "t" not in value:
        return False
    text = value[:-1] + "+00:00" if value[-1:] in ("Z", "z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def schema_errors(message: Any) -> list[str]:
    """Check ``message`` against ``schemas/transaction_event.schema.json``.

    A null ``customer_id`` is not reported here; it has its own reject reason.
    """
    if not isinstance(message, dict):
        return ["message: expected object"]
    errors = []
    if "offset" not in message:
        errors.append("offset: required")
    elif not _is_int(message["offset"]) or message["offset"] < 0:
        errors.append("offset: expected integer >= 0")
    key = message.get("key")
    if key is not None and not isinstance(key, str):
        errors.append("key: expected string or null")
    if "timestamp" in message and not _is_int(message["timestamp"]):
        errors.append("timestamp: expected integer")
    if "value" not in message:
        errors.append("value: required")
        return errors
    value = message["value"]
    if not isinstance(value, dict):
        errors.append("value: expected object")
        return errors

    for field in VALUE_REQUIRED_FIELDS:
        if field not in value:
            errors.append(f"value.{field}: required")
    for field in NON_EMPTY_STRING_FIELDS:
        if field not in value or (field == "customer_id" and value[field] is None):
            continue
        if not isinstance(value[field], str) or not value[field]:
            errors.append(f"value.{field}: expected non-empty string")
    if "amount" in value:
        amount = value["amount"]
        if not _is_number(amount) or not math.isfinite(amount) or amount <= 0:
            errors.append("value.amount: expected finite number > 0")
    if "currency" in value and not isinstance(value["currency"], str):
        errors.append("value.currency: expected string")
    if "event_time" in value:
        event_time = value["event_time"]
        if not isinstance(event_time, str) or not _is_rfc3339(event_time):
            errors.append("value.event_time: expected RFC 3339 date-time")
    return errors


def _reject_constant(name: str) -> None:
    raise ValueError(f"non-standard JSON constant {name}")


def _parse_line(raw: bytes) -> tuple[Any, str | None]:
    try:
        return json.loads(raw.decode("utf-8"), parse_constant=_reject_constant), None
    except (UnicodeDecodeError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


class _Validator:
    def __init__(self, approved_currencies: Iterable[str]):
        self.approved_currencies = frozenset(approved_currencies)
        self.accepted_ids: set[str] = set()

    def check(self, message: Any) -> tuple[str | None, list[str]]:
        """Return ``(reason, errors)``; ``reason`` is ``None`` if valid."""
        errors = schema_errors(message)
        if errors:
            return SCHEMA_VIOLATION, errors
        value = message["value"]
        if value["customer_id"] is None:
            return NULL_CUSTOMER_ID, ["value.customer_id: must not be null"]
        if value["currency"] not in self.approved_currencies:
            return UNAPPROVED_CURRENCY, [
                f"value.currency: {value['currency']!r} is not approved"
            ]
        if value["transaction_id"] in self.accepted_ids:
            return DUPLICATE_TRANSACTION_ID, [
                f"value.transaction_id: {value['transaction_id']!r} already accepted"
            ]
        self.accepted_ids.add(value["transaction_id"])
        return None, []


def _new_counts() -> dict:
    return {"records_read": 0, "valid": 0, "rejected": 0, "blank_lines_skipped": 0}


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
    validator = _Validator(approved_currencies)
    partitions = discover_partitions(input_dir)

    totals = _new_counts()
    per_partition: dict[str, dict] = {}
    reasons: Counter = Counter()

    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_dir / VALID_FILE, "w", encoding="utf-8") as valid_out, open(
        output_dir / REJECTS_FILE, "w", encoding="utf-8"
    ) as rejects_out:
        for partition, path in partitions:
            counts = per_partition[str(partition)] = _new_counts()
            with open(path, "rb") as fh:
                for line_number, raw in enumerate(fh, start=1):
                    raw = raw.rstrip(b"\r\n")
                    if not raw.strip():
                        counts["blank_lines_skipped"] += 1
                        continue
                    counts["records_read"] += 1
                    source = {
                        "partition": partition,
                        "file": path.name,
                        "line": line_number,
                    }
                    message, parse_error = _parse_line(raw)
                    if parse_error is not None:
                        reason, errors = MALFORMED_JSON, [parse_error]
                    else:
                        reason, errors = validator.check(message)

                    if reason is None:
                        counts["valid"] += 1
                        record = {
                            **message["value"],
                            "_source": {
                                **source,
                                "offset": message["offset"],
                                "key": message.get("key"),
                                "timestamp": message.get("timestamp"),
                            },
                        }
                        valid_out.write(json.dumps(record, sort_keys=True) + "\n")
                        continue

                    counts["rejected"] += 1
                    reasons[reason] += 1
                    reject = {"reason": reason, "errors": errors, "source": source}
                    if parse_error is None:
                        reject["message"] = message
                    else:
                        reject["raw"] = raw.decode("utf-8", errors="replace")
                    rejects_out.write(json.dumps(reject, sort_keys=True) + "\n")

            for key in totals:
                totals[key] += counts[key]

    metrics = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "partitions_processed": len(partitions),
        **totals,
        "rejects_by_reason": {reason: reasons[reason] for reason in REJECT_REASONS},
        "per_partition": per_partition,
        "approved_currencies": sorted(validator.approved_currencies),
    }
    with open(output_dir / METRICS_FILE, "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return metrics
