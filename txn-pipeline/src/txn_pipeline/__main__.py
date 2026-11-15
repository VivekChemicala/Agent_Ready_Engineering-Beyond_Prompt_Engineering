"""CLI: ``python -m txn_pipeline --input <dir> --output <dir>``."""

from __future__ import annotations

import argparse
import json
import sys

from txn_pipeline.pipeline import run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m txn_pipeline",
        description="Validate Kafka-style transaction events from JSON Lines.",
    )
    parser.add_argument(
        "--input", required=True, help="directory of partition-<N>.jsonl files"
    )
    parser.add_argument(
        "--output",
        required=True,
        help="directory for valid.jsonl, rejects.jsonl and metrics.json",
    )
    args = parser.parse_args(argv)
    try:
        metrics = run_pipeline(args.input, args.output)
    except (FileNotFoundError, NotADirectoryError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
