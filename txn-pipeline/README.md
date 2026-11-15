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

`run_pipeline(input_dir, output_dir)` reads every `partition-<N>.jsonl` in
numeric order of `N`, line by line, and writes rows in that order to
`output_dir`:

- `valid.jsonl`: `transaction_id`, `customer_id`, `amount`, `currency`,
  `event_time`, `merchant_id`, `source_partition`, `source_offset`. Other
  input fields are dropped.
- `rejects.jsonl`: `source_partition`, `source_offset` (`null` if unreadable),
  `reason_code`, `reason_detail`, `raw` (the original line).
- `metrics.json`: `schema_version` (`"1.0"`), `input_records`, `valid_records`,
  `rejected_records`, `rejects_by_reason` (all five codes), and `partitions`
  (`{"<N>": {input_records, valid_records, rejected_records}}`). It is also
  returned by `run_pipeline` and printed by the CLI.

Each event gets one reason code. The first failing check wins:

| reason_code | rule |
| --- | --- |
| `MALFORMED_EVENT` | not valid UTF-8/JSON, or not a JSON object |
| `NULL_CUSTOMER_ID` | `value.customer_id` is `null`, empty or whitespace |
| `SCHEMA_VIOLATION` | breaks `schemas/transaction_event.schema.json`, e.g. a missing field, a wrong type, an `amount` that is not a finite number > 0, or an `event_time` that is not a real `YYYY-MM-DDTHH:MM:SS[.ffffff]Z` |
| `INVALID_CURRENCY` | not in `config/approved_currencies.json` (exact, case-sensitive; read on every run) |
| `DUPLICATE_TRANSACTION` | `transaction_id` already accepted earlier in the run (any partition) |

Blank or whitespace-only lines are skipped and not counted.
