"""Aggregate trials.json + per-round scores into RESULTS.md.

    python experiment/aggregate.py [costs.json]

costs.json (optional) maps trial -> ACUs consumed.
"""

from __future__ import annotations

import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"
CATS = ["TestRequirements", "TestContract", "TestRobustness"]


def ts(s: str) -> int:
    return int(datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
               .replace(tzinfo=timezone.utc).timestamp())


def round_windows(t: dict) -> list[tuple[int, int]]:
    starts = [t["created_at"]] + [r["feedback_sent_at"]
                                  for r in t["rounds"][:-1]]
    return [(s, r["delivered_at"]) for s, r in zip(starts, t["rounds"])]


def compliance(events: dict, windows: list[tuple[int, int]]) -> list[bool]:
    ok = []
    for lo, hi in windows:
        ran = all(any(lo <= ts(e) <= hi for e in events[k])
                  for k in ("pytest", "flake8", "cli"))
        ok.append(ran)
    return ok


def main() -> int:
    ledger = json.loads((HERE / "trials.json").read_text())
    events = json.loads((RUNS / "verification_events.json").read_text())
    costs = {}
    if len(sys.argv) > 1:
        costs = json.loads(Path(sys.argv[1]).read_text())
    rows = {}
    for name, t in ledger["trials"].items():
        scores = [json.loads((RUNS / r["score_file"]).read_text())
                  for r in t["rounds"]]
        win = round_windows(t)
        ran = compliance(events[name], win)
        gates = [s["pytest"]["passed"] and s["flake8"]["passed"]
                 and s["cli_smoke"]["passed"] for s in scores]
        first = scores[0]
        accepted = scores[-1]["accepted"]
        rows[name] = {
            "arm": name.split("_")[0],
            "first_pass": first["accepted"],
            "first": {c: (first["acceptance"][c]["passed"],
                          first["acceptance"][c]["total"]) for c in CATS},
            "accepted": accepted,
            "rework": len(scores) - 1,
            "interventions": sum(1 for r in t["rounds"]
                                 if "feedback_sent_at" in r),
            "cycle_s": (t["rounds"][-1]["delivered_at"] - t["created_at"]
                        if accepted else None),
            "agent_s": sum(hi - lo for lo, hi in win),
            "verif_ran": ran,
            "verif_gates": gates,
            "tests": [s["pytest"]["tests"] for s in scores],
            "fingerprint": scores[-1]["fingerprint"],
            "first_fingerprint": first["fingerprint"],
            "commit": scores[-1]["commit"],
            "acus": costs.get(name),
        }
    (RUNS / "summary.json").write_text(json.dumps(rows, indent=2))
    print(render(rows))
    return 0


def mmss(s):
    return "-" if s is None else f"{s // 60}m{s % 60:02d}s"


def median_time(values: list[int]) -> str:
    return mmss(int(statistics.median(values))) if values else "-"


def render(rows: dict) -> str:
    out = ["| Trial | First pass | Req | Contract | Robust | Rework | "
           "Interventions | Cycle time | Agent time | Checks run before "
           "every delivery | Gates green every delivery | Final commit |",
           "|" + "---|" * 12]
    for n, r in rows.items():
        f = r["first"]
        out.append(
            f"| {n} | {'yes' if r['first_pass'] else 'no'} | "
            + " | ".join(f"{p}/{t}" for p, t in f.values())
            + f" | {r['rework']} | {r['interventions']} | "
            f"{mmss(r['cycle_s'])} | {mmss(r['agent_s'])} | "
            f"{sum(r['verif_ran'])}/{len(r['verif_ran'])} | "
            f"{sum(r['verif_gates'])}/{len(r['verif_gates'])} | "
            f"`{r['commit'][:8]}` |")
    out += ["", "| Arm | First-pass acceptance | Final acceptance | "
            "Mean first-pass contract | Total rework | Total interventions | "
            "Median cycle time | Total agent time | Distinct first-pass "
            "outputs | Agent time per accepted change |", "|" + "---|" * 10]
    for arm in ("basic", "skill"):
        rs = [r for r in rows.values() if r["arm"] == arm]
        acc = sum(r["accepted"] for r in rs)
        agent = sum(r["agent_s"] for r in rs)
        contract = statistics.mean(r["first"]["TestContract"][0] for r in rs)
        out.append(
            f"| {arm} | {sum(r['first_pass'] for r in rs)}/{len(rs)} | "
            f"{acc}/{len(rs)} | {contract:.1f}/19 | "
            f"{sum(r['rework'] for r in rs)} | "
            f"{sum(r['interventions'] for r in rs)} | "
            f"{median_time([r['cycle_s'] for r in rs if r['accepted']])} | "
            f"{mmss(agent)} | "
            f"{len({r['first_fingerprint'] for r in rs})} | "
            f"{mmss(agent // acc) if acc else '-'} |")
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(main())
