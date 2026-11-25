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

## Column sensitivity (DP-1501, contracts 2.4.0)

- Every stored/returned column is `{name, type, tags, sensitivity}`; `sensitivity` is one of
  `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `PII`. It is in `GET /v1/datasets/{urn}`,
  `GET /v1/datasets/{urn}/columns`, POST/PUT responses and every `metadata.dataset.changed.v1` event.
- Suggestion on `POST /v1/datasets` from tags (case-insensitive), most restrictive wins:
  `pii` -> `PII`, else `confidential` -> `CONFIDENTIAL`, else `public` -> `PUBLIC`, else `INTERNAL`.
  The register body itself does not accept `sensitivity`.
- Steward override: `PUT /v1/datasets/{urn}/columns/{column}/sensitivity` with
  `{"sensitivity": "<LEVEL>"}` (`metadata.column.sensitivity.request.v1`). Checks in order: no
  `steward` role -> 403 `FORBIDDEN`; unknown dataset or column (exact name) -> 404 `NOT_FOUND`;
  invalid body -> 400 `INVALID_REQUEST`. Success -> 200 with the updated column and an `UPDATED` event.
- Re-registering keeps steward overrides for columns still present; other columns are re-suggested
  from their current tags. Overrides of removed columns are dropped. Override bookkeeping lives in
  `GraphStore`, never in payloads.

## Develop

```bash
scripts/fetch_deps.sh            # or: export PLATFORM_CONTRACTS_PATH=/path/to/platform-contracts
python3 -m pytest -q
python3 -m flake8
```
