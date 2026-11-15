"""Launcher so ``python -m txn_pipeline`` works from the project root uninstalled.

The package source lives in ``src/txn_pipeline/``; this shim only redirects
the package path there.
"""

from pathlib import Path

__path__ = [str(Path(__file__).resolve().parents[1] / "src" / "txn_pipeline")]

from txn_pipeline.pipeline import run_pipeline  # noqa: E402

__all__ = ["run_pipeline"]
