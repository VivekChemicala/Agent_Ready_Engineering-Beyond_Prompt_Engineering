from __future__ import annotations

from datetime import datetime, timezone

from platform_sdk import events


def publish_schema_discovered(source: str, urn: str, name: str, domain: str,
                              columns: list[dict]) -> None:
    events.publish("ingestion.schema.discovered.v1", {
        "event_id": events.new_event_id(),
        "source_system": source,
        "dataset_urn": urn,
        "dataset_name": name,
        "domain": domain,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "columns": columns,
    }, schema_ref="platform-contracts://events/ingestion.schema.discovered.v1")


def publish_batch_landed(urn: str, batch_id: str, path: str, rows: int) -> None:
    events.publish("ingestion.batch.landed.v1", {
        "event_id": events.new_event_id(), "dataset_urn": urn,
        "batch_id": batch_id, "path": path, "row_count": rows,
    }, schema_ref="platform-contracts://events/ingestion.batch.landed.v1")


def publish_job_completed(job_id: str, source: str, target_urn: str) -> None:
    events.publish("ingestion.job.completed.v1", {
        "event_id": events.new_event_id(), "job_id": job_id,
        "source": source, "target_urn": target_urn,
    }, schema_ref="platform-contracts://events/ingestion.job.completed.v1")
