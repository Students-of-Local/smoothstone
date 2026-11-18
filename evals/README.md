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
judge score). Runs only append; evals/rejudge.py replaces the line of a run it judges again, so
the run counts once. `floor.json` holds, per suite and card (the next driver
counts as card "next"), the best pass rate and mean judge score so far and the specs that passed.

- `uv run python evals/ratchet.py <runs dir>`: below the floor it names the specs that regressed and
  exits 1; above it, or for a new group, it raises the floor. It never lowers one.
- `uv run python evals/ratchet.py --check-git origin/main` (in CI): fails when the diff lowers a floor,
  drops a passing spec from it, or deletes a spec in tuning/, figure/ or regressions/, unless a line
  added to LOG.md names it and says why.
- `regressions/`: each fault the owner reports, as a spec that fails on it before the fix merges, with
  his words in `why`. A spec with `"judge": {"faults_in": ["boundaries"]}` runs `judge_views.py` (a
  blind Opus judge that sees only the request, views.png and boundaries.png) and fails when the judge
  names a fault in those pictures. The judge is an LLM, so its verdict is a vote: two runs, and a
  third only when they disagree; the majority decides and the score is the median. A judge that
  cannot answer fails the run with the reason. The verdict is saved as judge.json next to the run.
  The ratchet counts a judge mean as below its floor only when it is more than 1 point under it.
- Every figure spec also runs `judge_likeness.py`: Opus names the Wikipedia article the request
  means (text only), the harness fetches that article's lead image, and a blind Opus run compares
  the render the figure was made from with it, feature by feature (hair, facial hair, glasses, skin,
  age, clothes). Below 6 of 10 the run fails with the judge's conflicts; a judge that cannot answer
  fails it too. The tool's own photos are never the reference: for "DHH" it once styled a protein,
  and every other check passed the made up man it sculpted. The verdict is likeness.json.
- The three figure modes (`figure-research/`, `figure-photo/`, `figure-desc/`, sealed in ../LOG.md on
  2026-11-19) have their own likeness bar. Research: the Wikipedia judge at 7 or more. Photos: the last
  photo a spec lists is held back from the tool and is the judge's reference, at 7 or more; seed 1
  gives the tool photo 1 only, seed 2 every photo but the reference (photo 1 by `stone new --image`,
  the rest as `image/source.z<k>.jpg`, which `job.photos()` lists after it); log.json records which.
  Description: `judge_traits.py` shows Opus only views.png and the spec's `expect.traits`, and every
  trait must be visible (traits.json). Each mode run is also scored by the craft judge
  (`judge_views.py`, judge.json), which never fails a run on its own. `evals/bar.py <runs dir>` prints
  per mode the runs that pass out of cases x 2 seeds against 80%, and the craft mean against 8 with the
  seeded control's score (judge_control.py, then judge_views.py on it), which must be under 8.
- `figure-random/`: five people drawn at random on 2026-11-21 (seed 20261121) from en.wikipedia's
  top 400 articles of 2026-10 with a photo, for Donovan's "5/5 perfection from the random pulled
  people". Research mode, with its likeness bar of 7; a run needs the craft judge at 8 too.
- Figures on a host without the style model (Linux has no mflux): `stone build` reuses a figure from
  the shared cache (~/.cache/stone-figure/<key>, `STONE_FIGURE_CACHE`) when the same photos and
  settings were built before, so copy the key folder from a Mac job's image/figure/ into the cache.
- A spec with `"colors": {"black": ["jacket"], "rest": "white"}` checks the painted 3MF: it reads back
  clean, its color edges pass, and every part prints in the color asked for.

## The teacher loop

A failing run says something is wrong, not where. `uv run python evals/distill.py <runs dir> ...`
reads each model run and finds its first divergence from stone's path (every stone message ends
with a NEXT line, so the path is known), then says where the fix goes: the card (`off`, `stopped`,
`values`), stone itself (`tool`, `steps`), or the trial's setup (`setup`, which does not count).
After a card edit, run each case twice and read the card-version ledger at the bottom: a version
with a lower pass rate on the specs both versions ran is reverted, not patched on top of. Adapted
from sybil-solutions/skill-distill.
