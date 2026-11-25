# DP-1423 — Column-level sensitivity classification and PII masking

Implementation plan (no code). Synthetic example; all repositories referenced
are the folders under `workspace/`, each a separate git repository in production.
Machine-readable impact data: `IMPACT_ANALYSIS.json` in this folder.

## 1. Summary

The ticket is owned by team-metadata, but only about a third of the work is in
`metadata-service`. Data enters through `ingestion-service`, contracts are owned by
`platform-contracts` and wrapped by `platform-sdk`, decisions come from
`entitlements-service`, enforcement is in `consumption-gateway`, and quality rules run in
`transformation-service`. Two compatibility hazards drive the ordering:

1. **platform-sdk drops undeclared fields.** `Column`, `Dataset` and `Decision` are
   explicit dataclasses. A consumer still on SDK 3.4.1 silently loses
   `classification` and `masked_columns`. That makes masking **fail open**: nothing
   gets masked and nothing errors.
2. **search-indexer validates strictly against a stale vendored schema.** Its copy of
   `metadata.dataset.changed.v1` was vendored from platform-contracts 2.1.0 and sets
   `additionalProperties: false` on the event, on `dataset` and on each column. As
   soon as `metadata-service` adds any column field, every change event goes to
   `search-indexer.dlq` and the catalog index stops updating.

Every contract change below is additive (optional fields, one new endpoint), so it
fits a platform-contracts **minor** release (2.3.0 → 2.4.0). No `.v2` topics or
`/v2` APIs are needed.

## 2. Repositories and work items

| # | Repository | Team | Impact | Depends on |
|---|---|---|---|---|
| R1 | platform-contracts | team-platform | code change | — |
| R2 | platform-sdk | team-platform | code change | R1 |
| R3 | search-indexer | team-discovery | code change | R1 (schema text) |
| R4 | reporting-service (not in workspace) | unknown | verify only | R1 |
| R5 | metadata-service | team-metadata | code change | R2; event emission gated on R3, R4 |
| R6 | ingestion-service | team-ingest | code change | R2 (tags reach classification only after R5) |
| R7 | entitlements-service | team-access | code change | R2, R5 |
| R8 | consumption-gateway | team-consumption | code change | R2, R7 |
| R9 | transformation-service | team-transformation | code change | R2, R5 |
| R10 | platform-e2e | team-platform + each team | code change | all of the above |

Not impacted: `lineage-service` (tolerant reader of `dataset.urn`/`dataset.name`),
`notification-service` (reads only `score`, `dataset_urn` and owner),
`usage-metering` (`consumption.access.logged.v1` is unchanged).

### R1 platform-contracts (release 2.4.0)
- `events/ingestion.schema.discovered.v1.json`: add optional
  `columns[].tags: array<string>`.
- `events/metadata.dataset.changed.v1.json`: add these optional column fields:
  `classification` (enum `PUBLIC|INTERNAL|CONFIDENTIAL|PII`, nullable),
  `classification_source` (enum `SUGGESTED|STEWARD`, nullable) and `tags`
  (array<string>). Do **not** add a new `change_type` value. A classification edit
  is published as `UPDATED`, because a new enum value would break strict readers.
- `openapi/metadata-service.yaml` (1.4.0 → 1.5.0): add the same three optional fields
  to `Column`. Add `PUT /v1/datasets/{urn}/columns/{column_name}/classification`
  with request `{classification}`, a 200 response returning `Column`, and
  400/403/404 errors.
- `openapi/entitlements-service.yaml` (1.2.0 → 1.3.0): add
  `masked_columns: array<string>` (default `[]`) to `Decision`.
- `openapi/consumption-gateway.yaml` (2.0.0 → 2.1.0): add optional
  `masked_columns: array<string>` to the 200 response, and document the mask value.
- Add contract tests: old sample payloads must still validate (backward), and new
  payloads must validate against the new schemas.

### R2 platform-sdk (release 3.5.0)
- Bump the `platform-contracts` pin to 2.4.0 in `pyproject.toml`.
- `metadata.Column`: add `classification: str | None = None`,
  `classification_source: str | None = None` and `tags: tuple[str, ...] = ()`.
  Parse them with `.get()` so the SDK keeps working against an old metadata-service.
- `MetadataClient.set_column_classification(urn, column_name, classification)`.
- `entitlements.Decision`: add `masked_columns: tuple[str, ...] = ()` (and optionally
  `policy_id`). Parse with `body.get("masked_columns", [])`. Add a way to tell
  "field absent" from "empty", e.g. `masking_evaluated: bool`, so the gateway can
  fail closed once enforcement is on.
- Every new field has a default, so existing call sites and positional constructors
  (`Decision(allow, reason)`) keep working. Publish 3.5.0, then raise bump PRs in
  R5–R10.

### R3 search-indexer
- Re-vendor `schemas/metadata.dataset.changed.v1.json` from platform-contracts
  2.4.0. Keep `additionalProperties: false` (which is intentional), but list the new
  column properties explicitly.
- Optionally index `classification` per column, for example so the catalog can
  filter by PII. Decide this with the index-mapping owners.
- Tests: a 2.4.0 payload with the classification fields is indexed and not sent to
  the DLQ. The existing unknown-field-goes-to-DLQ test still passes.
- **Must be deployed before R5 turns on the new event fields.**
- Follow-up (not blocking): add a CI check that compares the vendored schema with
  the released platform-contracts version. This drift is what caused the hazard.

### R4 reporting-service (verify only; repository not available)
- It is listed in the metadata-service README as a consumer of
  `metadata.dataset.changed.v1`. Ask its owners to replay 2.4.0 sample events and
  confirm it is a tolerant reader.
- Also confirm whether it exposes column data to users. If it does, masking may
  also be needed there (see open questions).
- Treat the result as a gate on R5 enabling the event fields.

### R5 metadata-service (team-metadata, owner of the ticket)
- **Model** (`model.py`): add `classification`, `classification_source` and `tags`
  to `Column`, all optional and defaulting to `None`/empty.
- **Storage** (`metadata_store.py`, production metadata DB): add the column-node
  properties. Existing nodes need no migration, because absent means unclassified.
  Persist an audit trail of steward changes (who, when, old value, new value), if
  the metadata DB supports it.
- **Suggestion on ingest** (`consumers.on_schema_discovered`):
  - Read `columns[].tags` from the event. Map them to a suggested classification
    with a configurable table in `config/settings.yaml`, e.g. `pii` → `PII`, with
    room for `confidential` → `CONFIDENTIAL`, etc.
  - Set `classification_source=SUGGESTED`.
  - **Merge by column name instead of replacing the column list.** If a column
    already has `classification_source=STEWARD`, keep the steward value. Today
    `existing.columns = columns` would wipe overrides on every re-discovery.
  - Tolerate events without `tags`, which is what ingestion-service sends today.
- **API** (`api.py`):
  - `GET /v1/datasets/{urn}/columns` returns the new fields.
  - Add `PUT /v1/datasets/{urn}/columns/{column_name}/classification`. It validates
    the enum, sets `classification_source=STEWARD`, upserts, and publishes
    `metadata.dataset.changed.v1` with `UPDATED`.
  - Add a steward authorization check (mechanism is an open question).
  - Optionally allow clearing an override, which reverts to the suggestion.
- **Publisher** (`publisher.py`): include the three fields per column, behind the
  flag `emit_column_classification`, which defaults off until R3/R4 are confirmed.
  Always publish on a classification change, because entitlements cache
  invalidation depends on it.
- **Dependencies**: bump `platform-sdk==3.5.0` and `platform-contracts==2.4.0`.
- **Tests**: tags → suggestion; steward override survives re-discovery; PUT
  validation and 404s; GET returns the fields; the published payload validates
  against 2.4.0 and (with the flag on) against search-indexer's new vendored schema.

### R6 ingestion-service
- `connectors/postgres.py`: parse `column_comment` with a tolerant parser that
  handles `tags: pii,email`, case and whitespace differences, extra comment text,
  and a missing or NULL comment. Emit `tags` (lowercased list, omitted or `[]` when
  there are none). Keep `name/type/nullable` unchanged.
- `publisher.py`: no signature change. Columns now carry `tags`.
- Bump `platform-sdk==3.5.0` so publish-time validation uses the 2.4.0 schema. The
  2.3.0 schema has no `additionalProperties: false`, so this could ship earlier,
  but pin anyway.
- Tests: update `test_discover_columns_maps_name_type_nullable`, whose expected
  output changes, and add parser edge cases.
- Other connectors: the workspace only shows Postgres. Check other connectors for
  equivalent tag sources (open question).
- Can ship any time after R2, because metadata-service ignores unknown column keys
  today. Suggestions only appear once R5 is live.

### R7 entitlements-service
- `policies.PolicyEngine`:
  - Also fetch columns (`MetadataClient.get_columns`, SDK 3.5.0) and cache them
    alongside the dataset. The existing `invalidate(urn)` on
    `metadata.dataset.changed.v1` must clear both.
  - After an allow decision, compute `masked_columns` as the columns with
    `classification == "PII"`, unless the principal holds `pii:read`. Proposed grant
    format: global `pii:read`, possibly with scoped variants (open question).
  - Deny decisions return `masked_columns=[]`.
  - `Decision` dataclass: add `masked_columns: list[str] = field(default_factory=list)`.
- `api.decide`: already uses `asdict`, so the new field is serialized automatically.
  Check JSON key order and types against the OpenAPI spec.
- Flag `compute_masked_columns` (default off → always `[]`) so the service can
  deploy safely before data is classified.
- **Fail-safe on metadata errors.** If columns cannot be fetched, either deny or
  mark every column of unknown classification. Do not silently return `[]`.
- Tests: no pii:read → PII columns listed; pii:read → `[]`; deny → `[]`; cache is
  invalidated on a change event.

### R8 consumption-gateway
- `query.QueryService.run`: after the allow decision, replace the values of
  `decision.masked_columns` in each row with the mask value, and add
  `masked_columns` to the response. Keys and row count are unchanged.
  `consumption.access.logged.v1` is unchanged.
- Proposed mask value: `"***"` for string-typed columns and `null` for others, so
  typed consumers do not get type changes (open question).
- Mapping result columns to source columns: phase 1 matches by result key name for
  single-dataset queries. Flag that aliases, expressions and joins can bypass this
  (major risk; see section 7).
- Rollout modes, controlled by the flag `pii_masking_mode`:
  - `off`: current behavior.
  - `shadow`: compute and log what would be masked, return rows unmasked.
  - `enforce`: mask the values.
  - In `enforce`, if the decision did not evaluate masking (old entitlements or old
    SDK), **fail closed** with 503/403 instead of returning PII.
- Bump `platform-sdk==3.5.0`. Without it, `Decision.masked_columns` is dropped and
  masking silently does nothing.
- Tests: masked rows, unmasked rows with pii:read, the 403 path is unchanged, and
  fail-closed in enforce mode.

### R9 transformation-service
- `rules/`: add PII-format rules, e.g. `pii_email_format`, `pii_phone_format` and
  `pii_ssn_format`, plus a generic `pii_format` that dispatches on the column tag.
  Null values are skipped or handled by `not_null`.
- `runner.py`: alongside `DEFAULT_BINDINGS` by `data_type`, add
  `CLASSIFICATION_BINDINGS = {"PII": [...]}`. Select the format-specific rule from
  `col.tags` (e.g. `email`). If there is no subtype, use the generic check or skip
  with a recorded reason.
- `transformation.result.published.v1` shape is unchanged (`rule` is a free string), so
  `metadata-service` and `notification-service` need no code change.
- Flag `pii_rules_affect_score`. Start report-only, i.e. results are published but
  excluded from `score`, so existing datasets do not suddenly drop below the
  notification threshold (0.9) and flood owners.
- Make sure transformation result payloads and logs never contain the raw PII values: results
  carry only `column`, `rule` and `passed`.
- Bump `platform-sdk==3.5.0`, which is required to see `classification`.
- Tests: rule unit tests; the runner applies PII rules only to PII columns.

### R10 platform-e2e
- `test_ingest_to_metadata.py`: a source column with comment `tags: pii,email` ends
  up with `classification == "PII"` and `classification_source == "SUGGESTED"`.
  A steward override survives a re-ingest.
- `test_access_flow.py`:
  - `bob` (`domain:crm:read`, no `pii:read`) gets rows with `email` masked and
    `masked_columns == ["email"]`.
  - `carol` (`domain:crm:read` + `pii:read`) gets unmasked rows.
  - The existing 403 test is unchanged.
  - After a steward reclassifies a column, the next query reflects it, which
    proves cache invalidation via `metadata.dataset.changed.v1`.
- `test_transformation_flow.py`: a PII email column with a malformed value produces a failed
  `pii_email_format` result.
- New test: a `metadata.dataset.changed.v1` event with classification is indexed by
  search-indexer and the DLQ stays empty.
- Extend the `int_env` helpers (`classify`, `grant` for `pii:read`, DLQ inspection).

## 3. Ordering

```
R1 platform-contracts 2.4.0
  └─> R2 platform-sdk 3.5.0
        ├─> R3 search-indexer (re-vendor schema)  ─┐  gates
        ├─> R4 reporting-service verification     ─┤  metadata-service
        ├─> R5 metadata-service (store/API; event fields behind flag) <─┘
        │     ├─> R7 entitlements-service ──> R8 consumption-gateway
        │     └─> R9 transformation-service
        ├─> R6 ingestion-service (tags; any time after R2)
        └─> SDK bumps in R7/R8/R9 can merge early (no behavior change)
R10 platform-e2e: suites added alongside each step, all green before enforcement
```

## 4. Rollout (no breaking change, no downtime)

1. **Contracts and SDK**: release platform-contracts 2.4.0 and platform-sdk 3.5.0.
   No runtime change.
2. **Make readers tolerant first**: deploy search-indexer with the new vendored
   schema. Get confirmation from reporting-service. Merge the SDK 3.5.0 bumps in
   entitlements-service, consumption-gateway and transformation-service with all flags off.
3. **metadata-service**: deploy storage, API fields and the PUT endpoint. The GET
   fields are additive and safe immediately. Turn on `emit_column_classification`
   in `int`, watch `search-indexer.dlq`, then turn it on in prod.
4. **ingestion-service**: deploy tag extraction. Optionally trigger re-discovery of
   existing datasets to backfill suggestions. Stewards review the suggestions and
   override where needed.
5. **entitlements-service**: turn on `compute_masked_columns`. Gateway is still
   `off`/`shadow`, so this has no user-visible effect.
6. **consumption-gateway**: run `shadow` and compare the would-mask logs with steward
   expectations. Grant `pii:read` to principals who legitimately need it (this
   must happen **before** enforcement, or those users lose access). Then switch to
   `enforce` per domain or tenant.
7. **transformation-service**: turn on PII rules report-only, then
   `pii_rules_affect_score=true` once results are reviewed.

Rollback: every step is controlled by its own flag. Turning a flag off returns that
step to current behavior. No contract step has to be reverted, because all of them
are additive.

## 5. Cross-repository testing

- **Contract tests (platform-contracts CI)**:
  - Golden payloads for each changed topic and endpoint must validate under 2.4.0.
  - Golden 2.3.0 payloads must still validate (backward compatibility).
  - A diff check must reject any removed or renamed field.
- **Consumer-driven contract tests**:
  - search-indexer: the vendored schema must accept the provider's golden
    `metadata.dataset.changed.v1` payloads. Run this in metadata-service CI against
    the latest search-indexer schema, and in search-indexer CI against the latest
    contracts.
  - entitlements and transformation-service: SDK `MetadataClient.get_columns` against a
    recorded metadata-service 1.5.0 response.
  - consumption-gateway: `EntitlementsClient.decide` against a recorded 1.3.0 response,
    including the old 1.2.0 response with no `masked_columns`, to exercise
    fail-closed.
- **Unit tests** in each repository, as listed per work item.
- **Integration / end-to-end** (`platform-e2e` in `int`): the suites in R10, run
  for each flag state (off / shadow / enforce). Include a mixed-version run (new
  metadata-service with old gateway, and the reverse) to prove step-by-step rollout
  is safe.
- **Production checks**: `search-indexer.dlq` depth, rate of
  masked_columns/decision, gateway 5xx/403 rate, transformation score distribution and
  notification volume.

## 6. Assumptions

- Only `PII` columns are masked. `PUBLIC`, `INTERNAL` and `CONFIDENTIAL` are stored
  and returned but not enforced in this ticket.
- Unclassified (null) columns are not masked, which preserves current behavior.
  A stricter default needs a governance decision.
- `pii:read` is a single global grant string checked by entitlements-service.
- The tags-to-classification mapping lives in metadata-service. ingestion-service
  only forwards raw tags.
- Column `tags` are stored and returned by metadata-service so transformation-service can choose
  the PII format subtype.
- Masking is enforced only in consumption-gateway, the documented consumer-facing path.
  entitlements-service stays decision-only.
- reporting-service exists outside this workspace. Its name comes from the
  metadata-service README.

## 7. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| search-indexer strict vendored schema (2.1.0) | All change events go to DLQ, catalog search goes stale | R3 deploys before the event flag; consumer contract test; DLQ alert |
| A service stays on SDK 3.4.1 | Classification / masked_columns silently dropped → PII returned unmasked | Required SDK bumps; gateway fails closed in enforce mode; e2e test |
| Re-discovery overwrites steward overrides | Classification regresses, PII exposed | Merge-by-name with STEWARD priority; e2e re-ingest test |
| Stale entitlements cache | Reclassified column not masked until cache refresh | Publish on every classification change; invalidate columns cache; TTL as backstop |
| SQL aliases/expressions/joins bypass name-based masking | PII leak | Restrict enforce to simple projections first, or warehouse-side masking/views; open question |
| Users who need PII lose access at enforcement | Business disruption | Shadow mode plus `pii:read` provisioning before enforce |
| Mask value changes column types | Typed BI consumers break | Type-preserving mask (null for non-strings); `masked_columns` in response |
| PII rules lower transformation scores | Spike in notification-service emails | Report-only phase before rules count toward the score |
| Tag parsing differs across sources | Missed or false PII suggestions | Tolerant parser, steward review, other connectors audited |
| reporting-service unknown | Possible break or unmasked exposure | Owner verification is a gate before the event flag |

## 8. Open questions

See `open_questions` in `IMPACT_ANALYSIS.json`. The ones that block design:
- `pii:read` grant scope.
- Mask representation.
- How SQL result columns are mapped back to source columns.
- Steward authorization for the PUT endpoint.
- Whether reporting-service (or any other path) exposes column data and also needs
  masking.
