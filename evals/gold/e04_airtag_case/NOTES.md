Reference design by GPT-6.1 Sol, smoothstone gold set. Copied as made.

# AirTag split-shell case

A one-piece PETG case for the 2021 Apple AirTag. Two half shells wrap the back,
sides and dome rim. An integral C flexure joins them at the rear; a releasable
cantilever latch closes the front. The opening motion is deliberate: the tag
does not have to stretch a rigid retaining ring. The rear loop is the assembly
flexure, with no rated keyring load.

The delivered STL is the closed, unloaded state, in millimeters. Its measured
size is **35.37 x 49.90 x 10.59245 mm**, volume 3497.18222 mm3. It is one closed,
consistently wound solid. No external load, attachment screws or mounting-hole
pattern is requested, so none is claimed in engineering.json.

## Product and fit

All product numbers are copied from `evals/engineering/e04_airtag_case.json`.
The source is [Apple's AirTag dimensional drawing, page 2](https://developer.apple.com/download/files/accessories/dimensional-drawings/airtag.pdf).

| Number | Source key | Use |
| --- | --- | --- |
| 31.87 mm width and depth | product.body.w, product.body.d | Diameter of the enclosing round body |
| 15.935 mm corner radius | product.body.corner_r | Round body, half its diameter |
| 7.98 mm height | product.body.h | Full dome height |
| All 24 radius/height pairs | product.body.profile | Exact enclosing lower cylinder and published dome profile |
| Center 15.935, 15.935 mm | product.features[0].c | Speaker opening axis in the product frame |
| Circular diameter 25.75 mm | product.features[0].size and shape | Speaker keepout |

The product's minimum corner maps to STL (-15.935, -15.935, 1.75). The dome faces
+z. Its axis maps to x=0, y=0. The published profile is revolved directly; the
case cavity offsets each segment outward by **0.15 mm along its normal**.
Adjacent offset lines meet at their intersection. This avoids both cylinder-only
fit assumptions and an arbitrary vertical gap on a sloping dome.

The 0.15 mm clearance is the midpoint of the grader's PETG snug band,
0.05 to 0.25 mm per side. The floor is 1.60 mm thick, so the tag bottom is
1.60 + 0.15 = 1.75 mm above the bed. The shell has 1.60 mm nominal normal wall
thickness: four nominal 0.4 mm extrusion widths and 0.40 mm above the 1.2 mm
engineering floor. The outer radius is 15.935 + 0.15 + 1.60 = 17.685 mm.

The speaker opening radius is 25.75/2 + 0.20 = **13.075 mm**, diameter 26.15 mm.
The extra 0.20 mm radial clearance protects the acoustic keepout from small
printing errors. The dome outside this opening still has a close-fitting roof.
The case's highest remaining rim is below the dome's center, which explains the
10.59245 mm case height.

A 0.70 mm diametral seam frees the half shells and their floors. It provides
separation larger than a nominal extrusion width while retaining more than 96%
of the back coverage. Circular tessellation uses 192 segments, with less than
0.0024 mm radial sag at the outer wall. A 0.35 mm, 45 degree outer bed chamfer
reduces first-layer edge interference without thinning the floor.

## Front snap

The snap closes the two half shells by engaging a receiver on the opposite
half. Its catch points toward the product. It sits outside the product, so it
does not press into the AirTag to hold it.

| Measured feature | Value and reason |
| --- | --- |
| Root point | (-7.0, 18.9, 3.4) mm, inside the beam at its junction |
| Thickness direction | (0, -1, 0), toward the product |
| Length direction | (1, 0, 0), parallel to the bed |
| Root thickness t | 1.40 mm, above the 1.2 mm floor with usable bending compliance |
| Length L | 14.00 mm from root to free tip |
| Free width w | 6.80 mm vertically, enough section without making the latch as tall as the case |
| Backing width | 8.00 mm at 0.50 mm behind the root, establishing the actual attachment |
| Maximum catch projection y | 0.80 mm past the root's inner face |
| Receiver engagement | 0.50 mm radially, with 0.30 mm longitudinal play |

The beam's inner face is y=18.20, leaving 18.20 - 17.685 = 0.515 mm clearance
from the case wall even at its closest point. The left root pedestal connects
to the shell and is taller than the arm. The receiver reaches x=5.30; the square
catch shoulder starts at x=5.60. That shoulder resists the receiver's motion as
the halves try to open. The opposite sloping face is the closing lead-in. The
catch polygon overlaps the beam by 0.05 mm to make a clean solid union.

The grader's strain calculation is:

```text
epsilon = 1.5*y*t/L^2
        = 1.5*0.8*1.4/14^2
        = 0.00857143 = 0.8571%, below PETG's 3% limit.
```

The catch shoulder is 12.60 mm from the root. Conservatively using that shorter
loaded length gives 1.0582%, also below 3%. Holding the tip 0.80 mm outward
produces 0.6804 mm shoulder motion under the cubic cantilever model, clearing
the 0.50 mm engagement by 0.1804 mm. The root is fixed and displacement increases
smoothly along the beam. This bending lies in the xy layers.

## Rear flexure and assembly

The rear flexure has center (0, -18), neutral radius **11.50 mm**, radial
thickness **1.40 mm**, and vertical height **1.60 mm**. Its neutral arc length is
pi*11.50 = 36.12832 mm. The center is behind the 17.685 mm case radius so the
free arc stays outside the shell. Tangent stems end at y=-12.50, entering the
floor at radius sqrt(11.50^2 + 12.50^2) = 16.98529 mm. The flexure and stems
remain below the tag's 1.75 mm bottom.

Opening each half by 25 degrees reduces the C arc's subtended angle from 180
to 130 degrees. A constant-length arc then has neutral radius 15.92308 mm.
Using the original inner fiber length gives the more conservative strain:

```text
theta = 25*pi/180 radians per half
epsilon_inner = t*theta / (pi*(R - t/2))
              = 1.4*(25*pi/180) / (pi*(11.5 - 0.7))
              = 0.01800412 = 1.8004%, below 3%.
```

This is a uniform-curvature beam calculation, not a nonlinear material or
fatigue simulation. The generous arc length trades 4 mm of overall length
against a substantially higher strain in the first compact prototype. Keep
opening to about 25 degrees per half. Physical hinge life remains untested.

To remove the tag, pull the front latch tip outward about 0.80 mm and hold it
clear. Spread the half shells about 25 degrees each while moving the tag toward
the front (+y) about 6.50 mm. Lift it straight upward. Insert in reverse: lower
the tag with the case open and the tag forward, then guide it back to center as
the shells close. Release the latch to engage its receiver.

The persistent verification uses the actual exported half meshes, a separate
product solid built from the spec, and compatible C-arc motion. It does not
rotate the cups around a fixed rear pivot. With opening angle a in degrees,
the tag's forward motion is 0.26*a mm. Across **101 states at 0.25 degree
increments**, product intersection and released latch intersection are both
0.0 mm3. A full-diameter 31.87 mm vertical insertion column at y=6.50 also has
0.0 mm3 intersection. The latch's deformed mesh is refined to 0.6 mm edge length
before applying its cubic bend. These are sampled geometric checks of an ideal
elastic motion, with an independent review returning no findings.

## Printing and checks

Print as exported, flat floor down at z=0, dome opening up. The floor, hinge,
root, receiver and full lower edge of the latch start on the bed. This keeps
both flexible features bending within the xy layers and avoids a floating
horizontal latch. The roof follows the curved dome with a short inward rim;
it does not span the speaker opening. No supports are designed into the part.

The process assumption is PETG, 0.4 mm nozzle and 0.2 mm layers, matching the
repository's slicer check. That check reports 53 layers, 1022.8 mm2 first-layer
area, 1.3 mm2 aggregate dropped cross-section area, no problems, and ok=true.
The dropped area is the report's aggregate metric, not a measured wall
thickness. The separately measured minimum wall is 1.40 mm.

The active physical nozzle, printer profile, adhesion, first-layer expansion,
rim surface quality and physical fit have not been tested. Preview the seam,
latch gap and dome rim in the intended slicer before a physical print. No print
was started. No load capacity or cycle life is claimed.

The engineering grader measured 5927 product samples:

| Face | Median normal gap, mm | Coverage |
| --- | --- | --- |
| -z | 0.150 | 96.1% |
| +z outside the speaker keepout | 0.150 | 99.0% |
| +x and -x | 0.148 | 100.0% |
| +y and -y | 0.148 | 99.5% |

Speaker-path obstruction is **0.0 mm3** over the measured 4.85 mm path.
The first build exposed degenerate triangles from coincident offset/cylinder
joins. Replacing those joins with a single explicit meridian and overlapping
the catch union removed them in the source. The final mesh has **8152 triangles,
zero degenerate triangles, zero boundary edges and zero nonmanifold edges**.

Rebuild and rerun the persistent dimensional, topology, assembly and slicer
checks with:

```sh
uv run python gold/e04_airtag_case/build/verify.py
```

Result: pass=true. Full results and source/STL hashes are in
`build/verification.json`; the grade measurements are in
`build/measurements.json`, the opening sweep in `build/assembly.json`, and the
slicer report in `build/slicer.json`. Rendered top, underside, side and
three-quarter views in `build/` were visually inspected.

Final required render and grade commands:

```sh
openscad -o gold/e04_airtag_case/part.stl gold/e04_airtag_case/part.scad
uv run python gold/grade.py evals/engineering/e04_airtag_case.json gold/e04_airtag_case
```

Render result: NoError, one manifold 3D object. Final grade output:

```json
{
 "pass": true,
 "why": []
}
```
