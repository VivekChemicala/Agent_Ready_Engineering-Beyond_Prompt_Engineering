# True architecture of the synthetic system (for the judge only)

Everything here is synthetic. Ground truth for ticket DP-1423 (column sensitivity classification and PII masking).

## Services and relations that matter for DP-1423
- `platform-contracts` holds every event JSON Schema and OpenAPI spec; semver; additive optional fields stay v1, breaking changes need v2 plus dual publish.
- `platform-sdk` pins a `platform-contracts` release and has explicit dataclass models (`Column`, `Dataset`, `Decision`) that **drop unknown fields**. Services call each other only through SDK clients, so new fields are invisible until the SDK is extended, released and bumped in consumers.
- `ingestion-service` discovers source columns (Postgres comments may carry `tags: pii,email`) and publishes `ingestion.schema.discovered.v1` to `metadata-service`.
- `metadata-service` stores columns, serves `GET /v1/datasets/{urn}` and `GET /v1/datasets/{urn}/columns`, and publishes `metadata.dataset.changed.v1`. A steward endpoint to set a column classification is new.
- `search-indexer` is a **strict** consumer of `metadata.dataset.changed.v1`: vendored schema with `additionalProperties: false`, invalid payloads go to a DLQ. It must accept the new field before metadata-service emits it.
- `lineage-service` is a tolerant consumer of `metadata.dataset.changed.v1`: verify only.
- `entitlements-service` computes access decisions (`POST /v1/access/decide`) via `MetadataClient`; it must return which columns to mask when the principal lacks `pii:read`.
- `consumption-gateway` enforces decisions (ADR-007) via `EntitlementsClient` and must mask the listed columns in returned rows.
- `transformation-service` reads columns via `MetadataClient` and must add PII-format rules for `PII` columns.
- `platform-e2e` holds cross-service tests in the `int` environment; it needs an ingest -> classify -> decide -> masked query test and a transformation PII test.

## Not impacted
- `notification-service` (transformation result emails; reads only dataset owner), `usage-metering` (access logs).
- `reporting-service` is decommissioned and archived; stale READMEs still mention it. Planning work for it is an error.
