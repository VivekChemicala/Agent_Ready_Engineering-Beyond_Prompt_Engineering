"""Ingest Kafka-style transaction events from JSON Lines files."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "transaction_event.schema.json"
DEFAULT_CURRENCIES_PATH = PROJECT_ROOT / "config" / "approved_currencies.json"

PARTITION_FILE_RE = re.compile(r"^partition-(\d+)\.jsonl$")

VALID_FILE = "valid.jsonl"
REJECTS_FILE = "rejects.jsonl"
METRICS_FILE = "metrics.json"

REASON_MALFORMED_JSON = "malformed_json"
REASON_SCHEMA = "schema_violation"
REASON_NULL_CUSTOMER = "null_customer_id"
REASON_CURRENCY = "unapproved_currency"
REASON_DUPLICATE = "duplicate_transaction_id"

_JSON_TYPES = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def load_schema(path: str | Path = DEFAULT_SCHEMA_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_approved_currencies(path: str | Path = DEFAULT_CURRENCIES_PATH) -> frozenset:
    with open(path, encoding="utf-8") as fh:
        return frozenset(json.load(fh)["approved_currencies"])


def _is_datetime(value: str) -> bool:
    """RFC 3339 date-time: ISO 8601 with a 'T' separator and a UTC offset."""
    if "T" not in value and "t" not in value:
        return False
    text = value[:-1] + "+00:00" if value[-1:] in ("Z", "z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def validate_schema(instance: Any, schema: dict, path: str = "$") -> list[str]:
    """Validate ``instance`` against the JSON Schema subset used by this project.

    Supports ``type``, ``required``, ``properties``, ``minLength``, ``minimum``,
    ``exclusiveMinimum`` and ``format: date-time``. Returns error messages.
    """
    errors: list[str] = []
    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_JSON_TYPES[t](instance) for t in types):
            errors.append(
                f"{path}: expected {' or '.join(types)}, "
                f"got {_json_type_name(instance)}"
            )
            return errors

    if isinstance(instance, dict):
        for name in schema.get("required", []):
            if name not in instance:
                errors.append(f"{path}.{name}: required field missing")
        for name, sub in schema.get("properties", {}).items():
            if name in instance:
                errors.extend(validate_schema(instance[name], sub, f"{path}.{name}"))

    if isinstance(instance, str):
        if len(instance) < schema.get("minLength", 0):
            errors.append(f"{path}: shorter than {schema['minLength']} characters")
        if schema.get("format") == "date-time" and not _is_datetime(instance):
            errors.append(f"{path}: not an RFC 3339 date-time")

    if _JSON_TYPES["number"](instance):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: less than minimum {schema['minimum']}")
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            errors.append(
                f"{path}: must be greater than {schema['exclusiveMinimum']}"
            )
    return errors


def _json_type_name(value: Any) -> str:
    for name in ("null", "boolean", "integer", "number", "string", "array", "object"):
        if _JSON_TYPES[name](value):
            return name
    return type(value).__name__


def discover_partitions(input_dir: Path) -> list[tuple[int, Path]]:
    """Return ``(partition, path)`` pairs sorted by partition number."""
    found = []
    for path in input_dir.iterdir():
        match = PARTITION_FILE_RE.match(path.name)
        if match and path.is_file():
            found.append((int(match.group(1)), path))
    return sorted(found)


def _read_lines(path: Path) -> Iterator[tuple[int, str]]:
    with open(path, encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            yield line_number, line.rstrip("\r\n")


def classify(
    message: Any,
    schema: dict,
    approved_currencies: Iterable[str],
    seen_transaction_ids: set,
) -> tuple[str | None, list[str]]:
    """Return ``(reason, errors)``; ``reason`` is ``None`` for a valid event.

    Checks, in precedence order: null customer id, schema, currency, duplicate.
    Only accepted events register their transaction id, so a rejected event
    never blocks a later valid event with the same id.
    """
    value = message.get("value") if isinstance(message, dict) else None
    if isinstance(value, dict) and "customer_id" in value and (
        value["customer_id"] is None
    ):
        return REASON_NULL_CUSTOMER, ["$.value.customer_id: is null"]

    errors = validate_schema(message, schema)
    if errors:
        return REASON_SCHEMA, errors

    currency = value["currency"]
    if currency not in approved_currencies:
        return REASON_CURRENCY, [f"$.value.currency: {currency!r} is not approved"]

    txn_id = value["transaction_id"]
    if txn_id in seen_transaction_ids:
        return REASON_DUPLICATE, [
            f"$.value.transaction_id: {txn_id!r} was already accepted"
        ]
    return None, []


def run_pipeline(
    input_dir: str | Path,
    output_dir: str | Path,
    *,
    schema_path: str | Path = DEFAULT_SCHEMA_PATH,
    currencies_path: str | Path = DEFAULT_CURRENCIES_PATH,
) -> dict:
    """Process every partition file in ``input_dir`` into ``output_dir``.

    Writes ``valid.jsonl``, ``rejects.jsonl`` and ``metrics.json`` and returns
    the metrics dict.
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    if not input_dir.is_dir():
        raise FileNotFoundError(f"input directory not found: {input_dir}")

    schema = load_schema(schema_path)
    approved = load_approved_currencies(currencies_path)
    partitions = discover_partitions(input_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    seen_ids: set = set()
    reasons: Counter = Counter()
    per_partition: dict[str, dict] = {}
    valid_amounts: dict[str, float] = {}
    totals = Counter()

    with open(output_dir / VALID_FILE, "w", encoding="utf-8") as valid_fh, open(
        output_dir / REJECTS_FILE, "w", encoding="utf-8"
    ) as rejects_fh:
        for partition, path in partitions:
            stats = Counter()
            for line_number, line in _read_lines(path):
                if not line.strip():
                    stats["blank_lines_skipped"] += 1
                    continue
                stats["messages_read"] += 1
                source = {
                    "partition": partition,
                    "file": path.name,
                    "line_number": line_number,
                }
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as exc:
                    reason, errors, message = REASON_MALFORMED_JSON, [str(exc)], None
                else:
                    reason, errors = classify(message, schema, approved, seen_ids)

                if reason is None:
                    value = message["value"]
                    seen_ids.add(value["transaction_id"])
                    record = {"partition": partition, **message}
                    valid_fh.write(json.dumps(record) + "\n")
                    stats["valid"] += 1
                    valid_amounts[value["currency"]] = (
                        valid_amounts.get(value["currency"], 0.0) + value["amount"]
                    )
                    continue

                offset = message.get("offset") if isinstance(message, dict) else None
                reject = {
                    **source,
                    "offset": offset if isinstance(offset, int) else None,
                    "reason": reason,
                    "errors": errors,
                    "raw": line,
                }
                rejects_fh.write(json.dumps(reject) + "\n")
                stats["rejected"] += 1
                reasons[reason] += 1

            per_partition[str(partition)] = {
                "file": path.name,
                "messages_read": stats["messages_read"],
                "valid": stats["valid"],
                "rejected": stats["rejected"],
                "blank_lines_skipped": stats["blank_lines_skipped"],
            }
            totals.update(stats)

    read = totals["messages_read"]
    metrics = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "partitions_processed": len(partitions),
        "messages_read": read,
        "valid": totals["valid"],
        "rejected": totals["rejected"],
        "blank_lines_skipped": totals["blank_lines_skipped"],
        "reject_rate": round(totals["rejected"] / read, 4) if read else 0.0,
        "rejects_by_reason": {r: reasons[r] for r in sorted(reasons)},
        "unique_valid_transaction_ids": len(seen_ids),
        "valid_amount_by_currency": {
            c: round(a, 2) for c, a in sorted(valid_amounts.items())
        },
        "partitions": per_partition,
        "outputs": {
            "valid": VALID_FILE,
            "rejects": REJECTS_FILE,
            "metrics": METRICS_FILE,
        },
    }
    with open(output_dir / METRICS_FILE, "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=2)
        fh.write("\n")
    return metrics
