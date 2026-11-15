"""Ingest Kafka-style transaction events from JSON Lines files.

Each ``partition-<N>.jsonl`` file in the input directory is one partition;
each non-blank line is one message. Every message ends up in exactly one of
``valid.jsonl`` or ``rejects.jsonl``, and ``metrics.json`` summarises the run.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from txn_pipeline.schema import iter_errors

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "transaction_event.schema.json"
DEFAULT_CURRENCIES_PATH = PROJECT_ROOT / "config" / "approved_currencies.json"

PARTITION_FILE = re.compile(r"^partition-(\d+)\.jsonl$")

VALID_FILE = "valid.jsonl"
REJECTS_FILE = "rejects.jsonl"
METRICS_FILE = "metrics.json"

MALFORMED_JSON = "malformed_json"
NULL_CUSTOMER_ID = "null_customer_id"
SCHEMA_VIOLATION = "schema_violation"
UNAPPROVED_CURRENCY = "unapproved_currency"
DUPLICATE_TRANSACTION_ID = "duplicate_transaction_id"

# A rejected event may break several rules; its primary ``reason`` is the
# first matching code in this order. All violations are kept in ``errors``.
REASON_PRIORITY = (
    MALFORMED_JSON,
    NULL_CUSTOMER_ID,
    SCHEMA_VIOLATION,
    UNAPPROVED_CURRENCY,
    DUPLICATE_TRANSACTION_ID,
)


def load_schema(path: str | Path = DEFAULT_SCHEMA_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_approved_currencies(path: str | Path = DEFAULT_CURRENCIES_PATH) -> frozenset:
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


def validate_message(
    message: Any,
    schema: dict,
    approved_currencies: frozenset,
) -> list[dict]:
    """Return stateless rule violations (everything except duplicates)."""
    errors = []
    value = message.get("value") if isinstance(message, dict) else None
    customer_is_null = isinstance(value, dict) and (
        "customer_id" in value and value["customer_id"] is None
    )

    for path, text in iter_errors(message, schema):
        if customer_is_null and path == "value.customer_id":
            continue
        errors.append(_error(SCHEMA_VIOLATION, path, text))

    if customer_is_null:
        errors.append(
            _error(NULL_CUSTOMER_ID, "value.customer_id", "customer_id is null")
        )

    if isinstance(value, dict) and isinstance(value.get("currency"), str):
        currency = value["currency"]
        if currency not in approved_currencies:
            errors.append(
                _error(
                    UNAPPROVED_CURRENCY,
                    "value.currency",
                    f"currency {currency!r} is not in the approved set",
                )
            )
    return errors


def run_pipeline(
    input_dir: str | Path,
    output_dir: str | Path,
    *,
    schema_path: str | Path = DEFAULT_SCHEMA_PATH,
    currencies_path: str | Path = DEFAULT_CURRENCIES_PATH,
) -> dict:
    """Process every partition file in ``input_dir`` into ``output_dir``."""
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    schema = load_schema(schema_path)
    approved_currencies = load_approved_currencies(currencies_path)
    partitions = discover_partitions(input_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    seen_transaction_ids: dict[str, dict] = {}
    reasons: Counter = Counter()
    violations: Counter = Counter()
    valid_by_currency: Counter = Counter()
    valid_amount_by_currency: dict[str, float] = {}
    partition_metrics = []
    totals = Counter()

    with open(output_dir / VALID_FILE, "w", encoding="utf-8") as valid_out, open(
        output_dir / REJECTS_FILE, "w", encoding="utf-8"
    ) as rejects_out:
        for partition, path in partitions:
            stats = Counter()
            for line_number, raw in _read_lines(path):
                stats["lines_read"] += 1
                if not raw.strip():
                    stats["blank_lines_skipped"] += 1
                    continue
                stats["messages_read"] += 1
                source = {
                    "partition": partition,
                    "file": path.name,
                    "line_number": line_number,
                }

                try:
                    message = json.loads(raw)
                except json.JSONDecodeError as exc:
                    message = None
                    errors = [_error(MALFORMED_JSON, "<root>", f"invalid JSON: {exc}")]
                else:
                    errors = validate_message(message, schema, approved_currencies)

                if not errors:
                    txn_id = message["value"]["transaction_id"]
                    first = seen_transaction_ids.get(txn_id)
                    if first is not None:
                        errors.append(
                            _error(
                                DUPLICATE_TRANSACTION_ID,
                                "value.transaction_id",
                                f"transaction_id {txn_id!r} already accepted from "
                                f"partition {first['partition']} offset "
                                f"{first['offset']}",
                            )
                        )
                    else:
                        seen_transaction_ids[txn_id] = {
                            "partition": partition,
                            "offset": message["offset"],
                        }

                if errors:
                    reason = _primary_reason(errors)
                    reasons[reason] += 1
                    violations.update(e["code"] for e in errors)
                    stats["rejected"] += 1
                    _write(
                        rejects_out,
                        _reject_record(source, raw, message, reason, errors),
                    )
                else:
                    value = message["value"]
                    stats["valid"] += 1
                    valid_by_currency[value["currency"]] += 1
                    valid_amount_by_currency[value["currency"]] = (
                        valid_amount_by_currency.get(value["currency"], 0.0)
                        + value["amount"]
                    )
                    _write(valid_out, _valid_record(partition, message))

            totals.update(stats)
            partition_metrics.append(
                {
                    "partition": partition,
                    "file": path.name,
                    **{k: stats[k] for k in _COUNT_KEYS},
                }
            )

    messages = totals["messages_read"]
    metrics = {
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "partitions_processed": len(partitions),
        **{k: totals[k] for k in _COUNT_KEYS},
        "valid_rate": round(totals["valid"] / messages, 4) if messages else None,
        "rejects_by_reason": {r: reasons[r] for r in REASON_PRIORITY},
        "violations_by_rule": {r: violations[r] for r in REASON_PRIORITY},
        "valid_by_currency": dict(sorted(valid_by_currency.items())),
        "valid_amount_by_currency": {
            c: round(a, 2) for c, a in sorted(valid_amount_by_currency.items())
        },
        "partitions": partition_metrics,
        "approved_currencies": sorted(approved_currencies),
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


_COUNT_KEYS = (
    "lines_read",
    "blank_lines_skipped",
    "messages_read",
    "valid",
    "rejected",
)


def _read_lines(path: Path) -> Iterable[tuple[int, str]]:
    with open(path, encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            yield line_number, line.rstrip("\r\n")


def _error(code: str, field: str, message: str) -> dict:
    return {"code": code, "field": field, "message": message}


def _primary_reason(errors: list[dict]) -> str:
    codes = {e["code"] for e in errors}
    return next(r for r in REASON_PRIORITY if r in codes)


def _valid_record(partition: int, message: dict) -> dict:
    return {
        "partition": partition,
        "offset": message["offset"],
        "key": message.get("key"),
        "timestamp": message.get("timestamp"),
        "value": message["value"],
    }


def _reject_record(
    source: dict, raw: str, message: Any, reason: str, errors: list[dict]
) -> dict:
    offset = message.get("offset") if isinstance(message, dict) else None
    value = message.get("value") if isinstance(message, dict) else None
    txn_id = value.get("transaction_id") if isinstance(value, dict) else None
    return {
        **source,
        "offset": offset,
        "transaction_id": txn_id,
        "reason": reason,
        "errors": errors,
        "raw": raw,
    }


def _write(fh, record: dict) -> None:
    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
