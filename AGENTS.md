# Agents

- Read docs/DIRECTION.md, the owner's standing direction, before planning work: where smoothstone is going and
  the bar a change must meet.
- A fault the owner reports gets a regression spec that fails on it before the fix merges.
  Specs live in evals/regressions/, with the request, the expect block, and in `why` the fault in
  his words. evals/ratchet.py keeps the floor in evals/floor.json: never lower it or delete a spec
  in evals/tuning, figure or regressions without a LOG.md line naming it and saying why.
