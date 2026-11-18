---
name: smoothstone
description: Make 3D printable parts that look designed, from a text request or a picture, by choosing and setting tested parametric recipes with the stone CLI. Works for small local models (tier S), mid models (M) and large models (L), and keeps its state on disk so it survives context compaction. Use when someone asks for a printable part, an STL, a 3D model for a printer, or something to 3D print from a photo or drawing.
---

# smoothstone

stone turns a request into a print-ready STL. The model picks a recipe and sets its numbers;
stone builds the part with OpenSCAD, checks that it prints (watertight, one piece, flat base,
walls, overhangs, size), and keeps every step in a job folder. Every stone message ends with one
line, NEXT: <command>, and `stone status` repeats it, so a model that loses its context goes on
from where it was.

## Pick your tier and follow that card

- Tier S, about 3B parameters and under: tiers/S.md
- Tier M, about 4B to 30B: tiers/M.md
- Tier L, frontier models: tiers/L.md

Set the tier with STONE_TIER=S|M|L or `tier = "S"` in stone.toml. stone status prints the
card's rules on every call, so they come back after a compaction.

## Research first

When the request names a real thing (a phone to fit, a person to look like, a famous statue),
follow research.md before stone set: exact sizes from the maker's own drawings, a list of what
makes a person recognizable, a real museum scan before a generated one. Keep each fact and its
source with `stone note "<fact>, <source>"`; stone status shows the notes again after a
compaction. Never make up a size a part has to fit.

## Pictures

`stone new "<request>" --image photo.png` (or `stone image photo.png`) traces outlines for
keychains, cookie cutters and signs, and makes a height map for lithophanes and reliefs.

## Figures of people, pets and things

The figure recipe makes a mini figure on a round plinth with a name on it. Ask for it plainly:
`stone new 'A mini figure of Jensen Huang, 90 mm tall, with "JENSEN" on the base'`. With no
photo, stone build says to run `stone find "<name>"`, which downloads free-licensed photos from
Wikimedia Commons and writes credits.txt. With your own photo, run `stone image <photo>` instead.
Then stone build runs three local models (describe, style, lift) and the print checks. Run
tools/figure/setup.sh once first.

## Measuring from a photo

When a photo has a ruler, a bank card or a US quarter beside the object, `stone measure
<photo>` (with `--ref card` or `--ref coin-us-quarter` for those) finds the object's real size,
and stone show fills it in. `--known 120mm` works when you know the long side.

## Start

stone status
