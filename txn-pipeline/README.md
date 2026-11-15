# txn-pipeline

Synthetic Kafka-style transaction ingestion. Kafka is emulated with JSON Lines
files: `data/input/partition-<N>.jsonl` holds the messages of partition `N`,
one message per line (`offset`, `key`, `timestamp`, `value`).

All data in this directory is synthetic.

```
config/approved_currencies.json      reference data
schemas/transaction_event.schema.json  message schema
data/input/                          sample partitions
src/txn_pipeline/                    pipeline package and CLI
tests/                               unit tests
```

```bash
pip install -r requirements-dev.txt
python -m pytest
flake8 src tests
```

## Running the pipeline

```bash
PYTHONPATH=src python -m txn_pipeline --input data/input --output out/run
# or: pip install -e . && python -m txn_pipeline --input data/input --output out/run
```

Optional `--currencies <file>` overrides `config/approved_currencies.json`.
From Python: `run_pipeline(input_dir, output_dir)` returns the metrics dict.

Partitions are processed in ascending partition number `N`, lines in file
order, and output rows follow that order. Blank (whitespace-only) lines are
skipped and not counted. Each event gets exactly one reject reason: the first
failing check, in this order:

| reason_code             | rule |
|-------------------------|------|
| `MALFORMED_EVENT`       | line is not UTF-8 JSON (`NaN`/`Infinity` rejected), not an object, or `offset` is not a non-negative integer (`source_offset` is then `null`) |
| `NULL_CUSTOMER_ID`      | `value.customer_id` is missing, `null`, empty or whitespace-only |
| `SCHEMA_VIOLATION`      | message does not match `schemas/transaction_event.schema.json`: `value` not an object, a required field missing, non-string `customer_id`/`transaction_id`/`merchant_id`/`currency`, `amount` not a finite JSON number > 0 (bools and strings rejected), `event_time` not `YYYY-MM-DDTHH:MM:SS[.ffffff]Z` or not a real date, bad `key`/`timestamp` types |
| `INVALID_CURRENCY`      | `value.currency` not in the approved set (exact, case-sensitive) |
| `DUPLICATE_TRANSACTION` | `transaction_id` already accepted earlier in the run (only accepted events reserve an ID) |

Outputs in `--output`:

- `valid.jsonl`: `transaction_id, customer_id, amount, currency, event_time,
  merchant_id, source_partition, source_offset` (other input fields dropped).
- `rejects.jsonl`: `source_partition, source_offset, reason_code,
  reason_detail, raw` (`raw` is the original line).
- `metrics.json`: `schema_version` (`"1.0"`), `input_records`,
  `valid_records`, `rejected_records`, `rejects_by_reason` (all five codes) and
  `partitions` (`{"<N>": {input_records, valid_records, rejected_records}}`).
