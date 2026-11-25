# Data platform overview (synthetic)

```mermaid
graph LR
  SRC[(Source DBs)] --> ING[ingestion-service]
  ING -- ingestion.schema.discovered.v1 --> MG[metadata-service]
  ING -- ingestion.batch.landed.v1 --> TR[transformation-service]
  ING -- ingestion.job.completed.v1 --> LIN[lineage-service]
  TR -- transformation.result.published.v1 --> MG
  TR -- transformation.result.published.v1 --> NOT[notification-service]
  MG -- metadata.dataset.changed.v1 --> ENT[entitlements-service]
  MG -- metadata.dataset.changed.v1 --> SRCH[search-indexer]
  MG -- metadata.dataset.changed.v1 --> LIN
  TR -- GET columns --> MG
  ENT -- GET dataset --> MG
  NOT -- GET dataset --> MG
  QG[consumption-gateway] -- POST /v1/access/decide --> ENT
  QG -- consumption.access.logged.v1 --> UM[usage-metering]
  USERS((Data consumers)) --> QG
```

- REST calls between services go through `platform-sdk` typed clients.
- Event schemas and OpenAPI specs live in `platform-contracts`; `platform-sdk`
  pins a contracts release and validates payloads on publish.
- `platform-e2e` holds cross-service tests run in the `int` environment.
- `reporting-service` was decommissioned in 2025 and its repository archived;
  some older READMEs still mention it.
