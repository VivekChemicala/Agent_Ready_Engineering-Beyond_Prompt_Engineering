# Metadata API (owned by metadata-graph)

| Method | Path | Request schema | Response |
|---|---|---|---|
| POST | `/v1/datasets` | `metadata.dataset.register.request.v1` | 201 (created) / 200 (updated): dataset |
| GET | `/v1/datasets/{urn}` | - | 200: dataset |
| GET | `/v1/datasets/{urn}/columns` | - | 200: `metadata.columns.response.v1` |
| PUT | `/v1/datasets/{urn}/owner` | `metadata.dataset.owner.request.v1` | 200: dataset (requires `steward` role) |
| PUT | `/v1/datasets/{urn}/columns/{column}/sensitivity` | `metadata.dataset.column.sensitivity.request.v1` | 200: column (requires `steward` role) |

Errors use `{"error": {"code": "...", "message": "..."}}` with codes
`INVALID_REQUEST` (400), `FORBIDDEN` (403), `NOT_FOUND` (404).
Every successful create/update emits `metadata.dataset.changed.v1`.

Columns carry an optional `sensitivity` (`PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `PII`); an absent
`sensitivity` means `INTERNAL`. For the sensitivity override, an unknown dataset or column returns
404 `NOT_FOUND`, and a successful override emits `metadata.dataset.changed.v1` with change `UPDATED`.
