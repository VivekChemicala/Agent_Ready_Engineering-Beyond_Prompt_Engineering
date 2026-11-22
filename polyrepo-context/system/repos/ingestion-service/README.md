# ingestion-service

Source connectors that discover source schemas and land data batches into the
lake. Synthetic example service written for an experiment.

Owner: team-ingest

## Events produced

| Topic | When |
|---|---|
| `ingestion.schema.discovered.v1` | A source table's schema is discovered or changes |
| `ingestion.batch.landed.v1` | A batch of rows has landed in the lake |
| `ingestion.job.completed.v1` | An ingestion job finished (source -> target mapping) |

Payloads are validated against `platform-contracts` via `platform-sdk` before publishing.
