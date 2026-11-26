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

## Column sensitivity (DP-1501, platform-contracts 2.4.0)

Every column carries `sensitivity`, one of `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `PII`. It is returned by
`POST /v1/datasets`, `GET /v1/datasets/{urn}`, `GET /v1/datasets/{urn}/columns` and included in every
`metadata.dataset.changed.v1` event. A stored column without a level (legacy data) is read as `INTERNAL`.

- Suggestion on `POST /v1/datasets`: from the column's tags (case-insensitive) `pii` -> `PII`,
  `confidential` -> `CONFIDENTIAL`, `public` -> `PUBLIC`, otherwise `INTERNAL`; if several apply the most
  restrictive wins (`PII` > `CONFIDENTIAL` > `INTERNAL` > `PUBLIC`). Register bodies must not carry
  `sensitivity` (the register contract is unchanged; such a body is a 400).
- Steward override: `PUT /v1/datasets/{urn}/columns/{column}/sensitivity` with body
  `{"sensitivity": "<LEVEL>"}` (contract `metadata.dataset.column.sensitivity.request.v1`). Checks in order:
  no `steward` role -> 403 `FORBIDDEN`; unknown dataset -> 404 `NOT_FOUND`; unknown column (exact name)
  -> 404 `NOT_FOUND`; invalid body -> 400 `INVALID_REQUEST`. Success returns 200 with the updated column
  `{"name", "type", "tags", "sensitivity"}` and emits one `UPDATED` event (also when the level is unchanged).
- Re-registration keeps a column's override while the column still exists (even if its tags change); new
  columns get a suggested level; overrides of removed columns are discarded.
- Rollout: deploy `query-gateway` on 2.4.0 before this service starts emitting `sensitivity`.

## Develop

```bash
scripts/fetch_deps.sh            # or: export PLATFORM_CONTRACTS_PATH=/path/to/platform-contracts
python3 -m pytest -q
python3 -m flake8
```
