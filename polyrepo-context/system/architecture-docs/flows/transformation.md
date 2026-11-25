# Flow: transformation (synthetic)

1. `ingestion.batch.landed.v1` triggers `transformation-service`.
2. `transformation-service` loads column metadata with `MetadataClient.get_columns(urn)` and
   picks rules per column from bindings (by data type today).
3. Results go out on `transformation.result.published.v1`; `metadata-service` stores the
   score, `notification-service` emails the owner when it is low.
