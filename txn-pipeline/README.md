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

Partitions are processed in ascending partition number, lines in file order.
Each non-blank line is checked in this order; the first failing check is the
record's reject `reason`:

| reason                     | rule                                                     |
|----------------------------|----------------------------------------------------------|
| `malformed_json`           | line is not valid UTF-8 JSON (`NaN`/`Infinity` rejected) |
| `schema_violation`         | message does not match `schemas/transaction_event.schema.json` (types are strict: `"12.5"` is not a number; `event_time` must be RFC 3339 with a timezone) |
| `null_customer_id`         | `value.customer_id` is `null`                            |
| `unapproved_currency`      | `value.currency` not in the approved set (case-sensitive) |
| `duplicate_transaction_id` | `transaction_id` was already accepted earlier in the run (first valid occurrence wins) |

Blank lines are skipped and counted in `blank_lines_skipped`.

Outputs in `--output`:

- `valid.jsonl`: accepted transactions (the message `value` plus `_source`:
  partition, file, line, offset, key, timestamp).
- `rejects.jsonl`: `{"reason", "errors", "source", "message"}`; malformed lines
  carry `raw` (the original line) instead of `message`.
- `metrics.json`: totals (`records_read`, `valid`, `rejected`,
  `blank_lines_skipped`), `rejects_by_reason`, `per_partition` counts,
  `partitions_processed` and the `approved_currencies` used.
