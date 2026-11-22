"""Score one trial's IMPACT_ANALYSIS.json against the hidden answer key.

usage: python score.py <IMPACT_ANALYSIS.json> [--trace]
Prints a JSON score object. Name matching is lenient (aliases below) and every
mapping is reported under "trace" so it can be audited.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import system_model as m

HERE = Path(__file__).resolve().parent
KEY = json.loads((HERE / "hidden" / "answer_key.json").read_text())

ALIASES = [  # (regex on normalised name, canonical repo)
    (r"ingest", "ingestion-service"),
    (r"metadata(graph)?$|contextgraph|^metadatagraph", "metadata-graph"),
    (r"entitlement|accesscontrol|authz|policy", "entitlements-service"),
    (r"gateway|queryservice|queryapi|serving|query", "query-gateway"),
    (r"^dq|dataquality|quality", "dq-engine"),
    (r"search", "search-indexer"),
    (r"lineage", "lineage-service"),
    (r"notif", "notification-service"),
    (r"metering|usage", "usage-metering"),
    (r"report", "reporting-service"),
    (r"sdk", "platform-sdk"),
    (r"contract|schemaregistry|schemas$", "platform-contracts"),
    (r"e2e|endtoend|integrationtest", "platform-e2e"),
]
KNOWN = set(m.COMPONENTS)
ALL_EDGES = m.edges()
# Owners publish their schemas into platform-contracts, so owner<->contracts is a
# real relation even though the catalog graph does not list it as an edge.
ALL_EDGES |= {frozenset((e, "platform-contracts")) for e in m.EVENTS.values()}
ALL_EDGES |= {frozenset((a["owner"], "platform-contracts")) for a in m.APIS.values()}
TOPICS = set(m.EVENTS)
ENDPOINTS = {e for a in m.APIS.values() for e in a["endpoints"]}


def canon(name: str) -> str | None:
    raw = name.strip().lower()
    if raw in KNOWN:
        return raw
    n = re.sub(r"[^a-z0-9]", "", raw.split("(")[0].split("/")[-1])
    for pat, repo in ALIASES:
        if re.search(pat, n):
            return repo
    return None


def norm_http(name: str) -> tuple[str, str] | None:
    mt = re.match(r"\s*(GET|PUT|PATCH|POST|DELETE)\s+(\S+)", name, re.I)
    if not mt:
        return None
    path = re.sub(r"\{[^}]*\}|:[a-z_]+", "{x}", mt.group(2).split("?")[0])
    return mt.group(1).upper(), path


def score(doc: dict) -> dict:
    trace: list[str] = []
    impacted = set(KEY["repositories"]["code_change"]) | set(
        KEY["repositories"]["verify_only"])
    not_impacted = set(KEY["repositories"]["not_impacted"])

    listed: dict[str, str] = {}
    unknown_repos = []
    for r in doc.get("repositories", []):
        c = canon(r["name"])
        trace.append(f"repo {r['name']!r} -> {c}")
        if c is None:
            unknown_repos.append(r["name"])
            continue
        if c not in listed or r.get("impact") == "code_change":
            listed[c] = r.get("impact", "")
    correct = sorted(set(listed) & impacted)
    missed = sorted(impacted - set(listed))
    wrong = sorted(set(listed) & not_impacted)
    cls_ok = sum(1 for c in KEY["repositories"]["code_change"]
                 if listed.get(c) == "code_change")
    cls_ok += sum(1 for c in KEY["repositories"]["verify_only"]
                  if listed.get(c) == "verify_only")

    key_edges = {frozenset(e[:2]) for e in KEY["relevant_edges"]}
    got_edges, bad_edges = set(), []
    for d in doc.get("dependencies", []):
        a, b = canon(d.get("consumer", "")), canon(d.get("provider", ""))
        if not a or not b or a == b:
            bad_edges.append(f"{d.get('consumer')}->{d.get('provider')}")
            continue
        pair = frozenset((a, b))
        if pair in key_edges:
            got_edges.add(pair)
        elif pair not in ALL_EDGES:
            bad_edges.append(f"{a}->{b}")
    missed_edges = sorted("|".join(sorted(p)) for p in key_edges - got_edges)

    hit = set()
    bad_contracts = []
    for c in doc.get("contracts", []):
        name = c.get("name", "")
        matched = False
        for k in KEY["contracts"]:
            if k["kind"] == "event" and k["match"] in name.lower():
                hit.add(k["id"])
                matched = True
            elif k["kind"] == "http":
                h = norm_http(name)
                if (h and h[0] in k["method"] and re.search(k["path_regex"], h[1])
                        and (not k.get("owner") or canon(c.get("owner", "")) == k["owner"])):
                    hit.add(k["id"])
                    matched = True
        if not matched:
            h = norm_http(name)
            exists = (name in TOPICS or (h and any(
                norm_http(e) == h for e in ENDPOINTS)))
            if not exists and c.get("change") != "new":
                bad_contracts.append(name)
        trace.append(f"contract {name!r} matched={matched}")

    return {
        "repos_correct": len(correct), "repos_total": len(impacted),
        "repos_missed": missed, "repos_incorrect": wrong + unknown_repos,
        "repo_classification_correct": cls_ok,
        "edges_correct": len(got_edges), "edges_total": len(key_edges),
        "edges_missed": missed_edges, "edges_incorrect": bad_edges,
        "contracts_correct": sorted(hit), "contracts_total": len(KEY["contracts"]),
        "contracts_incorrect": bad_contracts,
        "trace": trace,
    }


if __name__ == "__main__":
    s = score(json.loads(Path(sys.argv[1]).read_text()))
    if "--trace" not in sys.argv:
        s.pop("trace")
    print(json.dumps(s, indent=2))
