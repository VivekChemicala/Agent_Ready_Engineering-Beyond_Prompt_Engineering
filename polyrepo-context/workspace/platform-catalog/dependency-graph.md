# Dependency graph (generated from catalog)

Synthetic example. An arrow `A --> B` means A depends on B.

```mermaid
graph LR
  ingestion-service -->|library: platform-sdk| platform-sdk
  metadata-graph -->|event: ingestion.schema.discovered.v1| ingestion-service
  metadata-graph -->|event: dq.result.published.v1| dq-engine
  metadata-graph -->|library: platform-sdk| platform-sdk
  entitlements-service -->|event: metadata.dataset.changed.v1| metadata-graph
  entitlements-service -->|http: metadata-graph-api| metadata-graph
  entitlements-service -->|library: platform-sdk| platform-sdk
  query-gateway -->|http: entitlements-api| entitlements-service
  query-gateway -->|library: platform-sdk| platform-sdk
  dq-engine -->|event: ingestion.batch.landed.v1| ingestion-service
  dq-engine -->|http: metadata-graph-api| metadata-graph
  dq-engine -->|library: platform-sdk| platform-sdk
  search-indexer -->|event: metadata.dataset.changed.v1| metadata-graph
  search-indexer -->|library: platform-contracts| platform-contracts
  lineage-service -->|event: ingestion.job.completed.v1| ingestion-service
  lineage-service -->|event: metadata.dataset.changed.v1| metadata-graph
  lineage-service -->|library: platform-sdk| platform-sdk
  notification-service -->|event: dq.result.published.v1| dq-engine
  notification-service -->|http: metadata-graph-api| metadata-graph
  notification-service -->|library: platform-sdk| platform-sdk
  usage-metering -->|event: gateway.access.logged.v1| query-gateway
  platform-sdk -->|http: metadata-graph-api| metadata-graph
  platform-sdk -->|http: entitlements-api| entitlements-service
  platform-sdk -->|library: platform-contracts| platform-contracts
  platform-e2e -->|tests: ingestion-service| ingestion-service
  platform-e2e -->|tests: metadata-graph| metadata-graph
  platform-e2e -->|tests: entitlements-service| entitlements-service
  platform-e2e -->|tests: query-gateway| query-gateway
  platform-e2e -->|tests: dq-engine| dq-engine
```
