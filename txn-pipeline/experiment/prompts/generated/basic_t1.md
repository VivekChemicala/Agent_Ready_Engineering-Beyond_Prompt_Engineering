Repository: VivekChemicala/Python. Start from branch `exp/txn-pipeline-start` (commit `4e4973379ddc7689edb0d19ba4ea92bacaa19c92`); work only in the `txn-pipeline/` directory.

This is one trial of a controlled experiment, so please:
- Work only from this prompt and the repository contents at that commit. Do not read other branches, pull requests, or other Devin sessions.
- Do not ask questions; make reasonable decisions yourself and note them.
- When done, commit and push to a new branch named `exp/txn-basic-t1`. Do not open a pull request.
- Then reply with the pushed commit SHA, the commands you ran to verify the change and their results, and any assumptions you made.

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

Please implement the change and test it.
