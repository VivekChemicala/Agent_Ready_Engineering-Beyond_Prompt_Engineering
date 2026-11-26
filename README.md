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
- Sensitivity (DP-1501): every column carries `sensitivity`, one of `PUBLIC`, `INTERNAL`,
  `CONFIDENTIAL`, `PII`, in every response and event. On `POST /v1/datasets` it is suggested from
  the column's tags (exact, case-insensitive): `pii` -> `PII`, `confidential` -> `CONFIDENTIAL`,
  `public` -> `PUBLIC`, otherwise `INTERNAL`; the most restrictive wins
  (`PII` > `CONFIDENTIAL` > `INTERNAL` > `PUBLIC`). Clients do not send levels at registration.
- `PUT /v1/datasets/{urn}/columns/{column}/sensitivity` with `{"sensitivity": "<LEVEL>"}`
  (`metadata.column.sensitivity.request.v1`, `steward` role) sets a steward override: 403 without the
  role, 404 for an unknown dataset or column, 400 for an invalid body; 200 returns the updated column
  and emits an `UPDATED` event.
- Overrides survive re-registration while a column with the same name is present (type/tag changes
  do not matter); other columns get the suggestion from their current tags. An override of a column
  missing from a re-registration is discarded. Override bookkeeping is internal and never emitted.

## Develop

```bash
scripts/fetch_deps.sh            # or: export PLATFORM_CONTRACTS_PATH=/path/to/platform-contracts
python3 -m pytest -q
python3 -m flake8
```
