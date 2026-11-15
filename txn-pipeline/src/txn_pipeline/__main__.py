"""CLI: ``python -m txn_pipeline --input <dir> --output <dir>``."""

from __future__ import annotations

import argparse
import json
import sys

from txn_pipeline.pipeline import load_approved_currencies, run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="txn_pipeline",
        description="Validate Kafka-style transaction events from JSON Lines files.",
    )
    parser.add_argument(
        "--input", required=True, help="directory of partition-<N>.jsonl files"
    )
    parser.add_argument("--output", required=True, help="directory for output files")
    parser.add_argument(
        "--currencies",
        help="approved currencies JSON file (default: config/approved_currencies.json)",
    )
    args = parser.parse_args(argv)
    currencies = load_approved_currencies(args.currencies) if args.currencies else None
    try:
        metrics = run_pipeline(args.input, args.output, approved_currencies=currencies)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(metrics, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
