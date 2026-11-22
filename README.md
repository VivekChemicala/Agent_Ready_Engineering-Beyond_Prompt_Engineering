# platform-contracts

> Synthetic repository for a controlled experiment. Fictional services, no real data.

Owner: `team-platform`. Single source of truth for the wire contracts of the data platform:
JSON Schemas for HTTP payloads and events, plus the validator every service uses.

## Consumers

| Repo | How it uses the contracts |
|---|---|
| `metadata-graph` | Validates every HTTP request/response and every event it emits. Pins `platform-contracts==X.Y.Z` in `requirements.txt`. |
| `query-gateway` | Validates every metadata API response it receives (strict). Pins `platform-contracts==X.Y.Z`. |
| `usage-metering` | Does not depend on this repo (reads two event fields tolerantly). |

## Schemas (`src/platform_contracts/schemas/`)

| Schema | Used for |
|---|---|
| `metadata.dataset.register.request.v1` | `POST /v1/datasets` request body |
| `metadata.columns.response.v1` | `GET /v1/datasets/{urn}/columns` response body |
| `metadata.dataset.owner.request.v1` | `PUT /v1/datasets/{urn}/owner` request body |
| `metadata.column.sensitivity.request.v1` | `PUT /v1/datasets/{urn}/columns/{column}/sensitivity` request body |
| `metadata.dataset.changed.v1` | event emitted on every dataset create/update |

All object schemas are closed (`additionalProperties: false`), so a field that is not in the
schema is rejected by every validating producer and consumer.

Column `sensitivity` (since 2.4.0) is optional, one of `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `PII`.
A column without it must be treated as `INTERNAL`.

## Versioning rules

- The version lives in `VERSION` and `platform_contracts.__version__`; they must match.
- Adding an optional field or a new schema is backwards compatible: **minor** bump.
- Removing/renaming a field, making a field required or narrowing an enum is breaking:
  publish a new schema id (`.v2`) instead and bump **major**.
- Every release gets a `CHANGELOG.md` entry naming the Jira key.
- Payloads that were valid in the previous version must stay valid (see `tests/fixtures/`).

## Develop

```bash
python3 -m pytest -q
python3 -m flake8
```
