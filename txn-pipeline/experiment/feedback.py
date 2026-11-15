"""Simulated human-reviewer feedback for a failed scoring run.

Identical for both arms. It states the expected behaviour (what a reviewer
would tell the engineer) without revealing hidden test inputs or code. Each
message sent counts as one human intervention and one rework iteration.
"""

from __future__ import annotations

NOTES = {
    "test_r1_schema_violations_rejected":
        "Events with missing/mis-typed required fields (or a non-object value) "
        "must be rejected, not accepted.",
    "test_r2_null_customer_rejected":
        "Events whose customer_id is null or missing must be rejected.",
    "test_r3_duplicates_rejected_first_kept":
        "Duplicate transaction_ids (also across partitions) must be rejected; "
        "the first occurrence is kept.",
    "test_r4_unapproved_currency_rejected":
        "Currencies outside config/approved_currencies.json must be rejected.",
    "test_r5_invalid_events_go_to_reject_dataset":
        "Every invalid line, including unparseable ones, must appear in "
        "rejects.jsonl and nowhere in valid.jsonl.",
    "test_r6_structured_metrics":
        "metrics.json must report input/valid/rejected counts and equal the "
        "dict returned by run_pipeline.",
    "test_valid_record_shape":
        "valid.jsonl rows must have exactly: transaction_id, customer_id, "
        "amount, currency, event_time, merchant_id, source_partition, "
        "source_offset (extra input fields dropped, values unchanged).",
    "test_reject_record_shape":
        "rejects.jsonl rows must have exactly: source_partition, source_offset, "
        "reason_code, reason_detail, raw (raw = original line).",
    "test_reason_codes":
        "Use the reason codes MALFORMED_EVENT, NULL_CUSTOMER_ID, "
        "SCHEMA_VIOLATION, INVALID_CURRENCY, DUPLICATE_TRANSACTION.",
    "test_malformed_offset_is_null":
        "A line whose offset is not a non-negative integer is MALFORMED_EVENT, "
        "and source_offset must then be null.",
    "test_blank_customer_is_null_customer":
        "A missing, null, empty or whitespace-only customer_id is "
        "NULL_CUSTOMER_ID.",
    "test_non_string_customer_is_schema_violation":
        "A non-string customer_id is a SCHEMA_VIOLATION.",
    "test_precedence":
        "One reason per event, first failing check wins: MALFORMED_EVENT > "
        "NULL_CUSTOMER_ID > SCHEMA_VIOLATION > INVALID_CURRENCY > "
        "DUPLICATE_TRANSACTION.",
    "test_currency_is_case_sensitive":
        "Currency matching is exact and case-sensitive.",
    "test_amount_rules":
        "amount must be a JSON number (not bool/string), finite and > 0.",
    "test_event_time_rules":
        "event_time must be YYYY-MM-DDTHH:MM:SS[.ffffff]Z and a real date.",
    "test_rejected_event_does_not_reserve_id":
        "Only accepted events reserve a transaction_id for duplicate checks.",
    "test_numeric_partition_order":
        "Process partition files in numeric order of N.",
    "test_non_partition_files_ignored":
        "Only read files named partition-<N>.jsonl.",
    "test_blank_lines_not_counted":
        "Skip blank lines without counting them.",
    "test_metrics_exact":
        "metrics.json must be exactly: schema_version '1.0', input_records, "
        "valid_records, rejected_records, rejects_by_reason (all five codes), "
        "partitions {'<N>': {input_records, valid_records, rejected_records}}.",
    "test_output_order_is_processing_order":
        "Output rows must be in processing order (partition, then line).",
    "test_currencies_come_from_config":
        "Read approved currencies from config/approved_currencies.json "
        "(resolved from the project root) on each run; don't hard-code them.",
    "test_cli":
        "`python -m txn_pipeline --input D --output D` must work from any "
        "directory, exit 0 on success, non-zero if --input is missing.",
    "test_outputs_overwritten":
        "Re-running must overwrite previous outputs.",
    "test_hostile_lines_never_raise":
        "Arbitrary bad lines (non-objects, NaN, huge numbers, wrong types) "
        "must be rejected without raising.",
    "test_empty_input":
        "An input dir with no partitions must produce empty outputs and zero "
        "metrics.",
    "test_nested_output_dir_created":
        "Create the output directory (including parents) if missing.",
    "test_deterministic":
        "Output must be byte-for-byte deterministic across runs.",
}


def reviewer_message(result: dict) -> str:
    lines = ["Review of your change found problems. Please fix them, keep "
             "pytest and flake8 green, push to the same branch, and reply "
             "with the new commit SHA.", ""]
    if not result["pytest"]["passed"]:
        lines += ["- Your pytest suite fails:", "```",
                  result["pytest"]["tail"], "```"]
    if not result["flake8"]["passed"]:
        lines += ["- flake8 src tests reports issues:", "```",
                  result["flake8"]["tail"], "```"]
    if not result["cli_smoke"]["passed"]:
        lines += ["- `python -m txn_pipeline --input data/input --output out` "
                  "fails:", "```", result["cli_smoke"]["tail"], "```"]
    seen = set()
    for cat in ("TestRequirements", "TestContract", "TestRobustness"):
        for name in result["acceptance"][cat]["failed"]:
            note = NOTES.get(name, "Acceptance check failed.")
            if note not in seen:
                seen.add(note)
                lines.append(f"- {note}")
    return "\n".join(lines)
