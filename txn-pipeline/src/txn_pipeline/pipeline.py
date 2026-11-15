"""Ingest Kafka-style transaction events from JSON Lines files."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from pathlib import Path

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
    r"(?:\.([0-9]{1,6}))?Z"
)


class _Rejected(Exception):
    def __init__(self, reason_code: str, detail: str,
                 offset: int | None = None) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail
        self.offset = offset


def load_approved_currencies(path: str | Path | None = None) -> frozenset:
    if path is None:
        path = CURRENCIES_PATH
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    currencies = data["approved_currencies"]
    if not isinstance(currencies, list) or not all(
        isinstance(c, str) for c in currencies
    ):
        raise ValueError(f"{path}: approved_currencies must be a list of strings")
    return frozenset(currencies)


def discover_partitions(input_dir: Path) -> list[tuple[int, Path]]:
    """Return ``(partition, path)`` pairs in ascending numeric partition order."""
    found = []
    for path in input_dir.iterdir():
        match = _PARTITION_RE.fullmatch(path.name)
        if match and path.is_file():
            found.append((int(match.group(1)), path))
    found.sort(key=lambda item: (item[0], item[1].name))
    return found


def _iter_lines(path: Path):
    """Yield ``(raw_text, decode_ok)`` for each non-blank line of ``path``."""
    with open(path, "rb") as fh:
        for raw_bytes in fh:
            if raw_bytes.endswith(b"\n"):
                raw_bytes = raw_bytes[:-1]
                if raw_bytes.endswith(b"\r"):
                    raw_bytes = raw_bytes[:-1]
            try:
                text = raw_bytes.decode("utf-8")
                ok = True
            except UnicodeDecodeError:
                text = raw_bytes.decode("utf-8", errors="replace")
                ok = False
            if not text.strip():
                continue
            yield text, ok


def _is_non_blank_str(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _is_valid_offset(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_valid_amount(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(value, float) and not math.isfinite(value):
        return False
    return value > 0


def _is_valid_event_time(value) -> bool:
    if not isinstance(value, str):
        return False
    match = _EVENT_TIME_RE.fullmatch(value)
    if not match:
        return False
    year, month, day, hour, minute, second = (int(g) for g in match.groups()[:6])
    try:
        datetime(year, month, day, hour, minute, second)
    except ValueError:
        return False
    return True


def _parse_message(text: str, decode_ok: bool) -> tuple[int | None, dict]:
    """Return ``(offset, value)`` or raise ``_Rejected`` (MALFORMED_EVENT)."""
    if not decode_ok:
        raise _Rejected(MALFORMED_EVENT, "line is not valid UTF-8")
    try:
        message = json.loads(text)
    except (ValueError, RecursionError):
        raise _Rejected(MALFORMED_EVENT, "line is not valid JSON") from None
    if not isinstance(message, dict):
        raise _Rejected(MALFORMED_EVENT, "message is not a JSON object")
    offset = message.get("offset")
    if not _is_valid_offset(offset):
        raise _Rejected(MALFORMED_EVENT, "offset is not a non-negative integer")
    value = message.get("value")
    if not isinstance(value, dict):
        raise _Rejected(MALFORMED_EVENT, "value is not a JSON object", offset)
    return offset, value


def _validate_value(value: dict, approved_currencies: frozenset) -> None:
    customer_id = value.get("customer_id")
    if customer_id is None or (
        isinstance(customer_id, str) and not customer_id.strip()
    ):
        raise _Rejected(NULL_CUSTOMER_ID, "customer_id is missing, null or blank")
    if not isinstance(customer_id, str):
        raise _Rejected(SCHEMA_VIOLATION, "customer_id is not a string")

    for field in ("transaction_id", "amount", "currency", "event_time",
                  "merchant_id"):
        if field not in value:
            raise _Rejected(SCHEMA_VIOLATION, f"{field} is missing")
    if not _is_non_blank_str(value["transaction_id"]):
        raise _Rejected(SCHEMA_VIOLATION, "transaction_id is not a non-blank string")
    if not _is_valid_amount(value["amount"]):
        raise _Rejected(SCHEMA_VIOLATION, "amount is not a finite number > 0")
    if not isinstance(value["currency"], str):
        raise _Rejected(SCHEMA_VIOLATION, "currency is not a string")
    if not _is_valid_event_time(value["event_time"]):
        raise _Rejected(
            SCHEMA_VIOLATION,
            "event_time is not a valid YYYY-MM-DDTHH:MM:SS[.ffffff]Z datetime",
        )
    if not _is_non_blank_str(value["merchant_id"]):
        raise _Rejected(SCHEMA_VIOLATION, "merchant_id is not a non-blank string")

    if value["currency"] not in approved_currencies:
        raise _Rejected(
            INVALID_CURRENCY,
            f"currency {value['currency']!r} is not in the approved list",
        )


def _new_counts() -> dict:
    return {"input_records": 0, "valid_records": 0, "rejected_records": 0}


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=True)


def run_pipeline(input_dir: str | Path, output_dir: str | Path) -> dict:
    """Process every partition file in ``input_dir`` into ``output_dir``."""
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    if not input_dir.is_dir():
        raise FileNotFoundError(f"input directory not found: {input_dir}")
    approved_currencies = load_approved_currencies()
    partitions = discover_partitions(input_dir)

    metrics = {
        "schema_version": SCHEMA_VERSION,
        "input_records": 0,
        "valid_records": 0,
        "rejected_records": 0,
        "rejects_by_reason": {code: 0 for code in REASON_CODES},
        "partitions": {},
    }
    accepted_ids: set = set()

    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_dir / "valid.jsonl", "w", encoding="utf-8",
              newline="\n") as valid_fh, \
            open(output_dir / "rejects.jsonl", "w", encoding="utf-8",
                 newline="\n") as rejects_fh:
        for partition, path in partitions:
            counts = metrics["partitions"].setdefault(str(partition), _new_counts())
            for text, decode_ok in _iter_lines(path):
                counts["input_records"] += 1
                metrics["input_records"] += 1
                offset = None
                try:
                    offset, value = _parse_message(text, decode_ok)
                    _validate_value(value, approved_currencies)
                    if value["transaction_id"] in accepted_ids:
                        raise _Rejected(
                            DUPLICATE_TRANSACTION,
                            f"transaction_id {value['transaction_id']!r} "
                            "was already accepted",
                        )
                except _Rejected as err:
                    counts["rejected_records"] += 1
                    metrics["rejected_records"] += 1
                    metrics["rejects_by_reason"][err.reason_code] += 1
                    rejects_fh.write(_dumps({
                        "source_partition": partition,
                        "source_offset": offset if offset is not None
                        else err.offset,
                        "reason_code": err.reason_code,
                        "reason_detail": err.detail,
                        "raw": text,
                    }) + "\n")
                    continue

                accepted_ids.add(value["transaction_id"])
                counts["valid_records"] += 1
                metrics["valid_records"] += 1
                record = {field: value[field] for field in VALID_FIELDS}
                record["source_partition"] = partition
                record["source_offset"] = offset
                valid_fh.write(_dumps(record) + "\n")

    with open(output_dir / "metrics.json", "w", encoding="utf-8",
              newline="\n") as fh:
        json.dump(metrics, fh, indent=2)
        fh.write("\n")
    return metrics
