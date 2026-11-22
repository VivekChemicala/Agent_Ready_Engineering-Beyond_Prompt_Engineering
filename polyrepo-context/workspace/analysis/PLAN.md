# DP-1423 implementation plan: column sensitivity classification and PII masking

> Synthetic example. Every service, team and ticket is fictional.
> Machine-readable impact analysis: `IMPACT_ANALYSIS.json` (same folder).

## 1. Summary

The ticket lands on team-graph, but the data path crosses eight repositories
plus the e2e suite:

```
source comment "tags: pii,email"
  -> ingestion-service --ingestion.schema.discovered.v1 (columns[].tags)--> metadata-graph
       metadata-graph stores classification per column, steward PUT overrides
       --metadata.dataset.changed.v1 (columns[].classification)--> entitlements-service (cache invalidation), search-indexer (strict), lineage-service
       --GET /v1/datasets/{urn}/columns (classification)--> entitlements-service, dq-engine (through platform-sdk)
  query-gateway --POST /v1/access/decide--> entitlements-service returns masked_columns
  query-gateway masks those columns in POST /v1/query results
  dq-engine binds PII-format rules to columns classified PII
```

Three platform constraints decide the plan:

- **ADR-004.** `platform-sdk` typed models drop undeclared fields. A new field
  in the metadata-graph or entitlements API cannot be seen by
  entitlements-service, dq-engine or query-gateway until the SDK model is
  extended and released, and each of those repos bumps the SDK.
- **ADR-007.** entitlements-service decides and query-gateway enforces. Masking
  logic must not go into metadata-graph or the warehouses.
- **ADR-009 and the consumer registry.** Additive optional fields stay on `.v1`.
  `search-indexer` is a strict reader (vendored contracts 2.1.0,
  `additionalProperties: false`, unknown fields go to the DLQ). It must be
  upgraded and deployed before metadata-graph emits the new field on
  `metadata.dataset.changed.v1`.

Every contract change here is additive and optional. No `.v2` topic or `/v2`
API is needed.

## 2. Design decisions and assumptions

| # | Decision | Why |
|---|---|---|
| D1 | `ingestion-service` forwards the raw source tags (`columns[].tags: ["pii","email"]`). `metadata-graph` maps tags to a classification. | Keeps classification policy in one owning service. Ingestion only reports facts about the source. |
| D2 | Mapping: `pii`->PII, `confidential`->CONFIDENTIAL, `internal`->INTERNAL, `public`->PUBLIC. The most sensitive tag wins. Other tags (`email`, `phone`) are kept as hints for DQ rule selection. | AC1. The PII subtype is needed to pick a format rule (AC5). |
| D3 | Column fields: `classification` (nullable enum), `classification_source` (`SOURCE_TAG` or `STEWARD`), `suggested_classification` (last tag-derived value), `tags`. | A steward override must survive re-ingestion, and stewards need to see the suggestion next to the override. |
| D4 | A tag-derived suggestion becomes the effective classification when no steward value exists. A `STEWARD` value is never overwritten by ingestion. Only `suggested_classification` is refreshed. | Fail-safe: PII-tagged columns are masked before a steward reviews them (open question). |
| D5 | Untagged columns have `classification: null` (unclassified). They are not masked. | Avoids masking the whole platform on day one. Open question whether to default to INTERNAL. |
| D6 | Classification changes publish `metadata.dataset.changed.v1` with the existing `change_type: UPDATED`. No new enum value is added. | Adding an enum value changes meaning for strict and enum-validating readers (ADR-009). entitlements-service already invalidates its cache on any change event. |
| D7 | The decision gains `masked_columns: [column names]`. It is empty when the principal holds `pii:read` or the dataset has no PII columns. Datasets stay `allow: true`. | AC3. Additive. Old gateways ignore the field, which keeps today's behaviour. |
| D8 | The gateway replaces masked values with `null` (configurable token) and adds `masked_columns` to the response. Row keys stay the same. | AC4 without changing the response shape. Final format is an open question. |
| D9 | If the gateway cannot safely mask a query (a PII column used inside an expression, join, filter or alias it cannot resolve), it returns 403 with a reason. It does not return unmasked data. | Name-based masking can be bypassed. Fail closed. |
| D10 | Every user-visible behaviour sits behind per-environment flags, listed in section 5. | Change playbook step 5. Supports AC6 (no downtime). |

## 3. Per-repository work items

Item IDs (e.g. `C1`) are referenced in the ordering in section 4.

### platform-contracts (team-platform). Release 2.4.0 (minor)
- **C1** `events/ingestion.schema.discovered.v1.json`: add optional
  `columns[].tags` (array of strings).
- **C2** `events/metadata.dataset.changed.v1.json`: add optional
  `dataset.columns[].classification` (enum `PUBLIC|INTERNAL|CONFIDENTIAL|PII`,
  nullable), `classification_source` (enum `SOURCE_TAG|STEWARD`) and `tags`.
  Leave the `change_type` enum unchanged.
- **C3** `openapi/metadata-graph.yaml` (1.4.0 to 1.5.0): add the new fields to
  `Column`. Add `PUT /v1/datasets/{urn}/columns/{column}/classification` with
  body `{classification, reason?}` and responses 200 (Column), 400, 404 and
  403 (not a steward).
- **C4** `openapi/entitlements-service.yaml` (1.2.0 to 1.3.0): add
  `Decision.masked_columns` (array of strings, optional).
- **C5** `openapi/query-gateway.yaml` (2.0.0 to 2.1.0): add the optional
  response `masked_columns`. Document the masking token.
- **C6** `openapi/dq-engine.yaml`: add an optional rule-binding selector
  `{classification, tag?}`.
- **C7** Add example payloads and fixtures for every changed contract, used by
  consumer contract tests. Add a compatibility check in CI: every 2.3.0
  fixture must still validate against 2.4.0.

### platform-sdk (team-platform). Release 3.5.0
- **S1** Pin `platform-contracts==2.4.0`, so publish validation accepts the new
  event fields.
- **S2** `MetadataClient`: add optional `classification`,
  `classification_source`, `suggested_classification` and `tags` to the column
  dataclass (default `None` or empty). Add
  `set_column_classification(urn, column, classification, reason=None)`.
- **S3** `EntitlementsClient`: add `masked_columns: tuple[str, ...] = ()` to the
  `Decision` dataclass (and `policy_id`, which is dropped today).
- **S4** Add a shared `Classification` enum and a `classification_from_tags()`
  helper, so the mapping is not re-implemented in each repo. metadata-graph
  is the only caller that applies it.
- **S5** Tests: the models parse both 2.3.0 and 2.4.0 fixtures, and missing
  fields fall back to defaults.

### metadata-graph (team-graph, owning team)
- **M1** `model.py`: add `classification`, `classification_source`,
  `suggested_classification` and `tags` to `Column`. Migrate graph-DB column
  nodes with nullable properties, so no backfill is needed to deploy.
- **M2** `consumers.on_schema_discovered`: read optional `tags`, compute the
  suggestion, and **merge** with existing columns by name. Today
  `existing.columns = columns` replaces the columns, which would wipe steward
  overrides (and `description`). Keep `STEWARD` values. Apply the suggestion
  only when no steward value exists.
- **M3** `api.py`: return the new fields from `GET /v1/datasets/{urn}/columns`.
  Add the `PUT .../columns/{column}/classification` route with validation, a
  steward authorisation check (see open questions) and an audit log entry. It
  publishes `UPDATED`.
- **M4** `publisher.py`: include the new column fields in
  `dataset_changed_payload`, behind flag `classification.emit_in_events`
  (default off until search-indexer is upgraded everywhere).
- **M5** `requirements.txt`: bump to `platform-sdk==3.5.0` and
  `platform-contracts==2.4.0`.
- **M6** Tests: tag-to-classification mapping, steward override sticky across
  re-ingestion, PUT 200/400/404, event payload validates against 2.4.0 with
  the flag on and against 2.3.0 with it off, and GET columns provider contract
  test.
- **M7** README: fix the consumer list (it names the decommissioned
  reporting-service and omits lineage-service and search-indexer). Document
  the classification fields.

### ingestion-service (team-ingest)
- **I1** Postgres connector: parse `tags:` from column comments (case-insensitive,
  comma-separated, trimmed). Emit them as `columns[].tags`. Omit the field when
  a column has no tags. Other connectors leave it out.
- **I2** Bump `platform-sdk==3.5.0`, so publish validation knows the field.
- **I3** Tests: comment parsing edge cases (no tags, mixed case, other comment
  text) and the published payload validates against 2.4.0.
- Flag: `schema_discovery.emit_tags`.

### search-indexer (team-discovery). **Must ship first among consumers**
- **X1** Re-vendor the `metadata.dataset.changed.v1` schema from contracts
  2.4.0 (it is currently 2.1.0). First diff 2.1.0 against 2.3.0 and check the
  DLQ for events already rejected.
- **X2** Optional: index `classification`, so catalog search can show or filter
  PII columns. Never index column values.
- **X3** Contract test: a 2.4.0 fixture with classification is indexed and not
  dead-lettered.
- **X4** Deploy to every environment before metadata-graph turns on
  `classification.emit_in_events`.

### entitlements-service (team-access)
- **E1** Bump `platform-sdk==3.5.0`.
- **E2** Load columns with `MetadataClient.get_columns(urn)` next to the
  dataset attributes it already loads. Cache them with the same key and the
  same invalidation on `metadata.dataset.changed.v1`.
- **E3** Define or confirm the `pii:read` grant (scope is an open question).
  On `POST /v1/access/decide`, when `allow` is true and the principal lacks
  `pii:read`, set `masked_columns` to the PII column names. Record the policy
  in `policy_id` and `reason`.
- **E4** Fail closed: if columns cannot be loaded while masking is enabled,
  return `allow: false` with reason `CLASSIFICATION_UNAVAILABLE`.
- **E5** Flag `column_masking.decide` (default off, which keeps
  `masked_columns` empty).
- **E6** Tests: with and without the grant, no PII columns, cache invalidation
  after a classification change event, provider contract test for the
  Decision.

### query-gateway (team-serving)
- **Q1** Bump `platform-sdk==3.5.0`. Without it, `masked_columns` is dropped by
  the SDK (ADR-004).
- **Q2** Apply `masked_columns` to result rows: replace values with the masking
  token and add `masked_columns` to the response.
- **Q3** Resolve output-column lineage for the SQL (`SELECT *`, aliases,
  expressions). Reject with 403 any query that uses a masked column in a way
  that cannot be masked (WHERE, JOIN keys, GROUP BY, functions), per D9.
- **Q4** Flag `column_masking.enforce` with modes `off`, `shadow` (compute and
  log what would be masked, return unmasked data, which matches current
  behaviour) and `on`. Rows are never cached unmasked for a principal
  without `pii:read`.
- **Q5** Tests: masking applied, aliasing and `SELECT *`, 403 on unsafe
  expressions, principal with `pii:read` sees values, empty `masked_columns`
  leaves the response unchanged.

### dq-engine (team-quality)
- **D1** Bump `platform-sdk==3.5.0`, so `get_columns` returns classification
  and tags.
- **D2** Extend binding resolution: when a column is classified PII, bind
  PII-format rules (for example `pii.email_format` when the tag is `email`,
  `pii.phone_format` for `phone`) alongside the data-type rules. Add the new
  selector to `POST/GET /v1/rules`.
- **D3** Results stay on `dq.result.published.v1` with the existing shape.
  Results carry only the column name, rule and pass/fail. Never include
  sample values.
- **D4** Flag `pii_rules.enabled`. Tests: PII column gets PII rules,
  non-PII column is unchanged, a dataset fetched without classification
  (old graph) is unchanged.

### lineage-service, notification-service. Verify only
- **V1** Run the existing contract tests against the 2.4.0 fixtures for
  `metadata.dataset.changed.v1` (lineage) and `dq.result.published.v1` with
  the new PII rule names (notification). No SDK bump is required, because the
  fields they read are unchanged.

### platform-e2e (team-platform)
- **P1** New suite `column_classification_masking`, described in section 6.

### architecture-docs (documentation only, not a code change)
- Update `flows/access-decision.md` (column-level decisions),
  `flows/ingest-to-graph.md` (tags are now propagated) and
  `flows/data-quality.md` (classification bindings). Add a short ADR for
  D4, D6 and D9.

## 4. Ordering and dependencies

```
C1-C7 platform-contracts 2.4.0
  ├─> S1-S5 platform-sdk 3.5.0
  │     ├─> M1-M6 metadata-graph (store + API + PUT; events flag OFF)
  │     ├─> I1-I3 ingestion-service (tags; metadata-graph is tolerant so order vs M is free, but enable after M2 is live)
  │     ├─> E1-E6 entitlements-service (needs M3 live for get_columns fields)
  │     ├─> D1-D4 dq-engine (needs M3 live)
  │     └─> Q1-Q5 query-gateway (needs E3 deployed before enforcement)
  └─> X1-X4 search-indexer re-vendor + deploy to all envs
                └─> M4 flag classification.emit_in_events ON
V1 verification of lineage/notification against 2.4.0 fixtures (any time after C7)
P1 platform-e2e suite (after all of the above are in int)
```

| Wave | Ships | Gate to next wave |
|---|---|---|
| 0 | platform-contracts 2.4.0 | Compatibility CI green |
| 1 | platform-sdk 3.5.0; search-indexer re-vendored and deployed in all envs | SDK tests green on 2.3.0 and 2.4.0 fixtures; search-indexer DLQ is empty for 2.4.0 fixtures |
| 2 | metadata-graph (M1-M3, M5-M7) with the events flag off | GET columns returns the new fields in int; existing consumers' tests are green |
| 3 | ingestion-service tags on; metadata-graph `classification.emit_in_events` on, per env | Classifications appear on tagged columns; search-indexer DLQ unchanged; lineage and entitlements are healthy |
| 4 | entitlements-service (`column_masking.decide` on), dq-engine (`pii_rules.enabled` on), lineage/notification verification | Decisions contain the expected `masked_columns` in int |
| 5 | query-gateway `shadow`, then `on`, per env (int, staging, prod) | Shadow logs match expectations and steward review of the classifications is done; platform-e2e is green |

Optional backfill before wave 5 in prod: re-run schema discovery for Postgres
sources, so existing datasets get classifications.

## 5. Compatibility and rollout

- **Contracts.** Every change is additive and optional. Producers built on
  2.3.0 still validate against 2.4.0. Consumers on the old SDK ignore the new
  fields (ADR-004), so their behaviour does not change. That is safe for
  every service except the masking path, and the masking path is gated by
  flags.
- **Strict consumer.** search-indexer is upgraded and deployed everywhere
  before the metadata-graph event flag is on. Rollback: turn the flag off.
  Payloads go back to the 2.3.0 shape.
- **No breaking enum change.** Classification edits use `UPDATED` (D6).
- **Data migration.** New nullable properties on column nodes. No downtime.
  Rolling deploys work because old pods ignore the properties.
- **Flags, per environment, all default off.**

  | Flag | Repo | Rollback effect |
  |---|---|---|
  | `schema_discovery.emit_tags` | ingestion-service | No tags. Classifications stop being suggested. Existing ones are kept. |
  | `classification.emit_in_events` | metadata-graph | Events go back to the 2.3.0 shape. |
  | `column_masking.decide` | entitlements-service | `masked_columns` is empty. |
  | `pii_rules.enabled` | dq-engine | Only data-type rules run. |
  | `column_masking.enforce` (`off`/`shadow`/`on`) | query-gateway | Results are unmasked, as today. |

- **Consumer communication.** Before `column_masking.enforce=on`, announce
  which datasets will have masked columns. Owners of automated consumers
  that lack `pii:read` must request the grant, or accept nulls.
- **Catalog.** No new APIs, topics or edges. Update the entity descriptions only
  if teams want to. Bump API versions in `platform-catalog/apis/*` if the
  catalog tracks them.

## 6. Cross-repository testing

### Contract tests (per repo, against platform-contracts 2.4.0 fixtures)

| Consumer | Provider | Contract | Assertion |
|---|---|---|---|
| metadata-graph | ingestion-service | `ingestion.schema.discovered.v1` | Payloads with and without `tags` are accepted |
| search-indexer | metadata-graph | `metadata.dataset.changed.v1` | 2.4.0 payload is indexed, not dead-lettered |
| entitlements-service | metadata-graph | event + `GET /v1/datasets/{urn}/columns` | Cache is invalidated on `UPDATED`; classification is parsed |
| lineage-service | metadata-graph | `metadata.dataset.changed.v1` | Unaffected by the new fields |
| dq-engine | metadata-graph | `GET /v1/datasets/{urn}/columns` | Classification and tags are parsed; old responses still work |
| platform-sdk | metadata-graph, entitlements-service | both OpenAPI specs | Models accept 2.3.0 and 2.4.0 responses |
| query-gateway | entitlements-service | `POST /v1/access/decide` | `masked_columns` is read; its absence means no masking |
| notification-service | dq-engine | `dq.result.published.v1` | New PII rule names are tolerated |

Providers (metadata-graph, ingestion-service, entitlements-service,
query-gateway, dq-engine) validate their outputs against the 2.4.0 schemas or
OpenAPI in unit tests.

### platform-e2e suite `column_classification_masking` (run in int with all flags on)

1. Create a Postgres source table with `email text` commented `tags: pii,email`
   and `country text` with no tags. Run ingestion.
2. `GET /v1/datasets/{urn}/columns` returns `email` with `classification=PII`
   and `classification_source=SOURCE_TAG`, and `country` with `null`. A
   `metadata.dataset.changed.v1` event carries the same values. search-indexer
   indexed it and its DLQ is empty.
3. The steward calls PUT and sets `country` to CONFIDENTIAL. A re-run of
   ingestion keeps the steward value and refreshes `suggested_classification`.
4. As a principal without `pii:read`, `POST /v1/query` with `SELECT *` returns
   rows where `email` is masked, plus `masked_columns=["email"]`.
   `gateway.access.logged.v1` is still emitted.
5. The same query as a principal with `pii:read` returns the values unmasked.
6. A query using `email` in WHERE or `lower(email)` as the principal without
   `pii:read` returns 403.
7. The steward reclassifies `email` to INTERNAL. After the change event,
   step 4 returns unmasked data (cache invalidation).
8. Land a batch. `dq.result.published.v1` contains `pii.email_format` for
   `email` and no PII rules for `country`. The metadata-graph quality score
   updates.
9. Backward compatibility: run the existing platform-e2e suites unchanged,
   once with all flags off and once with them on.

Also run a rolling-upgrade test in int: deploy each wave while the
existing suites run continuously, to show zero downtime (AC6).

## 7. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| search-indexer sees the new fields before it is upgraded | Datasets are dead-lettered and drop out of search | Wave ordering; event flag; DLQ alert |
| Re-ingestion overwrites steward overrides (current code replaces columns) | Wrong classification; PII exposed | M2 merge logic and its test; e2e step 3 |
| A service runs an SDK that is not bumped | Fields are silently dropped (ADR-004), so there is no masking and no PII rules | Bump checklist per repo; contract tests assert the field is read |
| Masking bypassed via SQL expressions, aliases or joins | PII leak | Q3 lineage resolution plus fail-closed 403; security review |
| Stale entitlements cache after a reclassification | PII visible until the cache expires | Invalidate on the existing change event; set a short TTL as a backstop; e2e step 7 |
| Classification unavailable (metadata-graph down) | Leak, or an outage | Fail closed (E4); monitor the deny rate |
| Nulls break downstream consumers that expect non-null values | Consumer errors | Announce in advance; shadow mode; masking-format open question |
| Tags missing or wrong in source comments | PII not classified | Stewards review the classifications; backfill; untagged columns are reported |
| PII values leak through DQ results or notifications | Compliance issue | D3: column name, rule and pass/fail only |

## 8. Open questions

See `open_questions` in `IMPACT_ANALYSIS.json`. The main ones:

1. Should a tag suggestion apply automatically (assumed yes) or wait for a
   steward to confirm it?
2. Does `pii:read` exist, and what is its scope? How are stewards authorised
   for the PUT endpoint?
3. Masking format: null, or a type-preserving or partial mask?
4. Should unclassified columns default to INTERNAL?
5. Should masking be audited by adding `masked_columns` to
   `gateway.access.logged.v1` (usage-metering would then become
   verify-only)?
6. Is search-indexer already dead-lettering fields added in contracts
   2.2.0 or 2.3.0?
