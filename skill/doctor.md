# stone doctor: a print failed

Use this when someone says a print failed, shows a photo of a failed print, or asks why a print looks wrong.

## Rules

1. Run the NEXT line stone prints. Nothing else.
2. If NEXT says `ask the person`, write that question as your reply and stop. Wait for the answer.
3. Put the person's own words in quotes. Do not guess the cause for them.
4. Read every SAFETY line out loud to the person before they touch the printer.
5. stone never starts, pauses or cancels a print. Neither do you.
6. Lost track? Run `stone status`.

## Steps

1. Know the printer once: `stone printer`, then `stone printer set <id>`.
2. Describe what you see: `stone doctor "<what the print looks like>"`.
   With a photo: add `--image photo.jpg`. From the printer camera: add `--camera`.
   Photo but no words? stone saves the photo and NEXT asks you to look at it and describe it.
   You can see the photo? Run `stone doctor looks`. It lists each failure id and how it looks.
   Pick the ids that match the photo, likeliest first, at most 3. Add them with `--looks`:
   `stone doctor "<what you see>" --looks bed_adhesion,blob_on_nozzle`.
   Write the words too. stone weighs both.
   If you cannot see images, ask the person what the print looks like. Then leave out `--looks`.
3. Ask the one question in NEXT. Then: `stone doctor answer "<their answer>"`.
4. When NEXT says `stone doctor try <cause>`, run it and tell the person the steps.
5. If it worked: `stone doctor fixed "<what worked>"`. If not: the NEXT line names the next `stone doctor try`.
6. Sharing is optional, and stone sends nothing. First ask whether to share. On yes, `stone doctor share` prints
   every line that would go public, the photo path and a prefilled GitHub issue link. Read the person every line,
   show them the photo, and give them the link and the photo path. They open the link, attach the photo, read it
   there and submit it themselves. Then ask whether they submitted it and run what the answer names:
   `stone doctor share done` or `stone doctor share no`.

Words for each failure: `stone doctor looks`.

## The owner's case (Creality K2, PLA, IR camera photo)

The photo shows a flat part lying tilted on the plate with strands under its edges, and a lump of
plastic on the nozzle. The owner said: "this was likely due to the plate needing to be cleaned but
giving differentials also helps".

```
$ stone doctor --image k2.jpg
Case 20261124-012644, Creality K2
Photo saved (EXIF removed, at most 1280 px): stone-job/doctor/20261124-012644/photo.jpg
Look at it: describe what you see, and pass the ids that match it with --looks (each id and its look: stone doctor looks). ...
NEXT: stone doctor "<what you see in stone-job/doctor/20261124-012644/photo.jpg: the part, the plate, the nozzle>" --looks <ids from stone doctor looks that match, likeliest first>

$ stone doctor "flat plate print came loose and lies tilted on the bed with loose strands trailing from under its edges; a big lump of plastic is stuck around the nozzle and heater block. this was likely due to the plate needing to be cleaned but giving differentials also helps" --looks bed_adhesion,blob_on_nozzle --material PLA
Case 20261124-012644, Creality K2, PLA, seen: bed_adhesion, blob_on_nozzle
Most likely: Part came loose from the plate (bed_adhesion)
Also check: blob_on_nozzle: a loose part often ends up stuck on the nozzle; look for a lump around the heater block
Also check: first_layer: a first-layer problem leaves the part stuck but with gaps or ridges
Also check: warping: warping lifts only the corners while the middle stays stuck; a loose part came off whole
Cause 1: Oil from fingers, dust or old glue on the plate (plate_contaminated) 58%
Cause 2: First layer too far from the plate (leveling or Z offset) (first_layer_too_high) 17%
Cause 3: Bed too cold for the filament, or the slicer's plate or filament setting does not match (wrong_settings) 12%
Plate: PEI double-sided frosted (textured) flexible plate, 270 x 293 mm
Clean it (maker's steps): Hand sweat is the first cause Creality lists: wash the plate with dish soap and water; ...
SAFETY: Heat the hotend to about 30 C above the print temperature (PLA: about 250 C) before you pull plastic off; ...
SAFETY: The thermistor and heater wires are probably inside the blob: pull gently and never yank.
NEXT: ask the person: Wet the cold plate with a little water: does the water bead into drops, or spread as a thin film? (beads / spreads as a film / can't tell) Then: stone doctor answer "<their answer>"

$ stone doctor answer "the water beads up"
Answer taken as: beads.
Cause 1: Oil from fingers, dust or old glue on the plate (plate_contaminated) 71%
NEXT: stone doctor try plate_contaminated

$ stone doctor try plate_contaminated
1. Wash the cold plate with warm water and plain dish soap (no lotion or oils), scrub, rinse, dry with a paper towel.
2. Do not touch the print area afterward; hold the plate by its edges.
3. Use the plate the slice expects and a thin glue stick layer if the maker suggests it for this filament.
NEXT: ask the person: did that fix it? If it did: stone doctor fixed "<what worked>"; if not: stone doctor try first_layer_too_high

$ stone doctor fixed "washed the plate with dish soap and water"
NEXT: ask the person: Share this fix (photo, printer, material, what you saw and what fixed it) publicly on GitHub so other agents learn from it? The photo and words become public under smoothstone's MIT license. (yes / no) yes: stone doctor share. no: stone doctor share no

$ stone doctor share
Ready to share case 20261124-012644. stone sends nothing. This is all that would go public:
Photo: stone-job/doctor/20261124-012644/share/photo.jpg (EXIF removed, at most 1024 px)
...
Prefilled issue link:
https://github.com/baney75/smoothstone/issues/new?template=print-fix.yml&title=Fixed%3A+bed_adhesion+on+creality_k2&...
NEXT: ask the person: <read them the lines above and show them the photo>. To share it, open the link above, attach the photo, read it there and submit the issue yourself; stone sends nothing. Did you submit it? (yes / no) yes: stone doctor share done. no: stone doctor share no

$ stone doctor share done
Thanks. A maintainer reads the issue and adds the case; then stone doctor ranks this cause higher on this printer.
NEXT: none, the print problem is fixed
```

Lines marked `...` are cut here; stone prints them in full.
