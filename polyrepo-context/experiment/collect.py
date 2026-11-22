"""Fetch each trial branch, copy its outputs to runs/<trial>/ and record the commit time.

usage: python collect.py   (run from a git checkout that has the exp/poly-* branches)
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = "polyrepo-context/workspace/analysis"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=HERE, check=True,
                          capture_output=True, text=True).stdout


def main() -> None:
    trials = json.loads((HERE / "trials.json").read_text())
    for name, t in trials.items():
        arm, n = name.split("_t")
        ref = f"origin/exp/poly-{arm}-t{n}"
        try:
            git("fetch", "-q", "origin", f"exp/poly-{arm}-t{n}")
        except subprocess.CalledProcessError:
            print(f"{name}: no branch yet")
            continue
        dest = HERE / "runs" / name
        dest.mkdir(parents=True, exist_ok=True)
        for f in ("IMPACT_ANALYSIS.json", "PLAN.md"):
            try:
                (dest / f).write_text(git("show", f"{ref}:{OUT}/{f}"))
            except subprocess.CalledProcessError:
                print(f"{name}: missing {f}")
        t["sha"] = git("rev-parse", ref).strip()
        t["committed_at"] = int(git("log", "-1", "--format=%ct", ref))
        changed = git("diff", "--name-only", f"origin/exp/poly-{arm}-start", ref).split()
        t["files_outside_analysis"] = [c for c in changed if not c.startswith(OUT)]
        print(f"{name}: {t['sha'][:8]} {t['committed_at'] - t['created_at']}s")
    (HERE / "trials.json").write_text(json.dumps(trials, indent=2) + "\n")


if __name__ == "__main__":
    main()
