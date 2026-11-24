# stone supports

Tells, before printing, if the part needs supports, where, and why. It does not change the part.

## When to run it
- The person asks "does this need supports?", "will this print?", or about overhangs or bridges.
- After stone build, or on any STL: stone supports <file.stl>

## Rules
- Run: stone supports (the built part) or stone supports <file.stl>.
- Read the first line: "Supports needed: yes" or "Supports needed: no".
- Tell the person each region in plain words: the height (z), and why:
  "starts in mid air", "hangs past the layer below", or "bridge ... long, over 10 mm".
- "Tipping: RISK" means a tall thin part can fall over: tell them to turn on a brim.
- The Orientation line is advice. stone never rotates the part. Tell the person; they turn it in
  the slicer if they want.
- The picture is build/supports.png: red needs support, yellow is a bridge that prints fine.
- Then run the NEXT line it printed.

## What the words mean
- island: a piece with nothing under it. Needs support.
- ledge: a layer reaches more than 0.35 mm past the one below (steeper than 60 degrees from
  vertical, OrcaSlicer's 30 degree threshold). Needs support.
- bridge: held on two opposite sides. Up to 10 mm prints without support (OrcaSlicer's max
  bridge length). Longer needs support.

## Example
Request: Will this T bracket print without supports?
stone supports t_bracket.stl ->
  Supports needed: yes (2 regions)
  1. z 10.0 mm at x 5.8 y 3.0, 70 mm2, worst 90 deg: hangs past the layer below
  2. z 10.0 mm at x 24.1 y 3.0, 70 mm2, worst 90 deg: hangs past the layer below
  Overhang area by angle from vertical: 45-60 deg 0 mm2, 60-75 deg 0 mm2, 75-90 deg 144 mm2
  Support: about 1.4 cm3 of space under the regions, about 0.2 cm3 of plastic at 17% fill
  Tipping: low, stands on its own (height 13.0 mm, base 6.0 mm wide)
  Orientation: upside down needs 0.0 cm3 of support space instead of 1.4 cm3, first layer 180 mm2
  (advice only: turn it in the slicer)
  NEXT: none, the supports check is done
Reply: Yes, it needs supports under both arms of the T, 10 mm up. Printed upside down, on the
flat bar, it needs none. Turn it over in the slicer, or turn supports on.
