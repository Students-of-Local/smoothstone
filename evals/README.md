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
  drops a passing spec from it, or deletes a spec in tuning/, figure/, regressions/ or engineering/, unless a line
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

## Engineering specs

`engineering/`: parts made for a real product (a case, a holder, a mount, an adapter, a replacement
part), graded on whether they are engineered right, not on the recipe. Every product number in a
spec comes from the maker's published spec sheet or drawing, with the URLs in the spec; a product
whose numbers are not published is left out, never estimated. When a maker publishes the overall
size but no corner radius, `corner_r` is 0: the sharp box encloses the real body.

```json
{"id": "e01_rpi5_case", "request": "what a person types", "input": "text | model_number | photo",
 "image": "optional path next to the spec",
 "product": {"name": "...", "sources": ["https://..."],
   "body": {"w": 85, "d": 56, "h": 17, "corner_r": 3},
   "features": [{"name": "usb_c_power", "kind": "port | button | switch | vent | lens | screen | led | slot",
                 "face": "+x | -x | +y | -y | +z | -z", "c": [u, v], "size": [w, h], "plug": [w, h],
                 "source": "https://... and where"}]},
 "expect": {"kind": "case | holder | mount | adapter | replacement", "material": "PLA | PETG | TPU",
            "fit": "slip | snug | press", "retention": "friction | snap | screw | none | any",
            "load_n": 20, "load_dir": "-z", "safety": 2,
            "covered": ["faces the part wraps"], "open": ["faces that stay clear"]}}
```

The product frame: x is width, y depth, z height as the part holds the product, origin at the body's
min corner, so the body is the box [0,w] x [0,d] x [0,h] with its four vertical edges rounded by
`corner_r`. A feature's `c` is its center on its face, mm from the face's lower-left corner as seen
from outside the product; `size` is its opening and `plug` (optional) the plug or fingertip that must
pass through the part. A face in neither `covered` nor `open` is not checked.

| face | seen from | u (right) | v (up) |
| --- | --- | --- | --- |
| -y | the front | x | z |
| +y | behind | w - x | z |
| +x | the right | y | z |
| -x | the left | d - y | z |
| +z | above, +y up | x | y |
| -z | below, +y up | w - x | y |

The built part writes `build/engineering.json`; without it the run fails with "the part does not say
where the product sits (no engineering.json)".

```json
{"frame": [[1,0,0,2.3],[0,1,0,2.3],[0,0,1,2.3],[0,0,0,1]],
 "material": "PLA", "clearance": 0.3,
 "retention": {"type": "snap", "y": 0.6, "t": 1.5, "L": 12},
 "load": {"n": 20, "dir": "-z", "arm": 40, "b": 20, "h": 8, "across_layers": false},
 "sources": {"w": "https://...", "d": "...", "h": "...", "corner_r": "...", "usb_c_power": "calipers"}}
```

- `frame`: the 4x4 matrix (row major) that places the product frame in the part's STL coordinates, a
  rotation plus a move only. It puts the product where the design centers it, so each side's gap is
  its designed clearance.
- `clearance`: mm per side, a number or per face (`{"+x": 0.3, ...}`).
- `retention`, by type: `snap` {y undercut, t arm thickness at the root, L arm length}; `friction`
  {gap, mm, negative for interference}; `screw` {size M2 | M2.5 | M3, method self_tap | insert,
  hole_d}; `none` {}.
- `load` (when the spec has `load_n`): the force in N, its direction, and the critical section as a
  rectangle b x h mm at `arm` mm from the load, and whether the stress runs across the layers.
- `sources`: for w, d, h, corner_r and every feature by name, a URL, "calipers", or "photo with <the
  reference in the photo>".

`engineering_grade.py` checks, each failure a line with its measured number:

- fit: the product box sampled at 2 points per mm2 and placed by the frame; no sample inside the part
  (ray parity, then the shortest way out); on every covered face, the median gap along the face's
  normal (ports left out) in the range: PLA and PETG slip 0.15 to 0.45 mm, snug 0.05 to 0.25, press
  0.1 interference to 0.05; TPU 0.3 interference to 0.1 gap.
- covered and open: 80% of a covered face has the part within the most gap plus 1 mm; at most 10% of
  an open face has the part within 20 mm.
- access: every feature on a covered face has its plug (or opening) clear as a box from the product's
  face out through the wall plus 3 mm (manifold3d intersection, at most 0.5 mm3).
- retention: the type matches; a snap arm's strain 1.5 y t / L^2 is at most PLA 2%, PETG 3%, TPU 20%;
  a friction gap is in the fit range; a screw hole matches the EJOT PT pilot table (PLA 0.80 d, PETG
  0.75 d) or the heat-set insert hole (M2 3.2, M2.5 3.6, M3 4.0 mm), within 0.15 mm.
- strength (with `load_n`): 6 F arm / (b h^2) at most the printed yield (PLA 50, PETG 47 MPa), halved
  across layers, over the spec's safety factor; TPU is not checked.
- walls: the thinnest wall at least 1.2 mm; printable: stone's slicer pass is clean.
- sources: every body size and feature has one.

The sources of every material number are in the comments of `engineering_grade.py`.
