# DP-1423 - Column-level sensitivity classification and PII masking: implementation plan

> Synthetic: the ticket, repositories and services are synthetic examples written for an experiment.
> Companion file: `IMPACT_ANALYSIS.json` (repositories, dependency edges, contracts, open questions).

## 1. Summary

The ticket is assigned to team-metadata, but the data path crosses eight repositories:

```
source tags ──> ingestion-service ──(ingestion.schema.discovered.v1 + columns[].tags)──> metadata-service
                                                                                          │  stores classification,
                                                                                          │  steward PUT override
                     ┌──────────────(GET /v1/datasets/{urn}/columns + classification)─────┤
                     │                                                                    │
          entitlements-service ──(POST /v1/access/decide + masked_columns)──> consumption-gateway ──> masked rows
                     │                                                                    │
          transformation-service (PII-format rules) <──(GET columns)───────────────────────────────────┤
                                                                                          │
          search-indexer / lineage-service / reporting-service <──(metadata.dataset.changed.v1 + classification)
```

Shared layers: every service talks through `platform-sdk` 3.4.1, which bundles `platform-contracts` 2.3.0.
All contract changes are additive (optional fields plus one new endpoint), so no `.v2` topic or `/v2` API is needed,
with one hard exception: **search-indexer validates `metadata.dataset.changed.v1` against a vendored 2.1.0 schema with
`additionalProperties: false`**. If metadata-service adds a column field before search-indexer is updated, every
change event goes to `search-indexer.dlq` and the catalog index stops updating. That fixes the rollout order.

## 2. Decisions and assumptions

| # | Decision / assumption |
|---|---|
| A1 | Classification enum: `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `PII`. Field is nullable; `null` = not yet classified (treated as not masked). |
| A2 | ingestion-service forwards raw source tags (`columns[].tags`); metadata-service owns the tag -> classification mapping, so mapping policy lives with the owning team. Mapping: tag `pii` -> `PII`; else `confidential` -> `CONFIDENTIAL`; else `internal` -> `INTERNAL`; else `public` -> `PUBLIC`; else no suggestion. Highest sensitivity wins. |
| A3 | Each column stores `classification_source` = `SUGGESTED` or `STEWARD`. Re-discovery may update a `SUGGESTED` value but never overwrites a `STEWARD` value. |
| A4 | Steward override endpoint: `PUT /v1/datasets/{urn}/columns/{column}/classification`, body `{"classification": "...", "reason": "..."}`. |
| A5 | Classification changes are published on `metadata.dataset.changed.v1` with existing `change_type: COLUMNS_CHANGED`. A new enum value would break search-indexer's strict enum. |
| A6 | `pii:read` is a literal grant string, held globally (not per domain/dataset) for v1. |
| A7 | Masking applies to columns classified `PII`, whether `SUGGESTED` or `STEWARD` (fail closed). `CONFIDENTIAL` is classified but not masked in this ticket. |
| A8 | Entitlements decides, gateway enforces (current platform split). The decision returns `masked_columns: [names]`; gateway replaces those values with `"****"` for strings and `null` for other types, and returns `masked_columns` in the response. |
| A9 | The PII-format rule is chosen from the PII subtype tag (`email`, `phone`, ...). PII columns without a known subtype get no format rule in v1 (open question whether a dedicated `pii_type` field is needed). |
| A10 | `consumption.access.logged.v1` is not changed (keeps usage-metering out of scope). |

## 3. Per-repository work items

### 3.1 platform-contracts (team-platform) - release 2.4.0 (minor)
- `events/ingestion.schema.discovered.v1.json`: add optional `columns[].tags: string[]`.
- `events/metadata.dataset.changed.v1.json`: add optional `columns[].classification` (nullable enum per A1) and `columns[].tags`. Do not add a `change_type` value.
- `openapi/metadata-service.yaml` (1.4.0 -> 1.5.0): `Column` gains `classification`, `classification_source`, `tags`; add `PUT /v1/datasets/{urn}/columns/{column}/classification` (200 Column, 400 invalid value, 404 unknown dataset/column).
- `openapi/entitlements-service.yaml` (1.2.0 -> 1.3.0): `Decision` gains `masked_columns: string[]` (default `[]`).
- `openapi/consumption-gateway.yaml` (2.0.0 -> 2.1.0): 200 response gains optional `masked_columns: string[]`; document mask values.
- Add example payloads (old and new) and a CI check that every **old** example still validates against the **new** schema (backward compatibility) and no field becomes required.
- `VERSION` -> 2.4.0.

### 3.2 platform-sdk (team-platform) - release 3.5.0 (minor)
- `pyproject.toml`: `platform-contracts==2.4.0`, version 3.5.0.
- `metadata.py`: `Column` gains `classification: str | None = None`, `classification_source: str | None = None`, `tags: tuple[str, ...] = ()` (defaults keep existing constructors working); `get_columns` parses them with `.get()`; add `MetadataClient.set_column_classification(urn, column, classification, reason=None)`.
- `entitlements.py`: `Decision` gains `masked_columns: tuple[str, ...] = ()`; `decide` parses `body.get("masked_columns", [])`. (Also consider adding the already-missing `policy_id`.)
- Optionally export a `Classification` constants/enum.
- Tests: parsing old responses (fields absent) and new responses; unknown classification value does not crash parsing.

### 3.3 search-indexer (team-discovery) - must ship before metadata-service emits the field
- Re-vendor `schemas/metadata.dataset.changed.v1.json` from platform-contracts 2.4.0, keeping `additionalProperties: false` but allowing `classification` and `tags` on columns.
- Update the title/README "vendored from" note to 2.4.0.
- Tests: event with `classification`/`tags` is indexed (not DLQ'd); event with a truly unknown field still goes to DLQ (keeps `test_unknown_field_goes_to_dlq`).
- Indexing classification as a facet is optional / out of scope (open question).
- Suggested follow-up for team-discovery: a CI job that diffs the vendored schema against the latest platform-contracts release to catch the next additive change early.

### 3.4 ingestion-service (team-ingest)
- `connectors/postgres.py`: parse `column_comment` (`tags: pii,email` -> `["pii", "email"]`; case-insensitive, trimmed, tolerant of missing/other comments) and include `tags` in each column dict.
- `publisher.py`: no signature change; columns now carry `tags`.
- Upgrade to platform-sdk 3.5.0 (the bundled 2.4.0 schema documents `tags`; the 2.3.0 schema has no `additionalProperties: false`, so it would also pass, but upgrade for clarity).
- Tests: update `test_postgres.py` expected output to include `tags`; add cases for no comment, comment without `tags:`, mixed case/whitespace.

### 3.5 metadata-service (team-metadata, ticket owner)
- `model.py`: `Column` gains `classification: str | None = None`, `classification_source: str | None = None`, `tags: list[str] = []` (via `field(default_factory=list)`).
- New `classification.py`: tag -> classification mapping (A2), configurable via `config/settings.yaml` (`classification.tag_map`).
- `consumers.py` `on_schema_discovered`: today it **replaces** the column list wholesale (losing descriptions too). Change to merge by column name: keep `STEWARD` classifications (and descriptions); recompute `SUGGESTED` from new tags; new columns get a suggestion; removed columns drop.
- `api.py`: `get_columns` returns `classification`, `classification_source`, `tags`; add `PUT /v1/datasets/{urn}/columns/{column}/classification` (validate enum, set `classification_source=STEWARD`, upsert, publish `COLUMNS_CHANGED`, audit log who/why).
- `publisher.py`: include `classification` and `tags` per column, behind a feature flag `features.emit_column_classification` (default `false`) in `config/settings.yaml` so the field is only emitted after search-indexer (and reporting-service) are confirmed ready.
- Metadata DB: persist the new column properties (no migration of existing nodes needed; absent = `null`).
- `requirements.txt`: platform-sdk 3.5.0 and platform-contracts 2.4.0 (bump together; the SDK pins contracts exactly).
- README: fix the consumer list for `metadata.dataset.changed.v1` (it names entitlements-service and reporting-service but not search-indexer and lineage-service).
- Tests: suggestion from tags; steward override survives re-discovery; PUT validation/404; GET returns the fields; payload with flag on validates against the 2.4.0 schema **and** the search-indexer vendored schema; flag off produces today's payload.
- Backfill job/script: re-request schema discovery (or re-run suggestion from stored tags) for existing datasets so PII columns are classified before masking is relied on.

### 3.6 entitlements-service (team-access)
- Upgrade to platform-sdk 3.5.0.
- `policies.py`: `Decision` gains `masked_columns: list[str]`. After an allow decision, if the principal does not hold `pii:read`, set `masked_columns` to the names of columns with `classification == "PII"` (from `metadata.get_columns(urn)`); otherwise `[]`. Deny decisions return `[]`.
- Cache columns alongside dataset attributes; `consumers.py` already invalidates the cache on every `metadata.dataset.changed.v1` (including `COLUMNS_CHANGED`), so classification overrides take effect on the next decision. Add a TTL as a safety net against missed events.
- Failure mode: if columns cannot be fetched, fail closed (deny with reason `CLASSIFICATION_UNAVAILABLE`) or mask all columns - pick with team-access (open question); do not return an empty `masked_columns`.
- `api.py`: unchanged signature; `asdict` now includes `masked_columns`.
- Tests: with and without `pii:read`; dataset with no PII; dataset and domain grants; cache invalidation on `COLUMNS_CHANGED`.

### 3.7 consumption-gateway (team-consumption)
- Upgrade to platform-sdk 3.5.0 (required: 3.4.1's `Decision` drops `masked_columns`, which would silently return unmasked data).
- `query.py`: after `warehouse.execute`, replace values of any row key in `decision.masked_columns` with the mask (A8); return `{"rows": rows, "masked_columns": [...]}`.
- Make masking case-insensitive on column names; flag (and in v1, document) that aliases/expressions are not caught (open question; option to deny queries that reference masked columns in expressions).
- `consumption.access.logged.v1` payload unchanged.
- Tests: masked rows without `pii:read`, unmasked with it, response field present, decision without `masked_columns` (old entitlements) behaves as today.

### 3.8 transformation-service (team-transformation)
- Upgrade to platform-sdk 3.5.0.
- `rules/pii.py`: `pii_email_format`, `pii_phone_format` (and others as agreed); register in `RULES`.
- `runner.py`: in addition to `DEFAULT_BINDINGS` by `data_type`, for `col.classification == "PII"` add the format rule matching the subtype in `col.tags`. Consider exposing classification-based bindings via the existing `GET/POST /v1/rules` later (no contract change now).
- Results keep the shape `{column, rule, passed}`; never include raw values.
- Tests: PII column gets format rule; non-PII column unchanged; invalid emails fail.

### 3.9 platform-e2e (team-platform; each team contributes its suite)
- `test_ingest_to_metadata.py`: ingest a table whose `email` column comment is `tags: pii,email` -> `get_columns` shows `classification == "PII"`, `classification_source == "SUGGESTED"`.
- New `test_classification_override.py`: steward PUT -> GET columns reflects it -> `metadata.dataset.changed.v1` carries it -> search-indexer indexed (no DLQ) -> re-ingest does not revert it.
- `test_access_flow.py`: add `bob` (domain grant, no `pii:read`) -> `email` masked and `masked_columns == ["email"]`; `carol` with `pii:read` -> unmasked; existing two tests unchanged.
- `test_transformation_flow.py`: landed batch with bad emails -> transformation results contain `pii_email_format` failing, quality score attached.

### 3.10 Verify only
- **lineage-service**: tolerant reader of `metadata.dataset.changed.v1`; re-run tests on platform-sdk 3.5.0 and in the `int` environment with the flag on.
- **notification-service**: re-run on platform-sdk 3.5.0; expect more below-threshold emails once PII rules lower scores - warn dataset owners.
- **reporting-service** (inferred name, not in workspace): confirm with its owners that it tolerates new column fields before enabling the metadata-service flag.
- **usage-metering**: not impacted (`consumption.access.logged.v1` unchanged).

## 4. Ordering and dependencies

| Step | Repo | Depends on | Notes |
|---|---|---|---|
| 1 | platform-contracts 2.4.0 | - | All schema/OpenAPI changes, compatibility CI. |
| 2 | platform-sdk 3.5.0 | 1 | New fields default to empty, so it is a drop-in for every service. |
| 3a | search-indexer | 1 | Re-vendored schema; **deploy before step 5b**. |
| 3b | reporting-service check | 1 | Confirm tolerance (or update) before 5b. |
| 4 | ingestion-service | 2 | Emits `tags`; metadata-service 3.4.1 ignores unknown keys, so safe in any order with 5a. |
| 5a | metadata-service (store, suggest, PUT, GET; flag off) | 2 | Classification visible via REST; no event change yet. |
| 5b | metadata-service flag `emit_column_classification` on | 3a, 3b | Events now carry classification. |
| 5c | Backfill classifications | 4, 5a | Run before masking is announced as enforced. |
| 6 | entitlements-service | 2, 5a | Returns `masked_columns`; older gateways ignore it. |
| 7 | consumption-gateway | 2, 6 | Enforces masking - this is the point PII masking becomes live. |
| 8 | transformation-service | 2, 5a | Independent of 6/7. |
| 9 | platform-e2e suites | land with each step; full run after 7 and 8 | |
| 10 | Verify-only repos | 2, 5b | Re-run tests, observe `int`. |

Steps 3a/3b, 4, 5a, and 8 can proceed in parallel once 2 is released. 6 and 7 are sequential.

## 5. Compatibility and rollout (AC6: no breaking change, no downtime)

- **Additive only**: every new field is optional with a safe default; no field is renamed, removed or made required; no new `change_type` value; no `.v2` topic or `/v2` endpoint.
- **Readers before writers**: search-indexer (strict reader) and reporting-service are updated before metadata-service emits the new event field; the SDK (which drops unknown fields) is upgraded in a consumer before that consumer relies on a new field.
- **Feature flags**: metadata-service `emit_column_classification`; consumption-gateway `masking.enabled` (start in shadow mode: compute and log which columns would be masked, return unmasked, then enable). Entitlements can ship `masked_columns` without effect until the gateway enforces it.
- **Security caveat during rollout**: until step 7 is live, PII is still returned unmasked - same as today, so no regression, but communicate the go-live date. Once live, a gateway rollback re-exposes PII; prefer rolling forward or disabling access instead.
- **Rolling deploys**: every service accepts both old and new payloads, so mixed versions during a rolling deploy are safe.
- **Monitoring**: `search-indexer.dlq` rate (alert on any increase after 5b), entitlements decision latency (extra columns lookup), cache hit rate, gateway masked-response count, transformation score shift and notification volume.
- **Rollback**: flags off in reverse order; contracts/SDK releases stay (additive).

## 6. Cross-repository testing

**Contract tests**
- platform-contracts CI: new schemas validate old and new example payloads; OpenAPI diff check reports only additive changes (e.g. `oasdiff breaking` or equivalent).
- Producer-side: ingestion-service and metadata-service validate published payloads against the 2.4.0 schemas (the SDK already validates on publish) and, for metadata-service, also against search-indexer's vendored schema as a consumer-driven contract.
- Consumer-side: search-indexer, lineage-service, entitlements-service tests with recorded old and new `metadata.dataset.changed.v1` payloads; platform-sdk tests with old and new HTTP responses for `GET columns` and `POST /v1/access/decide`; consumption-gateway test with old (no `masked_columns`) and new decisions.

**Integration / end-to-end (platform-e2e in `int`)**
- Suites in 3.9, run on every step's deploy to `int` and nightly.
- Mixed-version run: new metadata-service with old entitlements/gateway, and vice versa, to prove rolling-deploy safety.
- Negative checks: `search-indexer.dlq` empty after classification events; no PII values in transformation results or logs.

## 7. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| search-indexer strict schema rejects new field | Catalog search stops updating (all events to DLQ) | Ship 3a first; flag in metadata-service; DLQ alert; replay DLQ if hit. |
| Unknown consumer (reporting-service) also strict | Silent breakage | Confirm with owners before 5b; same flag. |
| SDK dataclasses drop new fields | Gateway on SDK 3.4.1 silently returns PII unmasked | Gateway requires SDK >= 3.5.0; e2e asserts masking. |
| Re-discovery overwrites columns | Steward overrides (and descriptions) lost | Merge-by-name in `on_schema_discovered`; e2e override-survives-reingest test. |
| SQL aliases/expressions bypass name-based masking | PII leak | Documented limitation; consider denying or warehouse-native masking (open question). |
| Unclassified legacy columns | PII not masked | Backfill (5c) before declaring enforcement; dashboards of unclassified columns. |
| Entitlements extra lookup | Higher decision latency | Cache columns with invalidation + TTL. |
| New transformation rules lower scores | Alert noise from notification-service | Announce; optionally weight or phase in PII rules. |
| SDK pins contracts exactly | Dependency conflicts in metadata-service (pins both) | Bump both pins together. |

## 8. Open questions

See `open_questions` in `IMPACT_ANALYSIS.json`; the most important for go-live:
1. Scope of `pii:read` (global vs domain/dataset) - assumed global.
2. Enforce `SUGGESTED` PII for masking - assumed yes.
3. Mask representation and handling of SQL aliases/expressions in consumption-gateway.
4. Other data access paths that bypass consumption-gateway.
5. Steward authorization for the PUT endpoint.
6. Ownership and schema strictness of reporting-service.
7. Entitlements behaviour when column classifications cannot be fetched (deny vs mask all).
