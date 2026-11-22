from __future__ import annotations

from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str


class EntitlementsClient:
    def __init__(self, base_url: str, session=None):
        self.base_url = base_url.rstrip("/")
        self.http = session or requests.Session()

    def decide(self, principal: str, dataset_urn: str, action: str) -> Decision:
        body = self.http.post(f"{self.base_url}/v1/access/decide", json={
            "principal": principal, "dataset_urn": dataset_urn,
            "action": action}).json()
        return Decision(allow=body["allow"], reason=body["reason"])
