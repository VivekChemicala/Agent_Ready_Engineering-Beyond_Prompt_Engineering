# metadata-service

Metadata store service for the data platform. It stores datasets, their columns,
owners and quality scores and exposes them over REST.

> Synthetic example service written for an experiment. Not a real system.

Owner: team-metadata

## Run locally

```bash
pip install -r requirements.txt
python -m metadata_service.app
pytest
```

## Integrations

- Consumes `ingestion.schema.discovered.v1` from the ingestion service to create
  and update dataset and column nodes.
- Consumes transformation results to attach quality scores to datasets.
- Publishes `metadata.dataset.changed.v1` whenever a dataset or its columns
  change. Consumers: entitlements-service, reporting-service.
- REST clients should use `platform-sdk` (`MetadataClient`) rather than calling
  the API directly.

## Layout

| Path | What |
|---|---|
| `src/metadata_service/api.py` | REST routes |
| `src/metadata_service/model.py` | Dataset / Column model |
| `src/metadata_service/consumers.py` | Event consumers |
| `src/metadata_service/publisher.py` | Change-event publisher |
| `src/metadata_service/metadata_store.py` | In-memory metadata store (prod uses the metadata DB) |
| `config/settings.yaml` | Topics and runtime settings |
