"""Score one delivery of a trial and record it in trials.json.

    python experiment/score_round.py <trial> <commit_sha> <delivered_at_unix>

Prints the reviewer message to send if the delivery is not accepted.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from feedback import reviewer_message
from score import score, summary_line

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RUNS = HERE / "runs"


def main() -> int:
    trial, sha, delivered_at = sys.argv[1], sys.argv[2], int(sys.argv[3])
    ledger_path = HERE / "trials.json"
    ledger = json.loads(ledger_path.read_text())
    t = ledger["trials"][trial]
    branch = f"exp/txn-{trial.replace('_', '-')}"
    subprocess.run(["git", "fetch", "-q", "origin", branch], cwd=REPO, check=True)
    wt = RUNS / "worktrees" / f"{trial}_r{len(t['rounds'])}"
    if wt.exists():
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)],
                       cwd=REPO, check=True)
    subprocess.run(["git", "worktree", "add", "-q", "--detach", str(wt), sha],
                   cwd=REPO, check=True)
    changed = subprocess.run(
        ["git", "diff", "--stat", ledger["start_sha"], sha, "--", "."],
        cwd=REPO, capture_output=True, text=True).stdout.strip().splitlines()
    result = score(wt / "txn-pipeline")
    result.update(commit=sha, delivered_at=delivered_at,
                  diffstat=changed[-1] if changed else "")
    RUNS.mkdir(exist_ok=True)
    out = RUNS / f"{trial}_r{len(t['rounds'])}.json"
    out.write_text(json.dumps(result, indent=2))
    t["rounds"].append({"commit": sha, "delivered_at": delivered_at,
                        "accepted": result["accepted"], "score_file": out.name})
    ledger_path.write_text(json.dumps(ledger, indent=2) + "\n")
    print(f"{trial} round {len(t['rounds']) - 1}: {summary_line(result)}")
    print(f"diff: {result['diffstat']}")
    if not result["accepted"]:
        print("----- reviewer message -----")
        print(reviewer_message(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
