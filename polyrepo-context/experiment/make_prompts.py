"""Assemble per-trial prompts. Arms differ only by start branch/SHA (workspace contents)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def build(arm: str, trial: int, sha: str) -> str:
    header = (HERE / "prompts" / "common_header.md").read_text().format(
        start_branch=f"exp/poly-{arm}-start", start_sha=sha,
        trial_branch=f"exp/poly-{arm}-t{trial}")
    return header + (HERE / "task.md").read_text()


def main() -> None:
    shas = json.loads(Path(sys.argv[1]).read_text())
    out = HERE / "prompts" / "generated"
    out.mkdir(exist_ok=True)
    for arm, sha in shas.items():
        for t in (1, 2, 3):
            (out / f"{arm}_t{t}.md").write_text(build(arm, t, sha))


if __name__ == "__main__":
    main()
