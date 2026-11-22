# Metadata API (owned by metadata-graph)

| Method | Path | Request schema | Response |
|---|---|---|---|
| POST | `/v1/datasets` | `metadata.dataset.register.request.v1` | 201 (created) / 200 (updated): dataset |
| GET | `/v1/datasets/{urn}` | - | 200: dataset |
| GET | `/v1/datasets/{urn}/columns` | - | 200: `metadata.columns.response.v1` |
| PUT | `/v1/datasets/{urn}/owner` | `metadata.dataset.owner.request.v1` | 200: dataset (requires `steward` role) |
| PUT | `/v1/datasets/{urn}/columns/{column}/sensitivity` | `metadata.column.sensitivity.request.v1` | 200: updated column (requires `steward` role) |

Errors use `{"error": {"code": "...", "message": "..."}}` with codes
`INVALID_REQUEST` (400), `FORBIDDEN` (403), `NOT_FOUND` (404).
Every successful create/update emits `metadata.dataset.changed.v1`.

## Column sensitivity (DP-1501, contracts 2.4.0)

Columns in `metadata.columns.response.v1` and `metadata.dataset.changed.v1` carry an optional
`sensitivity`, one of `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `PII` (least to most restrictive,
`platform_contracts.SENSITIVITY_LEVELS`). A column without `sensitivity` must be treated as
`INTERNAL` (`platform_contracts.DEFAULT_SENSITIVITY`). The register request does not carry it:
metadata-graph suggests it from the column tags, and stewards override it with the `PUT` above.
