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
same and returns the metrics dict. Approved currencies are read from
`config/approved_currencies.json` on every run. Outputs in `output_dir`, rows
in processing order (partition number, then line):

- `valid.jsonl`: `transaction_id, customer_id, amount, currency, event_time,
  merchant_id, source_partition, source_offset` (other input fields dropped).
- `rejects.jsonl`: `source_partition, source_offset, reason_code,
  reason_detail, raw` (`raw` is the original line; `source_offset` is `null`
  when the offset cannot be read).
- `metrics.json`: `schema_version` (`"1.0"`), `input_records`,
  `valid_records`, `rejected_records`, `rejects_by_reason` (all five codes)
  and `partitions` (`{"<N>": {input_records, valid_records, rejected_records}}`).

## Validation rules

Partition files are read in numeric order of `N`, lines in file order. Blank
or whitespace-only lines are skipped and not counted. Each event gets exactly
one reason: the first failing check below.

| reason_code             | check                                                        |
|-------------------------|--------------------------------------------------------------|
| `MALFORMED_EVENT`       | not UTF-8, not strict JSON (`NaN`/`Infinity` included), or not a JSON object |
| `NULL_CUSTOMER_ID`      | `value.customer_id` is `null`, empty or whitespace only      |
| `SCHEMA_VIOLATION`      | bad envelope/value per `schemas/transaction_event.schema.json`: `offset` non-negative int, `key` string/null, `timestamp` int, required value fields present, ids non-empty strings (non-string `customer_id` included), `amount` a finite JSON number > 0 (not bool/string), `event_time` `YYYY-MM-DDTHH:MM:SS[.ffffff]Z` and a real date |
| `INVALID_CURRENCY`      | `value.currency` not in the approved set (exact, case-sensitive) |
| `DUPLICATE_TRANSACTION` | `transaction_id` already accepted earlier in the run (any partition) |

Only accepted events reserve a `transaction_id`. Values are never coerced.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest
flake8 src tests
```
