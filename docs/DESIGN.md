# smoothstone design

Small local models make print-ready 3D parts that look like a strong designer made them, from a
text request or a reference image, and keep working after their context is compacted.

## What round 1 taught (lfm3-3d-skill, 2026-11-12 to 13)

- LFM3-1.7B asked to write OpenSCAD from a spec: 0/5 on every part. It reads the spec, then thinks
  until the step budget runs out (16,000 tokens over 10 steps, no file).
- The only thing that worked: fill 6 numbers into a tested OpenSCAD body (drafts 4 and 6, 2/5).
  Failures were geometry doubts, syntax slips in the copied body and long thinking.
- So the small model must never write geometry code. It picks a recipe and fills typed parameters,
  and a tool does everything else and tells it the next step.

## Pieces

```
smoothstone/
  skill/SKILL.md            router: which tier card to follow, 20 lines
  skill/tiers/S.md          tiny models (about 3B and under): pick a recipe, fill parameters
  skill/tiers/M.md          mid models (4B to 30B): combine recipes, add labels and patterns
  skill/tiers/L.md          large models: write OpenSCAD against the library, add recipes
  stone/                    python package, CLI `stone`
  recipes/<name>/recipe.scad, recipe.json, example.json, preview.png
  vendor/BOSL2/             BSD-2, pinned commit
  evals/                    specs, sealed held-out set, harness adapters, results
```

## The `stone` CLI is the memory

All state lives in the job folder (default `./stone-job/`). Every command prints a short result and
ends with exactly one line `NEXT: <command>`. A model that lost its context runs `stone status` and
gets: the request in the user's words, the recipe and parameters so far, the last build result and
the NEXT line. Nothing the model needs lives only in its context.

| Command | Does | Ends with |
|---|---|---|
| `stone status` | prints brief, plan, last result | NEXT |
| `stone new "<request>" [--image PATH]` | makes the job, saves the request; with an image, runs `stone image` | NEXT: stone recipes |
| `stone recipes [words]` | menu, ranked by the words or the brief: name, one line, sizes | NEXT: stone show <best> |
| `stone show <recipe>` | every parameter: name, type, default, range, unit, one-line meaning; one example `stone set` line | NEXT: stone set ... |
| `stone set <recipe> k=v ...` | writes plan.json; validates names, types, ranges; unknown name lists the valid ones | NEXT: stone build |
| `stone build` | plan -> params file -> OpenSCAD -> STL -> checks -> preview PNG | NEXT: stone done, or the one parameter to change |
| `stone check [file.stl]` | print checks on any STL | NEXT |
| `stone image PATH` | reference image -> silhouette SVG and height PNG in the job, aspect ratio, suggested recipes | NEXT |
| `stone done` | final summary, paths to STL and preview | (none) |

Rules for every message the tool prints: under 25 lines, plain words, no stack traces (log them to
`stone-job/log.txt`), numbers with units. Error lines start with `FIX:` and name one change.

## Recipes

A recipe is a tested, parametric, good-looking part that prints without supports by construction.

- `recipe.scad`: `include <params.scad>` (written by `stone build`) then geometry. May use BOSL2.
  Base on z = 0, centered in X and Y, millimeters, `$fn` set from a `quality` parameter.
- `recipe.json`: `{"name", "title", "summary", "tags": [...], "tier": "S", "params": [{"name",
  "type": "number|int|bool|text|choice|image", "default", "min", "max", "choices", "unit", "help"}],
  "derived_checks": [...]}`. Every parameter has a default, so `stone set <recipe>` with nothing
  builds a good part.
- Design bar: fillets or chamfers on outside edges, no knife edges, walls at least 1.2 mm (3
  perimeters at 0.4 mm), first layer flat, overhangs at most 45 degrees or chamfered, text at least
  6 mm cap height and 0.8 mm deep, holes sized for real screws (M3 = 3.4 mm clearance).
- Each recipe ships a test: defaults and every `example*.json` compile, pass `stone check`, and match
  their own dimension claims.

First library (the round 1 parts plus parts people show off):
`fan_guard` (rings and spokes, honeycomb, spiral), `panel` (faceplate: cutouts, holes, rounded
corners, chamfer, label), `cable_comb`, `vase` (spiral vase mode: twist, ribs, waves, polygon),
`planter` (drain holes, faceted or ribbed, saucer), `gridfinity_bin` (grid units, height units,
dividers, label tab, stacking lip), `box` (sliding or snap lid, screw bosses, vents),
`phone_stand` (angle, cable slot, lip), `hook` (wall hook, screw holes, filleted arm),
`spur_gear` (BOSL2), `sign` (raised text, border, mounting holes),
`keychain` (from text or an image silhouette), `cookie_cutter` (image silhouette),
`lithophane` (image -> flat or curved panel, frame), `relief` (image -> plaque).

## Print checks (`stone check`)

Generic, from the STL, with trimesh: compiles, watertight, one body (unless the recipe allows
more), positive volume, fits the bed (default 260 x 260 x 260 mm, Creality K2), resting on z = 0
with a first-layer contact area of at least 15% of the footprint or 200 mm2, thinnest wall
estimate at least 0.8 mm (ray casting from sampled surface points), unsupported overhang area
under 5% of surface (faces steeper than 45 degrees from vertical facing down, not on the bed),
no part above 260 mm. Recipe `derived_checks` add dimension claims (bbox within 0.3 mm, hole
count, etc.). Output: one line per check, PASS or FIX with the parameter to change.

## Tiers

- S (about 3B and under, text only): never writes OpenSCAD and never reads recipe files. Steps:
  `stone status`, `stone recipes`, `stone show`, `stone set`, `stone build`, change one number on
  FIX, `stone done`. The card is under 40 lines and says to keep thinking to a few lines.
- S-vision (small VLM): the same, plus it looks at the reference image to pick the recipe and sizes.
- M: may set several recipes in one plan (`stone set panel ... + sign ...` is a union placed by
  offsets), and may pass `custom.scad` snippets that use only library modules.
- L: writes OpenSCAD with BOSL2 and the library modules, and can add a recipe with its test.

The tier comes from `STONE_TIER` or `stone.toml`; `stone status` prints the tier card's 5 rules
again, so the tier survives compaction too.

## Compaction

The eval harness can force a compaction: after step k it drops every turn except the system
prompt, the skill and the user message, and adds "Your context was compacted. Run stone status."
Done means the pass rate with a forced compaction at step 3 is within one run of the rate without.

## Evaluation (round 2)

- Same settings as round 1 harness v3: 10 steps of 2048 new tokens, temperature 0.1, top_k 50,
  repeat_penalty 1.1, thinking on, 5 seeds.
- Tuning set: fan guard, cable comb, faceplate (round 1 specs; their failures were seen).
- Held-out set: written and sealed (sha256 in LOG.md) before any tuning, never run until the
  skill is frozen: 5 new requests, 2 of them from reference images.
- A run passes when `stone check` passes and the spec's own dimension checks pass.
- Conditions: LFM3-1.7B alone (round 1 harness), LFM3-1.7B + tier S, LFM3-1.7B + tier S with a
  forced compaction, LFM3-VL-2B + S-vision on the image requests, LFM2.5-8B-A1B + tier M, Claude
  (tier L) reference.

## Done

1. `stone` CLI and print checks with tests (`uv run pytest` green).
2. At least 12 recipes, each with a render looked at, defaults and examples passing checks.
3. Tier cards S, M, L and the router, each loaded by a real run.
4. Held-out: LFM3-1.7B + tier S at least 4/5 on each held-out request, and within one run of that
   with a forced compaction. Every number from logged runs.
5. Image references: at least 2 held-out requests from images pass for the S-vision condition.
6. README with renders of real model outputs, install for Claude Code, Codex, pi and llama.cpp,
   results table, MIT license (BOSL2 stays BSD-2).
7. Repo baney75/smoothstone pushed, CI green.
