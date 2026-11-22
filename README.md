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
- DP-1501: every non-null value of a column whose `sensitivity` is `PII` is replaced with `"***"`
  unless the caller has `pii:read`. The response lists the masked columns, in dataset column order,
  in `masked_columns` (`[]` when nothing is masked). A column without a level is `INTERNAL`.

## Develop

```bash
scripts/fetch_deps.sh            # or: export PLATFORM_CONTRACTS_PATH=/path/to/platform-contracts
python3 -m pytest -q
python3 -m flake8
```
