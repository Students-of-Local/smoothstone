# Agents

- Read docs/DIRECTION.md, the owner's standing direction, before planning work: where smoothstone is going and
  the bar a change must meet.
- A fault the owner reports gets a regression spec that fails on it before the fix merges.
  Specs live in evals/regressions/, with the request, the expect block, and in `why` the fault in
  his words. evals/ratchet.py keeps the floor in evals/floor.json: never lower it or delete a spec
  in evals/tuning, figure or regressions without a LOG.md line naming it and saying why.
- Run the test suite, eval runs and anything else that loads meshes through `scripts/heavy` (capped memory, temp files on disk), with
  `pytest -n 8`, not `-n auto`: one worker per core on a 32-core host filled memory, and systemd-oomd
  killed the agent's whole session with it. Write eval `--out` folders to disk, not /tmp: on that host /tmp is RAM.
