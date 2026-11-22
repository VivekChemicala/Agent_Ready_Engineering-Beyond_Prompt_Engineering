# DP-1423 — Column-level sensitivity classification and PII masking

Implementation plan (no code). Synthetic workspace; each folder under `workspace/` is a separate repository.
Machine-readable impact data is in `IMPACT_ANALYSIS.json`.

## 1. Summary

Data flows: source column comment (`tags: pii,email`) → **ingestion-service** → `ingestion.schema.discovered.v1`
→ **metadata-graph** (stores classification, steward override API) → `GET /v1/datasets/{urn}/columns` and
`metadata.dataset.changed.v1` → **entitlements-service** (`masked_columns` in decisions) → **query-gateway** (masks
values) and **dq-engine** (PII-format rules). The shared shapes live in **platform-contracts**, and
**platform-sdk** must be updated or the new fields are silently dropped, because its dataclasses drop undeclared fields.

Two findings drive the ordering:

1. **platform-sdk drops unknown fields** (`Column` has only name/data_type/nullable; `Decision` has only
   allow/reason). Until SDK 3.5.0 is adopted, dq-engine, entitlements-service and query-gateway cannot see
   `classification` or `masked_columns`, even after the providers ship them.
2. **search-indexer validates `metadata.dataset.changed.v1` against a strict vendored 2.1.0 schema**
   (`additionalProperties: false` on the dataset and on each column). Adding `classification` to the event is
   additive under platform-contracts rules, but would send **every** dataset-changed event to
   `search-indexer.dlq`. search-indexer must be updated and deployed **before** metadata-graph emits the field.

## 2. Decisions and assumptions

- **Classification model** (per column, in the graph): `classification` ∈ `PUBLIC | INTERNAL | CONFIDENTIAL | PII`,
  nullable (null = unclassified); `classification_source` ∈ `SUGGESTED | STEWARD`; `tags`: list of
  lower-case source tags.
- **Suggestion lives in metadata-graph**, not ingestion. Ingestion publishes raw `tags` only, so the
  tag→classification mapping is in one place, owned by team-graph. Assumed mapping, in this order: any of
  `pii, email, phone, ssn` → `PII`; else `confidential` → `CONFIDENTIAL`; `internal` → `INTERNAL`;
  `public` → `PUBLIC`; else null. Confirm with data governance (open question).
- **Steward overrides win**: a re-discovered schema only updates the classification when
  `classification_source != STEWARD`. Today `on_schema_discovered` replaces `existing.columns` wholesale.
  It must merge by column name and keep classification, source and description.
- **No new `change_type` enum value.** Classification changes are published as `COLUMNS_CHANGED`, because adding
  an enum value would break strict readers (search-indexer pins the enum).
- **Masking rule**: if a principal is allowed to `read` a dataset but does not hold `pii:read`, every column
  classified `PII` is in `masked_columns`. Unclassified, PUBLIC, INTERNAL and CONFIDENTIAL columns are not
  masked (CONFIDENTIAL masking is out of scope for this ticket).
- `pii:read` is assumed to be a global grant string held in the existing grant sets. Scoped variants are an open question.
- **Mask format** (assumed): string columns → `"****"`; non-string → `null`. Row keys and row count are unchanged.
- All contract changes are **additive, optional fields** → platform-contracts **2.4.0** (minor) and
  platform-sdk **3.5.0** (minor). No `.v2` topics or `/v2` APIs are needed.
- Enforcement is switched on with **feature flags** so every service can be deployed dark, with no downtime.

## 3. Contract changes (platform-contracts 2.4.0)

| Contract | Owner | Change |
|---|---|---|
| `ingestion.schema.discovered.v1` | ingestion-service | `columns[].tags` optional array of strings |
| `metadata.dataset.changed.v1` | metadata-graph | `columns[].classification` (nullable enum), `columns[].classification_source` (nullable enum), `columns[].tags` (optional) |
| `GET /v1/datasets/{urn}/columns` | metadata-graph | `Column` gains `classification`, `classification_source`, `tags` (optional/nullable) |
| `PUT /v1/datasets/{urn}/columns/{column}/classification` | metadata-graph | **new**. Body `{classification}` → 200 Column; 400 invalid value, 403 not steward, 404 unknown dataset/column |
| `POST /v1/access/decide` | entitlements-service | `Decision.masked_columns: string[]` (optional; `[]` when nothing to mask or when denied) |
| `POST /v1/query` | query-gateway | masked values in `rows`; optional `masked_columns: string[]` in the 200 response |

Unchanged: `GET /v1/datasets/{urn}` (no column data), `dq.result.published.v1` (new rule names fit the existing
`results[].rule` string), `ingestion.batch.landed.v1`, `gateway.access.logged.v1`, dq `/v1/rules`.

## 4. Per-repository work items

### 4.1 platform-contracts (team-platform). Step 1
- Edit `events/ingestion.schema.discovered.v1.json`, `events/metadata.dataset.changed.v1.json`,
  `openapi/metadata-graph.yaml` (Column fields + new PUT path, version 1.5.0),
  `openapi/entitlements-service.yaml` (Decision.masked_columns, 1.3.0), `openapi/query-gateway.yaml`
  (`masked_columns` in response, 2.1.0).
- Keep all new fields out of `required`. Add a CI compatibility check: diff against 2.3.0 must contain no new required
  fields, removed or renamed fields, or narrowed enums.
- Add example payloads (old and new shape) for each changed topic. Consumers use them in contract tests.
- Release `VERSION` 2.4.0.

### 4.2 platform-sdk (team-platform). Step 2, depends on 4.1
- Pin `platform-contracts==2.4.0` in `pyproject.toml`. Bundled schemas validate new payloads on publish.
- `metadata.Column`: add `classification: str | None = None`, `classification_source: str | None = None`,
  `tags: tuple[str, ...] = ()`. Parse them with `.get()` so responses from an old metadata-graph still parse.
- `MetadataClient.set_column_classification(urn, column, classification)` → `PUT .../classification`.
- `entitlements.Decision`: add `masked_columns: tuple[str, ...] | None = None`. **`None` means the server did not
  send the field** (old entitlements). This lets the gateway tell "nothing to mask" (`()`) from "not supported".
- Optionally export a `Classification` enum/constants.
- Unit tests: parse old and new responses; frozen dataclass equality; publish validation with 2.4.0 examples.
- Release 3.5.0 (minor; defaults keep every existing call site working).

### 4.3 search-indexer (team-discovery). Step 3, depends on 4.1; **must be in production before 4.4's event flag**
- Re-vendor `schemas/metadata.dataset.changed.v1.json` from 2.4.0. Keep the strict `additionalProperties: false`
  policy, but declare `classification`, `classification_source`, `tags` on column items.
- `consumer.handle`: unchanged indexing, or optionally index classification (open question).
- Tests: a 2.4.0 sample with classification is indexed (not DLQ'd); an unknown field still goes to DLQ (existing
  test keeps passing); a 2.3.0-shaped event is still accepted.
- Check `search-indexer.dlq` is empty for this cause after metadata-graph enables the flag.

### 4.4 metadata-graph (team-graph). Step 4, depends on 4.2 (and 4.3 for the event flag)
- `requirements.txt`: `platform-sdk==3.5.0`, `platform-contracts==2.4.0`.
- `model.Column`: add `classification`, `classification_source`, `tags`. Persist them in the graph DB as column
  node properties; existing nodes read as null (no migration needed; lazy default).
- New `classification.py`: `suggest(tags) -> classification | None` (mapping in §2) and a
  validation helper for the four allowed values.
- `consumers.on_schema_discovered`: read optional `c.get("tags", [])`. **Merge** with existing columns by name:
  keep STEWARD classifications, set/refresh SUGGESTED ones, and keep `description`. Publish `COLUMNS_CHANGED`
  only if something changed (avoids event storms on re-discovery).
- `api.py`: `get_columns` returns the three new fields. Add
  `PUT /v1/datasets/{urn}/columns/{column}/classification`: validate, check steward permission (see open
  questions; initially dataset owner or a `metadata:classify` grant via entitlements), set
  `classification_source=STEWARD`, upsert, publish `COLUMNS_CHANGED`. Log an audit record (who, old→new).
- `publisher.dataset_changed_payload`: include the new column fields **behind flag
  `events.emit_column_classification`** (`config/settings.yaml`, default false). Turn it on only after search-indexer
  (4.3) is live and reporting-service is confirmed.
- Update the README consumer list (it lists reporting-service but omits search-indexer and lineage-service).
- Tests: suggestion mapping; override survives re-discovery; merge keeps descriptions; PUT 200/400/404/403;
  GET columns fields; event payload validates against 2.4.0 with flag on and against 2.3.0 shape with flag off.
- Backfill: a one-off job (or a re-discovery trigger in ingestion) so existing datasets get suggestions. See open questions.

### 4.5 ingestion-service (team-ingest). Step 4 (in parallel with 4.4), depends on 4.2
- `connectors/postgres.py`: parse `column_comment` (`r[3]`). Extract the `tags:` list (comma-separated, trimmed,
  lower-cased) and emit `"tags": [...]` per column. Omit the key or use `[]` when there is no comment. Tolerate
  comments without a `tags:` prefix and free text around it.
- `publisher.publish_schema_discovered`: unchanged signature; columns now carry `tags`.
- Upgrade to `platform-sdk==3.5.0` so publish-time validation uses the 2.4.0 schema. 2.3.0 also accepts the extra
  key, because that schema has no `additionalProperties: false`, but upgrading keeps validation meaningful.
- Tests: update `test_discover_columns_maps_name_type_nullable` (now expects `tags: ["pii","email"]`); add
  cases for no comment, comment without tags, mixed case and whitespace.
- Order vs metadata-graph is flexible: the current graph consumer ignores unknown column keys.
- Apply the same to other connectors if any exist (open question).

### 4.6 entitlements-service (team-access). Step 5, depends on 4.2 and 4.4 (API live)
- Upgrade `platform-sdk==3.5.0`.
- `policies.Decision`: add `masked_columns: list[str] = field(default_factory=list)`.
- `PolicyEngine.decide`: after an allow, fetch (cached) `metadata.get_columns(urn)`. If
  `"pii:read" not in held`, set `masked_columns = [c.name for c in cols if c.classification == "PII"]`.
  Denials return `[]`.
- Cache columns alongside the dataset. `invalidate(urn)` (already wired to `metadata.dataset.changed.v1`) must
  clear both. Add a TTL as a safety net for missed events.
- **Fail closed**: if columns cannot be fetched for an allowed read, return `allow=false, reason="METADATA_UNAVAILABLE"`
  (or mask all columns, to be decided). Never return an allow with a silently empty mask list.
- Make `pii:read` grantable through the existing grant store.
- Tests: no pii:read → PII columns masked; with pii:read → `[]`; deny → `[]`; invalidation clears the column
  cache; metadata error path; API response matches the 2.4.0 OpenAPI Decision.

### 4.7 query-gateway (team-serving). Step 6, depends on 4.2 and 4.6
- Upgrade `platform-sdk==3.5.0` (otherwise `Decision.masked_columns` is dropped).
- `QueryService.run`: after an allow, mask `decision.masked_columns` in every row (format in §2) and add
  `masked_columns` to the response. Flag `masking.mode` = `off | shadow | enforce`, which can be set per domain
  or dataset:
  - `shadow`: compute and log/metric which columns would be masked, but return unmasked rows.
  - `enforce`: mask. If `decision.masked_columns is None` (old entitlements), fail closed with 503 or 403
    rather than returning PII.
- Handle result columns that do not map 1:1 to dataset columns (aliases, expressions, `*`). Minimum:
  case-insensitive name match. Reject queries that alias or derive from a masked column, or
  mask fail-closed. See risks.
- Leave `gateway.access.logged.v1` unchanged (usage-metering not impacted).
- Tests: masking of string and non-string values; row count and keys unchanged; `masked_columns=None` under each
  mode; denied still 403; existing test passes.

### 4.8 dq-engine (team-quality). Step 5 (in parallel with 4.6), depends on 4.2 and 4.4
- Upgrade `platform-sdk==3.5.0`.
- `rules/pii.py`: `pii_email_format`, `pii_phone_format` (E.164), plus a generic `pii_format` default. Register them in
  `RULES`. Rules return pass/fail only and **never put sample values in results or logs**.
- `runner.run_batch`: keep data_type bindings, and for `col.classification == "PII"` add PII rules chosen by
  `col.tags` (`email` → email rule, `phone` → phone rule, none → `pii_format`). Explicit `/v1/rules` bindings
  can override this later.
- Publish `dq.result.published.v1` unchanged in shape.
- Tests: rule unit tests; a PII-classified column gets PII rules; a non-PII column does not; columns from an old
  graph (classification None) behave as today.

### 4.9 platform-e2e (team-platform with each team). Alongside steps 4–7
- Extend the `int_env` fixture: ingest a table with column comments, `set_classification`, grant `pii:read`, and
  read DQ results.
- New or extended suites:
  - `test_ingest_to_graph.py`: `email` with comment `tags: pii,email` → `get_columns` shows `PII/SUGGESTED`;
    steward override → `STEWARD` and it survives a re-ingest; the change event carries the classification.
  - `test_access_flow.py`: bob (`domain:crm:read`, no `pii:read`) → `email` masked, other columns clear;
    carol (`domain:crm:read` + `pii:read`) → unmasked; eve still 403. The existing two tests must still pass.
  - `test_dq_flow.py`: a batch with a malformed email in a PII column → a failing `pii_email_format` result, and
    `quality_score` still attached.
  - New `test_search_index.py` (or a check in the ingest suite): after a classification change the dataset is
    re-indexed and `search-indexer.dlq` stays empty.
- Run the full suite before each flag flip in `int`.

### 4.10 Verify-only
- **lineage-service**: add a consumer test feeding a 2.4.0 `metadata.dataset.changed.v1` example to the
  `rename` handler. No code change expected (tolerant reader of urn/name).
- **reporting-service** (repository not in the workspace): ask its owners to run the 2.4.0 example payloads
  through their consumer before the metadata-graph event flag is turned on.
- **notification-service, usage-metering**: not impacted. Re-run their existing tests when bumping the SDK, if they bump it.

## 5. Ordering and rollout

```
1 platform-contracts 2.4.0
        │
2 platform-sdk 3.5.0 ───────────────────────────────┐
        │                                            │
3 search-indexer (re-vendored schema) ── deployed ──┐│
        │                                           ││
4 metadata-graph (store/API; event flag OFF)  ║  4 ingestion-service (tags)
        │                                           │
  flip metadata-graph emit_column_classification ◄──┘ (after 3 + reporting-service confirmed)
        │
5 entitlements-service (masked_columns)  ║  5 dq-engine (PII rules)
        │
6 query-gateway (masking.mode=off → shadow)
        │
7 backfill / steward review → grant pii:read to legitimate principals → enforce per domain → enforce everywhere
```

Rollout notes (no breaking change, no downtime):
- Every service change is backward compatible with both old and new peers: new fields are optional and readers
  use `.get()` with defaults. Normal rolling deploys, no coordinated release.
- Each deploy step goes to `int`, then the platform-e2e suite runs, then production.
- **Shadow period** for gateway masking (for example 1–2 weeks): report which principals and datasets would see masked
  columns, so service accounts that need PII get `pii:read` before `enforce`. This change is intentional, but it can
  break consumers that read PII without a grant (AC6), so it is staged per domain.
- Rollback: each flag (`emit_column_classification`, `masking.mode`) can be turned off independently. Turning off the
  event flag is safe because consumers tolerate a missing field. Code rollbacks are safe because no stored data
  changes shape (new properties are only added).

## 6. Cross-repository testing

**Contract tests (in CI, per repo, using platform-contracts 2.4.0 examples)**
- platform-contracts: schema/OpenAPI compatibility diff vs 2.3.0 (additive only); old and new examples validate.
- Providers check their output against the spec: metadata-graph (event payload with the flag on and off, GET columns, PUT),
  ingestion-service (schema.discovered with tags), entitlements-service (Decision), query-gateway (query response).
- Consumers check they accept both old and new examples: search-indexer (strict schema), lineage-service, entitlements-service
  (dataset.changed + columns response), dq-engine (columns response), query-gateway (Decision with and without
  `masked_columns`), reporting-service (owners).
- platform-sdk: round-trip tests proving new fields survive parsing, and that old responses still parse.

**Integration / end-to-end (platform-e2e in `int`)**
- Suites listed in 4.9, run nightly and before every flag flip. Plus regression runs of the three existing suites.
- One full scenario: ingest a `customers` table with `tags: pii,email`, check the graph shows PII, steward overrides
  `phone` to PII, query as a principal without and then with `pii:read`, land a batch, check the PII DQ result,
  and check that the search index is updated and the DLQ is empty.

## 7. Risks

| Risk | Mitigation |
|---|---|
| search-indexer DLQs every dataset-changed event (strict vendored schema) | Deploy 4.3 first. Gate the event field behind a flag. Watch the DLQ after the flip and replay if needed. |
| SDK silently drops new fields → masking never applied / PII rules never bound | SDK 3.5.0 adoption is a hard prerequisite. Gateway treats `masked_columns is None` as unsupported and fails closed in enforce mode. |
| Re-discovery wipes steward overrides (columns replaced wholesale today) | Merge by column name and keep STEWARD values. Covered by unit and e2e tests. |
| SQL aliases, expressions or joins bypass name-based masking | Reject or fail-closed for derived references to masked columns. Consider warehouse-native masking long term. |
| Stale entitlement cache shows PII after reclassification | Invalidate on `metadata.dataset.changed.v1` (COLUMNS_CHANGED) plus a TTL. |
| Masked `null` or token breaks consumer type assumptions | Shadow period. Agree the mask format with consumers (open question). |
| Extra metadata call per decision adds latency | Column cache in entitlements. Measure p95 in shadow mode. |
| PII rules lower quality scores, so notification-service sends more owner emails | Communicate before rollout. Optionally report PII rules separately from the score. |
| PII values leak into DQ results or logs | Rules return booleans only. Add a review checklist and a test asserting no values in results. |
| Unknown consumers (reporting-service) of the changed event | Confirm with owners before the flag flip. Rely on topic consumer-group listing to find others. |

## 8. Open questions

See `open_questions` in `IMPACT_ANALYSIS.json`. The most important ones:
- mask format;
- `pii:read` scoping;
- steward authorization model;
- tag vocabulary and precedence;
- SQL alias handling;
- backfill strategy;
- PII rule set and whether failures count toward the score;
- reporting-service ownership and reader behaviour.
