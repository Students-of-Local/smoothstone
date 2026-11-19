# Evals

Each spec is a request a person would type, an optional picture, and what a passing part must
have. A run passes when the model reached `stone done`, the final part passes `stone check`, the
recipe matches, and every expected parameter is in range (`[lo, hi]` is inclusive, a plain value
must match, `sum` adds parameters, `image_used` means that image parameter was set).

- `tuning/`: specs used while improving the skill and the tool. Their results inform changes.
- `heldout/`: written and sealed before any tuning run (SHA-256 in ../LOG.md and in the
  lfm3-3d-skill LOG.md). They run once, after the skill and tool are frozen.

## The ratchet

Every run appends one line to `scores.jsonl` (date, git sha, suite, spec, card, driver, pass, total,
judge score). The file is only appended to. `floor.json` holds, per suite and card (the next driver
counts as card "next"), the best pass rate and mean judge score so far and the specs that passed.

- `uv run python evals/ratchet.py <runs dir>`: below the floor it names the specs that regressed and
  exits 1; above it, or for a new group, it raises the floor. It never lowers one.
- `uv run python evals/ratchet.py --check-git origin/main` (in CI): fails when the diff lowers a floor,
  drops a passing spec from it, or deletes a spec in tuning/, figure/ or regressions/, unless a line
  added to LOG.md names it and says why.
- `regressions/`: each fault the owner reports, as a spec that fails on it before the fix merges, with
  his words in `why`. A spec with `"judge": {"faults_in": ["boundaries"]}` runs `judge_views.py` (a
  blind Opus judge that sees only the request, views.png and boundaries.png) and fails on any fault it
  names in those pictures; the verdict is saved as judge.json next to the run.
- Every figure spec also runs `judge_likeness.py`: Opus names the Wikipedia article the request
  means (text only), the harness fetches that article's lead image, and a blind Opus run compares
  the render the figure was made from with it, feature by feature (hair, facial hair, glasses, skin,
  age, clothes). Below 6 of 10 the run fails with the judge's conflicts; a judge that cannot answer
  fails it too. The tool's own photos are never the reference: for "DHH" it once styled a protein,
  and every other check passed the made up man it sculpted. The verdict is likeness.json.
- A spec with `"colors": {"black": ["jacket"], "rest": "white"}` checks the painted 3MF: it reads back
  clean, its color edges pass, and every part prints in the color asked for.
