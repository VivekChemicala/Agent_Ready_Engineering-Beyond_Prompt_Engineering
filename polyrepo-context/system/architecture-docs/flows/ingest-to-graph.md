# Flow: ingest to graph (synthetic)

1. A connector in `ingestion-service` reads the source table schema.
   Postgres connectors also read column comments, where source owners keep
   tags such as `tags: pii,email`; these are not propagated today.
2. `ingestion-service` publishes `ingestion.schema.discovered.v1`.
3. `metadata-graph` creates or updates dataset and column nodes and publishes
   `metadata.dataset.changed.v1` (full dataset snapshot including columns).
