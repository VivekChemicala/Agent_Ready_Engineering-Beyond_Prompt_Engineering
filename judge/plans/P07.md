# DP-1423 — Column-level sensitivity classification and PII masking: implementation plan

> Synthetic ticket and synthetic workspace, written for an experiment. Machine-readable companion: `IMPACT_ANALYSIS.json`.

## 1. Summary

Classification originates in **ingestion-service** (source tags), is stored and owned by **metadata-graph**,
is propagated to **entitlements-service** (which decides which columns to mask) and enforced by
**query-gateway**, and is used by **dq-engine** for PII-format rules. All shared shapes live in
**platform-contracts** and are wrapped by **platform-sdk**. Every contract change is **additive**; enforcement
is switched on with flags only after all consumers are verified.

```
ingestion-service --(ingestion.schema.discovered.v1 + tags)--> metadata-graph
metadata-graph --(metadata.dataset.changed.v1 + classification)--> entitlements-service, search-indexer, lineage-service
metadata-graph --(GET /v1/datasets/{urn}/columns + classification)--> dq-engine, entitlements-service, notification-service, platform-sdk
steward --(PUT /v1/datasets/{urn}/columns/{column}/classification)--> metadata-graph
query-gateway --(entitlements access decision + masked_columns)--> entitlements-service
```

## 2. Sources and assumptions

Evidence used: the `metadata-graph` source and the `platform-catalog` repository (components, APIs, topics,
dependency graph). The other repositories' code and the OpenAPI/JSON Schema files in `platform-contracts`
are **not** in the workspace, so their internals are assumptions.

Assumptions (decisions taken without asking):
- **A1** Repository names are the catalog component names (`example-org/<name>`), per `platform-catalog/README.md`.
- **A2** The catalog (`topics.yaml`) is authoritative over the `metadata-graph` README: consumers of
  `metadata.dataset.changed.v1` are entitlements-service, lineage-service and search-indexer. `reporting-service`
  (listed in the README) is decommissioned/archived and is out of scope; the README will be corrected.
- **A3** Classification enum: `PUBLIC | INTERNAL | CONFIDENTIAL | PII`. Absent/`null` means *unclassified*.
- **A4** Unclassified columns are **not** masked (keeps existing consumers working, AC6). Fail-closed is an open question for governance.
- **A5** Steward overrides always win over suggestions; re-ingestion never overwrites a `STEWARD` classification.
- **A6** Classification changes are published as `change_type: COLUMNS_CHANGED` (no new enum value, to avoid breaking consumers that switch on `change_type`).
- **A7** We stay on `*.v1` topics and existing `/v1` paths; no v2 is needed because all changes are additive.
- **A8** The exact entitlements access-decision and query-api result paths are not visible; they are referred to by role.
- **A9** Version bumps are minor: platform-contracts `2.3.0 -> 2.4.0`, platform-sdk `3.4.1 -> 3.5.0` (current pins from `metadata-graph/requirements.txt`).

## 3. Per-repository work items

### 3.1 platform-contracts (team-platform) — code change, **step 1**
- `ingestion.schema.discovered.v1` schema: add optional `columns[].tags: string[]` and `columns[].comment: string`.
- `metadata.dataset.changed.v1` schema: add optional `columns[].classification` (enum + null) and `columns[].classification_source` (`SUGGESTED|STEWARD`).
- `openapi/metadata-graph.yaml`: add optional classification fields to the columns response; add
  `PUT /v1/datasets/{urn}/columns/{column}/classification` (200 / 400 `INVALID_CLASSIFICATION` / 403 / 404 `NOT_FOUND`).
- `openapi/entitlements-service.yaml`: add `masked_columns: string[]` (+ optional `masking_reason`) to the access-decision response; add `pii:read` to the grant vocabulary if grants are enumerated there.
- `openapi/query-gateway.yaml`: add optional `masked_columns` to the results response; document mask values.
- Add a shared `Classification` definition reused by all of the above.
- Make sure every new field is optional and no `required`/`enum` on existing fields is tightened. Add a schema-compat check in CI (old sample payloads validate against the new schemas; new payloads validate against the old schemas if consumers use `additionalProperties: false` — see risk R1).
- Release `2.4.0`.

### 3.2 platform-sdk (team-platform) — code change, **step 2** (after 3.1)
- Bump `platform-contracts` to `2.4.0`.
- `MetadataClient`: expose `classification`, `classification_source`, `suggested_classification` on column models (optional, default `None`); add `set_column_classification(urn, column, classification, reason=None)`.
- Entitlements client: expose `masked_columns` (default `[]`) on the decision model.
- Event helpers: ensure parsing ignores unknown fields (tolerant reader) so older services survive future additions.
- Unit tests against the new and the old contract fixtures. Release `3.5.0`.

### 3.3 ingestion-service (team-ingest) — code change, **step 3a** (after 3.1; parallel with 3.4)
- Read source column comments/tags in each connector; parse `tags: a,b` from comments (case-insensitive, trimmed, de-duplicated) into `columns[].tags`; include raw `comment`.
- Emit the new optional fields in `ingestion.schema.discovered.v1`. Behind flag `emit_column_tags` (default on in dev, staged in prod).
- Tests: parser cases (no tags, malformed, duplicates, mixed case), event-schema validation against platform-contracts 2.4.0.

### 3.4 metadata-graph (team-graph) — code change, **step 3b** (after 3.1/3.2)
Files: `src/metadata_graph/model.py`, `consumers.py`, `api.py`, `publisher.py`, `graph_store.py`, `config/settings.yaml`, `requirements.txt`, `README.md`, `tests/`.
- **Model** (`model.py`): add `Column.classification: str | None`, `classification_source: str | None`, `suggested_classification: str | None`, `tags: list[str]`, `classified_by`, `classified_at`.
- **Suggestion** (new small module, e.g. `classification.py`): pure function `suggest(tags) -> classification | None` with a configurable mapping in `config/settings.yaml` (e.g. `pii`, `email`, `phone`, `ssn` -> `PII`; `confidential` -> `CONFIDENTIAL`; `internal` -> `INTERNAL`; `public` -> `PUBLIC`; highest sensitivity wins).
- **Consumer** (`consumers.py:on_schema_discovered`): read optional `tags`; **merge columns by name instead of replacing the list** (today `existing.columns = columns` would drop any stored classification and description). For each column: keep `STEWARD` classification; otherwise set `suggested_classification` and `classification` from tags with source `SUGGESTED`. Missing `tags` => leave as is (old ingestion versions keep working).
- **API** (`api.py`): add classification fields to `GET /v1/datasets/{urn}/columns`; add `PUT /v1/datasets/{urn}/columns/{column}/classification` (validate enum, 404 for unknown dataset/column, record steward + timestamp, `store.upsert`, `publish_dataset_changed(ds, "COLUMNS_CHANGED")`). Add a steward authorization check (see Q5). Optional: `DELETE` to revert to suggested.
- **Publisher** (`publisher.py`): add `classification` and `classification_source` to each column in `dataset_changed_payload`. Guard with flag `publish_column_classification` so it can be enabled after consumers are verified (step 5).
- **Store**: persist new column properties in the graph DB (additive property; no migration of existing nodes required, absent = unclassified).
- **Backfill job** (one-off): re-derive suggestions for existing datasets from the latest discovered schema or trigger a re-discovery; emits `COLUMNS_CHANGED` events at a throttled rate.
- **Housekeeping**: bump `platform-sdk==3.5.0`, `platform-contracts==2.4.0`; fix README consumer list (remove reporting-service, add lineage-service and search-indexer).
- **Tests**: suggestion mapping; merge preserves steward override and description on re-ingestion; event without `tags` still works (existing `test_schema_discovered_creates_dataset` unchanged and green); PUT validation/404; GET returns fields; payload validates against `metadata.dataset.changed.v1` 2.4.0 schema; `test_get_columns` unchanged and green.

### 3.5 entitlements-service (team-access) — code change, **step 4** (after 3.2, 3.4)
- Consume classifications from `metadata.dataset.changed.v1` into its local dataset/column cache; fall back to `GET /v1/datasets/{urn}/columns` on cache miss (both edges already exist in the catalog).
- Support the `pii:read` grant (add grant type if missing — Q6).
- Access decision: compute `masked_columns` = columns classified `PII` when the principal lacks `pii:read` (scoped per dataset/domain if grants are scoped). Return `[]` otherwise. Allow/deny logic unchanged.
- Flag `return_masked_columns` (off -> always `[]`).
- Tests: decision matrix (with/without grant, no PII, unclassified, stale cache), consumer tolerant of events without classification.

### 3.6 query-gateway (team-serving) — code change, **step 5** (after 3.5)
- Upgrade platform-sdk to 3.5.0; read `masked_columns` from the decision.
- Apply masking to result rows before serialization: type-preserving mask (strings -> fixed token, e.g. `"***MASKED***"`; other types -> `null`) — final strategy per Q8. Add `masked_columns` to response metadata.
- Map result columns to source columns (direct projections first; for derived expressions referencing a masked column, mask the derived column — conservative).
- Modes via flag `pii_masking_mode`: `off` -> `shadow` (compute and log/metric would-be-masked columns, return unmasked) -> `enforce` (per domain allow-list, then global).
- `gateway.access.logged.v1` unchanged (optional additive `masked_columns` is Q10).
- Tests: masking of each type, `SELECT *`, aliases, joins, expressions, empty `masked_columns`, decision without the field (old entitlements).

### 3.7 dq-engine (team-quality) — code change, **step 4b** (after 3.4; parallel with 3.5)
- When a run starts (triggered by `ingestion.batch.landed.v1`), fetch columns via `MetadataClient` and select PII-format rules for columns classified `PII` (e.g. email regex, phone E.164, SSN pattern; choose by column tags/subtype where available, generic "looks like PII format" otherwise).
- Rules run in `report_only` mode first (results published but not counted in the quality score), then `enforce`.
- Keep `dq.result.published.v1` shape unchanged (adding a rule-category field is optional and additive — Q11); verify metadata-graph and notification-service still parse results.
- Tests: rule selection by classification, no PII columns, metadata-graph unavailable (skip PII rules, do not fail the run), rule correctness fixtures.

### 3.8 platform-e2e (team-platform) — code change, **step 6**
New scenarios (synthetic data only):
1. Ingest a source with `tags: pii,email` on `email` -> metadata-graph column `classification=PII, source=SUGGESTED` -> `metadata.dataset.changed.v1` contains it.
2. Steward overrides `phone` to `PII` and `email` to `CONFIDENTIAL` -> re-ingestion does not revert the override.
3. Query as user without `pii:read` -> `PII` columns masked; with `pii:read` -> clear values; unclassified columns clear.
4. DQ run on the dataset -> PII-format rule results present for PII columns only.
5. Compatibility: run the existing suite with the new flags off and with them on; run with old ingestion (no tags) and old consumers.

### 3.9 Verify-only repositories
| Repository | What to verify |
|---|---|
| search-indexer | Consumes `metadata.dataset.changed.v1` validating with `platform-contracts` directly: replay new-shape events (and upgrade its pin to 2.4.0 if validation is strict). |
| lineage-service | Replay new-shape `metadata.dataset.changed.v1` events; bump platform-sdk to 3.5.0 and run its tests. |
| notification-service | Run tests against the additive columns response; bump platform-sdk to 3.5.0. |
| platform-catalog | Re-check entries in the same PRs; correct the drift that metadata-graph depends on `platform-contracts` directly (requirements.txt) but its component lists only `platform-sdk`; add any new edge if Q5 introduces one (e.g. metadata-graph -> entitlements-api for steward authz). |

Not impacted: **usage-metering** (topic unchanged), **reporting-service** (decommissioned/archived).

## 4. Ordering and dependencies

| Step | Repo | Depends on | Can run in parallel with |
|---|---|---|---|
| 1 | platform-contracts 2.4.0 | — | — |
| 2 | platform-sdk 3.5.0 | 1 | — |
| 3a | ingestion-service (emit tags, flag) | 1 | 3b |
| 3b | metadata-graph (store/suggest/API; event field behind flag) | 1, 2 | 3a |
| V | verify search-indexer, lineage-service, entitlements-service, notification-service against new event/API shape | 1, 2 | 3a/3b |
| 4a | entitlements-service (`masked_columns`, flag off) | 2, 3b | 4b |
| 4b | dq-engine (PII rules, report-only) | 2, 3b | 4a |
| 5 | metadata-graph enables `publish_column_classification`; backfill; stewards review | V, 3a | — |
| 6 | query-gateway (shadow -> enforce) | 4a, 5 | — |
| 7 | platform-e2e scenarios (developed alongside 3-6, gate for each prod flag flip) | 3-6 | — |
| 8 | Enforce: entitlements flag on, gateway `enforce` per domain, dq `enforce` | 7 green, governance sign-off | — |

Critical path: contracts -> sdk -> metadata-graph -> entitlements-service -> query-gateway.

## 5. Compatibility and rollout (AC6)

- **Expand only**: every field is optional; no field removed/renamed; no `required` tightened; no new `change_type` value; no topic or path version bump.
- **Tolerant readers**: consumers must ignore unknown fields; confirm before step 5 (R1).
- **Producer-last for events**: consumers are verified against the new schema before metadata-graph starts emitting the new fields (`publish_column_classification`).
- **Old producers keep working**: metadata-graph handles schema events without `tags`; query-gateway treats a decision without `masked_columns` as `[]`.
- **Feature flags** per repo (`emit_column_tags`, `publish_column_classification`, `return_masked_columns`, `pii_masking_mode`, dq `pii_rules_mode`), each flippable independently for rollback without redeploy.
- **Shadow before enforce**: query-gateway logs would-be-masked columns for at least one release cycle; masking is announced to data consumers (it changes values, not schema).
- **Deploys** are rolling (no downtime); no graph DB migration needed (new optional properties).
- **Rollback**: flip flags off; data written (classifications) stays and is harmless to old readers.

## 6. Cross-repository testing

**Contract tests (per PR, in CI)**
- platform-contracts: backward-compat diff check on every changed schema/spec; golden old/new payload fixtures.
- Producer side: ingestion-service and metadata-graph validate emitted events against the 2.4.0 schemas; metadata-graph and entitlements-service validate HTTP responses against their OpenAPI specs.
- Consumer side (consumer-driven, e.g. Pact-style or fixture replay): entitlements-service, search-indexer, lineage-service replay old and new `metadata.dataset.changed.v1` fixtures; dq-engine, notification-service, platform-sdk against metadata-graph columns response; query-gateway and platform-sdk against the decision response (with and without `masked_columns`).
- Version-skew matrix: {old, new} producer x {old, new} consumer for each changed contract.

**Integration / end-to-end (platform-e2e, integration environment)**
- Scenarios 1-5 in section 3.8, run with flags off (regression) and on.
- Negative: metadata-graph down -> entitlements uses cache, dq skips PII rules gracefully; malformed tags ignored.
- Performance: query-gateway latency with masking enabled; entitlements decision latency with larger responses.

## 7. Risks

| # | Risk | Mitigation |
|---|---|---|
| R1 | Strict schema validation (`additionalProperties: false`) in consumers, especially search-indexer which uses platform-contracts directly, rejects new fields. | Verify step V before enabling the event flag; upgrade pins first. |
| R2 | Re-ingestion overwrites steward overrides (current consumer replaces the whole column list). | Merge-by-name with steward precedence; dedicated test. |
| R3 | PII leaks via unclassified or untagged columns (fail-open default A4). | Backfill + steward review queue; governance decision on fail-closed (Q3); shadow-mode metrics. |
| R4 | Masking breaks consumers expecting non-null values / specific types. | Type-preserving masks; shadow period; consumer comms. |
| R5 | Derived/aliased query columns bypass masking. | Conservative masking of expressions referencing masked columns; e2e cases; Q9. |
| R6 | Stale classification in entitlements cache after an override. | Event-driven invalidation + short TTL + API fallback. |
| R7 | Event volume spike from backfill. | Throttled backfill, off-peak. |
| R8 | Catalog/README drift (README lists reporting-service; catalog misses metadata-graph -> platform-contracts). | Fix in the same PRs (platform-catalog README rule). |
| R9 | Unauthorized classification changes (no auth visible in metadata-graph API). | Steward authz before enabling the PUT endpoint (Q5); audit fields. |

## 8. Open questions

See `open_questions` in `IMPACT_ANALYSIS.json` (Q1-Q13 in that order). The ones that block implementation:
- **Q1/Q2** tag syntax per connector and tag -> classification mapping / default.
- **Q3** fail-open vs fail-closed for unclassified columns.
- **Q4** strictness of consumer schema validation.
- **Q5/Q6** steward authorization and existence of the `pii:read` grant.
- **Q7** exact entitlements decision and query-api result paths.
- **Q8** masking strategy per data type.
