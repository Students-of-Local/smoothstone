# Agents

- A fault the owner reports gets a regression spec that fails on it before the fix merges.
  Specs live in evals/regressions/, with the request, the expect block, and in `why` the fault in
  his words. evals/ratchet.py keeps the floor in evals/floor.json: never lower it or delete a spec
  in evals/tuning, figure or regressions without a LOG.md line naming it and saying why.
