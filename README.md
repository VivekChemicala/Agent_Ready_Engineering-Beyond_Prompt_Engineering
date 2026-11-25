# metadata-graph

> Synthetic repository for a controlled experiment. Fictional services, no real data.

Owner: `team-metadata`. Stores datasets and their columns, serves the Metadata API and emits
`metadata.dataset.changed.v1` on every create/update.

- Contracts: every request body, every `GET .../columns` response and every event is validated
  against `platform-contracts` (pinned in `requirements.txt`). A payload the pinned contracts do not
  allow is a bug: the endpoint must fail rather than emit it.
- Consumers: `query-gateway` (calls `GET /v1/datasets/{urn}/columns`, validates strictly),
  `usage-metering` (consumes `metadata.dataset.changed.v1`).
- Errors: `{"error": {"code": ..., "message": ...}}`, codes `INVALID_REQUEST` 400, `FORBIDDEN` 403,
  `NOT_FOUND` 404. Roles arrive in the `X-Roles` header (comma separated); stewards have `steward`.
- Column sensitivity (DP-1501, contracts 2.4.0): every column carries `sensitivity` (`PUBLIC`,
  `INTERNAL`, `CONFIDENTIAL`, `PII`). `POST /v1/datasets` suggests it from tags (`pii` -> `PII`,
  `confidential` -> `CONFIDENTIAL`, `public` -> `PUBLIC`, else `INTERNAL`; most restrictive wins).
  Stewards override it with `PUT /v1/datasets/{urn}/columns/{column}/sensitivity`
  (`{"sensitivity": "<LEVEL>"}`, returns the updated column, emits `UPDATED`); the override survives
  re-registration while the column exists.

## Develop

```bash
scripts/fetch_deps.sh            # or: export PLATFORM_CONTRACTS_PATH=/path/to/platform-contracts
python3 -m pytest -q
python3 -m flake8
```
