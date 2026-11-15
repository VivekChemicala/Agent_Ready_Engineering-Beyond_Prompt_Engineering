"""Assemble the per-trial prompts. Arms differ only by the SKILL.md block."""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
START_BRANCH = "exp/txn-pipeline-start"


def build(arm: str, trial: int, start_sha: str) -> str:
    p = HERE / "prompts"
    header = (p / "common_header.md").read_text().format(
        start_branch=START_BRANCH, start_sha=start_sha,
        trial_branch=f"exp/txn-{arm}-t{trial}")
    body = header + (HERE / "task.md").read_text() + (
        p / "basic_footer.md").read_text()
    if arm == "skill":
        body += (p / "skill_footer.md").read_text().format(
            skill=(HERE / "skill" / "SKILL.md").read_text().strip())
    return body


def main() -> None:
    sha = sys.argv[1]
    out = HERE / "prompts" / "generated"
    out.mkdir(exist_ok=True)
    for arm in ("basic", "skill"):
        for trial in (1, 2, 3):
            (out / f"{arm}_t{trial}.md").write_text(build(arm, trial, sha))


if __name__ == "__main__":
    main()
