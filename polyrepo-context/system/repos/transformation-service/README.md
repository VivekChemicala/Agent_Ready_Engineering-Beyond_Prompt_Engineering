# transformation-service

Runs transformation rules when a batch lands and publishes results.
Synthetic example service written for an experiment.

Owner: team-transformation

- Trigger: `ingestion.batch.landed.v1`.
- Column metadata: `platform_sdk.MetadataClient.get_columns(urn)`.
- Rules: `not_null`, `unique`, `freshness` (see `src/transformation/rules/`). Rules are
  selected per column from rule bindings (`GET/POST /v1/rules`).
- Output: `transformation.result.published.v1` with a 0..1 score per dataset.
