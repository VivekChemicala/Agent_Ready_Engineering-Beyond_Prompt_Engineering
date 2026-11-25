# Plan-quality rubric (DP-1423, synthetic)

Score each plan on eight criteria: **0** = absent or wrong, **1** = present but
generic or partly wrong, **2** = specific and correct for this system. Judge
against `system_facts.md`, not against what the plan's author could see.

| # | Criterion | 2 points looks like |
|---|---|---|
| P1 | Ordering | Contracts first, then SDK, strict consumers made ready before producers emit the new fields, then producers, then features that depend on them. Dependencies between work items are explicit. |
| P2 | Compatibility | Additive, optional fields on existing v1 topics/APIs (or a justified v2 with dual publish). Explains why existing consumers keep working (AC6). |
| P3 | Strict-consumer risk | Names `search-indexer` (strict vendored schema, `additionalProperties: false`, DLQ) as a breaking risk and fixes it before producers ship. |
| P4 | Enforcement point | Masking decision computed in entitlements-service (columns to mask, `pii:read`), enforced in consumption-gateway on returned rows. |
| P5 | Shared library | platform-sdk models (Column, Decision) must be extended and released, and consuming repos must bump the SDK, because unknown fields are dropped. |
| P6 | Cross-repo testing | Contract tests for changed contracts per consumer/provider AND an end-to-end suite (platform-e2e / int environment) covering ingest -> classify -> decide -> masked query, plus transformation PII rules. |
| P7 | Rollout safety | Feature flag or staged enablement for masking, defaults/backfill for existing columns without a classification, rollback path. |
| P8 | Executable breakdown | Per-repository work items with owning team, concrete changes, and acceptance checks that another engineer could pick up. |

Total: 0-16.
