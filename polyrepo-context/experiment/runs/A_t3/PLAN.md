# DP-1423 Implementation Plan: column sensitivity classification and PII masking

> Synthetic ticket and workspace. Written as an impact analysis only; no code was changed.
> Companion file: `IMPACT_ANALYSIS.json`.

## 1. Context and what was observed

Only `metadata-graph` is present in the workspace. Everything else is inferred from it:

| Fact | Source |
|---|---|
| metadata-graph consumes `ingestion.schema.discovered.v1` and `dq.result.published.v1` | `metadata-graph/config/settings.yaml`, `consumers.py` |
| metadata-graph publishes `metadata.dataset.changed.v1`; consumers are `entitlements-service`, `reporting-service` | `metadata-graph/README.md`, `publisher.py` |
| REST spec of record is `platform-contracts` (`openapi/metadata-graph.yaml`); event schema ref `platform-contracts://events/metadata.dataset.changed.v1` | `api.py`, `publisher.py` |
| REST clients use `platform-sdk` `MetadataClient`; pinned `platform-sdk==3.4.1`, `platform-contracts==2.3.0` | `README.md`, `requirements.txt` |
| Schema-discovery columns carry only `name`, `type`, `nullable` (no comment/tags) | `consumers.py` |
| `on_schema_discovered` **replaces** the column list wholesale on every re-ingest | `consumers.py` |
| `GET /v1/datasets/{urn}/columns` returns `name, data_type, nullable, description`; the event omits `description` | `api.py`, `publisher.py` |
| `change_type` values: `CREATED`, `UPDATED`, `COLUMNS_CHANGED` | `publisher.py` |

Inferred repository names (not visible): `ingestion-service`, `data-quality-service`, `query-service`.

## 2. Assumptions

1. Classification enum: `PUBLIC | INTERNAL | CONFIDENTIAL | PII`. A column with no classification is returned as `null` (not defaulted), so absence is distinguishable from a decision. Masking treats `null` as not masked; the rollout backfills suggestions before enforcing.
2. Only `PII` columns are masked, and only when the requester lacks `pii:read` (as written in AC3). CONFIDENTIAL masking is out of scope (open question).
3. Per column, metadata-graph stores `suggested_classification` (from tags), `classification` (effective value), `classification_source` (`SUGGESTED | STEWARD`), `tags`, plus override audit fields (`classified_by`, `classified_at`).
4. Steward overrides take precedence over suggestions and survive re-ingestion. A re-ingest only updates `suggested_classification`; if no steward override exists, the effective classification follows the suggestion.
5. Tag mapping (configurable in `metadata-graph/config/settings.yaml`), highest sensitivity wins: `pii`/`email`/`phone`/`ssn`/`name`/`address` → `PII`; `confidential` → `CONFIDENTIAL`; `internal` → `INTERNAL`; `public` → `PUBLIC`. PII subtype tags (`email`, `phone`, ...) are kept in `tags` so DQ can pick format rules.
6. Classification-only changes are published with the existing `change_type: COLUMNS_CHANGED` so no new enum value reaches consumers that validate it.
7. Endpoint paths for entitlements (`POST /v1/access-decisions`) and query (`POST /v1/queries`) are placeholders; the real paths must be confirmed with the owning teams.
8. All contract changes are additive in `v1`; no `v2` topic/route is needed.

## 3. Ordering overview

```
(1) platform-contracts  ──►  (2) platform-sdk
        │                         │
        ├──► (3) ingestion-service (emit comment/tags)
        │                         │
        └──► (4) metadata-graph  ◄┘  (store/suggest/override, API, event)
                   │
                   ├──► (5) entitlements-service (masked_columns in decisions)
                   │            │
                   │            └──► (6) query-service (apply masking)
                   ├──► (7) data-quality-service (PII format rules)
                   └──► (8) reporting-service (verify only)
```

Steps 3 and 4 can run in parallel once 1–2 are released: metadata-graph must tolerate events with and without tags. Steps 5, 7 and 8 can run in parallel after 4 is deployed. Step 6 depends on 5. Enforcement flags are switched on only after the backfill (section 5).

## 4. Per-repository work items

### 4.1 platform-contracts (code_change, first)
- Event schema `ingestion.schema.discovered.v1`: add optional `columns[].comment: string` and `columns[].tags: string[]`.
- Event schema `metadata.dataset.changed.v1`: add optional `dataset.columns[].classification` (enum, nullable), `classification_source` (enum, nullable), `tags` (string[]). Do not add a `change_type` value.
- `openapi/metadata-graph.yaml`:
  - `GET /v1/datasets/{urn}/columns`: add the same optional fields plus `suggested_classification` to the column schema.
  - New `PUT /v1/datasets/{urn}/columns/{column}/classification`: request `{classification, reason?}`; responses 200 (column), 400 `INVALID_CLASSIFICATION`, 403 `FORBIDDEN`, 404 `NOT_FOUND`.
- Entitlements OpenAPI: add optional `masked_columns: [{dataset_urn, column}]` to the access-decision response.
- Query OpenAPI (if owned here): optional `masked_columns` in result metadata.
- Shared `Classification` enum definition reused by all of the above.
- CI: schema compatibility check (new schema must read old payloads and old schema must accept new payloads; i.e. BACKWARD+FORWARD / FULL compatibility). Release as minor `2.4.0`.

### 4.2 platform-sdk (code_change)
- Bump to `platform-contracts 2.4.0`; add `classification`, `classification_source`, `suggested_classification`, `tags` as optional attributes on the column model (default `None`).
- `MetadataClient.set_column_classification(urn, column, classification, reason=None)`.
- Optional helper `Classification` enum and `is_pii(column)`.
- Ensure event deserialisation ignores unknown fields (tolerant reader) so older services are unaffected.
- Release as minor `3.5.0`; `3.4.x` clients must keep working against the new API.

### 4.3 ingestion-service (code_change, name inferred)
- When discovering a source schema, read the column comment, parse `tags:` (comma-separated, trimmed, lower-cased) and emit `comment` and `tags` on each column in `ingestion.schema.discovered.v1`.
- Do not change existing fields. Feature flag `emit_column_tags` for staged enablement per source connector.
- Unit tests for the parser (`tags: pii,email`, spaces, case, missing, malformed) and a producer contract test against the 2.4.0 schema.

### 4.4 metadata-graph (code_change, owner team-graph)
- `model.py`: add to `Column` the optional fields `tags: list[str]`, `comment`, `suggested_classification`, `classification`, `classification_source`, `classified_by`, `classified_at` (all defaulted so existing constructors/tests keep working).
- New `classification.py`: `suggest(tags) -> Classification | None` using the mapping in `config/settings.yaml` (new `classification.tag_map` section).
- `consumers.py` `on_schema_discovered`:
  - Read optional `comment`/`tags` (tolerate absence).
  - **Merge by column name instead of replacing the list**: keep existing `classification`, `classification_source=STEWARD` and audit fields for columns that still exist; recompute `suggested_classification`; set effective classification to the suggestion only when there is no steward override.
  - Also map `comment` to `description` if absent (current gap, optional).
- `api.py`:
  - `get_columns` returns the new fields.
  - New `PUT /v1/datasets/{urn}/columns/{column}/classification`: validate enum, authorize steward (open question on grant name), set `classification_source=STEWARD`, audit fields, `store.upsert`, `publish_dataset_changed(ds, "COLUMNS_CHANGED")`.
  - Optional `DELETE` of the override (revert to suggestion) can be a follow-up.
- `publisher.py`: add `classification`, `classification_source`, `tags` per column to the payload.
- `graph_store.py` / graph DB: persist new column properties (additive properties, no migration of existing nodes required; nulls read as unclassified).
- Backfill job: recompute suggestions for existing datasets (request a re-discovery from ingestion or run over stored comments) and publish `COLUMNS_CHANGED` events in throttled batches.
- Tests: extend `tests/test_api.py`, `tests/test_consumers.py`; add publisher payload test validated against the 2.4.0 event schema; test that re-ingest preserves a steward override; test old-shape (no tags) events still create datasets.
- Bump `platform-sdk==3.5.0`, `platform-contracts==2.4.0`.

### 4.5 entitlements-service (code_change)
- Consumer of `metadata.dataset.changed.v1`: persist per-column classification (tolerate absent field = unclassified).
- Access decision: when requester lacks `pii:read`, return `masked_columns` = all columns of the requested dataset(s) with `classification == PII`. With `pii:read`, return an empty list. Existing `allow/deny` semantics unchanged.
- Define/register the `pii:read` grant if it does not exist.
- Freshness: decisions use the last consumed classification; document lag. Optional fallback lookup via `MetadataClient` if no classification is cached.
- Flag `return_masked_columns` (default on once deployed; field is additive and ignored by old clients).
- Tests: consumer contract test against the event schema, decision unit tests (with/without grant, unclassified, mixed).

### 4.6 query-service (code_change, name inferred)
- After the access decision, replace values of `masked_columns` in result rows with the mask token (assumed fixed `"****"` for strings, `null` for non-string types; open question) while keeping column names, order and types.
- Add optional `masked_columns` to response metadata.
- Fail closed: if the decision call fails, do not return PII-classified columns unmasked (return error or mask all classified columns), behind flag `enforce_pii_masking` with a `shadow` mode that logs would-be-masked columns without changing results.
- Tests: provider/consumer contract test with entitlements, masking unit tests, performance check on large result sets.

### 4.7 data-quality-service (code_change, name inferred)
- Before a run, fetch column metadata via `MetadataClient.get_columns` (platform-sdk 3.5.0) or cache from `metadata.dataset.changed.v1`.
- For `classification == PII` columns, add PII-format rules chosen by subtype tag (`email` regex, `phone` E.164, `ssn` pattern; default: generic "no plaintext in masked-expected field" rule is out of scope). Unknown subtype: no format rule, record a warning.
- `dq.result.published.v1` shape stays unchanged (results are aggregated into `score`); if per-rule results are to be published, that is a separate additive change (open question).
- Flag `pii_format_rules` so quality scores do not drop suddenly for all datasets on deploy; run in report-only mode first.
- Tests: rule unit tests, integration test with stubbed MetadataClient.

### 4.8 reporting-service (verify_only)
- Bump nothing required. Run its consumer tests against sample `metadata.dataset.changed.v1` payloads containing the new fields; confirm strict JSON-schema validation or typed deserialisation does not reject unknown fields.
- If it turns out reporting-service serves query results to consumers, it becomes a code_change with the same masking work as 4.6.

## 5. Compatibility and rollout

Expand-then-enforce, no downtime, no breaking change:

1. **Contracts + SDK** (`platform-contracts 2.4.0`, `platform-sdk 3.5.0`): additive optional fields only; compatibility check in CI.
2. **Verify tolerant readers**: run consumer tests for entitlements-service and reporting-service against new-shape payloads before metadata-graph publishes them.
3. **metadata-graph deploy**: reads tags if present, publishes new fields, new PUT endpoint live. Rolling deploy; old pods and new pods coexist safely because the only state change is additive column properties. The column merge fix ships in the same release.
4. **ingestion-service deploy**: start emitting `comment`/`tags` per connector behind `emit_column_tags`.
5. **Backfill** existing datasets' suggestions; stewards review/override high-risk datasets.
6. **entitlements-service deploy**: starts returning `masked_columns`.
7. **query-service** in `shadow` mode: log would-mask counts, compare with steward expectations, check latency. Then enable `enforce_pii_masking` per domain, then globally.
8. **data-quality-service**: enable PII-format rules in report-only mode, then let them affect scores.

Rollback: every step is behind a flag or is additive; disabling `enforce_pii_masking` restores previous query behaviour. Never roll contracts back after consumers adopt them; fix forward.

## 6. Cross-repository testing

### Contract tests
- **Schema compatibility** in platform-contracts CI for both event schemas and both OpenAPI specs (old vs new, full compatibility).
- **Producer tests**: ingestion-service validates emitted `ingestion.schema.discovered.v1` against 2.4.0; metadata-graph validates `metadata.dataset.changed.v1` payloads and OpenAPI responses against 2.4.0.
- **Consumer-driven tests** (e.g. Pact or schema-sample fixtures published by platform-contracts):
  - metadata-graph consumes old-shape and new-shape schema-discovery events.
  - entitlements-service and reporting-service consume old-shape and new-shape dataset-changed events.
  - data-quality-service against `GET /v1/datasets/{urn}/columns` via SDK 3.5.0.
  - query-service against the access-decision response with and without `masked_columns`.
- **SDK compatibility**: platform-sdk 3.4.1 test suite run against the new metadata-graph to prove existing clients keep working (AC6).

### Integration / end-to-end (staging)
1. Ingest a source table with column comment `tags: pii,email` on `email` and none on `id`.
2. Assert `GET /v1/datasets/{urn}/columns` shows `email.suggested_classification = classification = PII`, `classification_source = SUGGESTED`; `id` unclassified (AC1, AC2).
3. Assert a `metadata.dataset.changed.v1` event carries the classification (AC2).
4. Steward `PUT` `id` → `INTERNAL`; assert response, GET, and event reflect it; re-ingest the schema and assert the override persists.
5. Access decision for a user without `pii:read` lists `email` in `masked_columns`; with `pii:read` the list is empty (AC3).
6. Query as both users: `email` masked vs clear; column order/types unchanged (AC4).
7. Trigger a DQ run with invalid emails; assert PII-format rule fires on `email` only (AC5).
8. Run the full suite of existing consumer tests throughout steps 1–7 with old SDK/clients (AC6).
- Non-functional: masking latency overhead, event lag from steward override to enforced masking, fail-closed behaviour when entitlements is unavailable.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Re-ingest wipes steward overrides (current `on_schema_discovered` replaces columns) | Merge by column name; dedicated test |
| Strict consumers reject new event fields, turning an additive change into a breaking one | Verify tolerant readers before step 3; ship SDK tolerant deserialisation |
| PII exposed during rollout because columns are unclassified or event lag | Backfill + shadow mode before enforcement; fail closed on decision errors |
| Column renames lose classification (matched by name) | Document; stewards re-review renamed columns; follow-up for stable column IDs |
| Wrong tag parsing leads to over/under masking | Configurable mapping, parser tests, steward override |
| DQ scores drop sharply when rules enable | Report-only phase, per-domain enablement |
| Ordering slip (metadata-graph released before contracts/SDK) | Pin on 2.4.0/3.5.0 releases; CI blocks without them |
| Masked type changes break typed consumers | Keep column types; null for non-string types; open question on format |

## 8. Open questions

See `open_questions` in `IMPACT_ANALYSIS.json`. Most important to resolve before starting:
1. Which repository actually returns query results to data consumers (query-service is inferred).
2. Real names and endpoints of the ingestion, data-quality and entitlements services.
3. Default for unclassified columns, CONFIDENTIAL handling, and masking format.
4. Steward authorization model for the override endpoint.
