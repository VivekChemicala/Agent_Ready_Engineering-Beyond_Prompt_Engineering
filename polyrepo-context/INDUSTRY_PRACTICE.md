# Monorepo vs polyrepo for AI-assisted delivery: industry practice

Notes that go with experiment 3 (`experiment/`). They are written for teams
that build one product from several modules (ingestion, metadata/context graph,
entitlements, data quality, ...), with each module spread over several repos,
and that are moving to small AI-PODs that use coding agents.

> This summarises public practice and our own synthetic experiment. It does not
> describe any employer's systems.

## 1. Monorepo or polyrepo?

### What large engineering organisations do

| Pattern | Who uses it publicly | What makes it work |
|---|---|---|
| One monorepo for (almost) everything | Google (Potvin & Levenberg, *Why Google Stores Billions of Lines of Code in a Single Repository*, CACM 2016); Meta (Sapling) | Heavy investment in custom VCS, build system (Blaze/Bazel, Buck), code search, ownership files and trunk-based development. One version of every dependency. |
| Monorepo per product or language, built with graph-aware tools | Many mid-size companies, using Nx, Turborepo, Bazel, Pants or Gradle composite builds | The build tool knows the dependency graph and builds/tests only "affected" projects; CODEOWNERS keeps team ownership. |
| Polyrepo plus a catalog and contracts | Common in microservice organisations organised around independent teams | Every repo registers in a service catalog (e.g. Backstage `catalog-info.yaml` with `dependsOn`, `providesApis`, `consumesApis`). Contracts live in a schema registry or contracts repo (OpenAPI, AsyncAPI, JSON Schema/Avro). Consumer-driven contract tests (Pact) and a cross-service end-to-end suite catch integration breaks. |

No pattern wins everywhere. The deciding factors are coupling and release
cadence, and an agent's needs do not change them:

- **Monorepo** helps when modules change together, share libraries, and are
  released together. An atomic cross-module change is a single PR, and an agent
  can grep across all the code.
- **Polyrepo** helps when teams own and release modules on their own schedule,
  when access must be restricted, or when repos use different stacks. The cost
  is that cross-repo knowledge (who consumes what, through which contract, and
  how strictly) is not in any single checkout. You must publish it on purpose.

### What changes when agents do the work

An agent only knows what is in its context window plus what it can find. In a
polyrepo, the integration knowledge is not in the repo the ticket lands on, so
the agent has three options:

1. **Search other repos' code.** This is what a monorepo checkout gives you
   (arm D in our experiment). It works for things written in code (topic
   names, client calls, version pins). It misses intent and policy, such as
   "decide in entitlements, enforce in the gateway" or "this consumer validates
   strictly and must change first". It also costs more tokens, and the cost
   grows with the size of the codebase.
2. **Read a curated context layer.** Catalog, dependency graph, contracts,
   ADRs and a consumer registry (arms B and C). This is cheap to read, and it
   carries intent that code does not. It is only as good as it is kept up to
   date.
3. **Ask a tool.** Expose the same context layer through an MCP server or a
   code-search tool (Backstage API, Sourcegraph, a schema-registry API,
   Confluence/Jira) so the agent can query it on demand.

### Recommendation for a modular product with several scrum teams

- **Do not merge everything into a monorepo just for AI.** First publish a
  **platform context repo**, sometimes called a meta-repo or architecture repo,
  and point every service repo at it from its `AGENTS.md`:
  - `catalog/`: one entity per repo, with owner team, lifecycle (including
    *decommissioned*), APIs provided/consumed, topics produced/consumed, and
    library dependencies. Generate it from code where you can.
  - `contracts/`: OpenAPI, AsyncAPI and event schemas, versioned and released.
  - `architecture/`: C4 diagrams, key flows, ADRs, and a **consumer registry**
    that records how strictly each consumer reads each contract.
  - `playbooks/`: how a cross-repo change is ordered, tested and rolled out.
  - `e2e/`: or a pointer to the cross-service test suite and environment.
- **Consider a monorepo per module (bounded context)** when the repos inside a
  module are tightly coupled and released together, for example all ingestion
  connectors and their shared libraries. This keeps the repo boundary at team
  boundaries (Conway's law; *Team Topologies*, Skelton & Pais) while giving
  agents a single checkout for the work an AI-POD does most often.
- **Give agents multi-repo checkouts on demand.** For a cross-module ticket,
  check out the affected repos side by side, the way VS Code multi-root
  workspaces or multi-repo agent sessions do. Use the context repo to decide
  *which* repos to check out.

## 2. Keeping cross-repo dependencies understandable to agents

### Make dependencies machine-readable and verified

| Practice | Why it matters for agents |
|---|---|
| Catalog entity per repo (`catalog-info.yaml`), aggregated into a dependency graph | The agent can list impacted repos from a few small files instead of reading every repo's code. |
| Generate graph edges from code (topic names in config, SDK pins, generated API clients) and fail CI when the catalog drifts | Stale docs are worse than no docs. In our experiment the stale README sent arm A toward a decommissioned service. |
| Contracts as the source of truth (schema registry or contracts repo) with a compatibility policy (additive = minor; breaking = new version) | The agent can say exactly which contract changes and whether the change is additive. |
| Consumer registry: who reads which fields, tolerant vs strict | This is the knowledge that turns "verify" into "must change first". Code alone rarely says it in one place. |
| Shared SDK with explicit models, released versions, and automated bumps (Renovate/Dependabot) | The agent can plan the "release SDK, then bump consumers" step. |
| Consumer-driven contract tests (Pact, with a `can-i-deploy` gate) | They catch a provider change that breaks a consumer before it merges, in either repo. |
| Cross-service e2e suite and an ephemeral or shared integration environment | They prove that the end-to-end behaviour of a multi-repo ticket works. |
| ADRs for placement decisions (where a rule is decided and where it is enforced) | Agents put logic in the right repo. |
| `AGENTS.md` in every repo pointing at the context repo, the verify commands, and the change playbook | Every agent session starts from the same instructions. |

### One Jira story, many repos: a workflow for AI-PODs

1. **Story quality gate.** The story has acceptance criteria and names the
   owning module. A requirements agent can check this against a template.
2. **Impact analysis (agent + context repo).** The agent produces a structured
   impact analysis: repos to change or verify, dependency edges, contracts, and
   open questions. This is the `IMPACT_ANALYSIS.json` from our experiment. A
   human (POD lead or architect) approves it.
3. **Split into linked sub-tasks**, one per repo, in dependency order:
   contracts, then SDK, then strict consumers, then providers/producers, then
   features, then e2e.
4. **Coding agents per repo.** Each one gets its sub-task, the approved plan,
   and the repo's harness (rules, skills, verify loop). The agents open linked
   PRs that reference the parent story.
5. **Contract tests in every PR. E2E tests in the integration environment**
   once the chain of PRs is merged or deployed to a preview.
6. **Deploy behind flags, monitor, then enable.** Producers emit new fields
   only after consumers are ready (expand/contract, also called parallel change).

## 3. What our experiment adds

Full results: [`experiment/RESULTS.md`](experiment/RESULTS.md). 3 Devin trials
per arm, one synthetic cross-module ticket:

| Arm | Repos found (of 10) | Planned work for a decommissioned repo | Contracts found (of 5) | Plan score (of 16) |
|---|---|---|---|---|
| A: one repo + README | 6.7 | 3/3 | 4.0 | 9.0 |
| B: + catalog and dependency graph | 10.0 | 0/3 | 4.0 | 13.7 |
| C: + contracts and architecture docs | 10.0 | 0/3 | 5.0 | 16.0 |
| D: all code side by side, no docs | 9.7 | 3/3 | 5.0 | 15.0 |

The catalog fixed discovery. Contracts, ADRs and the consumer registry made the
plan correct. Having all the code gave nearly the same plan quality, but it
did not tell agents that a service was retired, so a stale README still misled
them.

## References

- R. Potvin, J. Levenberg. "Why Google Stores Billions of Lines of Code in a
  Single Repository." *Communications of the ACM*, 59(7), 2016.
- Backstage software catalog: descriptor format (`catalog-info.yaml`) and
  well-known relations (`dependsOn`, `providesApi`, `consumesApi`).
- OpenAPI Specification; AsyncAPI Specification.
- I. Robinson. "Consumer-Driven Contracts: A Service Evolution Pattern."
  martinfowler.com, 2006. Pact (consumer-driven contract testing).
- M. Fowler. "TolerantReader." D. Sato. "ParallelChange." martinfowler.com bliki.
- M. Skelton, M. Pais. *Team Topologies*. IT Revolution, 2019.
- AGENTS.md (open format for agent instructions); Model Context Protocol (MCP).
