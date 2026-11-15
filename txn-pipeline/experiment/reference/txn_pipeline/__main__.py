import argparse
import sys
from pathlib import Path

from txn_pipeline.pipeline import run_pipeline


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="txn_pipeline")
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args(argv)
    if not args.input.is_dir():
        print(f"input directory not found: {args.input}", file=sys.stderr)
        return 2
    metrics = run_pipeline(args.input, args.output)
    print(f"input={metrics['input_records']} valid={metrics['valid_records']} "
          f"rejected={metrics['rejected_records']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
