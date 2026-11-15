# txn-pipeline

Synthetic Kafka-style transaction ingestion. Kafka is emulated with JSON Lines
files: `data/input/partition-<N>.jsonl` holds the messages of partition `N`,
one message per line (`offset`, `key`, `timestamp`, `value`).

All data in this directory is synthetic.

```
config/approved_currencies.json      reference data
schemas/transaction_event.schema.json  message schema
data/input/                          sample partitions
src/txn_pipeline/                    pipeline package + CLI
tests/                               unit tests
```

```bash
pip install -r requirements-dev.txt
python -m pytest
flake8 src tests
```

## Running

```bash
PYTHONPATH=src python -m txn_pipeline --input data/input --output out
```

`run_pipeline(input_dir, output_dir)` reads every `partition-<N>.jsonl` (in
partition order, then file order) and writes to `output_dir`:

- `valid.jsonl` - accepted messages, each with an added `partition` field.
- `rejects.jsonl` - one record per rejected message: `partition`, `file`,
  `line_number`, `offset`, `reason`, `errors`, and the `raw` line.
- `metrics.json` - totals, `rejects_by_reason`, reject rate, valid amount per
  currency and per-partition counts (also returned by `run_pipeline` and
  printed by the CLI).

Reject reasons, first matching rule wins:

| reason | rule |
| --- | --- |
| `malformed_json` | line is not valid JSON |
| `null_customer_id` | `value.customer_id` is `null` |
| `schema_violation` | fails `schemas/transaction_event.schema.json` (wrong type, missing field, non-positive amount, bad `event_time`, ...) |
| `unapproved_currency` | currency not in `config/approved_currencies.json` (case-sensitive) |
| `duplicate_transaction_id` | `transaction_id` already accepted earlier in the run, in any partition |

Blank lines are not messages; they are skipped and counted in
`blank_lines_skipped`.
