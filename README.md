# query-gateway

> Synthetic repository for a controlled experiment. Fictional services, no real data.

Owner: `team-access`. Runs queries for callers and enforces data access. It is the only place
where access rules are applied to result rows.

- Upstream: `metadata-graph` `GET /v1/datasets/{urn}/columns`, called through `MetadataClient`.
  Responses are validated strictly against `platform-contracts` (pinned in `requirements.txt`);
  a response the pinned contracts do not allow raises `UpstreamContractError` and the query fails
  with 502.
- Models: `query_gateway.models.Column` is an explicit typed model; fields it does not declare are
  dropped when parsing.
- Callers pass their permissions as a set of strings; `dataset:read` is required to query.
- PII masking (DP-1501): every column carries a `sensitivity` (`PUBLIC`, `INTERNAL`,
  `CONFIDENTIAL`, `PII`; a column without one is `INTERNAL`). Unless the caller has `pii:read`,
  every non-null value of a `PII` column is replaced with `"***"` (nulls stay null). Other levels
  are not masked. Every 200 response has `masked_columns`: the masked column names in dataset
  column order (`[]` when nothing is masked), e.g.
  `{"status": 200, "rows": [...], "masked_columns": ["email"]}`. Error responses are unchanged.

## Develop

```bash
scripts/fetch_deps.sh            # or: export PLATFORM_CONTRACTS_PATH=/path/to/platform-contracts
python3 -m pytest -q
python3 -m flake8
```

End-to-end check against a metadata-graph checkout (skipped unless `METADATA_GRAPH_PATH` is set):

```bash
METADATA_GRAPH_PATH=/path/to/metadata-graph python3 -m pytest -q tests/test_e2e_metadata_graph.py
```
