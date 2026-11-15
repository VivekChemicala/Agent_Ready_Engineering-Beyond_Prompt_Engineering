# Does a domain-conventions skill improve first-pass acceptance?

Task: build a synthetic Kafka-style transaction ingestion and validation pipeline
(JSONL partitions in, `valid.jsonl` / `rejects.jsonl` / `metrics.json` out).

## Setup

| | Basic arm | Skill arm |
|---|---|---|
| Prompt | `task.md` only | `task.md` + `skill/SKILL.md` |
| Agent | Devin session, `normal` mode | Devin session, `normal` mode |
| Starting commit | `4e49733` (`exp/txn-pipeline-start`) | same |
| Agent writes its own tests | yes | yes |
| Hidden acceptance suite | `acceptance/` (6 requirement, 19 contract, 4 robustness), never visible to agents | same |

Each trial is accepted only if **all** gates pass on the pushed commit, re-run
independently by `score.py` in a clean worktree: the agent's own pytest suite,
`flake8 src tests`, a CLI smoke run, and 29/29 hidden checks.
A rejected delivery gets one scripted reviewer message (`feedback.py`; it states
the expected behaviour, never the test inputs), at most 2 rounds per trial.
Each round counts as one rework iteration and one human intervention.
All six sessions ran in parallel (2026-11-15, 18:50 to 18:58 UTC).

## Results

| Trial | First pass | Req | Contract | Robust | Rework | Interventions | Cycle time | Agent time | Checks run before every delivery | Gates green every delivery | Final commit |
|---|---|---|---|---|---|---|---|---|---|---|---|
| basic_t1 | no | 6/6 | 3/19 | 3/4 | 2 | 2 | 3m28s | 2m43s | 3/3 | 3/3 | `76b19958` |
| basic_t2 | no | 6/6 | 4/19 | 3/4 | 1 | 1 | 5m42s | 5m25s | 2/2 | 2/2 | `1d9a0299` |
| basic_t3 | no | 6/6 | 3/19 | 3/4 | 2 | 2 | 6m43s | 6m03s | 3/3 | 3/3 | `19d13626` |
| skill_t1 | yes | 6/6 | 19/19 | 4/4 | 0 | 0 | 3m39s | 3m39s | 1/1 | 1/1 | `5ac592cf` |
| skill_t2 | yes | 6/6 | 19/19 | 4/4 | 0 | 0 | 3m08s | 3m08s | 1/1 | 1/1 | `3924ac85` |
| skill_t3 | yes | 6/6 | 19/19 | 4/4 | 0 | 0 | 4m28s | 4m28s | 1/1 | 1/1 | `3764f974` |

| Arm | First-pass acceptance | Final acceptance | Mean first-pass contract | Total rework | Total interventions | Median cycle time | Total agent time | Distinct first-pass outputs | Agent time per accepted change |
|---|---|---|---|---|---|---|---|---|---|
| basic | 0/3 | 3/3 | 3.3/19 | 5 | 5 | 5m42s | 14m11s | 3 | 4m43s |
| skill | 3/3 | 3/3 | 19.0/19 | 0 | 0 | 3m39s | 11m15s | 1 | 3m45s |

Column definitions:
- **Req / Contract / Robust**: hidden-suite checks passed by the first delivery.
- **Cycle time**: from session creation to the accepted push. It includes reviewer turnaround, which was 10 to 30 s here because review was automated.
- **Agent time**: the time the agent was working. Waiting for review is excluded.
- **Checks run before every delivery**: pytest, flake8 and the CLI command all appear in the agent's shell log between the start of the round and the push.
- **Gates green every delivery**: our independent re-run of the agent's pytest, flake8 and CLI passed.

### Metric summary

| Metric | Basic | Skill |
|---|---|---|
| First-pass acceptance | 0/3 | **3/3** |
| Final acceptance (≤2 corrections) | 3/3 | 3/3 |
| Rework iterations | 5 (2, 1, 2) | **0** |
| Human interventions | 5 reviewer messages | **0** |
| Verification compliance | 8/8 deliveries ran and passed all 3 checks | 3/3 |
| Reliability | 3 different first-pass outputs; contract 3–4/19 | 1 identical output across 3 trials; 19/19 each |
| Median cycle time | 5m42s | **3m39s** |
| Agent time per accepted change (cost proxy) | 4m43s | **3m45s** |
| ACUs per accepted change | not available (see below) | not available |
| Lines added (first delivery) | 579–763 | 794–864 |

## Findings

1. **The skill moved first-pass acceptance from 0/3 to 3/3.** In every trial
   both arms met all six functional requirements. Every basic-arm failure was
   a contract failure: output key names, the reason-code vocabulary, what to do
   with an unreadable offset, validation precedence, numeric partition order,
   and the metrics shape. Basic-arm robustness was also 3/4 in each trial.
2. **The agents' own tests did not catch these failures.** All 8 basic
   deliveries had green pytest/flake8/CLI (35–113 tests each), yet the first
   deliveries passed only 3–4 of 19 contract checks. The agents' tests encode
   the agents' own guesses about the contract. Verification compliance was
   100% in both arms, so the gap is in what the tests check, not whether the
   agents ran them.
3. **The skill did not just produce more code.** The skill arm's first
   deliveries were about the same size as the basic arm's *final* deliveries
   (794–864 vs 717–890 lines). Corrections pushed the basic arm toward the
   same code, and its final outputs are byte-identical to the skill arm's.
4. **Two of three basic trials needed a second correction round** for the same
   three edge cases: a malformed offset is `MALFORMED_EVENT`, a blank or
   missing customer ID is `NULL_CUSTOMER_ID`, and the order in which checks
   are applied. Round-1 feedback stated these rules in looser terms. A
   reviewer has to state edge-case rules very precisely, and the skill does
   that once, up front.
5. **The sample-data fingerprint is not enough to detect contract drift.**
   `basic_t3` round 1 produced byte-identical output on the sample data while
   still failing 3 contract checks. The hidden edge-case suite is what decides
   acceptance.

## Limitations

- n = 3 per arm. 3/3 vs 0/3 is a large effect, but the confidence interval
  is wide.
- The skill states the contract explicitly, and the contract checks test that
  contract. The result shows that giving the agent the domain conventions
  removes contract misses. It does not show that the skill makes the agent
  better at engineering in general. Both arms were equally good at the
  functional requirements.
- Cycle time is a lower bound for the basic arm. Here review took about 20 s;
  a human reviewer would take hours, so the real gap is larger.
- **Cost:** the Devin API reported `acus_consumed = 0.0` for all six child
  sessions, even after they ended, so we could not compute ACU cost per
  accepted change. Agent working time is used as the cost proxy instead.
  `aggregate.py costs.json` re-renders the tables once ACUs are available.
- Both arms ran in the same Devin mode (`normal`). The API does not expose
  which underlying model each session used.

## Reproduce

```bash
cd txn-pipeline/experiment
python score.py <path-to-delivered-txn-pipeline>   # all gates for one delivery
python score_round.py <trial> <sha> <unix_ts>      # score + record a round
python aggregate.py                                # rebuild the tables above
```

Trial branches: `exp/txn-{basic,skill}-t{1,2,3}`. Per-round scores and
reviewer messages are in `runs/`, and the ledger is `trials.json`.
