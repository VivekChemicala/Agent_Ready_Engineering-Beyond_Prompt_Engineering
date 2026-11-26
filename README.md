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
- Callers pass their permissions as a set of strings; `dataset:read` is required to query
  (403 `FORBIDDEN` otherwise, checked first).
- PII masking (DP-1501): each column carries a `sensitivity` level (`PUBLIC`, `INTERNAL`,
  `CONFIDENTIAL`, `PII`); a column that arrives without one is treated as `INTERNAL`. Unless the
  caller holds `pii:read`, every non-null value of a `PII` column is replaced with `"***"` (whatever
  its type, so `""`, `0` and `false` are masked too; nulls stay null). Other levels are not masked.
- Success responses are `{"status": 200, "rows": [...], "masked_columns": [...]}`. `masked_columns`
  lists the masked `PII` columns in dataset column order, computed from the metadata alone (so it is
  filled even with zero rows); it is `[]` when the caller holds `pii:read` or there is no `PII`
  column. Error responses do not carry `masked_columns`.

## Develop

```bash
scripts/fetch_deps.sh            # or: export PLATFORM_CONTRACTS_PATH=/path/to/platform-contracts
python3 -m pytest -q
python3 -m flake8
```
