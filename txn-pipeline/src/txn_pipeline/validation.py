"""Per-event validation rules for transaction messages."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Collection

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

OUTPUT_FIELDS = (
    "transaction_id",
    "customer_id",
    "amount",
    "currency",
    "event_time",
    "merchant_id",
)

_EVENT_TIME_RE = re.compile(
    r"([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(\.[0-9]{1,6})?Z"
)


@dataclass(frozen=True)
class Rejection:
    reason_code: str
    reason_detail: str
    offset: int | None = None


@dataclass(frozen=True)
class Accepted:
    offset: int
    value: dict


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_non_blank_str(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _is_valid_event_time(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    match = _EVENT_TIME_RE.fullmatch(value)
    if match is None:
        return False
    try:
        datetime.strptime(match.group(1), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return False
    return True


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_positive_finite(value: int | float) -> bool:
    try:
        return math.isfinite(value) and value > 0
    except OverflowError:
        return value > 0


def _schema_violation(value: dict) -> str | None:
    """Return a detail message for the first invalid field, if any."""
    if not isinstance(value["customer_id"], str):
        return "customer_id must be a string"
    if "transaction_id" not in value:
        return "transaction_id is missing"
    if not _is_non_blank_str(value["transaction_id"]):
        return "transaction_id must be a non-blank string"
    if "amount" not in value:
        return "amount is missing"
    if not _is_number(value["amount"]):
        return "amount must be a JSON number"
    if not _is_positive_finite(value["amount"]):
        return "amount must be finite and greater than 0"
    if "currency" not in value:
        return "currency is missing"
    if not isinstance(value["currency"], str):
        return "currency must be a string"
    if "event_time" not in value:
        return "event_time is missing"
    if not _is_valid_event_time(value["event_time"]):
        return "event_time must be a valid UTC datetime YYYY-MM-DDTHH:MM:SS[.ffffff]Z"
    if "merchant_id" not in value:
        return "merchant_id is missing"
    if not _is_non_blank_str(value["merchant_id"]):
        return "merchant_id must be a non-blank string"
    return None


def validate_line(
    line: str,
    approved_currencies: Collection[str],
    accepted_ids: Collection[str],
) -> Accepted | Rejection:
    """Apply checks 1-5 in order and return the first failure or the event."""
    try:
        message = json.loads(line)
    except (ValueError, RecursionError):
        return Rejection(MALFORMED_EVENT, "line is not valid JSON")
    if not isinstance(message, dict):
        return Rejection(MALFORMED_EVENT, "message is not a JSON object")

    offset = message.get("offset")
    if not _is_non_negative_int(offset):
        return Rejection(MALFORMED_EVENT, "offset must be a non-negative integer")

    value = message.get("value")
    if not isinstance(value, dict):
        return Rejection(MALFORMED_EVENT, "value must be a JSON object", offset)

    customer_id = value.get("customer_id")
    if customer_id is None or (
        isinstance(customer_id, str) and customer_id.strip() == ""
    ):
        return Rejection(
            NULL_CUSTOMER_ID, "customer_id is missing, null or blank", offset
        )

    detail = _schema_violation(value)
    if detail is not None:
        return Rejection(SCHEMA_VIOLATION, detail, offset)

    currency = value["currency"]
    if currency not in approved_currencies:
        return Rejection(
            INVALID_CURRENCY, f"currency {currency!r} is not approved", offset
        )

    transaction_id = value["transaction_id"]
    if transaction_id in accepted_ids:
        return Rejection(
            DUPLICATE_TRANSACTION,
            f"transaction_id {transaction_id!r} was already accepted",
            offset,
        )

    return Accepted(offset, {field: value[field] for field in OUTPUT_FIELDS})
