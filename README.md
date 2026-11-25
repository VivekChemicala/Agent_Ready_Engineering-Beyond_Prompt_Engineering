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
- Column sensitivity (DP-1501): every column has `sensitivity`, one of `PUBLIC`, `INTERNAL`,
  `CONFIDENTIAL`, `PII`. `POST /v1/datasets` suggests it from the column tags (`pii` → `PII`,
  `confidential` → `CONFIDENTIAL`, `public` → `PUBLIC`, else `INTERNAL`; most restrictive wins).
  Stewards override it with `PUT /v1/datasets/{urn}/columns/{column}/sensitivity`
  `{"sensitivity": "<LEVEL>"}` (200: the updated column, emits `UPDATED`); overrides survive
  re-registration while the column exists. A stored column without a level is served as `INTERNAL`.

## Develop

```bash
scripts/fetch_deps.sh            # or: export PLATFORM_CONTRACTS_PATH=/path/to/platform-contracts
python3 -m pytest -q
python3 -m flake8
```
