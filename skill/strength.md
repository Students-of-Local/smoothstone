# Will it hold: stone strength

Run this card when a part carries a load: a hook, a bracket, a shelf, a handle, a mount.
`stone strength` puts the load on a model of the printed part and says if it breaks, where, and
what helps most.

## 1. After stone build, say the load, where it goes, and how it is held

```
stone strength load=20N at=tip dir=down fixed=bottom
```

- `load=`: the weight, like `20N`, `2kg`, `500g` or `5lb`. Use what the person said; if they gave
  none, ask how heavy the thing is.
- `at=`: where the load goes: `tip` (the end farthest from the hold), `top`, `center`, a face
  (`bottom back front left right top`), or a point `x,y,z` in mm.
- `dir=`: the way the load pushes: `down up left right front back`, or an axis like `-y`.
- `fixed=`: what holds it still: a face, `holes` (screws through its holes), a point `x,y,z`, or a box
  `x0,y0,z0,x1,y1,z1`. Join two with `+`, like `fixed=holes+back`.

`at`, `dir` and `fixed` always use the STL's own axes: `down` is -z, `bottom` is the lowest z, whatever
`orient=` says. A part that prints on its side is used turned: the hook recipe prints on its side,
so its "down" on the wall is `-y`.
The answer says which holes it held and where. A hole the load hangs from must not be one of them:
then use a box or a point instead of `holes`.

Optional: `material=PETG`, `walls=2`, `infill=15`, `orient=x` (which part axis points up on the
bed), `sag=2` (the deflection limit in mm). The material starts as the job's own pick.
`walls=` adds lines around each layer only. Top and bottom layers stay the slicer's.

## 2. Read the answer

- Safety factor: how many times the load the part takes before it breaks or bends too far.
  2 or more is fine. Under 2 is little margin. Under 1 it fails.
- Breaks between layers: printed layers pull apart before the plastic does. Rotating the part
  so the load runs along the layers often fixes this.
- Buckles: a thin post or plate pushed toward its hold bows out sideways before the plastic breaks.
- Deflection: how far the loaded spot moves.
- What helps most: single changes, best first, each with the safety factor it reaches.

The NEXT line re-runs the check with a print change that reaches 2, or asks the person when only
a thicker part or a lighter load would do. A thicker part is a recipe change: `stone set`, then
`stone build`, then `stone strength` again.
When the answer says "This holds only for a print with ...", tell the person those settings: the
slicer does not know them. "not sure, ..." means the model cannot judge it yet: run NEXT.

The numbers and every assumption are in build/strength.json. The "Picture:" file shows the part from above, the
front and the right, red where it is nearest to breaking, the worst spot ringed. Look at it before you describe it.

This is a model, not a break test: real prints vary with the printer, the temperature, and the
moisture in the filament. A load held for weeks creeps, more so when warm.

## Example

```
$ stone strength load=20N at=tip dir=-y fixed=holes
Part: part.stl, 44 x 77 x 20 mm, PLA, 2 walls, 15% infill, as printed.
Load: 20.0 N (2.04 kg) at the tip (13, -34, 10) toward -y; held at the 2 holes at (-18, 8, 10), (-18, 25, 10).
Safety factor 2.0: fine (weakest: bends too far: 1.1 mm, limit 2.3 mm).
Deflection 1.14 mm at the tip (limit 2.3 mm).
Stress: peak 15.1 MPa (99.5th percentile 11.2, smoothed max 11.8), 7.1 MPa pulling or sliding layers apart; PLA holds 35 along, 31 between layers.
What helps most: 4 walls (2.7).
Model: 104,903 voxels of 0.556 mm, solved in 30 s; linear, untested by a real break; assumptions in strength.json.
NEXT: none, the part is ready
```
