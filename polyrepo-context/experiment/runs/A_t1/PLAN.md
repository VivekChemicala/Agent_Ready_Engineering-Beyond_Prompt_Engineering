# DP-1423 — Column-level sensitivity classification and PII masking

Implementation plan (no code). Synthetic ticket and workspace written for an experiment.
Machine-readable companion: `IMPACT_ANALYSIS.json` in this folder.

## 1. What I could see and what I inferred

Only `metadata-graph` is present in the workspace. Every other repository below is
named from references inside it:

| Repository | Name source | Where it is referenced |
|---|---|---|
| metadata-graph | observed | the repository itself |
| platform-contracts | observed | `requirements.txt` (`platform-contracts==2.3.0`), `api.py` (spec of record `openapi/metadata-graph.yaml`), `publisher.py` (`platform-contracts://events/...`) |
| platform-sdk | observed | `requirements.txt` (`platform-sdk==3.4.1`), `README.md` (`MetadataClient`), `platform_sdk.events` imports |
| entitlements-service | observed | `README.md` (consumer of `metadata.dataset.changed.v1`) |
| reporting-service | observed | `README.md` (consumer of `metadata.dataset.changed.v1`) |
| ingestion-service | inferred | `README.md` "the ingestion service", producer of `ingestion.schema.discovered.v1` |
| dq-service | inferred | producer of `dq.result.published.v1` (`settings.yaml`, `consumers.py`) |
| query-service | inferred | not referenced; AC4 needs whatever returns query results to consumers |

Endpoints outside metadata-graph (`POST /v1/access/decisions`, `POST /v1/queries`) are
placeholders for the real paths, which I could not see.

## 2. Assumptions (decisions made without asking)

- A1. Classification values: `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `PII`. A column with no
  tags and no steward value has `classification: null` (unclassified). It is **not**
  masked, so existing behaviour is unchanged.
- A2. Masking (AC3/AC4) applies only to `PII` columns when the requester lacks `pii:read`.
  `CONFIDENTIAL` is stored and returned but does not drive masking in this ticket.
- A3. ingestion-service parses the source comment convention `tags: a,b` into
  `columns[].tags` (lowercase, trimmed). metadata-graph maps tags to a suggestion:
  - `pii` gives `PII`; `confidential`, `internal` and `public` map to the matching level.
  - If several tags match, the most sensitive wins.
  - Anything else gives no suggestion.
  - Other tags (`email`, `phone`, ...) are kept as the PII subtype that chooses the DQ format rule.
- A4. Effective classification is the steward value if one is set, otherwise the suggestion.
  Each column stores `suggested_classification`, `classification`, `classification_source`
  (`SUGGESTED` | `STEWARD`). Re-ingestion updates the suggestion. It never overwrites a
  steward value.
- A5. Classification changes are published on the existing `metadata.dataset.changed.v1`
  with `change_type: COLUMNS_CHANGED`. I do not add a new enum value, because strict
  consumers might reject it. I do not create a v2 topic.
- A6. Masked values keep the column's type so typed consumers do not break:
  - strings become a fixed token (e.g. `"***"`) or a partial mask;
  - other types become `null` (nullable).
  - The exact format is an open question.
- A7. During rollout, masking is behind feature flags and starts in shadow mode
  (compute and log, do not mask). Fail-open or fail-closed after GA is an open question.
  The plan recommends fail-closed for columns known to be `PII`.

## 3. Contract changes (all additive)

| Contract | Owner | Change |
|---|---|---|
| `ingestion.schema.discovered.v1` (event) | ingestion-service | + optional `columns[].tags: string[]`, `columns[].comment: string` |
| `metadata.dataset.changed.v1` (event) | metadata-graph | + optional `columns[].classification`, `classification_source`, `tags` |
| `GET /v1/datasets/{urn}/columns` | metadata-graph | + `classification`, `classification_source`, `suggested_classification`, `tags` per column |
| `PUT /v1/datasets/{urn}/columns/{column}/classification` | metadata-graph | **new**: body `{classification, reason}`; 200 updated column / 400 invalid value / 403 not a steward / 404 unknown dataset or column; publishes `COLUMNS_CHANGED` |
| `POST /v1/access/decisions` (path inferred) | entitlements-service | + `masked_columns: string[]` (empty when nothing to mask or requester holds `pii:read`) |
| `POST /v1/queries` (path inferred) | query-service | masked values replaced in place; + optional `masked_columns` in response metadata |

Compatibility rules for every schema change:
- New fields are optional in JSON Schema / OpenAPI.
- No field is renamed, removed or retyped.
- `additionalProperties` must not be tightened.
- Topic names and versions stay the same.
- Producers may emit the new fields only after the contracts release that declares them.
- Consumers must not require the new fields until every producer emits them.

## 4. Per-repository work items

### 4.1 platform-contracts (first)
1. `events/ingestion.schema.discovered.v1`: add optional `columns[].tags`, `columns[].comment`.
2. `events/metadata.dataset.changed.v1`: add optional `columns[].classification` (enum + null),
   `columns[].classification_source` (enum `SUGGESTED|STEWARD`), `columns[].tags`.
3. `openapi/metadata-graph.yaml`:
   - extend the column schema for `GET /v1/datasets/{urn}/columns`;
   - add `PUT /v1/datasets/{urn}/columns/{column}/classification` with a `Classification` enum component.
4. Entitlements access-decision schema: add `masked_columns`. Query-service response schema: add `masked_columns`.
5. Add backward-compatibility checks in CI. Diff against 2.3.0 with an OpenAPI/JSON-Schema
   breaking-change detector, and add golden v2.3.0 sample payloads that must still validate.
6. Release as a minor version (e.g. 2.4.0).

### 4.2 platform-sdk (after 4.1)
1. `MetadataClient`:
   - add the new column fields to the column model, optional and defaulting to `None`;
   - add `set_column_classification(urn, column, classification, reason)`.
2. Optional: add a shared `Classification` enum and a masking helper (`mask_value(value, data_type)`),
   so query-service and any other masking service mask the same way.
3. Make sure the event deserialisation helpers ignore unknown fields.
4. Release as a minor version (e.g. 3.5.0).

### 4.3 metadata-graph (after 4.1/4.2; team-graph owns)
1. `model.py`: add to `Column`:
   - `tags: list[str] = []`;
   - `suggested_classification: str | None = None`, `classification: str | None = None`;
   - `classification_source: str | None = None`.

   Put a `Classification` enum and the tag-to-classification mapping in a small new module
   (e.g. `classification.py`).
2. `consumers.py` `on_schema_discovered`:
   - read optional `c.get("tags", [])`; compute `suggested_classification`.
   - **Merge columns by name instead of replacing the list.** Today the code does
     `existing.columns = columns`, which would erase steward classifications (and
     descriptions) on every re-ingestion.
   - Keep the steward `classification` and `classification_source` for columns that still exist.
   - Update the suggestion. Set the effective value from the suggestion only when the source is not `STEWARD`.
   - Drop removed columns and add new ones.
   - Keep the existing `publish_dataset_changed(ds, kind)` signature (the tests monkeypatch it).
3. `api.py`:
   - add the new fields to `get_columns`;
   - add `PUT /v1/datasets/{urn}/columns/{column}/classification`. It validates the enum,
     checks the steward permission, stores the value, publishes `COLUMNS_CHANGED`, and records
     who and when (audit fields if required).
4. `publisher.py`: add `classification`, `classification_source` and `tags` to each column
   in `dataset_changed_payload`. Bump `platform-contracts` to 2.4.0 so `SCHEMA_REF` validation knows the fields.
5. `graph_store.py` / graph DB:
   - persist the new column properties;
   - write a one-off backfill that sets `null` for existing columns (no-op when properties are optional).
6. `requirements.txt`: bump `platform-sdk` and `platform-contracts`.
7. Tests:
   - extend `test_api.py` and `test_consumers.py`;
   - cover tag parsing, the most-sensitive-wins rule, steward override surviving re-ingestion,
     PUT validation (400/403/404), and event payload fields;
   - validate the payload against the contracts schema.
8. Feature flag `classification.publish_fields` (default on once contracts are released).
   The new fields are additive, so the flag is only a kill switch.

### 4.4 ingestion-service (after 4.1; parallel with 4.3)
1. Read source column comments in each connector. Parse `tags: ...` (case-insensitive,
   comma-separated, trimmed, lowercase) into `columns[].tags`, and pass the raw comment as `columns[].comment`.
2. Emit only after the contracts 2.4.0 bump. Columns without tags omit the field or send `[]`.
3. Tests:
   - parser unit tests: no comment, malformed comment, mixed case, extra spaces;
   - schema validation of the produced event against contracts.
4. Order versus metadata-graph does not matter: the current `on_schema_discovered` reads only
   the keys it knows, so extra fields are already ignored.

### 4.5 entitlements-service (after 4.3 is publishing classifications)
1. In its `metadata.dataset.changed.v1` consumer, store the effective classification per column
   (tolerate missing fields as `null`).
2. In access decisions, compute `masked_columns`: columns with `classification == PII` when the
   principal lacks a `pii:read` grant. Return an empty list otherwise.
3. Add the `pii:read` grant type if it does not exist, and give it to the current PII-authorised users before enforcement.
4. Flag: `masking.decisions.enabled`. Old callers ignore the new field.
5. Tests:
   - decision matrix (with/without grant x PII/non-PII/unclassified);
   - consumer test with old (v2.3.0) and new payloads.

### 4.6 query-service (inferred; after 4.5)
1. Read `masked_columns` from the access decision. Before returning results, replace those
   columns' values (type-preserving, see A6) and list them in response metadata.
2. Cover every egress path: result sets, exports/downloads, previews and samples, and caches
   (cache keys must include the masking set or grant).
3. Rollout modes:
   - `off`;
   - `shadow`: log what would be masked;
   - `enforce`.

   If the decision has no `masked_columns` field (older entitlements), mask nothing while not
   enforcing. After GA, apply the fail-closed policy from open questions.
4. Tests:
   - unit masking per data type;
   - contract test against the entitlements decision schema;
   - golden-response test that unmasked requests are byte-identical to today.

### 4.7 dq-service (inferred; after 4.3 + 4.2)
1. When building a DQ run for a dataset, fetch columns through `MetadataClient`
   (`GET /v1/datasets/{urn}/columns`). This gives the current classification and tags at run time.
   Alternative: consume `metadata.dataset.changed.v1`.
2. For `PII` columns, add PII-format rules chosen by tag subtype (`email`, `phone`, `ssn`, ...).
   Use a generic "PII present" rule when the subtype is unknown.
   - Rule failures must not log raw values; log only counts and redacted samples.
3. Keep `dq.result.published.v1` unchanged (metadata-graph only reads `score`). Per-rule
   detail goes in optional fields only if contracts add them (open question).
4. Flag: `dq.pii_rules.enabled`; first run in report-only mode so new failures do not drop scores overnight.
5. Tests: rule unit tests, and a contract test against the metadata-graph OpenAPI column schema.

### 4.8 reporting-service (verify only)
1. Run its `metadata.dataset.changed.v1` consumer tests with the new payload (contracts 2.4.0
   samples). Confirm unknown fields are ignored, and that it does not fail on the
   `COLUMNS_CHANGED` events produced by steward overrides (more events than before).
2. Confirm whether it returns column values to users. If it does, it becomes a code change
   that masks like query-service (open question).

## 5. Ordering

```
platform-contracts 2.4.0 ──┬─> platform-sdk 3.5.0 ──┬─> metadata-graph ──┬─> entitlements-service ──> query-service
                           │                        │                    ├─> dq-service
                           ├─> ingestion-service ───┘ (parallel)         └─> reporting-service (verify)
```

| Step | Work | Gate to proceed |
|---|---|---|
| 1 | platform-contracts 2.4.0 (additive) | breaking-change check green, old samples validate |
| 2 | platform-sdk 3.5.0 | SDK tests green against contracts 2.4.0 |
| 3a | metadata-graph deploy (store, API, event fields, merge fix) | existing tests + new tests green; reporting/entitlements consumer tests pass on new payload |
| 3b | ingestion-service emits tags (can go with 3a) | produced events validate against 2.4.0 |
| 4 | Backfill: re-ingest or replay schemas so existing datasets get suggestions; stewards review PII candidates | coverage report of classified columns |
| 5 | entitlements-service `masked_columns` (flag on) | decision matrix tests; `pii:read` grants provisioned |
| 6 | query-service shadow mode, then enforce per domain | shadow logs reviewed with data governance |
| 7 | dq-service PII rules report-only, then enforce | rule false-positive rate reviewed |
| 8 | Make masking fail-closed (if agreed); remove flags | — |

## 6. Compatibility and rollout (AC6)

- No topic, endpoint or field is removed or renamed. Every new field is optional. The only
  new endpoint is additive. No consumer must upgrade at the same time as a producer.
- Rolling deploys: each service ignores unknown fields and handles missing fields as
  `null`, so old and new versions can run side by side.
- Masking changes behaviour, not shape. That is why it ships last, behind flags, in shadow
  first, and is enabled per domain. Before `enforce`, grant `pii:read` to principals who
  legitimately read PII today, so they see no change.
- Rollback: turn the flags off (query masking, entitlements decisions, DQ rules). The
  metadata fields can stay because they are inert for old consumers.
- Graph data: the new column properties are optional. The backfill is idempotent and can be
  re-run, with no downtime and no migration lock.

## 7. Cross-repository testing

**Contract tests**
- platform-contracts CI: breaking-change diff against 2.3.0, and validation of old and new
  sample payloads for both event schemas and the OpenAPI.
- Producer-side schema validation:
  - metadata-graph validates `dataset_changed_payload` output against `metadata.dataset.changed.v1` 2.4.0;
  - ingestion-service validates its event against `ingestion.schema.discovered.v1` 2.4.0.
- Consumer-driven (Pact-style) tests:
  - entitlements-service and reporting-service on `metadata.dataset.changed.v1`;
  - metadata-graph on `ingestion.schema.discovered.v1` and `dq.result.published.v1`;
  - dq-service on `GET /v1/datasets/{urn}/columns`;
  - query-service on the access-decision response.
- Each provider verifies the published consumer expectations in CI.
- Compatibility matrix in every consumer: new consumer with an old payload (no new fields),
  and old consumer with a new payload (extra fields).

**Integration / end-to-end (staging, synthetic data)**
1. Ingest a source table whose column `email` has comment `tags: pii,email` and whose column
   `country` has no comment. Expect:
   - `ingestion.schema.discovered.v1` carries tags;
   - `GET .../columns` shows `email` with suggested and effective `PII`, and `country` as `null`;
   - the change event carries the same values.
2. A steward runs `PUT .../columns/country/classification` with `CONFIDENTIAL`. Expect a
   `COLUMNS_CHANGED` event, then re-ingest the same schema and check the override persists.
3. Request an access decision without `pii:read`: `masked_columns == ["email"]`. With `pii:read`: `[]`.
4. Query the dataset as both principals:
   - without `pii:read`: `email` is masked and the other columns match today's output;
   - with `pii:read`: the result is identical to today.
5. Trigger a DQ run:
   - the email-format rule runs on `email` only;
   - `dq.result.published.v1` still validates;
   - metadata-graph still updates `quality_score`.
6. A steward downgrades `email` to `INTERNAL`. Expect the event to propagate and masking to stop.
   Measure end-to-end propagation latency against an agreed SLO.
7. Regression: run the existing metadata-graph test suite and the reporting-service suite unchanged.

## 8. Risks

| Risk | Mitigation |
|---|---|
| Re-ingestion wipes steward classifications (current `existing.columns = columns` replace) | Merge by column name in 4.3; dedicated test |
| PII leak through an unmasked egress path (exports, caches, previews, reporting-service) | Inventory egress paths in query-service and reporting-service; shadow logs; fail-closed after GA |
| Event lag: a classification change has not reached entitlements when a query runs | Define a propagation SLO; consider entitlements fetching classification on cache miss; fail-closed for known PII |
| Users who legitimately read PII lose access when enforcement starts | Provision `pii:read` before `enforce`; per-domain rollout |
| Untagged PII columns stay unclassified (suggestion only as good as source comments) | Steward review queue / coverage report; optional name-based heuristics later |
| Strict consumers reject unknown fields | Consumer compatibility tests before metadata-graph starts publishing |
| DQ PII rules lower quality scores suddenly | Report-only phase first |
| DQ logs leak raw PII from failing values | Redact samples in rule output |
| Inferred repo names and endpoints are wrong | Confirm with the owning teams before work items are created (open questions) |

## 9. Open questions

See `open_questions` in `IMPACT_ANALYSIS.json`. The main ones:
- Which repositories own ingestion, DQ and the query path? Does reporting-service serve data values?
- Is masking limited to `PII`, or also some `CONFIDENTIAL` columns? What is the default for unclassified columns?
- Should masking fail closed or fail open? What is the mask format per type?
- What is the tag-to-classification and tag-to-DQ-rule mapping? Is a classification-change audit trail required?
