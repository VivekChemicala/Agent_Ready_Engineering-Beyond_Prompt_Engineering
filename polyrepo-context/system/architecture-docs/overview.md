# Data platform overview (synthetic)

```mermaid
graph LR
  SRC[(Source DBs)] --> ING[ingestion-service]
  ING -- ingestion.schema.discovered.v1 --> MG[metadata-graph]
  ING -- ingestion.batch.landed.v1 --> DQ[dq-engine]
  ING -- ingestion.job.completed.v1 --> LIN[lineage-service]
  DQ -- dq.result.published.v1 --> MG
  DQ -- dq.result.published.v1 --> NOT[notification-service]
  MG -- metadata.dataset.changed.v1 --> ENT[entitlements-service]
  MG -- metadata.dataset.changed.v1 --> SRCH[search-indexer]
  MG -- metadata.dataset.changed.v1 --> LIN
  DQ -- GET columns --> MG
  ENT -- GET dataset --> MG
  NOT -- GET dataset --> MG
  QG[query-gateway] -- POST /v1/access/decide --> ENT
  QG -- gateway.access.logged.v1 --> UM[usage-metering]
  USERS((Data consumers)) --> QG
```

- REST calls between services go through `platform-sdk` typed clients.
- Event schemas and OpenAPI specs live in `platform-contracts`; `platform-sdk`
  pins a contracts release and validates payloads on publish.
- `platform-e2e` holds cross-service tests run in the `int` environment.
- `reporting-service` was decommissioned in 2025 and its repository archived;
  some older READMEs still mention it.
