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

## Column sensitivity (DP-1501)

Every column returned or emitted (`POST /v1/datasets`, `GET /v1/datasets/{urn}`,
`GET /v1/datasets/{urn}/columns`, `PUT .../owner`, `PUT .../sensitivity` and every
`metadata.dataset.changed.v1` event) has exactly `name`, `type`, `tags` and `sensitivity`, one of
`PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `PII` (from `platform_contracts.SENSITIVITY_LEVELS`).

- Suggestion at registration (`metadata_graph.sensitivity.suggest_sensitivity`): each tag is compared
  as an exact token after `strip().lower()`: `pii` -> `PII`, `confidential` -> `CONFIDENTIAL`,
  `public` -> `PUBLIC`. The most restrictive match wins (`PII` > `CONFIDENTIAL` > `INTERNAL` >
  `PUBLIC`); no match gives `INTERNAL`. The register request cannot set a level.
- Steward override: `PUT /v1/datasets/{urn}/columns/{column}/sensitivity` with body
  `{"sensitivity": "<LEVEL>"}` (`metadata.dataset.column.sensitivity.request.v1`). Checks, in order:
  no `steward` role -> 403 `FORBIDDEN`; unknown dataset -> 404 `NOT_FOUND`; unknown column (exact
  name) -> 404 `NOT_FOUND`; invalid body -> 400 `INVALID_REQUEST`. On success returns 200 with the
  updated column and emits one `UPDATED` event with the full dataset.
- Override persistence: overrides are stored per (urn, column name) in `GraphStore`, outside the
  column objects. Re-registering keeps the override of every column that still exists (even if its
  type or tags changed); other and new columns get the suggestion from their new tags; overrides of
  dropped columns are discarded.

## Develop

```bash
scripts/fetch_deps.sh            # or: export PLATFORM_CONTRACTS_PATH=/path/to/platform-contracts
python3 -m pytest -q
python3 -m flake8
```
