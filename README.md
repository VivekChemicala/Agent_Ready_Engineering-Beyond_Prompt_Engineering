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

## PII masking (DP-1501, contracts 2.4.0)

- Each upstream column carries `sensitivity` (`PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `PII`);
  `Column.sensitivity` defaults to `INTERNAL` when the field is absent (2.3.0-style payloads).
  An out-of-enum level fails contract validation -> 502 `UPSTREAM_CONTRACT`.
- Unless the caller has `pii:read`, every non-null value of a `PII` column is replaced by `"***"`
  (nulls stay null). Other levels are never masked.
- Successful responses are `{"status": 200, "rows": [...], "masked_columns": [...]}`:
  `masked_columns` lists the `PII` columns masked for this caller, in dataset column order
  (`[]` with `pii:read` or when no column is `PII`). 403/502 responses are unchanged.

## Develop

```bash
scripts/fetch_deps.sh            # or: export PLATFORM_CONTRACTS_PATH=/path/to/platform-contracts
python3 -m pytest -q
python3 -m flake8
```
