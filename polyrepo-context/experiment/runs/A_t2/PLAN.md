# DP-1423 — Column-level sensitivity classification and PII masking: implementation plan

> Synthetic example written for an experiment. Analysis only, no code.
> Machine-readable companion: `IMPACT_ANALYSIS.json`.

## 1. Summary

Only `metadata-service` is visible in this workspace. From its README, config, requirements and code, the feature touches seven repositories:

| Repository | Impact | Name source | Role in DP-1423 |
|---|---|---|---|
| platform-contracts | code change | observed (`requirements.txt`, `api.py`, `publisher.py`) | Spec of record: OpenAPI + event schemas |
| platform-sdk | code change | observed (`requirements.txt`, README) | `MetadataClient` + event models |
| ingestion-service | code change | inferred ("ingestion service" in README) | Emits source column tags (AC1) |
| metadata-service | code change | observed | Stores classification, suggests it, steward API, change events (AC1, AC2) |
| entitlements-service | code change | observed (README consumer list) | `masked_columns` in access decisions (AC3) |
| reporting-service | code change | observed (README consumer list) | Masks query/report results (AC4) |
| transform-service | code change | inferred (topic `transformation.result.published.v1`) | PII-format rules (AC5) |

Assumptions:
- A1. "Query results returned to data consumers" are served by `reporting-service`. No query engine is visible. If a separate consumption gateway exists, it gets the masking work in section 3.6 and `reporting-service` becomes verify-only (open question Q2).
- A2. The access-decision API is `POST /v1/access/decisions` on `entitlements-service`. The exact path is not visible.
- A3. Only `PII` columns are masked, and only when the requester lacks `pii:read`. `CONFIDENTIAL` keeps its current behaviour.
- A4. Every contract change is additive and keeps the `.v1` names. No `.v2` topic or path is needed, provided consumers ignore unknown fields.
- A5. A steward override beats a suggestion. Re-ingestion never overwrites a `STEWARD` classification.

## 2. Contract changes (do these first, in `platform-contracts`)

| Kind | Name | Owner | Change | Compat | Details |
|---|---|---|---|---|---|
| event | `ingestion.schema.discovered.v1` | ingestion-service | modify | additive | Optional `columns[].tags: string[]` |
| event | `metadata.dataset.changed.v1` | metadata-service | modify | additive | Optional `dataset.columns[].classification` (enum `PUBLIC`/`INTERNAL`/`CONFIDENTIAL`/`PII`, nullable), `classification_source` (`SUGGESTED`/`STEWARD`). Classification edits use the existing `change_type` `COLUMNS_CHANGED`. |
| http | `GET /v1/datasets/{urn}/columns` | metadata-service | modify | additive | Same two fields on each column |
| http | `PUT /v1/datasets/{urn}/columns/{column}/classification` | metadata-service | new | additive | Body `{classification, reason?}`. Returns 200 with the column, 400 for an invalid enum, 403 for a non-steward, 404 for an unknown dataset or column. |
| http | `POST /v1/access/decisions` | entitlements-service | modify | additive | Response gains `masked_columns: string[]` (default `[]`) |

Rules for every schema change: new fields are optional, enums are nullable, and no existing field is renamed or retyped. Publish this as a minor version (`platform-contracts` 2.3.0 → 2.4.0). Run the schema-compatibility check (BACKWARD/FULL) in CI against the previous version.

Not adding a new `change_type` value (for example `CLASSIFICATION_CHANGED`) is deliberate: a consumer with a closed enum would reject it (Q8). `GET /v1/datasets/{urn}` does not return columns, so it does not change. `transformation.result.published.v1` keeps its current shape unless Q11 says otherwise.

## 3. Per-repository work items

### 3.1 platform-contracts (owner: platform / contracts maintainers)
- C1. Update `openapi/metadata-service.yaml`: add the column fields and the new PUT route with the steward security scope.
- C2. Update the event schemas `events/metadata.dataset.changed.v1` and `events/ingestion.schema.discovered.v1`.
- C3. Update the entitlements OpenAPI to add `masked_columns`.
- C4. Add example payloads, with and without the new fields, for contract tests. Release 2.4.0.

### 3.2 platform-sdk (depends on C4)
- S1. Bump to `platform-contracts` 2.4.0 and regenerate or extend the models. Add `Column.classification` and `classification_source`, both defaulting to `None`.
- S2. Add `MetadataClient.get_columns()` support for the new fields. Add `MetadataClient.set_column_classification(urn, column, classification, reason=None)`.
- S3. Add a `Classification` enum and an entitlements-client field `masked_columns`.
- S4. Check that the event deserialisers tolerate unknown fields. If not, fix this first and release it on its own, because it gates every additive change.
- S5. Release as a minor version (3.4.1 → 3.5.0). Old SDK versions must keep working against the new payloads (see S4).

### 3.3 ingestion-service (depends on C4, S5)
- I1. Parse source column comments and tags (for example `tags: pii,email`) into a normalised, lowercased, de-duplicated `tags` list.
- I2. Emit `columns[].tags` on `ingestion.schema.discovered.v1`. Omit the field (do not send `null`) when there are no tags.
- I3. Unit-test the parser against connector-specific comment formats.

### 3.4 metadata-service (depends on C4, S5; independent of I1–I3)
- M1. `model.py`: add `classification: str | None = None` and `classification_source: str | None = None` to `Column`.
- M2. Metadata DB migration: add the optional column-node properties with no backfill, so absent means unclassified. `metadata_store.py` needs no interface change.
- M3. `consumers.py` `on_schema_discovered`:
  - Read the optional `tags` and map them to a suggested classification. The mapping is a config table in `config/settings.yaml` (Q6).
  - Today the function replaces `existing.columns` wholesale. Change this to merge by column name, so that existing `STEWARD` classifications survive re-ingestion (A5) and suggestions update only `SUGGESTED` or empty values.
- M4. `api.py`: return `classification` and `classification_source` from `get_columns`. Add the `PUT .../columns/{column}/classification` route with enum validation, a steward authorisation check, an audit log line, `store.upsert`, and `publish_dataset_changed(ds, "COLUMNS_CHANGED")`.
- M5. `publisher.py`: add the two fields to each column in `dataset_changed_payload`.
- M6. Feature flag `classification.suggest_enabled` (default off) to control writing suggestions. The read and write API ships on.
- M7. Tests:
  - Extend `tests/test_consumers.py` to cover the tags→suggestion mapping, no tags, and a steward override that survives re-ingestion.
  - Extend `tests/test_api.py` to cover the GET fields, PUT 200/400/403/404, and the event published on PUT.
  - Add a publisher payload test validated against the 2.4.0 schema.

### 3.5 entitlements-service (depends on S5, M5)
- E1. Consume the new `classification` from `metadata.dataset.changed.v1` and persist per-column classification for each dataset. Apply `COLUMNS_CHANGED` idempotently and keep the latest by `occurred_at`.
- E2. In the access decision, compute `masked_columns` as the `PII` columns of the dataset when the principal lacks the `pii:read` grant. Return `[]` otherwise.
- E3. Make sure the `pii:read` grant exists in the grant catalogue and can be assigned (Q9).
- E4. Backfill classification state on deploy, either by replaying the topic or by a one-off read through `MetadataClient`.
- E5. Tests:
  - Unit tests for decisions with and without `pii:read`, and for an unclassified dataset.
  - Consumer tests for event payloads with and without the new fields.

### 3.6 reporting-service (depends on S5, E2)
- R1. Read `masked_columns` from the access decision for each query or report request and mask those columns' values before returning them (format: Q7). Masked values must keep the column type, or be documented as string-typed.
- R2. Add flag `masking.mode` with the values `off`, `shadow` (log what would be masked) and `enforce`.
- R3. Re-verify its `metadata.dataset.changed.v1` consumer against payloads that carry the new fields.
- R4. Masking must also apply to caches, exports and downloads, not only the interactive API.
- R5. Tests: masked and unmasked responses, mixed columns, and an empty `masked_columns`.

### 3.7 transform-service (depends on S5, M4)
- D1. Before or at the start of a run, fetch the column classifications through `MetadataClient.get_columns()`.
- D2. For columns classified `PII`, attach PII-format rules such as email, phone and national ID, selected by tag subtype where available (Q10). Apply them in addition to the existing rules.
- D3. Keep the `transformation.result.published.v1` shape unchanged (Q11). Add an optional per-rule breakdown only if it is agreed in `platform-contracts`.
- D4. Gate behind flag `transformation.pii_rules_enabled`.
- D5. Tests: PII column triggers the rules, non-PII does not, and the metadata-service lookup failing degrades gracefully.

## 4. Ordering and dependencies

```
C (platform-contracts 2.4.0)
  └─> S (platform-sdk 3.5.0)
        ├─> I  ingestion-service   (emit tags)            ─┐
        ├─> M  metadata-service      (store/API/event)     <─┘ suggestions only useful once I ships
        │     ├─> E  entitlements-service (masked_columns)
        │     │     └─> R  reporting-service (masking)
        │     └─> D  transform-service (PII rules)
```

Dependency edges that matter (consumer → provider):
- metadata-service → ingestion-service (`ingestion.schema.discovered.v1`)
- metadata-service → transform-service (`transformation.result.published.v1`, no change)
- entitlements-service and reporting-service → metadata-service (`metadata.dataset.changed.v1`)
- transform-service → metadata-service (`GET /v1/datasets/{urn}/columns` via `platform-sdk`)
- reporting-service → entitlements-service (`POST /v1/access/decisions`)
- every service → `platform-sdk`; `platform-sdk` and metadata-service → `platform-contracts`

Parallelism: after S ships, I and M can run in parallel. After M, E and D can run in parallel. R needs E.

## 5. Compatibility and rollout (AC6: no breaking change, no downtime)

1. **Tolerant readers first.** Confirm (S4) that the SDK and every consumer ignore unknown JSON fields. Confirm that `metadata-service`'s schema-discovered consumer ignores the missing `tags`, which it already does by using only the `name`, `type` and `nullable` keys.
2. **Contracts and SDK** release as minor versions. Consumers upgrade when convenient, and older SDK versions keep working.
3. **Expand the storage.** Run the metadata-service migration that adds the optional properties (no backfill, online).
4. **Deploy metadata-service** with the read/write API and the event fields, and with `suggest_enabled=off`. Stewards can start classifying. Events now carry the fields, and existing consumers ignore them.
5. **Deploy ingestion-service** to emit tags, then turn on `suggest_enabled`. Re-run schema discovery or wait for the next cycle so suggestions populate. Optionally run a one-off backfill job that suggests classifications from historical tags.
6. **Deploy entitlements-service**: run the backfill (E4) and then return `masked_columns`. The field is ignored by callers that do not read it yet.
7. **Deploy reporting-service** with `masking.mode=shadow`. Compare the shadow logs with what stewards expect for at least one full reporting cycle. Grant `pii:read` to the users who legitimately need raw values before switching to `enforce`.
8. **Enable the transformation PII rules** (`transformation.pii_rules_enabled`) on a small set of datasets, then on all of them.
9. Every step is a rolling deploy behind a flag, and rollback means turning off the flag. No step removes or renames a field, so no `.v2` topic or path is needed.

Behavioural note: enforcing masking changes the values returned to users without `pii:read`. That is the purpose of the ticket, but it is a functional change for those users. Hence the shadow phase, the advance grant provisioning and the communication to consumers.

## 6. Cross-repository testing

**Contract tests** (consumer-driven, for example Pact or schema-based, run in CI on both sides):
- Event schemas:
  - `ingestion.schema.discovered.v1` (ingestion-service producer, metadata-service consumer), with and without `tags`.
  - `metadata.dataset.changed.v1` (metadata-service producer, entitlements-service and reporting-service consumers), with and without `classification`.
- Backward compatibility: run the schema registry or `platform-contracts` compatibility check against 2.3.0 in CI.
- HTTP contracts:
  - `GET /v1/datasets/{urn}/columns` and the new `PUT .../classification` (metadata-service provider, `platform-sdk` `MetadataClient` and transform-service consumers).
  - `POST /v1/access/decisions` with `masked_columns` (entitlements-service provider, reporting-service consumer).
- Old-client tests: the previous `platform-sdk` 3.4.1 deserialises the new payloads, and the previous consumer builds pass against new producer payloads.

**Integration / end-to-end** (staging, all seven services, synthetic data only):
1. Ingest a synthetic source table whose column comments are `tags: pii,email` and `tags: public`.
   Expect: metadata-service `GET .../columns` shows `PII/SUGGESTED` and `PUBLIC/SUGGESTED`, and a `COLUMNS_CHANGED` event carries both.
2. A steward overrides the second column to `CONFIDENTIAL` through `MetadataClient`, then the source is re-ingested.
   Expect: the override persists (`STEWARD`) and an event is emitted.
3. A requester without `pii:read` asks for an access decision, then runs a report.
   Expect: the decision's `masked_columns = [email]` and the email column is masked in the report output, including exports.
4. A requester with `pii:read` repeats step 3.
   Expect: `masked_columns = []` and the values are unmasked.
5. Run transformation on the dataset.
   Expect: the PII email-format rule runs on the PII column only, and `transformation.result.published.v1` is still consumed by metadata-service, so the quality score updates.
6. Compatibility run: repeat steps 1–4 with one consumer pinned to the old SDK and an old build.
   Expect: no errors.
7. Rollout rehearsal: toggle every flag on and off in staging under load.
   Expect: no 5xx errors and no consumer lag spikes.

## 7. Risks

- **Re-ingestion overwrites overrides.** `on_schema_discovered` currently replaces the whole column list. Without the M3 merge, every discovery would wipe steward classifications.
- **Strict consumers.** If any consumer rejects unknown fields or enum values, the "additive" change breaks it. Mitigate with S4, the contract tests, and no new `change_type`.
- **Stale entitlement state.** If entitlements-service lags on events, masking can briefly under-mask a newly classified PII column. Consider failing closed (mask) for columns with a classification change in flight, or reading synchronously from metadata-service (Q4).
- **Unclassified columns** are not masked under A3. PII exposure then depends on tag quality and steward coverage. The backfill and steward review reduce this.
- **Masking bypass paths:** caches, exports, direct DB access or other readers outside reporting-service (Q2).
- **transformation volume and cost.** New rules increase run time. They are gated per dataset.
- **Inferred names and paths.** `ingestion-service`, `transform-service` and `POST /v1/access/decisions` are guesses that must be confirmed with their owners.

## 8. Open questions

Q1. What are the exact names of the ingestion and transformation repositories?
Q2. Is reporting-service the only path returning data to consumers, or is there a separate consumption gateway?
Q3. What are the exact entitlements decision API path and shape?
Q4. What is the default classification for legacy or unclassified columns, and should masking fail closed?
Q5. Should `CONFIDENTIAL` also be masked for some audiences?
Q6. What is the tag→classification mapping table, and who owns it?
Q7. What masking format is required (redact, partial, hash), and must it be type-preserving?
Q8. Do consumers validate `change_type` against a closed enum?
Q9. Where do the steward role and the `pii:read` grant come from, and is an override audit trail required?
Q10. Which PII-format rules are needed, and are they selected by tag subtype?
Q11. Does `transformation.result.published.v1` need a per-rule breakdown for the PII checks?
