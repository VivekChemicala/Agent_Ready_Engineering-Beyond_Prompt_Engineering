# Task: transaction ingestion and validation pipeline

Build a synthetic Kafka-style transaction ingestion and validation pipeline in
`txn-pipeline/`. Kafka is emulated with JSON Lines files: `data/input/` holds
one `partition-<N>.jsonl` file per partition, one message per line.

Implement `run_pipeline(input_dir, output_dir)` in
`src/txn_pipeline/pipeline.py` (it returns the metrics as a dict) and a CLI:
`python -m txn_pipeline --input <dir> --output <dir>`.

Requirements:
1. Validate the incoming event schema.
2. Reject null customer IDs.
3. Reject duplicate transaction IDs.
4. Validate currency against an approved set.
5. Separate invalid events into a reject dataset.
6. Produce structured processing metrics.

Write to `output_dir`: `valid.jsonl` (accepted transactions), `rejects.jsonl`
(rejected events) and `metrics.json` (processing metrics).
