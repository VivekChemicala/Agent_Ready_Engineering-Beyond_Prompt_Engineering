#!/usr/bin/env bash
# Fetch platform-contracts into .deps/platform-contracts.
# Usage: scripts/fetch_deps.sh [git-ref]
# Released versions are published as git refs of the platform repository:
#   2.3.0 -> exp2/start/platform-contracts
#   2.4.0 -> exp2/C-t2/platform-contracts
set -euo pipefail
REF="${1:-exp2/C-t2/platform-contracts}"
cd "$(dirname "$0")/.."
git fetch -q origin "$REF"
rm -rf .deps/platform-contracts && mkdir -p .deps/platform-contracts
git archive FETCH_HEAD | tar -x -C .deps/platform-contracts
echo "platform-contracts $(cat .deps/platform-contracts/VERSION) from $REF"
