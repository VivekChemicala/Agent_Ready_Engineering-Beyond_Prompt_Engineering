"""Build each arm's workspace from ../system. Arms differ only by what they contain.

A  metadata-graph only (the assigned team's repo and its README)
B  A + platform-catalog (service catalog + dependency graph)
C  B + platform-contracts (OpenAPI / event schemas) + architecture-docs
D  every live repository's code side by side (monorepo-equivalent), no catalog/docs
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

SYSTEM = Path(__file__).resolve().parent.parent / "system"
LIVE_REPOS = ["dq-engine", "entitlements-service", "ingestion-service",
              "lineage-service", "metadata-graph", "notification-service",
              "platform-contracts", "platform-e2e", "platform-sdk",
              "query-gateway", "search-indexer", "usage-metering"]

ARMS = {
    "A": ["repos/metadata-graph"],
    "B": ["repos/metadata-graph", "platform-catalog"],
    "C": ["repos/metadata-graph", "platform-catalog", "repos/platform-contracts",
          "architecture-docs"],
    "D": [f"repos/{r}" for r in LIVE_REPOS],
}

NOTICE = ("# Workspace (synthetic)\n\nEverything here is a SYNTHETIC example "
          "written for an experiment. Each top-level folder is a separate git "
          "repository in production.\n")


def build(arm: str, dest: Path) -> None:
    ws = dest / "workspace"
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    (ws / "README.md").write_text(NOTICE)
    for rel in ARMS[arm]:
        shutil.copytree(SYSTEM / rel, ws / Path(rel).name)


if __name__ == "__main__":
    build(sys.argv[1], Path(sys.argv[2]))
