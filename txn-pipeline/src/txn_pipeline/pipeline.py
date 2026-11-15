"""Ingest Kafka-style transaction events from JSON Lines files."""

from __future__ import annotations

from pathlib import Path


def run_pipeline(input_dir: str | Path, output_dir: str | Path) -> dict:
    """Process every partition file in ``input_dir`` into ``output_dir``."""
    raise NotImplementedError
