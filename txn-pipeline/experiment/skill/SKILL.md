---
name: txn-pipeline-conventions
description: Team conventions for the synthetic transaction ingestion pipeline in txn-pipeline/ - input format, validation order, reject reason codes, output and metrics contracts, and the definition of done. Use when changing anything under txn-pipeline/.
---

# txn-pipeline conventions

## Input
- `input_dir` contains `partition-<N>.jsonl` files; ignore every other file.
  Process partitions in ascending **numeric** order of `N` (`partition-2`
  before `partition-10`), and lines in file order within a partition.
- One Kafka message per line: `{"offset", "key", "timestamp", "value"}`.
  Only `offset` and `value` are used.
- Blank or whitespace-only lines are skipped and not counted anywhere.
- Reference data comes from `config/approved_currencies.json` (resolve it
  relative to the `txn-pipeline/` project root, not the working directory).
  Do not hard-code the currency list.

## Validation
Evaluate checks in this order; an event gets exactly one reason code, the
first one that fails:

| # | reason_code | Fails when |
|---|---|---|
| 1 | `MALFORMED_EVENT` | line is not valid JSON, is not an object, `offset` is not a non-negative integer, or `value` is not an object |
| 2 | `NULL_CUSTOMER_ID` | `value.customer_id` is missing, `null`, or a blank/whitespace-only string |
| 3 | `SCHEMA_VIOLATION` | any other field in `value` is missing or invalid (rules below), or `customer_id` is not a string |
| 4 | `INVALID_CURRENCY` | `currency` is not in the approved list (exact, case-sensitive: `usd` is invalid) |
| 5 | `DUPLICATE_TRANSACTION` | `transaction_id` was already **accepted** earlier in this run |

Field rules for `SCHEMA_VIOLATION`:
- `transaction_id`, `merchant_id`: non-blank strings.
- `amount`: JSON number (not a string, not a boolean), finite, `> 0`.
- `currency`: string.
- `event_time`: string `YYYY-MM-DDTHH:MM:SS[.ffffff]Z` (UTC, `Z` suffix,
  1-6 fractional digits optional) that is a real calendar datetime.
- Unknown extra fields in `value` are allowed and dropped from the output.

Duplicates: the first event that passes checks 1-4 wins; a rejected event never
reserves its `transaction_id`. Duplicate detection spans all partitions.

`run_pipeline` must never raise because of bad event content.

## Outputs (`output_dir`, created if missing, files overwritten)
All JSON Lines, UTF-8, one object per line, in processing order.

`valid.jsonl` - exactly these keys:
`transaction_id`, `customer_id`, `amount`, `currency`, `event_time`,
`merchant_id` (values unchanged from the input), `source_partition` (int `N`),
`source_offset` (int).

`rejects.jsonl` - exactly these keys:
`source_partition` (int), `source_offset` (int, or `null` when the offset
cannot be read), `reason_code`, `reason_detail` (short human-readable string),
`raw` (the original line, without the trailing newline).

`metrics.json` - exactly this structure (also the return value of
`run_pipeline`):

```json
{
  "schema_version": "1.0",
  "input_records": 0,
  "valid_records": 0,
  "rejected_records": 0,
  "rejects_by_reason": {
    "MALFORMED_EVENT": 0, "NULL_CUSTOMER_ID": 0, "SCHEMA_VIOLATION": 0,
    "INVALID_CURRENCY": 0, "DUPLICATE_TRANSACTION": 0
  },
  "partitions": {"0": {"input_records": 0, "valid_records": 0,
                       "rejected_records": 0}}
}
```
All five reason codes are always present. `partitions` keys are the partition
numbers as strings. `input_records == valid_records + rejected_records`.
Output must be deterministic: no timestamps, run IDs or random values.

CLI: `python -m txn_pipeline --input <dir> --output <dir>` exits 0 when the
run completes (even with rejects) and non-zero if `--input` does not exist.

## Code
- Python 3.10+, standard library only. Code lives in `src/txn_pipeline/`.

## Definition of done
From `txn-pipeline/`, all of these must pass, and you must report their output:
```bash
python -m pytest
flake8 src tests
python -m txn_pipeline --input data/input --output out
```
Tests: one or more tests per reason code, plus metrics, ordering, and
duplicate-after-reject cases. Build test inputs in `tmp_path`.
