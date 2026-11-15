"""Shim so ``python -m txn_pipeline`` works from the project root uninstalled.

All code lives in ``src/txn_pipeline``; this only redirects the package path.
"""

from pathlib import Path

__path__ = [str(Path(__file__).resolve().parent.parent / "src" / "txn_pipeline")]

from txn_pipeline.pipeline import run_pipeline  # noqa: E402

__all__ = ["run_pipeline"]
