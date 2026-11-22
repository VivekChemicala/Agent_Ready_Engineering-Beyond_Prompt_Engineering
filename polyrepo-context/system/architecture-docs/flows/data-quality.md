# Flow: data quality (synthetic)

1. `ingestion.batch.landed.v1` triggers `dq-engine`.
2. `dq-engine` loads column metadata with `MetadataClient.get_columns(urn)` and
   picks rules per column from bindings (by data type today).
3. Results go out on `dq.result.published.v1`; `metadata-graph` stores the
   score, `notification-service` emails the owner when it is low.
