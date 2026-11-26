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

## Endpoints

| Method | Path | Body | Success |
|---|---|---|---|
| POST | `/v1/datasets` | `metadata.dataset.register.request.v1` | 201 created / 200 re-registered: dataset |
| GET | `/v1/datasets/{urn}` | - | 200: dataset |
| GET | `/v1/datasets/{urn}/columns` | - | 200: `metadata.columns.response.v1` |
| PUT | `/v1/datasets/{urn}/owner` | `metadata.dataset.owner.request.v1` | 200: dataset (requires `steward`) |
| PUT | `/v1/datasets/{urn}/columns/{column}/sensitivity` | `metadata.column.sensitivity.request.v1` | 200: column (requires `steward`) |

PUT endpoints check, in order: `steward` role (403), dataset exists (404), column exists by exact
name (404, sensitivity only), body valid (400).

## Column sensitivity (DP-1501)

Every column is `{"name", "type", "tags", "sensitivity"}` in every response and event; levels are
`PUBLIC` < `INTERNAL` < `CONFIDENTIAL` < `PII` (from `platform_contracts.SENSITIVITY_LEVELS`).

- Registration suggests a level from tags (case-insensitive): `pii` -> `PII`,
  `confidential` -> `CONFIDENTIAL`, `public` -> `PUBLIC`, otherwise `INTERNAL`; the most restrictive
  match wins. Registration bodies never carry `sensitivity`.
- A steward override (`PUT .../sensitivity`) persists, emits one `UPDATED` event and survives
  re-registration while the column still exists. Other columns are re-suggested from their current
  tags; a column removed by re-registration loses its override. Overrides are tracked in the store,
  outside the column objects.
- A stored column without a level is served as `INTERNAL`.

## Develop

```bash
scripts/fetch_deps.sh            # or: export PLATFORM_CONTRACTS_PATH=/path/to/platform-contracts
python3 -m pytest -q
python3 -m flake8
```
