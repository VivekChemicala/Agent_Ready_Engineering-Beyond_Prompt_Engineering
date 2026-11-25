# DP-1423 Implementation plan: column sensitivity classification and PII masking

> Synthetic exercise. Every repository, team and contract is fictional and comes from `workspace/`.
> The machine-readable version of this analysis is in `IMPACT_ANALYSIS.json`.

## 1. Summary

The ticket is assigned to team-metadata, but it touches the whole path from ingest to serving:

```
ingestion-service --(schema.discovered.v1 + columns[].tags)--> metadata-service
metadata-service --(dataset.changed.v1 + columns[].classification)--> search-indexer (strict!), entitlements-service, lineage-service
metadata-service --(GET /v1/datasets/{urn}/columns + classification)--> entitlements-service, transformation-service   [via platform-sdk]
entitlements-service --(POST /v1/access/decide + masked_columns)--> consumption-gateway                   [via platform-sdk]
consumption-gateway --(POST /v1/query, masked values + masked_columns)--> data consumers
```

| Repository | Owner | Impact | Acceptance criteria covered |
|---|---|---|---|
| platform-contracts | team-platform | code change (schemas, release 2.4.0) | all |
| platform-sdk | team-platform | code change (models, client method, contracts pin, release 3.5.0) | 2, 3, 5 |
| ingestion-service | team-ingest | code change | 1 |
| metadata-service | team-metadata | code change | 1, 2 |
| search-indexer | team-discovery | code change (vendored schema), must ship **before** metadata-service emits | 6 |
| entitlements-service | team-access | code change | 3 |
| consumption-gateway | team-consumption | code change | 4 |
| transformation-service | team-transformation | code change | 5 |
| platform-e2e | team-platform | code change (new e2e suite) | 1-6 |
| lineage-service | team-discovery | verify only | 6 |
| notification-service | team-platform | verify only | 6 |
| usage-metering, reporting-service, platform-catalog, architecture-docs | - | not impacted (see JSON); docs refresh as a follow-up | - |

Three constraints from the docs drive the plan:

- **ADR-004**: SDK models drop undeclared fields. A new field is invisible to entitlements-service,
  transformation-service and consumption-gateway until platform-sdk declares it, is released, and each of those repos
  bumps to that release.
- **ADR-007**: entitlements-service decides and consumption-gateway enforces. Masking logic must not be
  placed in metadata-service or in the warehouse.
- **ADR-009 / consumer registry**: additive optional fields stay on `.v1`. The exception is
  search-indexer, which validates strictly against a vendored contracts 2.1.0 schema with
  `additionalProperties: false` and sends unknown fields to the DLQ. It must be upgraded
  before metadata-service adds fields to `metadata.dataset.changed.v1`.

## 2. Design decisions (assumptions)

1. **Classification values**: `PUBLIC | INTERNAL | CONFIDENTIAL | PII`, or `null` for unclassified.
   Every new field is optional or nullable, so existing payloads stay valid.
2. **Raw tags travel and the mapping lives in one place.** ingestion-service only parses and forwards
   the source tags. metadata-service turns tags into a *suggested* classification:
   `pii`->PII, `confidential`->CONFIDENTIAL, `internal`->INTERNAL, `public`->PUBLIC. The most
   sensitive match wins, and no recognised tag gives `null`.
3. **Precedence**: a steward override (`classification_source = STEWARD`) always beats the
   suggestion. Re-ingestion updates the stored suggestion and tags but never overwrites a
   steward value. Clearing the override (PUT with `null`) falls back to the suggestion.
4. **Column fields exposed** on both the REST API and the change event: `classification`,
   `classification_source` (`SOURCE_TAGS | STEWARD | null`) and `tags` (source tags; transformation-service needs
   the subtype, e.g. `email`).
5. **Change events**: a steward override publishes `metadata.dataset.changed.v1` with the existing
   `change_type = COLUMNS_CHANGED`. Adding a new enum value would be a breaking change for
   strict readers.
6. **Masking scope**: only `PII` columns are masked, and only when the principal holds no `pii:read`
   grant. Unclassified columns are not masked, which matches today's behaviour.
7. **Masked value format**: string columns get a fixed token (e.g. `"****"`) and other types get
   `null`. Row keys and column order do not change. The response lists `masked_columns` so
   consumers can tell a masked value from a real null.
8. **Fail mode**: if entitlements-service cannot load columns, the decision fails closed, the same
   as today when dataset metadata cannot be loaded.

## 3. Contract changes (platform-contracts 2.3.0 -> 2.4.0, one minor release)

| Kind | Name | Owner | Change |
|---|---|---|---|
| event | `ingestion.schema.discovered.v1` | ingestion-service | + `columns[].tags: string[]` (optional) |
| event | `metadata.dataset.changed.v1` | metadata-service | + `dataset.columns[].classification`, `classification_source`, `tags` (optional, nullable) |
| http | `GET /v1/datasets/{urn}/columns` | metadata-service | `Column` + the same three fields (metadata-service-api 1.4.0 -> 1.5.0) |
| http | `PUT /v1/datasets/{urn}/columns/{column_name}/classification` | metadata-service | **new**: body `{classification, reason?}`, returns `Column`; 400 invalid enum; 404 unknown dataset/column |
| http | `POST /v1/access/decide` | entitlements-service | `Decision` + `masked_columns: string[]` (default `[]`) (entitlements-api 1.2.0 -> 1.3.0) |
| http | `POST /v1/query` | consumption-gateway | 200 response + `masked_columns: string[]`; masked values (query-api 2.0.0 -> 2.1.0) |
| http | `POST /v1/rules` (and `GET`) | transformation-service | binding + optional `classification` / `tag` selectors |

All of these are additive. No `.v2` topic or `/v2` API is needed. `consumption.access.logged.v1` and
`transformation.result.published.v1` are unchanged: transformation result items already carry `column` and `rule`.

## 4. Work items per repository

### WI-1 platform-contracts (team-platform)
- Edit `events/ingestion.schema.discovered.v1.json`, `events/metadata.dataset.changed.v1.json`,
  `openapi/metadata-service.yaml` (Column fields + new PUT path), `openapi/entitlements-service.yaml`
  (`Decision.masked_columns`), `openapi/consumption-gateway.yaml` (`masked_columns`), and
  `openapi/transformation-service.yaml` (binding schema, which is currently untyped; define it with optional selectors).
- Add a `Classification` enum component and reuse it everywhere.
- Add schema tests that every 2.3.0 example payload still validates against 2.4.0, as a
  backward-compatibility check.
- Release **2.4.0**.

### WI-2 platform-sdk (team-platform), depends on WI-1
- Pin `platform-contracts==2.4.0`; publish validation then accepts the new fields.
- `MetadataClient`: extend the column dataclass with `classification`, `classification_source` and
  `tags` (optional, default `None`/`()`). Add `set_column_classification(urn, column, classification, reason=None)`.
- `EntitlementsClient`: extend `Decision` with `masked_columns: tuple[str, ...] = ()` and
  `policy_id`. Today the SDK reads only `allow` and `reason`.
- Unit tests: parse 2.3.0-shaped responses (fields missing -> defaults) and 2.4.0-shaped responses.
- Release **3.5.0** as a minor release; existing callers are unaffected.

### WI-3 search-indexer (team-discovery), depends on WI-1 and must deploy before WI-5 emits
- Vendor the `metadata.dataset.changed.v1` schema from contracts 2.4.0. The current copy is 2.1.0.
  The diff between 2.1.0 and 2.3.0 also needs review, because indexer may already be behind.
- Optional: index `classification` for search facets (open question).
- Contract test: a 2.4.0 payload with classification is indexed, not sent to the DLQ. 2.3.0 payloads
  still index.
- Deploy to every environment and confirm the DLQ rate is flat before WI-5 phase B.

### WI-4 ingestion-service (team-ingest), depends on WI-2
- Bump to platform-sdk 3.5.0.
- Postgres connector: parse column comments matching `tags: a,b,c` (case-insensitive, trimmed,
  de-duplicated). Emit them as `columns[].tags`, and omit the field when there are no tags.
  Other connectors are unchanged.
- Unit tests for the parser, covering no comment, a comment without tags, mixed case, and extra text.
- Contract test: the emitted payload validates against 2.4.0.
- Can ship any time after WI-2, because metadata-service is a tolerant reader. Behind flag
  `ingest.propagate_column_tags`.

### WI-5 metadata-service (team-metadata, owner of the ticket), depends on WI-2; phase B depends on WI-3
- Bump `platform-sdk==3.5.0` and `platform-contracts==2.4.0` in `requirements.txt`.
- `model.py`: add `tags`, `suggested_classification`, `steward_classification` and
  `classification_updated_by/at` to `Column`, plus effective `classification` and `classification_source`
  properties. Persist them in the metadata DB as column-node properties; `metadata_store.py` covers the in-memory version.
- `consumers.py::on_schema_discovered`: today it **rebuilds the column list from scratch**, which
  would wipe classifications. Change it to merge by column name. Keep the steward fields,
  update tags and the suggestion, drop removed columns, and add new ones.
- New `classification.py`: the tag -> classification mapping (configurable in `config/settings.yaml`).
- `api.py`: return the new fields from `get_columns`. Add the
  `PUT /v1/datasets/{urn}/columns/{column_name}/classification` route (validate the enum, 404
  unknown column, record who changed it and why), which publishes `COLUMNS_CHANGED`.
- `publisher.py`: add the three fields to each column in `dataset_changed_payload`. Use flag
  `publish_column_classification` (phase A off, phase B on after WI-3 is live everywhere).
- Fix the README integrations list: replace reporting-service with entitlements-service,
  lineage-service and search-indexer, and note that search-indexer is strict.
- Tests: tags -> suggestion mapping; override survives re-ingestion; clearing an override; PUT
  validation and 404; event payload with the flag on and off validates against 2.4.0; existing tests unchanged.
- Backfill: the phase-A rollout starts storing tags from the next discovery run. Ask team-ingest for
  a one-off forced re-discovery of Postgres sources (or a metadata-service backfill job) so that
  existing datasets get suggestions.

### WI-6 entitlements-service (team-access), depends on WI-2 and WI-5 (API fields live)
- Bump to platform-sdk 3.5.0.
- Load columns with `MetadataClient.get_columns(urn)` next to the existing dataset fetch. Use the
  same cache, and invalidate it on `metadata.dataset.changed.v1`; `COLUMNS_CHANGED` is already
  delivered.
- Add a `pii:read` grant type in the grants model (scope still to be decided: global, domain or dataset).
- Decision: when `allow` is true and the principal lacks `pii:read`, set
  `masked_columns = [c.name for c in columns if c.classification == "PII"]`. Otherwise `[]`. Flag
  `entitlements.column_masking_decisions`.
- Tests: with and without the grant, no PII columns, unclassified columns, cache invalidation on a
  classification change, and a metadata fetch failure (fails closed).
- Provider contract test: the Decision response validates against entitlements-api 1.3.0 and
  is still parseable by the SDK 3.4.x `Decision`, so old gateways keep working.

### WI-7 consumption-gateway (team-consumption), depends on WI-2; enabling depends on WI-6
- Bump to platform-sdk 3.5.0 so that `Decision.masked_columns` is visible (ADR-004).
- After running the query, replace the values of every column in `masked_columns`, using the
  format in section 2.7. Add `masked_columns` to the response.
- Derived columns: resolve which output columns come from a masked column (aliases, expressions,
  `SELECT *`). If that cannot be determined for a query that touches a masked column, fail closed:
  mask the derived output, or return 403 with a new `reason` (decision pending, see Risks).
- Flag `gateway.enforce_column_masking`, default off; roll out per environment and per domain.
- Tests: masking by name, `SELECT *`, aliases, expressions, an empty `masked_columns`, and the
  flag off (byte-identical to today).

### WI-8 transformation-service (team-transformation), depends on WI-2 and WI-5 (API fields live)
- Bump to platform-sdk 3.5.0. Read `classification` and `tags` from `get_columns`.
- Extend rule bindings with optional `classification` and `tag` selectors, alongside the existing
  data-type selector. Seed bindings: `classification=PII, tag=email -> email_format`,
  `tag=phone -> phone_format`, and a generic PII rule for other PII columns (the rule set is an open question).
- Results are emitted on `transformation.result.published.v1` unchanged (`column` and `rule` already exist).
- Tests: binding resolution by classification and tag; unclassified columns get only type rules.
- Flag `transformation.pii_rules`. Watch score changes, because they feed metadata-service and notification-service.

### WI-9 platform-e2e (team-platform), written alongside WI-4 to WI-8, run in `int`
- New suite `pii_classification` with these cases:
  1. A Postgres source column commented `tags: pii,email` -> after ingest, `GET .../columns` shows
     `classification=PII, classification_source=SOURCE_TAGS`, and the change event carries it.
  2. Steward PUT overrides it to `INTERNAL` -> a change event is published -> re-ingest keeps `INTERNAL`.
  3. A principal without `pii:read` runs `POST /v1/query` -> the PII column is masked and listed in
     `masked_columns`. A principal with `pii:read` sees clear values.
  4. Alias and expression queries over a PII column do not leak clear values.
  5. A batch landed on the PII dataset -> the transformation result includes `email_format` results for the column.
  6. Regression: datasets without tags behave exactly as before, for decisions, query results and transformation.
  7. search-indexer DLQ stays empty, and lineage-service still processes change events.

### WI-10 verify only: lineage-service, notification-service
- lineage-service: run its consumer contract tests with a 2.4.0 `metadata.dataset.changed.v1`
  fixture. No SDK bump is required.
- notification-service: run its contract tests with `transformation.result.published.v1` fixtures that include PII
  rule results. Confirm with the owner that lower scores do not cause a flood of emails during rollout.

### Follow-ups (documentation, no code)
- architecture-docs: update `flows/access-decision.md` (column-level decisions),
  `flows/ingest-to-metadata.md` (tags are propagated), `flows/transformation.md` (classification bindings),
  and `integration/consumer-registry.md`. In the registry, entitlements-service now reads columns, and
  the SDK `EntitlementsClient` reads `masked_columns`.
- platform-catalog: no new integration edges are expected. Re-check entities in each PR.

## 5. Ordering and dependencies

```
WI-1 contracts 2.4.0
  └─> WI-2 sdk 3.5.0 ───────────┬─> WI-4 ingestion (tags, flag)
  └─> WI-3 search-indexer ──┐   ├─> WI-5a metadata-service (store/API, events flag OFF)
                            └───┴─> WI-5b metadata-service events flag ON   (needs WI-3 deployed everywhere)
                                    WI-5a ─┬─> WI-6 entitlements (masked_columns, flag)
                                           └─> WI-8 transformation-service (PII rules, flag)
                                    WI-2 ───> WI-7 consumption-gateway (masking code, flag OFF)
                                    WI-6 + WI-7 ─> enable masking per environment
WI-9 platform-e2e is developed alongside and gates every flag flip in int.
```

The order follows the change playbook: contracts, then SDK, then strict consumers, then tolerant
consumers and readers, then producers. Behaviour is switched on last.

1. WI-1, then WI-2 (team-platform).
2. In parallel: WI-3 (search-indexer) and WI-4 (ingestion, flag off), WI-5a (metadata-service store and API),
   WI-7 (gateway code shipped with the flag off).
3. WI-5b: turn on classification in change events, only after WI-3 is deployed in every environment.
4. WI-6 and WI-8 (they need classification served by the metadata-service API).
5. Turn on `ingest.propagate_column_tags` and run the backfill re-discovery.
6. Turn on decisions (`entitlements.column_masking_decisions`), then enforcement
   (`gateway.enforce_column_masking`), then `transformation.pii_rules`. Go environment by environment
   (int -> staging -> prod), and in prod domain by domain after stewards have reviewed suggestions.

## 6. Compatibility and rollout (AC6)

- **Additive only.** No field is removed, renamed or re-typed; no enum value is added; no `.v2`.
  Old SDK versions drop the new fields (ADR-004), so services that do not upgrade keep working.
- **Strict consumer first.** search-indexer must accept 2.4.0 before `publish_column_classification`
  is turned on. Otherwise every dataset change goes to the DLQ and search stops updating.
- **Producer flags.** Every producer change and every behaviour change has its own flag and can be
  turned off independently without a redeploy.
- **Safe intermediate states.** If decisions return `masked_columns` but gateway enforcement is off,
  nothing is masked, which is today's behaviour. If the gateway is on but decisions are off,
  `masked_columns` is empty and nothing is masked. Masking takes effect only when both are on.
- **Communicate before enforcing.** Consumers without `pii:read` will see masked values once
  enforcement is on. That is the intended behaviour, but `pii:read` grants should be issued to
  legitimate users before each domain is enabled, so that existing jobs keep working. Use a
  shadow mode: decisions computed, gateway logs the columns it *would* mask, and nothing is masked.
- **No downtime.** Rolling deploys only. The metadata DB changes only add optional column-node properties,
  so no migration lock is needed.

## 7. Cross-repository testing

| Level | Where | What |
|---|---|---|
| Schema compatibility | platform-contracts | 2.3.0 fixtures validate against 2.4.0; enum defined once |
| SDK model | platform-sdk | old/new response shapes parse; defaults when fields are absent |
| Consumer contract | search-indexer, entitlements-service, transformation-service, consumption-gateway, lineage-service, notification-service, metadata-service (consumer of schema.discovered) | each consumer tests what it reads against the 2.4.0 fixtures published by contracts |
| Provider contract | metadata-service (GET columns, PUT classification, change event), entitlements-service (decide), ingestion-service (schema.discovered), consumption-gateway (query) | provider responses and payloads validate against 2.4.0 and parse with both SDK 3.4.x and 3.5.0 |
| End-to-end | platform-e2e in `int` | suite WI-9, run with each flag combination (off/off, decisions-only, both on) |
| Production checks | all | search-indexer DLQ rate, entitlements decision latency (extra columns fetch), gateway masked-column counts in shadow mode, transformation score deltas |

## 8. Risks

| Risk | Mitigation |
|---|---|
| search-indexer DLQs every change event (strict, vendored 2.1.0 schema) | WI-3 first; WI-5b flag gated on its deployment; DLQ alert |
| Re-ingestion wipes classifications (`on_schema_discovered` currently replaces columns) | merge-by-name in WI-5 + e2e case 2 |
| Masking bypass via aliases or expressions in SQL | column-lineage resolution in the gateway, fail closed; e2e case 4 |
| New fields silently dropped by SDK (ADR-004) so masking never happens | all of entitlements, gateway and transformation-service bump to SDK 3.5.0; e2e asserts that masking happens |
| Existing users lose access to clear values they relied on | shadow mode, issue `pii:read` before enforcement, roll out per domain |
| Extra metadata call adds decision latency | use the existing cache with event-based invalidation; monitor p99 |
| Stale cache shows an old classification after a steward change | invalidate on `COLUMNS_CHANGED`; set a TTL as a backstop |
| PII rules lower transformation scores and trigger notification floods | flag `transformation.pii_rules`; inform notification-service owners; consider a grace period |
| Wrong suggestions from free-text comments | suggestions are visible to stewards (`classification_source=SOURCE_TAGS`) before enforcement in each domain |

## 9. Open questions

See `open_questions` in `IMPACT_ANALYSIS.json`. The ones that block design decisions are:

1. Who are stewards, and how is the PUT endpoint authorised? Any option that needs
   entitlements-service adds a new dependency.
2. The scope of the `pii:read` grant: global, per domain or per dataset.
3. The masked value format and how to handle derived SQL expressions.
4. Whether unclassified columns default to "not masked" (assumed) or `INTERNAL`, and whether a backfill
   must finish before enforcement.
5. Whether `CONFIDENTIAL` ever triggers masking.
6. The PII-format rule set and whether it is chosen by tag.
7. Whether `consumption.access.logged.v1` should record masked columns for audit. That would touch
   usage-metering and is out of scope here.
