# txn-pipeline

Synthetic Kafka-style transaction ingestion. Kafka is emulated with JSON Lines
files: `data/input/partition-<N>.jsonl` holds the messages of partition `N`,
one message per line (`offset`, `key`, `timestamp`, `value`).

All data in this directory is synthetic.

```
config/approved_currencies.json      reference data
schemas/transaction_event.schema.json  message schema
data/input/                          sample partitions
src/txn_pipeline/                    pipeline package (run_pipeline, CLI)
txn_pipeline/                        shim: lets `python -m txn_pipeline` run from here
tests/                               unit tests
```

```bash
pip install -r requirements-dev.txt
python -m pytest
flake8 src tests
python -m txn_pipeline --input data/input --output out
```

The run writes `valid.jsonl`, `rejects.jsonl` and `metrics.json` to `--output`.
Each rejected event carries one `reason_code`: `MALFORMED_EVENT`,
`NULL_CUSTOMER_ID`, `SCHEMA_VIOLATION`, `INVALID_CURRENCY` or
`DUPLICATE_TRANSACTION` (checked in that order).
