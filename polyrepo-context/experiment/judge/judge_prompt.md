Repository: VivekChemicala/Agent_Ready_Engineering-Beyond_Prompt_Engineering. Check out branch `exp/poly-judge` (commit `{sha}`). Everything there is synthetic.

You are a blind reviewer in a controlled experiment. Folder `judge/` contains:
- `rubric.md` - eight criteria scored 0/1/2.
- `system_facts.md` - the true architecture of the synthetic system.
- `plans/P01.md` ... `plans/P12.md` - twelve implementation plans for the same Jira ticket, written by different agents with different context. Their order is random.

Score every plan against the rubric, using `system_facts.md` as ground truth. Judge each plan on its own merits; do not try to guess how it was produced. Do not read other branches, PRs or sessions.

Write `judge/scores.json` as `{"P01": {"P1": 0-2, ..., "P8": 0-2, "notes": "<one sentence>"}, ...}`, commit it, and push to branch `exp/poly-judge-scores`. Do not open a pull request. Reply with the commit SHA.
