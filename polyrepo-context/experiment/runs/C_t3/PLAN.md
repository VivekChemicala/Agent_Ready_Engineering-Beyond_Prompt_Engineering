# DP-1423 implementation plan: column sensitivity classification and PII masking

> Synthetic example. All services, teams and data are fictional (see `workspace/README.md`).

Machine-readable impact: `IMPACT_ANALYSIS.json` (same folder). Paths below are
relative to `polyrepo-context/workspace/`. Repositories are `example-org/<name>`
per `platform-catalog/README.md`.

## 1. Summary

The feature crosses the whole platform, not just `metadata-service`:

```
source column comment "tags: pii,email"
  -> ingestion-service  (ingestion.schema.discovered.v1 + columns[].tags)
  -> metadata-service     (suggest + store classification, steward PUT, GET columns, metadata.dataset.changed.v1)
  -> entitlements-service (decision.masked_columns unless principal holds pii:read)
  -> consumption-gateway      (masks those columns in POST /v1/query results)
  -> transformation-service          (PII-format rules for columns classified PII)
```

All contract changes are additive and stay on `.v1` topics / `/v1` paths
(ADR-009). Two facts drive the ordering:

- `platform-sdk` typed models drop undeclared fields (ADR-004) and the SDK
  validates payloads on publish against a pinned contracts release. Nothing new
  is visible to SDK users or publishable until contracts and SDK ship.
- `search-indexer` validates `metadata.dataset.changed.v1` strictly against a
  vendored contracts 2.1.0 schema (`additionalProperties: false`). If
  `metadata-service` emits `classification` first, every change event goes to its
  DLQ and search stops updating. It must ship first.

## 2. Decisions and assumptions

| # | Decision / assumption |
|---|---|
| A1 | Classification enum: `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `PII`. Nullable = unclassified. Stored with `classification_source` = `SUGGESTED` or `STEWARD`. |
| A2 | Tag mapping (in metadata-service, configurable): any of `pii, email, phone, ssn, name, address` -> `PII`; `confidential` -> `CONFIDENTIAL`; `internal` -> `INTERNAL`; `public` -> `PUBLIC`; highest sensitivity wins; no tag -> no suggestion. |
| A3 | ingestion-service sends raw tags only; metadata-service owns the mapping (one place to change policy). |
| A4 | A steward override (`STEWARD`) is never overwritten by re-ingestion; suggestions only update `SUGGESTED` or null values. |
| A5 | Suggested `PII` is enforced immediately (fail closed). Unclassified columns are not masked (no breaking change for existing consumers). Only `PII` is masked in this ticket. |
| A6 | Masked values are returned as `null` with the column key kept; the response adds `masked_columns` so consumers can tell masked from real nulls and types stay stable. |
| A7 | Classification changes publish `metadata.dataset.changed.v1` with existing `change_type` `COLUMNS_CHANGED` (no new enum value, which strict readers would reject). |
| A8 | entitlements-service reads column classifications via `MetadataClient.get_columns` (existing `GET /v1/datasets/{urn}/columns`), cached and invalidated by `metadata.dataset.changed.v1` like today's dataset cache. |
| A9 | `pii:read` is a new grant type in entitlements-service's existing grants model; scope (global vs per domain) to confirm with team-access. |
| A10 | PII transformation rules are selected inside transformation-service by classification; no `transformation-api` contract change in this ticket. |

## 3. Contract changes (platform-contracts 2.3.0 -> 2.4.0, minor)

| Contract | Owner | Change |
|---|---|---|
| `ingestion.schema.discovered.v1` | ingestion-service | add optional `columns[].tags: string[]` |
| `metadata.dataset.changed.v1` | metadata-service | add optional `dataset.columns[].classification` (enum, nullable) and `classification_source` |
| `GET /v1/datasets/{urn}/columns` | metadata-service | `Column` gains optional `classification`, `classification_source` (api 1.4.0 -> 1.5.0) |
| `PUT /v1/datasets/{urn}/columns/{column}/classification` | metadata-service | **new**: body `{classification, reason?}`; 200 returns Column; 400 invalid value; 403 not a steward; 404 unknown dataset/column |
| `POST /v1/access/decide` | entitlements-service | `Decision` gains optional `masked_columns: string[]` (api 1.2.0 -> 1.3.0) |
| `POST /v1/query` | consumption-gateway | masked values become `null`; response gains optional `masked_columns: string[]` (api 2.0.0 -> 2.1.0) |

Unchanged: `GET /v1/datasets/{urn}` (no columns in it), `transformation.result.published.v1`
(PII rules are just new `results[].rule` names), `ingestion.batch.landed.v1`,
`ingestion.job.completed.v1`, `consumption.access.logged.v1`, `transformation-api`.

Do not add `classification` to `required` anywhere; old producers must stay valid.

## 4. Work items per repository

### WI-1 platform-contracts (team-platform)
- Edit `events/ingestion.schema.discovered.v1.json`, `events/metadata.dataset.changed.v1.json`,
  `openapi/metadata-service.yaml`, `openapi/entitlements-service.yaml`, `openapi/consumption-gateway.yaml` per section 3.
- Add a `Classification` enum component shared by the metadata-service spec.
- Schema compatibility test: every 2.3.0 example payload still validates against 2.4.0.
- Release 2.4.0, bump `VERSION`.

### WI-2 platform-sdk (team-platform), depends on WI-1
- Pin `platform-contracts==2.4.0` (publish validation now accepts the new fields).
- `MetadataClient`: add `classification: str | None = None`, `classification_source: str | None = None`
  to the Column dataclass; add `set_column_classification(urn, column, classification, reason=None)`.
- `EntitlementsClient`: add `masked_columns: tuple[str, ...] = ()` to the Decision dataclass
  (today it declares only `allow`, `reason`).
- Defaults keep older servers working (missing field -> `None` / empty).
- Release 3.5.0 (minor); changelog notes the new fields.

### WI-3 search-indexer (team-discovery), depends on WI-1; must be in prod before WI-4b
- Re-vendor `metadata.dataset.changed.v1` from contracts 2.4.0 (currently 2.1.0; also picks up anything added in 2.2/2.3).
- Optional: index `classification` as a filterable field.
- Test: a payload with `classification` validates and indexes; a 2.1.0-shape payload still indexes.
- Check the DLQ is empty after deploy.

### WI-4 metadata-service (team-metadata), depends on WI-2
Split in two deployable steps:

**WI-4a (store, API, no event change)**
- `model.py`: `Column.classification: str | None = None`, `Column.classification_source: str | None = None`.
- Metadata store / metadata DB: persist both as column node properties (no migration needed for
  nullable properties; confirm for the prod metadata DB).
- `consumers.on_schema_discovered`: today it **replaces** `existing.columns` wholesale, which would
  erase steward overrides. Change to merge by column name: keep `STEWARD` values, compute a
  suggestion from `c.get("tags", [])` (A2) for new / `SUGGESTED` / null columns, drop removed columns.
- New module for the tag -> classification mapping, configured in `config/settings.yaml`.
- `api.get_columns`: return `classification` and `classification_source`.
- `api`: new `PUT /v1/datasets/{urn}/columns/{column}/classification` with validation, steward
  authorisation, audit log line; publishes `COLUMNS_CHANGED`.
- Flag `classification.suggest_from_tags` (default off until WI-5 is live).

**WI-4b (event change)**, after WI-3 is in prod
- `publisher.dataset_changed_payload`: add `classification` / `classification_source` per column,
  behind flag `classification.emit_in_events`.
- Tests: extend `tests/test_api.py` and `tests/test_consumers.py` (suggestion, override survives
  re-ingest, PUT validation/404/403, payload validates against contracts 2.4.0).
- Fix stale README line listing `reporting-service` as a consumer (it is decommissioned); list
  entitlements-service, lineage-service, search-indexer.
- Update `platform-catalog/components/metadata-service.yaml` only if the description changes.

### WI-5 ingestion-service (team-ingest), depends on WI-2
- Postgres connector: parse `tags:` from column comments (case-insensitive, comma separated, trimmed,
  lowercase, deduplicated); ignore malformed comments without failing the job.
- Emit `columns[].tags` in `ingestion.schema.discovered.v1` (omit when empty).
- Tests: comment parsing table tests; published payload validates against 2.4.0.
- Can ship in parallel with WI-4; metadata-service is a tolerant reader and ignores tags until WI-4a.

### WI-6 entitlements-service (team-access), depends on WI-2 and WI-4a
- Add `pii:read` grant type to the grants model and admin tooling.
- On `POST /v1/access/decide` with `action=read` and `allow=true`: load columns via
  `MetadataClient.get_columns` (cached, invalidated by `metadata.dataset.changed.v1` on `dataset.urn`
  as today), set `masked_columns` = names of `PII` columns unless the principal holds `pii:read`.
- If column metadata cannot be loaded: fail closed (deny or mask all columns, decide with team-access) rather than return unmasked.
- Flag `decision.column_masking` (when off, `masked_columns` is always empty).
- Add a cache TTL as backstop for missed invalidation events.
- Tests: contract test for Decision 1.3.0; grant/no-grant/unclassified/write-action cases.

### WI-7 consumption-gateway (team-consumption), depends on WI-2 and WI-6
- Read `decision.masked_columns`; after running the query, set those columns' values to `null`
  and add `masked_columns` to the response.
- Handle derived columns: resolve output columns back to source columns (SQL column lineage) for
  aliases/expressions; reject (403) queries that use masked columns in expressions/predicates if
  lineage cannot be resolved. Needs team-consumption design sign-off (see risks).
- Flag `enforce_column_masking` with modes `off` -> `shadow` (log what would be masked, return
  unmasked) -> `enforce`.
- `consumption.access.logged.v1` unchanged.
- Tests: masking unit tests, `SELECT *`, alias, expression, join cases; contract test on Decision.

### WI-8 transformation-service (team-transformation), depends on WI-2 and WI-4a
- Bump SDK to 3.5.0 so `get_columns` exposes `classification`.
- Add PII-format rules (e.g. `pii_email_format`, `pii_phone_format`, `pii_ssn_format`) and bind them
  to columns classified `PII`, picking the specific rule from the column's data type / name or the
  original tag (open question: metadata-service may need to expose the PII sub-type).
- Keep existing data-type bindings; PII rules are added, not substituted.
- Results go out on the unchanged `transformation.result.published.v1`; check score weighting with team-transformation
  so new failing rules do not spam owners via notification-service on day one.
- Flag `rules.pii_enabled`.

### WI-9 platform-e2e (team-platform), depends on WI-4..WI-8 in `int`
New suite `pii_classification`:
1. Seed a Postgres source with a column comment `tags: pii,email`; run ingestion.
2. Assert `GET /v1/datasets/{urn}/columns` shows `PII` / `SUGGESTED`.
3. Assert the `metadata.dataset.changed.v1` event carries the classification and search-indexer indexed it (DLQ empty).
4. Query via `POST /v1/query` as a principal without `pii:read`: column is `null`, listed in `masked_columns`.
5. Same with `pii:read`: real values, `masked_columns` empty.
6. Steward `PUT` to `INTERNAL`: after the change event, the next query is unmasked (checks cache invalidation); re-run ingestion: override survives.
7. Land a batch with invalid emails: `transformation.result.published.v1` contains failing `pii_email_format` results.
8. Regression: existing suites unchanged and green with all flags on and off.

### WI-10 verify only: lineage-service, notification-service
- Re-run contract tests with a 2.4.0 `metadata.dataset.changed.v1` payload (lineage) and with the
  1.5.0 metadata-service-api / unchanged `transformation.result.published.v1` (notification). Bump SDK to 3.5.0
  at their own pace; no code change expected.

### WI-11 docs and catalog (no code, after rollout)
- `architecture-docs/flows/ingest-to-metadata.md`, `access-decision.md`, `transformation.md`: describe tags, column-level decisions, PII rules.
- `architecture-docs/integration/consumer-registry.md`: entitlements-service now reads `GET columns` (classification); search-indexer vendored version 2.4.0; Decision reads now include `masked_columns`.
- `platform-catalog`: no new edges; update descriptions if desired.

## 5. Ordering

```
WI-1 contracts 2.4.0
  -> WI-2 sdk 3.5.0
       -> WI-3 search-indexer (prod)  ----------------------------+
       -> WI-5 ingestion-service (tags)                           |
       -> WI-4a metadata-service store/API/suggest                  |
             -> WI-4b metadata-service emits classification  <------+
             -> WI-6 entitlements masked_columns
                   -> WI-7 consumption-gateway masking (shadow -> enforce)
             -> WI-8 transformation-service PII rules
  WI-9 platform-e2e as each step reaches int; WI-10 anytime after WI-1/WI-2; WI-11 last
```

WI-3, WI-5, WI-4a can run in parallel once WI-2 is released. Critical path:
WI-1 -> WI-2 -> WI-4a -> WI-6 -> WI-7.

## 6. Compatibility and rollout (AC6: no breaking change, no downtime)

1. All schema changes optional; no `required` additions; no enum additions on existing fields; no `.v2`
   topics or `/v2` paths needed (ADR-009).
2. Strict consumer first: search-indexer deployed with 2.4.0 schema before any producer emits new
   fields (WI-3 before WI-4b), as the change playbook and ADR-009 require.
3. Tolerant consumers and old SDK users keep working: old SDK versions drop the new fields (ADR-004);
   new SDK defaults the fields when talking to old servers.
4. Behaviour behind flags, enabled per environment `dev -> int -> prod`:
   `classification.suggest_from_tags`, `classification.emit_in_events` (metadata-service),
   `decision.column_masking` (entitlements), `enforce_column_masking` off/shadow/enforce (gateway),
   `rules.pii_enabled` (transformation-service).
5. Before enabling enforcement in prod: backfill classifications (re-run schema discovery for Postgres
   sources), grant `pii:read` to principals who legitimately need raw PII, and run gateway shadow mode
   long enough to review what would be masked and who would lose access. Communicate the change to data consumers.
6. Rolling deploys only; no service needs a stop-the-world migration (new nullable column-node properties).
7. Rollback: turn the relevant flag off; schemas stay at 2.4.0 (additive, harmless).

## 7. Testing

**Contract tests (per repo, CI)**
- platform-contracts: backward-compat check (old examples validate against new schemas).
- Producers validate emitted payloads against 2.4.0: ingestion-service, metadata-service.
- Consumers test what they read: search-indexer (strict, full payload), entitlements-service and
  lineage-service (tolerant, extra fields ignored), transformation-service and entitlements-service (Column via SDK),
  consumption-gateway (Decision via SDK), notification-service (unchanged reads).
- platform-sdk: model parsing with and without new fields (new SDK vs old server, old SDK vs new server).

**Integration / end-to-end (`int`, platform-e2e)**
- WI-9 suite, run with flags off (regression: identical results to today) and on.
- Failure injection: metadata-service unavailable during decide (fail closed), delayed change event
  (TTL backstop), malformed tag comment (ingestion still succeeds).

## 8. Risks

| Risk | Mitigation |
|---|---|
| search-indexer DLQs every change event if a producer emits first | WI-3 gated before WI-4b; flag on emission; DLQ alert |
| Re-ingestion wipes steward overrides (current `on_schema_discovered` replaces columns) | Merge-by-name logic and test in WI-4a |
| PII leak via SQL aliases/expressions/predicates when masking by output name | Column lineage in gateway or reject; e2e cases |
| PII leak via stale entitlements cache | Event invalidation plus TTL; e2e step 6 |
| Consumers lose data they used to see when enforcement starts | Shadow mode, backfill, `pii:read` grants issued before enforce, comms |
| Tag conventions inconsistent across sources (only Postgres reads comments today) | Mapping is configurable; stewards override; other connectors out of scope |
| New PII transformation rules lower scores and trigger owner emails | Flag, staged rollout, agree score weighting with team-transformation |
| Extra metadata-service load from entitlements fetching columns per decision | Cache by urn; load-test in int |

## 9. Open questions

See `open_questions` in `IMPACT_ANALYSIS.json`. The ones that block design:
tag-to-classification mapping and PII sub-types (data governance), `pii:read` scope (team-access),
masking format and SQL-expression handling (team-consumption), steward authorisation for the PUT
endpoint (team-metadata), and backfill ownership (team-ingest).
