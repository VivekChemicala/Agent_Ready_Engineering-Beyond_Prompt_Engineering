# txn-pipeline

Synthetic Kafka-style transaction ingestion. Kafka is emulated with JSON Lines
files: `data/input/partition-<N>.jsonl` holds the messages of partition `N`,
one message per line (`offset`, `key`, `timestamp`, `value`).

All data in this directory is synthetic.

```
config/approved_currencies.json      reference data
schemas/transaction_event.schema.json  message schema
data/input/                          sample partitions
src/txn_pipeline/                    pipeline package
tests/                               unit tests
```

## Running

```bash
PYTHONPATH=src python -m txn_pipeline --input data/input --output out
```

`run_pipeline(input_dir, output_dir)` (in `txn_pipeline.pipeline`) does the
same and returns the metrics dict. Optional `--schema` / `--currencies`
override the reference files. Outputs in `output_dir`:

- `valid.jsonl`: accepted messages, `{partition, offset, key, timestamp, value}`.
- `rejects.jsonl`: rejected lines with `partition`, `file`, `line_number`,
  `offset`, `transaction_id`, primary `reason`, every violation in `errors`
  (`code`, `field`, `message`) and the untouched `raw` line for replay.
- `metrics.json`: line/message/valid/reject counts, `rejects_by_reason`
  (primary reason), `violations_by_rule` (all violations), valid counts and
  amounts per currency, and per-partition counts.

## Validation rules

Partitions are read in numeric order, lines in file order. Blank lines are
skipped (counted, not rejected). Each remaining line is checked for:

| reason                     | rule                                                    |
|----------------------------|---------------------------------------------------------|
| `malformed_json`           | line is not valid JSON                                  |
| `null_customer_id`         | `value.customer_id` is `null`                           |
| `schema_violation`         | violates `schemas/transaction_event.schema.json` (wrong type, missing field, `amount <= 0`, bad `event_time`, ...) |
| `unapproved_currency`      | `value.currency` not in `config/approved_currencies.json` (case-sensitive) |
| `duplicate_transaction_id` | `transaction_id` already accepted earlier in the run (any partition) |

When several rules fail, `reason` is the first in the table order. Only
accepted events claim a transaction ID, so a rejected first copy does not
block a later valid one. No values are coerced (e.g. `"567.34"` is rejected).

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest
flake8 src tests
```
