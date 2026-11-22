# metadata-graph

Context graph service for the data platform. It stores datasets, their columns,
owners and quality scores as a graph and exposes them over REST.

> Synthetic example service written for an experiment. Not a real system.

Owner: team-graph

## Run locally

```bash
pip install -r requirements.txt
python -m metadata_graph.app
pytest
```

## Integrations

- Consumes `ingestion.schema.discovered.v1` from the ingestion service to create
  and update dataset and column nodes.
- Consumes DQ results to attach quality scores to datasets.
- Publishes `metadata.dataset.changed.v1` whenever a dataset or its columns
  change. Consumers: entitlements-service, reporting-service.
- REST clients should use `platform-sdk` (`MetadataClient`) rather than calling
  the API directly.

## Layout

| Path | What |
|---|---|
| `src/metadata_graph/api.py` | REST routes |
| `src/metadata_graph/model.py` | Dataset / Column model |
| `src/metadata_graph/consumers.py` | Event consumers |
| `src/metadata_graph/publisher.py` | Change-event publisher |
| `src/metadata_graph/graph_store.py` | In-memory graph store (prod uses the graph DB) |
| `config/settings.yaml` | Topics and runtime settings |
