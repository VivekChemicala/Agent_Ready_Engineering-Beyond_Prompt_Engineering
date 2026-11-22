# search-indexer

Keeps the catalog search index in sync with dataset metadata.
Synthetic example service written for an experiment.

Owner: team-discovery

- Consumes `metadata.dataset.changed.v1`.
- Every event is validated against the vendored schema in `schemas/` before it
  is indexed; invalid events go to the dead-letter topic
  `search-indexer.dlq` and are not indexed. Validation is strict on purpose so
  unexpected fields never reach the index mapping.
- Vendored from platform-contracts 2.1.0.
