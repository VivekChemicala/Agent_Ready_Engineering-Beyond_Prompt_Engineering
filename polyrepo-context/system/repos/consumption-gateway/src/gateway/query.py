from __future__ import annotations

from platform_sdk import EntitlementsClient, events


class QueryService:
    def __init__(self, entitlements: EntitlementsClient, warehouse):
        self.entitlements = entitlements
        self.warehouse = warehouse

    def run(self, principal: str, dataset_urn: str, sql: str) -> tuple[int, dict]:
        decision = self.entitlements.decide(principal, dataset_urn, "read")
        if not decision.allow:
            return 403, {"error": "FORBIDDEN", "reason": decision.reason}
        rows = self.warehouse.execute(sql)
        events.publish("consumption.access.logged.v1", {
            "event_id": events.new_event_id(), "principal": principal,
            "dataset_urn": dataset_urn, "row_count": len(rows),
        }, schema_ref="platform-contracts://events/consumption.access.logged.v1")
        return 200, {"rows": rows}
