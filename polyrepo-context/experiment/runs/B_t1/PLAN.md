# DP-1423 — Column-level sensitivity classification and PII masking

Implementation plan (no code). Synthetic ticket and workspace, written for an experiment.

Sources used: `workspace/metadata-service/` (source, config, tests, README) and
`workspace/platform-catalog/` (components, APIs, topics, dependency graph).
The other repositories are known only from the catalog, so their internals
(including the exact entitlements and query OpenAPI paths) are assumptions;
see Open questions. The machine-readable summary is `IMPACT_ANALYSIS.json`.

## 1. Summary of the design

| Concern | Where | How |
|---|---|---|
| Source tags | ingestion-service | Add optional `comment` and `tags[]` per column to `ingestion.schema.discovered.v1`. |
| Suggestion + storage | metadata-service | Map tags to a suggested classification on ingest; store `classification`, `classification_source`, `pii_type` per column. |
| Steward override | metadata-service | New `PUT /v1/datasets/{urn}/columns/{column}/classification`. Steward values always win over suggestions. |
| Read paths | metadata-service | `GET /v1/datasets/{urn}/columns` and `metadata.dataset.changed.v1` carry the new optional fields. |
| Access decision | entitlements-service | Decision response gains `masked_columns` when requester lacks `pii:read`. |
| Enforcement | consumption-gateway | Mask values of `masked_columns` in query results. |
| transformation | transformation-service | Read classifications, apply PII-format rules to `PII` columns. |
| Contracts / clients | platform-contracts, platform-sdk | Schemas, OpenAPI and typed clients for all of the above. |

Design decisions (assumptions):

- **Effective classification** = steward value if set, else suggested value, else `null` (unclassified).
  `null` is treated as non-PII, so nothing is masked until data is classified (keeps AC6).
- **`pii_type`** (e.g. `email`, `phone`) is stored alongside `PII`, taken from the remaining tags; transformation-service uses it to pick format rules.
- **Masking decision lives in entitlements-service; enforcement in consumption-gateway.** The gateway never reads metadata-service directly, so no new dependency edges are created and `platform-catalog` needs no new entries.
- **No new topic or `v2`.** All changes are optional, additive fields. Classification changes reuse `change_type: COLUMNS_CHANGED` instead of adding a new enum value that strict consumers could reject.
- **Default tag mapping** (configurable in `metadata-service/config/settings.yaml`): `pii`, `email`, `phone`, `ssn`, `address` → `PII`; `confidential` → `CONFIDENTIAL`; `internal` → `INTERNAL`; `public` → `PUBLIC`. The most sensitive match wins (PII > CONFIDENTIAL > INTERNAL > PUBLIC).

## 2. Per-repository work items

### platform-contracts (team-platform) — code change, goes first
1. `events/ingestion.schema.discovered.v1`: add optional `columns[].comment` (string) and `columns[].tags` (array of string).
2. `events/metadata.dataset.changed.v1`: add optional `dataset.columns[].classification` (enum `PUBLIC|INTERNAL|CONFIDENTIAL|PII`, nullable), `classification_source` (`SUGGESTED|STEWARD`), `pii_type` (string, nullable). Do not change `change_type` enum.
3. `openapi/metadata-service.yaml`: extend the column object of `GET /v1/datasets/{urn}/columns`; add `PUT /v1/datasets/{urn}/columns/{column}/classification` (body `{classification, pii_type?, reason?}`; 200 updated column, 400 invalid value, 404 unknown dataset/column).
4. `openapi/entitlements-service.yaml`: add `masked_columns: string[]` (and optional `masking_reason`) to the access-decision response; if the request does not already carry requested columns, add optional `columns[]` to the request.
5. `openapi/consumption-gateway.yaml`: add `masked_columns: string[]` to the query-result response and document the mask value.
6. Add compatibility checks in CI: every new field optional; old sample payloads still validate against new schemas, new sample payloads validate against new schemas.
7. Release as a **minor** version (current pin in metadata-service is `platform-contracts==2.3.0`, so e.g. `2.4.0`).

### platform-sdk (team-platform) — code change, after contracts
1. Bump `platform-contracts` to the new minor.
2. `MetadataClient`: new optional fields on the column model; new `set_column_classification(urn, column, classification, pii_type=None, reason=None)`.
3. Entitlements client: expose `masked_columns` on the decision model, defaulting to `[]` when absent (so the SDK works against an old entitlements-service).
4. Ensure model parsing ignores unknown fields (forward compatibility).
5. Release as a minor (current pin `platform-sdk==3.4.1`, so e.g. `3.5.0`).

### ingestion-service (team-ingest) — code change, after contracts
1. In each connector's schema discovery, read the source column comment and native tags.
2. Parse `tags: a,b` out of comments into a normalised lower-case `tags[]`; pass the raw `comment` through.
3. Emit both fields in `ingestion.schema.discovered.v1` behind a flag (`emit_column_tags`), on by default once metadata-service tolerates them (it already ignores unknown keys; see `consumers.py`).
4. Unit tests per connector for parsing (`tags: pii,email`, mixed case, whitespace, no tags).

### metadata-service (team-metadata) — code change, after contracts + SDK
Files from this workspace:
1. `model.py`: add to `Column` `classification: str | None`, `classification_source: str | None`, `suggested_classification: str | None`, `pii_type: str | None`, `classified_by`, `classified_at`, `tags: list[str]`, `comment`.
2. New `classification.py`: enum, tag → classification mapping (loaded from `config/settings.yaml`), `effective()` helper.
3. `consumers.py` `on_schema_discovered`: read `tags`/`comment`, compute `suggested_classification`. **Important:** this function currently replaces `existing.columns` wholesale, which would wipe steward overrides. Change it to merge by column name: keep a STEWARD classification, refresh only the suggestion, drop removed columns, add new ones.
4. `api.py`: add the new fields to `get_columns`; add the `PUT .../columns/{column}/classification` route with validation (400/404) and steward authorization (see open questions); publish `COLUMNS_CHANGED` on change.
5. `publisher.py` `dataset_changed_payload`: include the new optional column fields in **every** change event (CREATED, UPDATED, COLUMNS_CHANGED), so consumers always see the current classification. Gate behind `publish_classification` flag.
6. `metadata_store.py` / production metadata DB: persist the new column properties; add a migration that adds them as nullable (no backfill needed for the schema).
7. `config/settings.yaml`: tag mapping and flags `classification.suggest_enabled`, `classification.publish_enabled`.
8. Requirements: bump `platform-sdk` and `platform-contracts` to the new minors.
9. Tests: extend `tests/test_consumers.py` (suggestion from tags, override preserved on re-discovery, no tags → null) and `tests/test_api.py` (fields returned, PUT happy path, 400, 404, event published).
10. Housekeeping: fix README consumer list (reporting-service is decommissioned; add lineage-service and search-indexer).
11. Optional: one-off backfill job that re-reads tags for existing datasets (or triggers re-discovery) so existing columns get suggestions.

### entitlements-service (team-access) — code change, after metadata-service publishes fields
1. Bump SDK/contracts.
2. Keep a per-dataset column classification cache fed by `metadata.dataset.changed.v1`; on cache miss, call `GET /v1/datasets/{urn}/columns` (both integrations already exist in the catalog).
3. Ensure the `pii:read` grant type exists (create if missing) and grant it to current PII-authorised users/groups **before** enforcement.
4. In the decision: `masked_columns` = requested (or all) columns whose effective classification is `PII`, if the requester lacks `pii:read`; else `[]`.
5. Flag `masking.decisions_enabled` (when off, always return `[]`).
6. Tests: with/without grant, unclassified columns, cache refresh on event, metadata-service unavailable (decide fail-open vs fail-closed; see risks).

### consumption-gateway (team-consumption) — code change, after entitlements
1. Bump SDK.
2. Pass requested columns in the decision call (if supported) and read `masked_columns` (absent → `[]`).
3. Apply masking to result rows for those columns, keeping column names, order and types; add `masked_columns` to the response.
4. Mode flag `masking.mode = off | shadow | enforce`. `shadow` computes and logs/metrics the columns it would mask without changing values.
5. Make sure masking also applies to every output path (exports, cached results, pagination).
6. Tests: masked vs unmasked requester, null handling, typed columns (mask as null or fixed string), shadow mode leaves values unchanged.

### transformation-service (team-transformation) — code change, after metadata-service exposes fields
1. Bump SDK.
2. When a run starts (on `ingestion.batch.landed.v1`), fetch columns via `MetadataClient` and select columns with effective classification `PII`.
3. Add PII-format rule set keyed by `pii_type` (email, phone, national id, …), with a generic rule when `pii_type` is unknown. Results flow through the existing `transformation.result.published.v1` with no schema change (assumption).
4. Flag `pii_rules_enabled`; start in report-only mode (rules computed but excluded from the dataset score) to avoid surprise quality-score drops and owner notifications.
5. Tests: PII column gets rules, non-PII column does not, unknown `pii_type`.

### platform-e2e (team-platform) — code change (new tests)
See section 4.

### lineage-service, search-indexer, notification-service — verify only
1. Upgrade `platform-contracts` (search-indexer) or `platform-sdk` (lineage, notification) to the new minors.
2. Run the existing suite plus a consumer contract test that feeds a new-shape `metadata.dataset.changed.v1` (or new-shape columns response) and asserts no error.
3. search-indexer is the highest risk because it validates against platform-contracts directly; if its pinned version uses `additionalProperties: false`, it must upgrade **before** metadata-service turns on `classification.publish_enabled`.

### platform-catalog — verify only
No new topics, APIs or edges in this design. If any team adds one (e.g. masking audit in `consumption.access.logged.v1`), update its entity in the same PR, per the catalog README. Optionally fix the existing drift (metadata-service depends on platform-contracts per `requirements.txt` but its entity does not list it).

## 3. Ordering and rollout

Every step is backward compatible; each can be deployed and rolled back on its own.

| Step | Repo | Action | Depends on |
|---|---|---|---|
| 1 | platform-contracts | Release minor with optional fields + new endpoint spec | – |
| 2 | platform-sdk | Release minor with new fields/calls, tolerant defaults | 1 |
| 3 | lineage-service, search-indexer, notification-service, entitlements-service, consumption-gateway, transformation-service | Upgrade contracts/SDK only; run verify tests; deploy | 1, 2 |
| 4 | ingestion-service | Emit `comment`/`tags` | 1 |
| 5 | metadata-service | Deploy storage, merge logic, PUT endpoint, GET fields; then enable `suggest_enabled`, then `publish_enabled` | 1, 2, 3 (consumers tolerant) |
| 6 | metadata-service | Optional backfill; stewards review suggestions | 4, 5 |
| 7 | entitlements-service | Create/assign `pii:read`; deploy decision logic; enable `decisions_enabled` | 5 |
| 8 | transformation-service | Deploy PII rules in report-only, then count in score | 5 |
| 9 | consumption-gateway | Deploy masking in `shadow`; compare would-mask counts; switch to `enforce` per domain/tenant | 7 |
| 10 | platform-catalog | Confirm no edge changes | – |

Steps 4 and 2–3 can run in parallel. Steps 7 and 8 can run in parallel. Step 9 must not go to `enforce` until `pii:read` is assigned to everyone who currently needs PII access.

Rollback: turn off the relevant flag (`masking.mode=off`, `decisions_enabled=false`, `publish_enabled=false`, `pii_rules_enabled=false`). Because all fields are optional, older versions of any service keep working with newer peers.

## 4. Cross-repository testing

**Contract tests (CI, per repo)**
- platform-contracts: schema compatibility check (old samples validate against new schemas; new fields optional; enum `change_type` unchanged).
- Producer side: metadata-service validates generated `dataset.changed` payloads and GET/PUT responses against the new contracts; ingestion-service validates `schema.discovered` payloads; entitlements validates decision responses; consumption-gateway validates query responses.
- Consumer side (consumer-driven, e.g. Pact-style or sample payload fixtures published from platform-contracts):
  - metadata-service consumes old and new `schema.discovered`.
  - entitlements, lineage, search-indexer consume old and new `dataset.changed`.
  - SDK `MetadataClient` against old and new columns response; SDK entitlements client against decision with and without `masked_columns`.
  - consumption-gateway against decision with and without `masked_columns`.
  - transformation-service against columns response with and without classification.

**Integration / end-to-end (platform-e2e, integration environment)**
1. Ingest a synthetic source where `email` has comment `tags: pii,email` → GET columns shows `suggested_classification=PII`, `pii_type=email`; a `dataset.changed` event carries it.
2. Steward PUTs `email` → `CONFIDENTIAL`; re-ingest the same schema → override preserved.
3. Steward sets a column to `PII`; user without `pii:read` queries → column masked and listed in `masked_columns`; user with `pii:read` → unmasked.
4. Unclassified dataset → no masking for anyone (no regression).
5. transformation run on a batch with PII columns → PII-format rules executed and reported.
6. Mixed-version test: new metadata-service with previous release of entitlements/consumption-gateway, and vice versa, to prove AC6.
7. Shadow-mode test: `masking.mode=shadow` leaves values unchanged but records would-mask metrics.

## 5. Risks

- **Override loss on re-ingest**: `on_schema_discovered` overwrites the column list today; without the merge change, every re-discovery erases steward classifications.
- **Strict schema validation** in search-indexer (direct platform-contracts dependency) or others could reject events with new fields if they are not upgraded first.
- **Access regressions**: enforcing masking before `pii:read` is assigned would hide data from legitimate users. Mitigated by shadow mode and staged enforcement.
- **Fail-open vs fail-closed**: if entitlements cannot get classifications (metadata-service down, cache cold), it must either deny/mask (safe, but availability impact) or allow (keeps AC6, but leaks PII). Needs a decision from data governance.
- **Masking bypass**: other output paths (exports, caches, direct warehouse access) not covered by consumption-gateway.
- **Tag quality**: wrong or missing source tags give wrong suggestions; stewards must review. Untagged existing data stays unmasked until classified.
- **transformation noise**: new PII rules may lower quality scores and trigger notification-service emails; hence report-only start.
- **Catalog/README drift**: the metadata-service README lists a decommissioned consumer, so other docs may also be stale; rely on `topics.yaml`/catalog and confirm with owning teams.

## 6. Open questions

1. Exact entitlements access-decision endpoint and request shape (path in this plan is inferred; spec is `platform-contracts/openapi/entitlements-service.yaml`, not in this workspace). Does it already receive requested columns?
2. Exact query-api results endpoint and acceptable mask representation (null, `***`, format-preserving)?
3. Does a `pii:read` grant exist? Who must receive it before enforcement?
4. Do connectors already capture source column comments/tags?
5. Should SUGGESTED PII (not steward-confirmed) mask and trigger PII transformation rules? (Assumed yes.)
6. Default for existing/untagged columns: null (assumed) or `INTERNAL`? Is a backfill required before enforcement?
7. How is the steward override authorised in metadata-service?
8. Who owns the tag → classification mapping?
9. Which PII-format rules per `pii_type`, and should transformation results change `transformation.result.published.v1`? (Assumed no.)
10. Should masked columns be recorded in `consumption.access.logged.v1` for audit? (Assumed out of scope; would affect usage-metering.)
11. Fail-open or fail-closed when classification data is unavailable?
