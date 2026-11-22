# DP-1423: Column-level sensitivity classification and PII masking (implementation plan)

> Synthetic example. This is an analysis of the synthetic polyrepo workspace, not a real system.

Companion file: `IMPACT_ANALYSIS.json` (repositories, dependency edges, contracts, open questions).

## 1. Summary

The ticket was assigned to team-graph, but delivering it touches 8 repositories with code changes and 3 that only need re-verification:

| Repository | Owner | Impact | Why |
|---|---|---|---|
| platform-contracts | team-platform | code change | Source of truth for event schemas and OpenAPI specs |
| platform-sdk | team-platform | code change | Typed clients and event helpers used by most services |
| ingestion-service | team-ingest | code change | Must emit source column tags (AC1) |
| metadata-graph | team-graph | code change | Stores, suggests, overrides and publishes classification (AC1, AC2) |
| entitlements-service | team-access | code change | `pii:read` grant and `masked_columns` in decisions (AC3) |
| query-gateway | team-serving | code change | Masks result values (AC4) |
| dq-engine | team-quality | code change | PII-format rules for PII columns (AC5) |
| platform-e2e | team-platform | code change | New end-to-end scenarios |
| search-indexer | team-discovery | verify only | Consumes `metadata.dataset.changed.v1`; pins platform-contracts directly |
| lineage-service | team-discovery | verify only | Consumes `metadata.dataset.changed.v1` |
| notification-service | team-platform | verify only | Consumes metadata-graph-api and `dq.result.published.v1` |

Not impacted: `reporting-service` is decommissioned and archived (the metadata-graph README still lists it as an event consumer, which is stale), `usage-metering` (its only input, `gateway.access.logged.v1`, is unchanged) and `platform-catalog` (no new edges, topics or API entities).

Sources: the catalog (`platform-catalog/components`, `apis`, `topics.yaml`, `dependency-graph.json`) and the metadata-graph source. The catalog is treated as authoritative over the metadata-graph README.

## 2. Design decisions (assumptions)

1. **Data model.** Each column gets `classification` (`PUBLIC | INTERNAL | CONFIDENTIAL | PII`, nullable), `classification_source` (`SUGGESTED | STEWARD`), `tags` (list of strings), `classified_by`, `classified_at`. `null` means not yet classified.
2. **Suggestion (AC1).** ingestion-service forwards source tags verbatim as `columns[].tags` (parsed from comments like `tags: pii,email`). metadata-graph owns the tag-to-classification mapping, so the rule lives in one place: the strongest matching tag wins (`pii` > `confidential` > `internal` > `public`), and no matching tag gives `null`. The mapping is config in `metadata-graph/config/settings.yaml`.
3. **Steward override wins.** Re-ingestion must never overwrite a `STEWARD` classification. It may update a `SUGGESTED` one. Today `on_schema_discovered` replaces `existing.columns` wholesale, which would drop classifications (it already drops `description`). It must be changed to merge by column name.
4. **All contract changes are additive.** There are only new optional fields and one new endpoint, with no new topic and no `.v2`. Classification changes are published as `metadata.dataset.changed.v1` with the existing `change_type: COLUMNS_CHANGED`, so consumers with a strict `change_type` enum keep working.
5. **Masking decision lives in entitlements-service, and enforcement lives in query-gateway.** entitlements-service learns classifications from `metadata.dataset.changed.v1`, which it already consumes, and falls back to `GET /v1/datasets/{urn}/columns` on a cache miss. It returns `masked_columns`. query-gateway applies the mask. Old gateways ignore the field, which is safe for rollout but means no masking until the gateway is upgraded.
6. **Mask representation is type-safe.** String columns get a fixed mask (e.g. `"***"`) and other types get `null`. The column list, order and declared types are unchanged. The response gains optional `masked_columns` metadata.
7. **Unclassified columns are not masked (fail-open)** during rollout. Whether to switch to fail-closed later is an open question.
8. **Feature flags** (default off) guard each behavior change: `classification.suggest` (metadata-graph), `masking.decisions` (entitlements-service), `masking.enforce` (query-gateway), `dq.pii_rules` (dq-engine).
9. Inferred names: entitlements decision endpoint `POST /v1/access-decisions`, query endpoint `POST /v1/queries`. Their real paths are in `platform-contracts/openapi/*.yaml`, which is not in this workspace. Confirm them before starting.

## 3. Work items per repository

### 3.1 platform-contracts (team-platform): first
- `events/ingestion.schema.discovered.v1`: add optional `columns[].tags: string[]` and `columns[].comment: string`.
- `events/metadata.dataset.changed.v1`: add optional `dataset.columns[].classification` (enum + null), `classification_source`, `tags`. Do not change `change_type`.
- `openapi/metadata-graph.yaml`: extend the column schema in `GET /v1/datasets/{urn}/columns`. Add `PUT /v1/datasets/{urn}/columns/{column}/classification` (request `{classification, reason?}`, 200 column, 400/403/404).
- `openapi/entitlements-service.yaml`: add `masked_columns: string[]` (default `[]`) and optional `mask_policy` to the decision response. Document the `pii:read` grant.
- `openapi/query-gateway.yaml`: document the mask semantics and the optional `masked_columns` response field.
- CI: add backward-compatibility checks (for example a schema diff that fails on removed/renamed fields or new required fields) and check for `additionalProperties: false` on the affected objects.
- Release a **minor** version (metadata-graph pins `2.3.0`, so this becomes `2.4.0`).

### 3.2 platform-sdk (team-platform): after 3.1
- Bump the platform-contracts dependency.
- `MetadataClient`: column model gains optional classification fields. Add `set_column_classification(urn, column, classification, reason=None)`.
- Entitlements client: decision model gains `masked_columns` (default empty list).
- Event helpers: tolerate unknown fields when deserializing (verify; fix if strict).
- Optional shared helper `mask_value(value, data_type)` so gateway behavior is consistent.
- Release a **minor** version (metadata-graph pins `3.4.1`, so this becomes `3.5.0`).

### 3.3 ingestion-service (team-ingest): after 3.1/3.2
- In each connector's schema discovery, read column comments and parse `tags: a,b` into a lower-cased, trimmed list. Emit `tags` (and the raw `comment`) on `ingestion.schema.discovered.v1`.
- No classification logic here.
- Tests: parser edge cases (no comment, spacing, case, other comment text), and events validate against the new schema.

### 3.4 metadata-graph (team-graph): after 3.1/3.2, can start in parallel with 3.3
- `model.py`: add the classification fields to `Column`.
- `consumers.py` `on_schema_discovered`: read optional `tags`. Merge new columns with existing ones by name, keeping the `STEWARD` classification and `description`. Apply the suggestion mapping when `classification.suggest` is on and the source is not `STEWARD`.
- `api.py`: return the new fields from `GET /v1/datasets/{urn}/columns`. Add the `PUT .../columns/{column}/classification` route: validate the enum, enforce the steward grant, store with source `STEWARD`, publish `COLUMNS_CHANGED`.
- `publisher.py`: include `classification`, `classification_source` and `tags` per column.
- Graph DB: add the column properties, nullable, with no data rewrite needed. Optional backfill job: re-run the suggestion for existing datasets from the latest ingested tags, and publish one change event per dataset (rate-limited).
- `config/settings.yaml`: tag mapping and flag.
- `README.md`: fix the consumer list (entitlements-service, lineage-service, search-indexer; remove reporting-service).
- Tests: suggestion mapping, override precedence across re-ingest, `PUT` validation and 404/403, payload contains the fields, existing tests still pass, and consumer-driven contract tests against the platform-contracts schemas.

### 3.5 entitlements-service (team-access): after 3.2, needs 3.4 deployed to get real data
- Add a `pii:read` grant type and an admin path to grant it.
- Keep a per-dataset column-classification cache fed by `metadata.dataset.changed.v1` and filled on cache misses from `GET /v1/datasets/{urn}/columns`.
- Decision: if the requester lacks `pii:read`, `masked_columns` lists the dataset's PII columns, otherwise `[]`. This is behind `masking.decisions`, and returns `[]` when the flag is off.
- Tests: grant / no grant, unclassified columns, cache refresh on `COLUMNS_CHANGED`, existing decision fields unchanged.

### 3.6 query-gateway (team-serving): after 3.2 and 3.5
- Upgrade the SDK. After the decision call, mask values of `masked_columns` in result rows using the type-safe rule. Add `masked_columns` to the response metadata.
- Make sure masking also applies to every result path (streaming/paginated/export, cached results). Cache keys must include the mask set, or masking must happen after the cache.
- Behind `masking.enforce` (shadow mode first: compute and log what would be masked, without masking).
- Do not change `gateway.access.logged.v1`.
- Tests: masked/unmasked by grant, non-string types, column order/type unchanged, flag off means identical output.

### 3.7 dq-engine (team-quality): after 3.2 and 3.4
- When running rules for a batch, fetch column metadata (`GET /v1/datasets/{urn}/columns` via SDK). For columns classified `PII`, add PII-format rules selected by tag subtype (e.g. `email` gives the email regex, `phone` gives E.164). With no subtype, run a generic rule set or skip it (open question).
- Rule failure details and `dq.result.published.v1` payloads must not contain raw PII sample values (report counts/row ids only). The event shape is unchanged.
- Decide whether PII rules affect `score` (metadata-graph stores it as `quality_score`). Default: they are included, behind `dq.pii_rules`.
- Tests: rules applied only to PII columns, no raw values in output.

### 3.8 platform-e2e (team-platform): written in parallel, run after each deploy
- Scenario A: ingest a source with `tags: pii,email` on `email`. The column is suggested `PII` and shows in GET columns and the change event.
- Scenario B: a steward overrides `email` to `CONFIDENTIAL` and then back to `PII`. Re-ingest does not revert the override.
- Scenario C: a requester without `pii:read` queries the dataset, `email` is masked, other columns are intact. With `pii:read`, it is unmasked.
- Scenario D: a DQ run on a landed batch applies the email-format rule to `email` only. The DQ result/notification has no raw values.
- Scenario E (compatibility): with all flags off, current responses and events are unchanged except for the new optional fields.

### 3.9 Verify-only repositories
- **search-indexer:** upgrade/run against platform-contracts 2.4.0 and replay sample `metadata.dataset.changed.v1` events with the new fields. Confirm indexing succeeds and the fields are ignored (or indexed, if desired later).
- **lineage-service:** replay new-shape events and confirm no deserialization errors.
- **notification-service:** run against the new metadata-graph-api response and DQ results containing PII-rule failures. Confirm emails are sent and contain no raw values.

## 4. Ordering and dependencies

```
platform-contracts (2.4.0)
   └─> platform-sdk (3.5.0)
          ├─> ingestion-service ─────────────┐
          ├─> metadata-graph ────────────────┤ (needs tags from ingestion for AC1,
          │       │                          │  but works without them: override only)
          │       ├─> entitlements-service ──┴─> query-gateway
          │       └─> dq-engine
          └─> (verify) search-indexer, lineage-service, notification-service
platform-e2e: scenarios written alongside, gated per phase
```

Deploy order (producers before consumers, flags off):
1. Release platform-contracts 2.4.0, then platform-sdk 3.5.0.
2. Run verify-only checks for search-indexer, lineage-service, notification-service against the new schemas (before any producer emits the new fields).
3. Deploy metadata-graph (fields and endpoint live, `classification.suggest` off). Stewards can classify now.
4. Deploy ingestion-service (emits `tags`). Turn on `classification.suggest`. Run the optional backfill.
5. Deploy dq-engine, then turn on `dq.pii_rules`.
6. Deploy entitlements-service with `masking.decisions` on. Provision `pii:read` for all current legitimate PII consumers (identified from access logs/policies).
7. Deploy query-gateway in shadow mode, review would-mask logs, then turn on `masking.enforce`, per domain/tenant if possible.

Steps 3–5 can proceed in parallel once step 2 passes. Step 7 depends on 6.

## 5. Compatibility and rollout (AC6)

- Every contract change is additive (optional fields, defaults, one new endpoint, no enum extension). No topic version bump and no dual-publishing are needed. Each service is deployed with rolling updates and no downtime.
- Readers must tolerate unknown fields. This is verified explicitly for every consumer of a changed contract before producers emit (deploy step 2).
- Masking is an intentional behavior change for consumers without `pii:read`. To avoid breaking existing consumers, grants are provisioned before enforcement, enforcement starts in shadow mode, and values keep their declared type (no string in an integer column).
- Rollback: each step is reverted by switching off its flag. The new fields can stay in place because they are optional. Steward classifications persist across rollback.
- Update the platform-catalog only if the design changes to add a new topic or API entity (current plan: none).

## 6. Cross-repository testing

**Contract tests**
- platform-contracts CI runs a schema compatibility diff (no removed/renamed fields, no new required fields, enum not narrowed) and validates example payloads.
- Producers (ingestion-service, metadata-graph) validate emitted events and HTTP responses against the released schemas in unit tests.
- Consumer-driven contract tests (e.g. Pact or schema-fixture tests):
  - entitlements-service, dq-engine and platform-sdk against `GET /v1/datasets/{urn}/columns`.
  - query-gateway and platform-sdk against the entitlements decision response.
  - entitlements, lineage and search-indexer against `metadata.dataset.changed.v1` fixtures, both old-shape and new-shape.
- Old-shape fixtures are kept so the new code also accepts events/responses without the new fields (mixed-version window).

**Integration / end-to-end** (platform-e2e, integration environment)
- Scenarios A–E above, run after each deploy step with the matching flags. Scenario E runs before any flag is turned on.
- Mixed-version test: new metadata-graph with old entitlements/gateway, and new gateway with old entitlements (empty `masked_columns`). Both must work.
- Security checks: no raw PII in DQ results, notifications, gateway logs or `gateway.access.logged.v1`.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Re-ingestion wipes steward classifications (current wholesale column replace) | Merge by column name, with a test for override precedence |
| A consumer validates strictly and rejects new fields | Verify step before producers emit; `additionalProperties` audit |
| Existing PII consumers suddenly see masked data | Provision `pii:read` first, shadow mode, staged enable |
| Masking bypass via cache/export/pagination paths in the gateway | Mask after cache; tests for every result path |
| Stale classification cache in entitlements means unmasked PII | Event-driven refresh plus a TTL; optional fail-closed for PII-tagged-but-uncached |
| Wrong or absent source tags give unclassified PII (fail-open) | Steward review queue for unclassified columns; open question on fail-closed |
| DQ outputs leak PII samples into events/emails | Counts/row ids only; e2e check |
| Inferred entitlements/query paths are wrong | Confirm in platform-contracts before starting |
| The metadata-graph README lists a decommissioned consumer and omits two real ones | Use the catalog; fix the README in this ticket |

## 8. Open questions

See `open_questions` in `IMPACT_ANALYSIS.json`. The most decision-critical are:
1. Fail-open vs fail-closed for unclassified columns.
2. Mask representation per data type.
3. The steward authorization model.
4. Whether DQ needs a PII subtype (from tags) in addition to the classification.
5. The real entitlements/query endpoint paths and shapes.
6. Who receives `pii:read` before enforcement.
