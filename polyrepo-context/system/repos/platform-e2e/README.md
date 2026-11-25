# platform-e2e

Cross-service end-to-end tests, run nightly and on demand in the shared
integration environment (`int`). Synthetic example repository.

Owner: team-platform

| Suite | Flow |
|---|---|
| `tests/test_ingest_to_metadata.py` | ingestion -> metadata-service |
| `tests/test_access_flow.py` | consumption-gateway -> entitlements -> metadata-service |
| `tests/test_transformation_flow.py` | batch landed -> transformation-service -> metadata-service quality score |

Each service team adds or updates a suite here when a change crosses services.
