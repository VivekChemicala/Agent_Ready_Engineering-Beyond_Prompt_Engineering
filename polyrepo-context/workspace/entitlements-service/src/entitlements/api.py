from __future__ import annotations

from dataclasses import asdict

from .policies import PolicyEngine


def decide(engine: PolicyEngine, body: dict):
    """POST /v1/access/decide"""
    d = engine.decide(body["principal"], body["dataset_urn"], body["action"])
    return 200, asdict(d)


def grants(engine: PolicyEngine, principal_id: str):
    """GET /v1/principals/{principal_id}/grants"""
    return 200, {"principal": principal_id,
                 "grants": sorted(engine.grants.get(principal_id, set()))}
