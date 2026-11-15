"""Command line entry point: ``python -m txn_pipeline``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from txn_pipeline.pipeline import run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m txn_pipeline",
        description="Validate Kafka-style transaction partitions.",
    )
    parser.add_argument("--input", required=True, type=Path,
                        help="directory with partition-<N>.jsonl files")
    parser.add_argument("--output", required=True, type=Path,
                        help="directory for valid.jsonl, rejects.jsonl, "
                             "metrics.json")
    args = parser.parse_args(argv)

    if not args.input.is_dir():
        print(f"error: input directory not found: {args.input}", file=sys.stderr)
        return 2
    metrics = run_pipeline(args.input, args.output)
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
