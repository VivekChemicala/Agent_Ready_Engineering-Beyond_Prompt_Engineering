# lineage-service

Builds dataset-level lineage from ingestion jobs. Synthetic example service.

Owner: team-discovery

- `ingestion.job.completed.v1` -> adds source -> target edges.
- `metadata.dataset.changed.v1` -> refreshes dataset display names. Reads only
  `dataset.urn` and `dataset.name`; other fields are ignored (tolerant reader).
