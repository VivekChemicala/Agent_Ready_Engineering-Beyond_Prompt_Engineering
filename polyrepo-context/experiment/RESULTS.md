# Experiment 3 results: can an agent understand a polyrepo system?

All services, teams, topics, APIs and the Jira ticket are **synthetic**.

## Setup

- **System:** 13 fictional repos for a data platform (ingestion, metadata/context
  graph, entitlements, query gateway, DQ, search, lineage, notification, usage
  metering, a decommissioned reporting service, a shared SDK, a contracts repo
  and a cross-service e2e repo). Source of truth: `system_model.py`.
- **Ticket:** DP-1423, column sensitivity classification and PII masking
  (`task.md`). It lands on team-graph (`metadata-graph`) but needs code changes
  in 9 repos and verification in 1.
- **Traps built in:** `metadata-graph`'s README is stale and still lists
  `reporting-service` as a consumer (it is decommissioned). `search-indexer`
  validates events strictly (`additionalProperties: false`). `platform-sdk`
  models drop unknown fields.
- **Arms** (only the workspace differs; prompt and task are identical):

| Arm | Workspace | Files | Bytes |
|---|---|---|---|
| A | `metadata-graph` repo only | 13 | 8,242 |
| B | A + Backstage-style catalog and dependency graph | 34 | 24,177 |
| C | B + OpenAPI/event contracts + architecture docs (flows, ADRs, consumer registry, change playbook) | 56 | 36,581 |
| D (added) | All 12 live repos' code side by side ("monorepo checkout"), no catalog or docs | 79 | 32,730 |

- **Agent:** Devin sessions in Normal mode, 3 trials per arm, run in parallel
  from fixed start commits (`start_shas.json`). The platform does not expose the
  underlying model, so these results describe Devin in that mode, not any
  specific model.
- **Scoring:**
  - `IMPACT_ANALYSIS.json` scored by `score.py` against `hidden/answer_key.json`
    (10 impacted repos, 11 relevant edges, 5 contracts). The key was kept off
    the trial branches.
  - `PLAN.md` scored 0-16 by a separate blind Devin session (`judge/rubric.md`,
    `judge/system_facts.md`). Plans were shuffled and renamed P01-P12
    (`hidden/judge_mapping.json`); scores are in `judge/scores.json`.

## Results

### Per arm (mean of 3 trials; time is median)

| Arm | Repos found (of 10) | Decommissioned repo planned | Edges found (of 11) | Wrong edges | Contracts found (of 5) | Wrong contracts | Plan score (of 16) | Time to push |
|---|---|---|---|---|---|---|---|---|
| A: one repo | 6.7 | 3/3 | 5.3 | 2.0 | 4.0 | 1.7 | 9.0 | 2m11s |
| B: + catalog | **10.0** | 0/3 | **11.0** | 0.0 | 4.0 | 2.0 | 13.7 | 2m46s |
| C: + contracts and docs | **10.0** | 0/3 | **11.0** | 0.0 | **5.0** | 0.0 | **16.0** | 3m18s |
| D: all code, no docs | 9.7 | 3/3 | 10.0 | 1.3 | **5.0** | 0.0 | 15.0 | 3m12s |

Per-trial numbers, including missed and wrong repos, are in
[`RESULTS_TABLES.md`](RESULTS_TABLES.md). Raw outputs are in `runs/`.

### Findings

1. **One repo is not enough (A).** Every A trial missed `search-indexer`
   (the strict consumer), `lineage-service` and `platform-e2e`, guessed repo
   names that do not exist (such as `query-service`), and followed the stale
   README into the decommissioned `reporting-service`. One trial put masking
   enforcement there.
2. **A catalog alone fixes discovery (B).** All three B trials found all 10
   repos and all 11 edges, and none planned work for the decommissioned
   service, because the catalog marks its lifecycle. B could not name exact
   API paths (no contracts) and did not see that `search-indexer` is strict or
   that the SDK drops unknown fields, which cost plan points.
3. **Contracts and architecture docs make the plan correct (C).** All C
   trials scored 16/16: exact contracts, `search-indexer` updated before
   producers emit the new field, SDK release and bumps, decision in
   entitlements and enforcement in the gateway (from the ADRs), per-consumer
   contract tests plus the e2e suite.
4. **All the code, without curated docs, gets close but trusts stale docs
   (D).** D found the strict consumer and the SDK hazard by reading code and
   got every contract right, scoring 15/16. But all three D trials still
   planned a readiness gate for `reporting-service`. Code shows what exists;
   only the catalog said that the service is retired. D also missed edges in
   2 of 3 trials (lineage, vendored schema).
5. **Cost of discovery.** C and D took about 1 minute longer than A
   (median 3m18s and 3m12s vs 2m11s). The extra minute bought +3.3 repos and
   +7 plan points. Token counts and ACUs were not available (the API reported
   0 ACUs for every session).

### What this means for the two questions

- **Q1, monorepo or polyrepo:** a monorepo-style checkout (D) helps an agent
  nearly as much as curated context (C) on this task, but it does not replace
  lifecycle, ownership and intent (ADRs, strictness). A polyrepo with a
  maintained catalog, contracts and architecture docs (C) did best.
- **Q2, dependencies:** the minimum is a machine-readable catalog with
  `dependsOn`/`providesApis`/`consumesApis`, topics and lifecycle (B). Adding
  versioned contracts, a consumer registry (strict vs tolerant) and a change
  playbook (C) is what turned a correct repo list into a correctly ordered,
  testable multi-repo plan.

## Scoring notes and corrections

- `notification-service` is listed as a wrong repo in 7 trials. Every one of
  those trials marked it `verify_only` because it calls metadata-graph through
  the SDK being bumped. The answer key says "not impacted"; the trials' reason
  is defensible, so treat that column as conservative.
- `platform-catalog` (B_t1, B_t3) was listed as a `verify_only` "repo". It is
  the catalog folder, not a service.
- After seeing the outputs, `score.py` was changed to accept
  "owner -> platform-contracts" edges (every service publishes its schemas
  there), which all 12 trials listed. This changed only the "wrong edges"
  column. A second fix corrected an indentation bug in contract matching; it
  did not change any score.

## Limitations

- 3 trials per arm, one ticket, one synthetic system written by the
  experimenter. The direction is consistent; effect sizes are not precise.
- The hidden key and the judge's system facts reflect the same architecture
  that arm C's docs describe, so C is partly scored on facts it was given. The
  experiment shows that publishing those facts lets agents use them, not that
  agents reason better in general.
- Plan quality was scored by one automated reviewer, not by humans. Plans may
  carry hints about their arm (for example "path not visible in workspace").
- Real systems are larger. Arm D's cost would grow with code size, while B and
  C's would grow with the number of services.
- No cost data (0 ACUs reported) and no model identity.

## Reproduce

```bash
cd polyrepo-context/experiment
python3 build_catalog.py ../system/platform-catalog   # regenerates the catalog
python3 make_workspaces.py A /tmp/arm-A               # builds one arm's workspace (A-D)
python3 make_prompts.py            # writes prompts/generated/*.md
python3 collect.py                 # fetches exp/poly-<arm>-t<n> branches into runs/
python3 aggregate.py               # scores and writes RESULTS_TABLES.md
```
