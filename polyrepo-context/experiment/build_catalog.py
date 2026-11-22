"""Generate the platform-catalog repo (arm B/C context) from system_model.py.

Backstage-style entity files plus a dependency graph (JSON + Mermaid).
It lists who depends on whom and through which API/topic; it does not
contain schemas, endpoints or architecture notes (those are arm C).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import system_model as m

HEADER = "# SYNTHETIC example catalog entry written for an experiment.\n"


def yaml_list(items: list[str], indent: int) -> str:
    if not items:
        return " []\n"
    pad = " " * indent
    return "\n" + "".join(f"{pad}- {i}\n" for i in items)


def component_yaml(name: str, c: dict) -> str:
    kind = "Component"
    s = HEADER + f"apiVersion: backstage.io/v1alpha1\nkind: {kind}\nmetadata:\n"
    s += f"  name: {name}\n  description: {c['description']}\n"
    s += f"  annotations:\n    github.com/project-slug: example-org/{name}\n"
    s += f"spec:\n  type: {c['type']}\n  lifecycle: {c['lifecycle']}\n"
    s += f"  owner: {c['owner']}\n  system: data-platform\n"
    s += "  providesApis:" + yaml_list(c["provides_apis"], 4)
    s += "  consumesApis:" + yaml_list(c["consumes_apis"], 4)
    s += "  dependsOn:" + yaml_list([f"component:{d}" for d in c["depends_on"]], 4)
    s += "  events:\n    produces:" + yaml_list(c["produces"], 6)
    s += "    consumes:" + yaml_list(c["consumes"], 6)
    return s


def api_yaml(name: str, a: dict) -> str:
    consumers = [n for n, c in m.COMPONENTS.items() if name in c["consumes_apis"]
                 and c["lifecycle"] != "decommissioned"]
    return (HEADER + "apiVersion: backstage.io/v1alpha1\nkind: API\nmetadata:\n"
            f"  name: {name}\nspec:\n  type: openapi\n  lifecycle: production\n"
            f"  owner: {m.COMPONENTS[a['owner']]['owner']}\n"
            f"  providedBy: component:{a['owner']}\n"
            f"  definition: platform-contracts/openapi/{a['owner']}.yaml\n"
            "  consumedBy:" + yaml_list([f"component:{c}" for c in consumers], 4))


def graph() -> list[dict]:
    out = []
    for name, c in m.COMPONENTS.items():
        if c["lifecycle"] == "decommissioned":
            continue
        for t in c["consumes"]:
            out.append({"from": name, "to": m.EVENTS[t], "via": "event", "ref": t})
        for a in c["consumes_apis"]:
            out.append({"from": name, "to": m.APIS[a]["owner"], "via": "http", "ref": a})
        for d in c["depends_on"]:
            kind = "library" if m.COMPONENTS[d]["type"] == "library" else "tests"
            out.append({"from": name, "to": d, "via": kind, "ref": d})
    return out


def main(dest: Path) -> None:
    (dest / "components").mkdir(parents=True, exist_ok=True)
    (dest / "apis").mkdir(exist_ok=True)
    for name, c in m.COMPONENTS.items():
        (dest / "components" / f"{name}.yaml").write_text(component_yaml(name, c))
    for name, a in m.APIS.items():
        (dest / "apis" / f"{name}.yaml").write_text(api_yaml(name, a))
    topics = {t: {"producer": p, "consumers": sorted(
        n for n, c in m.COMPONENTS.items() if t in c["consumes"]
        and c["lifecycle"] != "decommissioned")} for t, p in m.EVENTS.items()}
    (dest / "topics.yaml").write_text(HEADER + "".join(
        f"{t}:\n  producer: {v['producer']}\n  consumers:"
        + yaml_list(v["consumers"], 4) for t, v in topics.items()))
    edges = graph()
    (dest / "dependency-graph.json").write_text(json.dumps(
        {"note": "SYNTHETIC. 'from' depends on 'to'.", "edges": edges}, indent=2) + "\n")
    lines = ["# Dependency graph (generated from catalog)", "",
             "Synthetic example. An arrow `A --> B` means A depends on B.", "",
             "```mermaid", "graph LR"]
    lines += [f"  {e['from']} -->|{e['via']}: {e['ref']}| {e['to']}" for e in edges]
    lines += ["```", ""]
    (dest / "dependency-graph.md").write_text("\n".join(lines))
    (dest / "README.md").write_text(
        "# platform-catalog\n\nService catalog for the data platform (Backstage-style).\n"
        "Synthetic example repository written for an experiment.\n\n"
        "- `components/` - one entity per repository: owner team, lifecycle, APIs\n"
        "  provided/consumed, library dependencies, events produced/consumed.\n"
        "- `apis/` - one entity per REST API with provider and consumers.\n"
        "- `topics.yaml` - every event topic with producer and consumers.\n"
        "- `dependency-graph.json` / `.md` - generated graph of all of the above.\n\n"
        "Each component is a separate git repository named after the component\n"
        "(`example-org/<name>`). Teams update their entity in the same PR that\n"
        "changes an integration.\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
