# platform-e2e

Cross-service end-to-end tests, run nightly and on demand in the shared
integration environment (`int`). Synthetic example repository.

Owner: team-platform

| Suite | Flow |
|---|---|
| `tests/test_ingest_to_graph.py` | ingestion -> metadata-graph |
| `tests/test_access_flow.py` | query-gateway -> entitlements -> metadata-graph |
| `tests/test_dq_flow.py` | batch landed -> dq-engine -> metadata-graph quality score |

Each service team adds or updates a suite here when a change crosses services.
