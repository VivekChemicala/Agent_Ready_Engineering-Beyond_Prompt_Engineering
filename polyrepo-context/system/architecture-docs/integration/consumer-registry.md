# Consumer registry (synthetic)

How each consumer reads each contract. "Tolerant" = ignores unknown fields.
"Strict" = rejects payloads with unknown fields.

| Contract | Consumer | Reads | Mode |
|---|---|---|---|
| `ingestion.schema.discovered.v1` | metadata-service | columns[name,type,nullable] | tolerant |
| `ingestion.batch.landed.v1` | transformation-service | dataset_urn, batch_id, path | tolerant |
| `ingestion.job.completed.v1` | lineage-service | source, target_urn | tolerant |
| `metadata.dataset.changed.v1` | entitlements-service | dataset.urn (cache invalidation) | tolerant |
| `metadata.dataset.changed.v1` | lineage-service | dataset.urn, dataset.name | tolerant |
| `metadata.dataset.changed.v1` | search-indexer | full payload, vendored JSON Schema with `additionalProperties: false` (contracts 2.1.0) | **strict**: unknown fields -> DLQ, not indexed |
| `transformation.result.published.v1` | metadata-service | dataset_urn, score | tolerant |
| `transformation.result.published.v1` | notification-service | dataset_urn, score | tolerant |
| `consumption.access.logged.v1` | usage-metering | principal, dataset_urn, row_count | tolerant |
| `metadata-service-api` | platform-sdk `MetadataClient` | declared dataclass fields only (ADR-004) | drops unknown |
| `entitlements-api` | platform-sdk `EntitlementsClient` | `allow`, `reason` only (ADR-004) | drops unknown |
| `metadata-service-api` GET dataset | notification-service (via SDK) | owner | tolerant |
