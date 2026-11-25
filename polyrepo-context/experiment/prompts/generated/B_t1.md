Repository: VivekChemicala/Agent_Ready_Engineering-Beyond_Prompt_Engineering (formerly VivekChemicala/Python). Start from branch `exp/poly-B-start` (commit `4866576eb4f40d4263585c0e3ee7f4ff1a0911c9`). All material is under `polyrepo-context/workspace/`.

This is one trial of a controlled experiment, so please:
- Work only from this prompt and the repository contents at that commit. Do not read other branches, pull requests, other Devin sessions, or the internet.
- Do not ask questions; make reasonable decisions yourself and note them as assumptions or open questions.
- Write the two output files under `polyrepo-context/workspace/analysis/`, commit them, and push to a new branch named `exp/poly-B-t1`. Do not open a pull request. Do not change any other files.
- Then reply with the pushed commit SHA and a two-line summary.

Paths in the task below are relative to `polyrepo-context/`.

## Jira ticket DP-1423 (synthetic)

**Title:** Column-level sensitivity classification and PII masking

**Reporter:** data governance. **Assigned team:** team-metadata (owns `metadata-service`).

**Story.** As a data steward, I want every dataset column to carry a sensitivity
classification (`PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `PII`) so that people
without PII access see masked values, and PII columns get PII-specific quality
checks.

**Acceptance criteria**
1. When a source schema is ingested, a classification is suggested from the
   source column tags (for example a column comment `tags: pii,email`).
2. Stewards can set or override a column's classification through the
   metadata API. The classification is stored per column in the metadata store
   and returned wherever column metadata is returned, including change events.
3. Access decisions say which columns must be masked when the requester does
   not hold a `pii:read` grant.
4. Query results returned to data consumers have those columns masked.
5. Transformation runs apply PII-format validation rules to columns classified
   `PII`.
6. Existing consumers keep working throughout the rollout (no breaking change,
   no downtime).

---

## What we need from you: impact analysis and implementation plan (no code)

The ticket landed on team-metadata, but it probably needs changes in other
repositories too. In production, each top-level folder under `workspace/` is
a separate git repository (we use a polyrepo). The folders you have are the
repositories and documents you have access to for this task.

Do not implement the feature. Produce two files:

### 1. `workspace/analysis/IMPACT_ANALYSIS.json`

```json
{
  "ticket": "DP-1423",
  "repositories": [
    {"name": "<repo name>", "impact": "code_change | verify_only",
     "reason": "<one sentence>", "evidence": ["<file paths you relied on>"],
     "name_source": "observed | inferred"}
  ],
  "considered_not_impacted": [{"name": "<repo name>", "reason": "<one sentence>"}],
  "dependencies": [
    {"consumer": "<repo>", "provider": "<repo>", "via": "event | http | library",
     "contract": "<topic, METHOD /path, or library name>"}
  ],
  "contracts": [
    {"kind": "event | http", "name": "<topic name or METHOD /path>",
     "owner": "<repo that owns/provides it>", "change": "modify | new",
     "compatibility": "additive | breaking", "description": "<what changes>"}
  ],
  "open_questions": ["<question>"]
}
```

- `repositories`: every repository that needs a code change or must be
  re-verified (tests only) for this ticket. Use exact repository names when you
  can see them; otherwise give your best guess and set `name_source: inferred`.
- `dependencies`: the direct dependency edges that matter for this ticket
  (consumer depends on provider), including shared-library dependencies.
- `contracts`: every API endpoint or event topic whose shape changes or that
  must be created.

### 2. `workspace/analysis/PLAN.md`

An implementation plan another engineer could execute: per-repository work
items, ordering and dependencies between them, compatibility and rollout
approach, cross-repository testing (contract and integration/end-to-end), and
risks/open questions.
