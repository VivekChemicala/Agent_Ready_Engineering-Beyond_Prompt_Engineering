# txn-pipeline

Synthetic Kafka-style transaction ingestion. Kafka is emulated with JSON Lines
files: `data/input/partition-<N>.jsonl` holds the messages of partition `N`,
one message per line (`offset`, `key`, `timestamp`, `value`).

All data in this directory is synthetic.

```
config/approved_currencies.json      reference data
schemas/transaction_event.schema.json  message schema
data/input/                          sample partitions
src/txn_pipeline/                    pipeline package (run_pipeline is a stub)
tests/                               unit tests
```

```bash
pip install -r requirements-dev.txt
python -m pytest
flake8 src tests
```
