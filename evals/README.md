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
   "body": {"w": 85, "d": 56, "h": 17, "corner_r": 3, "profile": [[0, 0], [15.9, 0], "...", [0, 7.98]]},
   "features": [{"name": "usb_c_power", "kind": "port | button | switch | vent | lens | screen | led | slot | hole",
                 "face": "+x | -x | +y | -y | +z | -z", "c": [u, v], "size": [w, h], "plug": [w, h],
                 "shape": "rect | circle", "depth": 14.0, "plug_note": "why no plug size", "pad": [6, 6],
                 "source": "https://... and where"}]},
 "expect": {"kind": "case | holder | mount | adapter | replacement", "material": "PLA | PETG | TPU",
            "fit": "slip | snug | press", "retention": "friction | snap | screw | none | any",
            "load_n": 20, "load_dir": "-z", "support": "-z", "safety": 2,
            "covered": ["faces the part wraps"], "open": ["faces that stay clear"],
            "face_gap": {"+z": [0.0, 1.0]}, "min_gap": {"-z": 2.5}, "min_gap_note": "why",
            "attach": {"face": "+z", "against": "the desk", "screw": "M4", "min": 2, "source": "..."},
            "part_holes": [{"name": "vesa_75", "axis": "-z", "d": 4.5, "pattern": [[-37.5, -37.5], "..."],
                            "source": "..."}]}}
```

The product frame: x is width, y depth, z height as the part holds the product, origin at the body's
min corner, so the body is the box [0,w] x [0,d] x [0,h] with its four vertical edges rounded by
`corner_r`. A feature's `c` is its center on its face, mm from the face's lower-left corner as seen
from outside the product; `size` is its opening and `plug` (optional) the plug or fingertip that must
pass through the part. A port, button or switch with no published plug size says why in
`plug_note`, and only its opening is checked; a button's plug is a fingertip (e01: Ø10, our lower
bound, from the least fingertip pushbutton diameter in MIL-STD-1472F Figure 12, which sizes the
button, not a finger). A hole's `pad` (optional) is the area around it a standoff may bear on, left
out of the fit numbers like the hole itself. `shape: circle` makes the feature round, its size and
plug a diameter. `depth`
(optional) is how far out from the face the path must stay clear, when the maker publishes one.
A `hole` feature is a mounting hole the part screws through. A face in neither `covered` nor `open`
is not checked for coverage, but no part may sit inside the product anywhere.

A round body may give its `profile`: [r, z] points from the axis at the bottom, out and up its side,
back to the axis at the top, revolved about the middle of the w x d box. Then the product is that
shape, not the box (e04's AirTag dome, from Apple's Detail A).

`support` (default `load_dir`): the face the product bears on, which the part must hold up without
covering it. `face_gap`: a face's own gap range when it carries no fit (a shaft's end), on a covered face or the support face (a board on standoffs that rise into the box from below its lowest underside part, e01).
`part_holes`: a hole pattern the part itself must carry, on the product's `axis` face side.
`min_gap`: per face, how far the part must stay off it outside its features (e08: 2.5 mm under a
board whose through-hole leads stand out), with why in `min_gap_note`.
`attach`: how the part is fixed to a desk or wall: at least `min` screw holes through the part's wall
on the `face` side, each an ISO 273 clearance hole for `screw`. A spec with `attach` has `load_n` too,
since the part hangs from it (e05, e07).
Each number's source (`body_sources`, a feature's `source`) cites the URL it comes from;
`product.sources` lists the documents and ties none of them to a number.

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
- `retention`, by type: `snap` {y the catch's overhang past the arm's face toward the product, t arm
  thickness at the root, L arm length to its tip, w arm width, at the root point where the arm joins
  the part, t_dir, L_dir}; `friction` {gap, mm, negative for interference}; `screw` {size M2 | M2.5 | M3, method
  self_tap | insert | through (a bolt and nut, or a bought standoff), hole_d, holes [{at the mouth,
  axis into the part}]}; `none` {}.
- `load` (when the spec has `load_n`): the force in N, its direction, and the critical section as a
  rectangle b x h mm whose moment is F x `arm`, whether the stress runs across the layers, and
  `section` {at a point in it, b_dir, h_dir along the load}.
- `attach` (when the spec has it): `holes` [{at the mouth, on the side that goes against the desk or
  wall}].
- `part_holes` (when the spec has them): per pattern, `c` its center on the part's face and `u` its
  first axis.
- `sources`: for w, d, h, corner_r, a profiled body's `profile`, and every feature by name. From text
  or a model number, a URL the spec cites for that number in its own body or feature source (the
  part cannot have measured the product); from a photo, any URL with a host, "calipers", or "photo
  with <the reference in the photo>".

Points and directions are in the part's STL coordinates: the snap arm, the holes and the section are
measured in the mesh, so engineering.json cannot claim a part it does not have.

`engineering_grade.py` checks, each failure a line with its measured number:

- fit: the product box sampled at 2 points per mm2 and placed by the frame; no sample inside the part
  (ray parity, then the shortest way out); on every covered face, the median gap along the face's
  normal (ports left out) in the range: PLA and PETG slip 0.15 to 0.45 mm, snug 0.05 to 0.25, press
  0.1 interference to 0.05; TPU 0.3 interference to 0.1 gap.
- covered and open: 80% of a covered face has the part within the most gap plus 1 mm; at most 10% of
  an open face has the part within 20 mm.
- support (with `load_dir` or `support`): the part within the most gap plus 1 mm under at least 3 of
  the face's 4 quarters, 4 mm2 in each, so the product cannot drop or tip out.
- access: every feature but a hole, on any face, has its plug (or opening) clear as a box, or a
  cylinder for a round one, from the product's face out through the wall plus 3 mm, or its `depth`,
  or 20 mm on an open face (manifold3d intersection, at most 0.5 mm3). A part that is not a closed
  solid fails here, since an open mesh reads as empty.
- clear (with `min_gap`): no spot of that face, outside its features and pads, has the part nearer
  than the gap.
- holes: each `hole` feature has a bore (the screw's hole_d, or the feature's size, less 0.15 mm a
  side) clear 3 mm into the part and the part around it to bear on; each `part_holes` hole is a bore
  clear through the part with the part around it.
- attach (with `attach`): at least `min` distinct holes, each with its mouth on the part's outermost
  plane on that side, a bore of the ISO 273 fine hole less 0.15 mm clear through the wall there (its
  thickness read beside the hole), the part around the coarse hole plus 0.15 mm, and room for the
  screw's head inside: an M4 pan head (Ø8.2 x 3.1 mm, the larger of DIN 7981 ST4.2 and ISO 7045 M4)
  on the part's face beside the hole (the wall's inner face or a counterbore's floor) must meet
  neither the product nor the part, or a countersink must hold an ISO 7046 flat head (Ø8.4, 90
  degrees) flush with the wall's inner face. The holes that count spread at least a quarter of the
  part's largest extent across that face, so it cannot turn about them.
- retention: the type matches; a snap arm's strain 1.5 y t / L^2 is at most PLA 2%, PETG 3%, TPU 20%;
  a friction gap is in the fit range; a screw hole matches the EJOT PT pilot table (PLA 0.80 d, PETG
  0.75 d), the heat-set insert hole (M2 3.2, M2.5 3.6, M3 4.0 mm), or for `through` the ISO 273
  clearance hole from fine to coarse (M2.5 2.7 to 3.1 mm), within 0.15 mm. In the mesh: the arm is t
  thick at its root and runs L from it within 0.2 mm either way; 0.5 mm behind the root the part is
  wider than w (the arm joins it there); from 5% of its length every 0.5 mm to 0.25 mm short of its
  tip it is no wider than w (free at its sides); and in its outer half it stands out y past its root
  face on the side the product is on, within 0.2 mm (its catch; a bump on the far face hooks nothing;
  the overhang is at least the deflection, so the strain errs high). Each screw hole is a bore 2 d
  deep, or for `through` clear through the wall at the hole (its thickness read beside the hole, not
  on to a lid past it), with the part around it. Every input is a finite number above 0.
- strength (with `load_n`): 6 F arm / (b h^2) at most the printed yield (PLA 50, PETG 47 MPa), halved
  across layers, over the spec's safety factor; TPU is not checked. b and h are measured through
  the section's point, and the smaller of the declared and measured counts. h_dir must lie along the
  load and b_dir square to it. The arm is measured as the moment the section carries over F: each
  bearing spot of the product carries an equal share of F, at its distance from the section along the
  beam's axis (b_dir x h_dir). On each side of the section's plane only the piece of the part the
  section belongs to counts, so a lip under the far side of the product loads its own root, not this
  one. With `attach` each share goes to its nearest screw hole square to the load and counts only when
  that screw is not on its own piece, both sides added; without, the larger side counts. A declared
  arm shorter than the measured one fails and the longer counts, and a section that carries none of
  the load fails, since it is not the critical one. The stress is across the layers when the beam's
  axis is more than 15 degrees out of the STL's xy plane, whatever `across_layers` says.
- walls: the thinnest wall at least 1.2 mm; printable: stone's slicer pass is clean.
- sources: every body size and feature has one, as above.

The sources of every material number are in the comments of `engineering_grade.py`.
