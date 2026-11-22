"""Rebuild the results tables in RESULTS_TABLES.md from runs/, trials.json and judge scores."""

from __future__ import annotations

import json
import statistics as st
from pathlib import Path

from score import score

HERE = Path(__file__).resolve().parent
ARMS = ["A", "B", "C", "D"]


def fmt_time(s: float) -> str:
    return f"{int(s // 60)}m{int(s % 60):02d}s"


def main() -> None:
    trials = json.loads((HERE / "trials.json").read_text())
    judge = {}
    scores_path, map_path = HERE / "judge" / "scores.json", HERE / "hidden" / "judge_mapping.json"
    if scores_path.exists():
        mapping = json.loads(map_path.read_text())
        judge = {mapping[p]: v for p, v in json.loads(scores_path.read_text()).items()}
    rows, per_arm = [], {a: [] for a in ARMS}
    for name, t in trials.items():
        f = HERE / "runs" / name / "IMPACT_ANALYSIS.json"
        if not f.exists():
            continue
        s = score(json.loads(f.read_text()))
        s.pop("trace")
        s["decommissioned"] = "reporting-service" in s["repos_incorrect"]
        s["time_s"] = t["committed_at"] - t["created_at"]
        s["acus"] = t.get("acus")
        s["plan"] = sum(v for k, v in judge.get(name, {}).items()
                        if k.startswith("P") and isinstance(v, int)) if name in judge else None
        (HERE / "runs" / name / "score.json").write_text(json.dumps(s, indent=2) + "\n")
        per_arm[name[0]].append(s)
        rows.append((name, s))

    out = ["## Per trial", "",
           "| Trial | Repos found (of 10) | Missed repos | Wrong repos | Decommissioned repo planned | Change/verify class correct (of 10) "  # noqa: E501
           "| Edges found (of 11) | Wrong edges | Contracts found (of 5) | Wrong contracts | Plan score (of 16) | Time to push | ACUs |",  # noqa: E501
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, s in rows:
        out.append(
            f"| {name} | {s['repos_correct']} | {', '.join(s['repos_missed']) or '-'} | "
            f"{', '.join(s['repos_incorrect']) or '-'} | {'yes' if s['decommissioned'] else 'no'} | "
            f"{s['repo_classification_correct']} | "
            f"{s['edges_correct']} | {len(s['edges_incorrect'])} | {len(s['contracts_correct'])} | "
            f"{len(s['contracts_incorrect'])} | {s['plan'] if s['plan'] is not None else 'n/a'} | "
            f"{fmt_time(s['time_s'])} | {s['acus'] if s['acus'] is not None else 'n/a'} |")
    out += ["", "## Per arm (mean over trials; time is median)", "",
            "| Arm | Repos found (of 10) | Wrong repos | Decommissioned repo planned | Class correct (of 10) | Edges found (of 11) "  # noqa: E501
            "| Wrong edges | Contracts found (of 5) | Wrong contracts | Plan score (of 16) | Median time |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for a in ARMS:
        ss = per_arm[a]
        if not ss:
            continue
        mean = lambda k: f"{st.mean(k(s) for s in ss):.1f}"  # noqa: E731
        plans = [s["plan"] for s in ss if s["plan"] is not None]
        out.append(
            f"| {a} | {mean(lambda s: s['repos_correct'])} | {mean(lambda s: len(s['repos_incorrect']))} | "
            f"{sum(s['decommissioned'] for s in ss)}/{len(ss)} | "
            f"{mean(lambda s: s['repo_classification_correct'])} | {mean(lambda s: s['edges_correct'])} | "
            f"{mean(lambda s: len(s['edges_incorrect']))} | {mean(lambda s: len(s['contracts_correct']))} | "
            f"{mean(lambda s: len(s['contracts_incorrect']))} | "
            f"{f'{st.mean(plans):.1f}' if plans else 'n/a'} | "
            f"{fmt_time(st.median(s['time_s'] for s in ss))} |")
    (HERE / "RESULTS_TABLES.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
