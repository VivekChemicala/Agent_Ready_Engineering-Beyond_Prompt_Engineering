from __future__ import annotations

from dataclasses import dataclass

from platform_sdk import MetadataClient


@dataclass
class Decision:
    allow: bool
    reason: str
    policy_id: str | None = None


class PolicyEngine:
    def __init__(self, grants: dict[str, set[str]], metadata: MetadataClient):
        self.grants = grants
        self.metadata = metadata
        self._cache: dict[str, dict] = {}

    def _dataset(self, urn: str):
        if urn not in self._cache:
            self._cache[urn] = self.metadata.get_dataset(urn)
        return self._cache[urn]

    def invalidate(self, urn: str) -> None:
        self._cache.pop(urn, None)

    def decide(self, principal: str, urn: str, action: str) -> Decision:
        held = self.grants.get(principal, set())
        ds = self._dataset(urn)
        if f"dataset:{urn}:{action}" in held:
            return Decision(True, "DATASET_GRANT", "pol-dataset")
        if f"domain:{ds.domain}:{action}" in held:
            return Decision(True, "DOMAIN_GRANT", "pol-domain")
        return Decision(False, "NO_GRANT")
