# Metadata API (owned by metadata-graph)

| Method | Path | Request schema | Response |
|---|---|---|---|
| POST | `/v1/datasets` | `metadata.dataset.register.request.v1` | 201 (created) / 200 (updated): dataset |
| GET | `/v1/datasets/{urn}` | - | 200: dataset |
| GET | `/v1/datasets/{urn}/columns` | - | 200: `metadata.columns.response.v1` |
| PUT | `/v1/datasets/{urn}/owner` | `metadata.dataset.owner.request.v1` | 200: dataset (requires `steward` role) |
| PUT | `/v1/datasets/{urn}/columns/{column}/sensitivity` | `metadata.column.sensitivity.request.v1` | 200: column (requires `steward` role) |

Errors use `{"error": {"code": "...", "message": "..."}}` with codes
`INVALID_REQUEST` (400), `FORBIDDEN` (403), `NOT_FOUND` (404).
Every successful create/update emits `metadata.dataset.changed.v1`.

Every column in responses and events carries `sensitivity` (`PUBLIC`, `INTERNAL`,
`CONFIDENTIAL`, `PII`). It is suggested from the column's source tags on registration and can be
overridden by a steward; consumers treat a column without it as `INTERNAL`.
