"""Score one txn-pipeline workspace against every gate.

    python experiment/score.py <path/to/txn-pipeline> [--json out.json]

Gates: agent's own pytest suite, flake8, CLI smoke run on data/input, and the
hidden acceptance suite (requirements / contract / robustness). The workspace
is copied first so the hidden suite cannot modify it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ACCEPTANCE = HERE / "acceptance"
CATEGORIES = ("TestRequirements", "TestContract", "TestRobustness")
CLEAN_ENV_DROP = re.compile(r"KEY|TOKEN|SECRET|PASSWORD", re.I)


def env(**extra) -> dict:
    e = {k: v for k, v in os.environ.items() if not CLEAN_ENV_DROP.search(k)}
    e.pop("PYTHONPATH", None)
    e.update(extra)
    return e


def sh(cmd, cwd, timeout=600, **extra):
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env(**extra),
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        if isinstance(out, bytes):
            out = out.decode(errors="replace")
        return 124, f"{out}\nTIMEOUT after {timeout}s"
    return p.returncode, (p.stdout + p.stderr)


def tail(text: str, n: int = 40) -> str:
    return "\n".join(text.strip().splitlines()[-n:])


def count_tests(output: str) -> int:
    m = re.search(r"(\d+) passed", output)
    f = re.search(r"(\d+) failed", output)
    return (int(m.group(1)) if m else 0) + (int(f.group(1)) if f else 0)


def acceptance(ws: Path, xml: Path) -> dict:
    sh([sys.executable, "-m", "pytest", str(ACCEPTANCE), "-q",
        "-p", "no:cacheprovider", f"--junitxml={xml}",
        f"--rootdir={ACCEPTANCE}"], cwd=ws, TXN_WORKSPACE=str(ws))
    scores = {c: {"passed": 0, "total": 0, "failed": []} for c in CATEGORIES}
    if not xml.exists():
        for s in scores.values():
            s["failed"].append("<no report>")
        return scores
    for case in ET.parse(xml).iter("testcase"):
        cat = case.get("classname", "").rsplit(".", 1)[-1]
        ok = case.find("failure") is None and case.find("error") is None
        targets = [cat] if cat in scores else list(CATEGORIES)
        for t in targets:
            scores[t]["total"] += 1
            scores[t]["passed"] += ok
            if not ok:
                scores[t]["failed"].append(case.get("name"))
    return scores


def fingerprint(ws: Path) -> str | None:
    """Canonical hash of outputs on the sample data (reason_detail ignored)."""
    out = ws / "_fp_out"
    code, _ = sh([sys.executable, "-c",
                  "import sys; from txn_pipeline import run_pipeline; "
                  "run_pipeline(sys.argv[1], sys.argv[2])",
                  "data/input", "_fp_out"], cwd=ws, timeout=120,
                 PYTHONPATH=str(ws / "src"))
    if code:
        return None
    parts = []
    for name in ("valid.jsonl", "rejects.jsonl"):
        try:
            rows = [json.loads(x) for x in
                    (out / name).read_text().splitlines() if x.strip()]
        except (OSError, ValueError):
            return None
        for r in rows:
            if isinstance(r, dict):
                r.pop("reason_detail", None)
        parts.append(json.dumps(rows, sort_keys=True))
    try:
        parts.append(json.dumps(json.loads((out / "metrics.json").read_text()),
                                sort_keys=True))
    except (OSError, ValueError):
        return None
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def score(project: Path, keep: Path | None = None) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="txn-score-"))
    ws = tmp / "txn-pipeline"
    shutil.copytree(project, ws, ignore=shutil.ignore_patterns(
        "__pycache__", ".pytest_cache", "out", "experiment", ".venv"))
    result: dict = {"project": str(project)}
    extra = sorted(p.name for p in ws.glob("requirements*.txt")
                   if p.name != "requirements-dev.txt")
    result["added_requirement_files"] = extra
    for name in extra:
        sh([sys.executable, "-m", "pip", "install", "-q", "-r", name], cwd=ws)

    code, out = sh([sys.executable, "-m", "pytest", "-q", "-o", "addopts=",
                    "-p", "no:cacheprovider"], cwd=ws)
    result["pytest"] = {"passed": code == 0, "tests": count_tests(out),
                        "tail": tail(out)}
    code, out = sh([sys.executable, "-m", "flake8", "src", "tests"], cwd=ws)
    result["flake8"] = {"passed": code == 0, "issues": len(out.splitlines()),
                        "tail": tail(out)}
    code, out = sh([sys.executable, "-m", "txn_pipeline", "--input",
                    "data/input", "--output", "out"], cwd=ws, timeout=120,
                   PYTHONPATH=str(ws / "src"))
    result["cli_smoke"] = {"passed": code == 0, "tail": tail(out, 10)}
    result["acceptance"] = acceptance(ws, tmp / "acceptance.xml")
    result["fingerprint"] = fingerprint(ws)
    acc = result["acceptance"]
    result["requirements_pass"] = (acc["TestRequirements"]["passed"]
                                   == acc["TestRequirements"]["total"] > 0)
    result["contract_pass"] = acc["TestContract"]["passed"] \
        == acc["TestContract"]["total"] > 0
    result["robustness_pass"] = acc["TestRobustness"]["passed"] \
        == acc["TestRobustness"]["total"] > 0
    result["accepted"] = all([
        result["pytest"]["passed"], result["flake8"]["passed"],
        result["cli_smoke"]["passed"], result["requirements_pass"],
        result["contract_pass"], result["robustness_pass"]])
    if keep:
        shutil.copy2(tmp / "acceptance.xml", keep)
    shutil.rmtree(tmp, ignore_errors=True)
    return result


def summary_line(r: dict) -> str:
    a = r["acceptance"]
    cats = " ".join(f"{c[4:]}={a[c]['passed']}/{a[c]['total']}"
                    for c in CATEGORIES)
    return (f"accepted={r['accepted']} pytest={r['pytest']['passed']}"
            f"({r['pytest']['tests']} tests) flake8={r['flake8']['passed']}"
            f" cli={r['cli_smoke']['passed']} {cats} fp={r['fingerprint']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    r = score(args.project.resolve())
    if args.json:
        args.json.write_text(json.dumps(r, indent=2))
    print(summary_line(r))
    for c in CATEGORIES:
        if r["acceptance"][c]["failed"]:
            print(f"  {c}: {', '.join(r['acceptance'][c]['failed'])}")
    return 0 if r["accepted"] else 1


if __name__ == "__main__":
    sys.exit(main())
