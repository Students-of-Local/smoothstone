# smoothstone, tier L (large models)

You can drive stone like tier M, and you can also write new recipes when no recipe fits.

## Rules
- Use an existing recipe when one can make the part the request asks for, even if a new recipe
  could do more; it is tested and prints. Search stone recipes by the part's kind (box, hook,
  plate, case), not by what goes in it.
- A new recipe is a folder recipes/<name>/ in the job folder, written with your file tools: recipe.scad
  and recipe.json, built with the helpers in recipes/lib/stone.scad and BOSL2 (vendor/BOSL2). Read
  the closest catalog recipe first and copy its pattern; never change a catalog recipe.
- Every recipe prints without supports: flat base, no overhang past 45 degrees, walls of at
  least 1.2 mm, top edges rounded or chamfered, holes sized for real screws.
- Sizes: work out the room inside first, then add every wall and floor, and anything that reaches
  inside, such as a lid's lip (a box's lip_h takes that much of its inside height: a 30 mm stack on
  a 2 mm floor under a 5 mm lip needs h of at least 37). An opening the request sizes keeps that
  size and shape; a flat top up to 15 mm wide prints as a bridge.
- Check every new recipe: stone show <name>, stone set <name> with the request's sizes, stone build.
  Its defaults and every example must build and pass too (the grader runs tools/sheet.py on it).
- A refused command refuses only that command: stone commands still run, so go on and build with stone.
- Open views.png and look at every panel before you stop; if a panel shows a fault, say what and where, and fix it.
- Stop when the request's part is built with stone, the build says Part ready, and the checks below that fit the part
  (load, heat, fit, ledge) ran, or the person can't give the number: ask once, then reply that the part is built and
  that is not checked.
- Colors: if the build says NEXT: stone colors, run it, then run the NEXT line it prints; it already follows the colors in the request. Parts go by name: jacket=black rest=white. You may change the mapping after looking at regions.png, and check colors.png after it.

## Research
- Follow research.md in full: maker drawings and datasheets first, a second source for every
  fit-critical number, clearances, a fit-test slice, a look list for likeness, and a real
  museum scan before generating any famous artwork. Save every fact with stone note.

- A product the catalog lacks: its size comes from the maker's spec page or the person's ruler,
  never a guess. Ask when you cannot cite one, then stone product add "<name>" --size W D H
  --source "<URL or measured by the person>" (--round, --corner-r, --open as the source says);
  every product recipe takes it like a catalog product.

## Figures and image models
- The figure recipe takes a unit-height mesh (image_kind "figure"). stone builds it from photos
  with src/smoothstone/figure.py: describe (LFM3-VL-2B), style (FLUX.2 klein 4B), lift
  (tools/lift), repair. Every step is cached in the job's images/figure folder.
- You may pass your own mesh: stone set figure figure=path/to/unit_height.stl.

## Found models
- For a landmark, run stone landmark "<name>" first. Follow its NEXT line.
- To find or download a model, run stone models "<landmark>" instead.
- When stone landmark refuses one, or a shape of it is missing, follow landmarks.md: write the shapes and facts it lacks
  as JSON, each with its source (docs/REFERENCE_PARTS.md), and build with stone landmark "<name>" --refs <file>.
- stone models "<landmark>" searches Printables, Wikimedia Commons, and Sketchfab only with the
  person's own key in STONE_SKETCHFAB_TOKEN. --take <n> downloads, repairs (src/smoothstone/models.py)
  and makes it the job's part; stone build scales, measures thin features, cuts it to the bed with
  pins and checks each part (src/smoothstone/modelprint.py). build/model/parts.json has every cut,
  pin and check. Never pass a found model off as stone's own: credits.txt goes with it.

## Before it prints, and when a print fails
- A part that carries a load, lives in heat, fits something or has a ledge: run stone strength, stone heat,
  stone fit or stone supports before you call it done, with the person's own load and place. Ask for a number you
  don't have. Read the command's card for what it models, and pass on the limits it prints.
- A change that helps (walls, infill, orientation, material) is a slicer setting or the person's choice: tell them
  which one the answer depends on. A thicker part is a recipe change: stone set, build, run the check again.
- stone timelapse shows the print and its time; stone timelapse --fail shows the predicted failure, a model and not
  a recording.
- A failed print: doctor.md. Name no cause before stone does: when they answer its question, run
  stone doctor answer "<their answer>" and say nothing about what it means, not even probably. Give stone doctor
  the person's words (and what you see with --image and --looks), let it rank the causes for that printer, read every SAFETY line, and record what worked. Never start, pause or
  cancel a print.
- When NEXT says ask the person, ask that question in its own words and stop: no command in the same turn.

## Recipe format
- recipe.scad: one assignment per parameter at the top, with a comment that gives the unit, then
  the geometry. Base on z = 0, centered in X and Y, millimeters. stone passes values with -D.
- recipe.json: name, title, summary, tags, tier, params (name, type, default, min, max, unit,
  help; choices for choice; image_kind and required for image), dims, max_bodies,
  max_overhang, min_wall, fix (which parameter each failing check should change), examples.
- Build anything that sits on the bed with soft_extrude, soft_slab or bed_chamfer() from
  lib/stone.scad, so it steps in 0.4 mm at the bed (the bed_edge check). Text echoes
  stone_text and a guard grille echoes stone_grille, so the text and finger_gap checks can
  name the setting to change (docs/DESIGN.md, Print checks).
- Give the defaults a part someone would be glad to print, and add two or three examples that
  show the range.
- Write help text a 1.7B model can act on: plain words, the unit, what the number does.
