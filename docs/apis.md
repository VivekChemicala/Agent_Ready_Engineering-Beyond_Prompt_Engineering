# Metadata API (owned by metadata-graph)

| Method | Path | Request schema | Response |
|---|---|---|---|
| POST | `/v1/datasets` | `metadata.dataset.register.request.v1` | 201 (created) / 200 (updated): dataset |
| GET | `/v1/datasets/{urn}` | - | 200: dataset |
| GET | `/v1/datasets/{urn}/columns` | - | 200: `metadata.columns.response.v1` |
| PUT | `/v1/datasets/{urn}/owner` | `metadata.dataset.owner.request.v1` | 200: dataset (requires `steward` role) |
| PUT | `/v1/datasets/{urn}/columns/{column}/sensitivity` | `metadata.column.sensitivity.request.v1` | 200: updated column `{name, type, tags, sensitivity}` (requires `steward` role) |

Errors use `{"error": {"code": "...", "message": "..."}}` with codes
`INVALID_REQUEST` (400), `FORBIDDEN` (403), `NOT_FOUND` (404).
Every successful create/update emits `metadata.dataset.changed.v1`.

Column `sensitivity` (since 2.4.0): `PUBLIC`, `INTERNAL`, `CONFIDENTIAL` or `PII`. It is optional
in `metadata.columns.response.v1` and `metadata.dataset.changed.v1`; a column without it is `INTERNAL`.
On `POST /v1/datasets` it is suggested from the column tags (`pii` -> `PII`, `confidential` ->
`CONFIDENTIAL`, `public` -> `PUBLIC`, else `INTERNAL`; most restrictive wins). A steward override
(`PUT .../sensitivity`) is kept on re-registration while the column exists, and emits an `UPDATED`
`metadata.dataset.changed.v1` event.
