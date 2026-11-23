Reference design by GPT-6.1 Sol, smoothstone gold set. Copied as made.

# Apple TV 4K wall cradle

A single solid PLA cradle for the Apple TV 4K, third generation. Its left rail screws to
the wall; the device stays horizontal, with its ports toward product +y. Drop it in from
above and lift it out for service. Shallow end stops prevent sliding along the wall.

## Dimensions and fit

The spec's Apple support page, https://support.apple.com/en-us/111839, supplies the
93 x 93 x 31 mm enclosing box. The unpublished corner radius remains zero. No port
positions or actual corner radii are inferred. The source keys appear beside the named
product dimensions at the start of part.scad.

The STL is in millimeters, with bounds [0, 0, 0] to [101.6, 98.4, 35.3]. The product
origin is [4.3, 2.7, 4.3], with no rotation. The channel is 93.6 mm across, allowing
0.30 mm per side, the midpoint of the grader's 0.15 to 0.45 mm PLA slip band.
The same allowance separates the nominal product box from the floor and end stops.
Under gravity the device settles 0.30 mm onto the floor; engineering.json describes
the nominal fit position used by the grader.

The continuous floor and both side rails are 4.0 mm thick. A 90 degree countersink
from 9.0 mm to 4.5 mm needs 2.25 mm of depth. Keeping at least 1.2 mm beneath that
seat requires 3.45 mm of wall, rounded up to 4.0 mm for a practical, stiff section.
The remaining straight bore length is 1.75 mm. This is a local feature dimension;
the grader's sampled wall statistic of 4.0 mm is not a claim that every spot is 4 mm.
The 0.6 mm chamfers soften the exposed top and foot edges and guide insertion.
They slope at 45 degrees. The uninterrupted floor spans between the rails without
a separate joint. The stops overlap the rails by 0.2 mm for robust solid unions.

Each end stop is 2.4 mm thick, six nominal 0.4 mm lines. It rises 1.8 mm above the
floor, with a 0.6 mm outward top bevel. Its peak is 1.5 mm above the product's nominal
bottom, or 4.84% of the 31 mm face height. The bevel lowers the inside contact edge
by 0.6 mm. Measured front and rear obstruction is 4.4% each, under the 10% limit;
the top is 0% blocked. The floor and right face have 100% coverage, and the mounting
face has 97.7% coverage after allowing for its holes. Every covered face has a
measured median gap of 0.30 mm. All four floor quarters bear on the product.

## Attachment and load

Use two M4 screws with ISO 7046 style 90 degree flat heads, up to 8.4 mm head diameter,
and wall anchors appropriate to the mounting surface. Pan heads would intrude into
the product and are unsuitable. Install the screws before inserting the device.
Tighten only until seated, without crushing the PLA. Anchor capacity and installation
torque are outside the mesh strength calculation.

The bores are 4.5 mm, the spec's ISO 273 medium M4 clearance. Their wall-side mouths
are [0, 21.2, 19.8] and [0, 77.2, 19.8], along +x into the wall rail. The 9.0 mm
countersink mouths leave 0.6 mm diametral allowance around the specified head.
The heads recess below the inner fit plane. The grader measures zero material in
either required flat head cone and a full bearing ring at each fixing. The 56 mm
pitch puts the centers 18.5 mm in from the product's front and rear and exceeds the
24.6 mm minimum spread, one quarter of the part's 98.4 mm mounting face extent.

The spec requires 10 N downward with safety factor 2. Its own weight rationale is
about 2.1 N, leaving margin for a bump or cable pull. The declared floor root is
[4.5, 49.2, 2.0]. Rays through the exported mesh measure b = 98.4 mm along y and
h = 4.0 mm along z. The load centroid is at x = 50.8 mm, giving a measured arm of
50.8 - 4.5 = 46.3 mm.

The rectangular estimate is:

    sigma = 6 F arm / (b h^2)
          = 6 * 10 * 46.3 / (98.4 * 4^2)
          = 1.76 MPa

The grader also sweeps the actual connected load path, including the rail up to
the screws. Its worst cut is 0.24 mm toward the wall from the declared section:
effective arm 46.54 mm, section modulus 158.71 mm^3, stress 2.93 MPa. This is below
the 50 / 2 = 25 MPa PLA allowance. The floor beam runs along x, within the printed
layers. The complete measured grade is saved in build/grade.json.

## Retention and printing

Retention type is `none`, permitted by the spec's `any`. Gravity holds the device
on the floor, both rails constrain x, and low stops constrain y. There is no top
latch, so intentional upward removal is free. This is a wall cradle for upright
use, not an inverted or vibration locked enclosure.

Insertion requires no designed elastic deflection, so the required retention strain
is 0%. The snap equation, epsilon = 1.5 y t / L^2, is inapplicable because there is
no snap arm. No fictitious arm dimensions or root points are declared. Choosing a
lift out cradle avoids repeated flexing of PLA while keeping the required top open.

Print exactly in the exported orientation: the broad floor at STL z = 0 on the bed,
with the channel facing up. Use PLA, a 0.4 mm nozzle, 0.2 mm layers, five perimeter
walls and 100% infill to support the solid section strength assumptions. No supports
are designed in. The screw bores are short horizontal openings; the small circular
roofs require short local bridging. Their 90 degree countersinks have 45 degree
slopes. The rails and end stops grow continuously from the floor.

The repository's layer simulation reports 176 layers, 9899.0 mm^2 first layer area,
zero problems, and 3.5 mm^2 summed cross section detail dropped over all layers.
That last number is rasterized edge detail, not a missing functional wall.
build/slicer.json contains the report. The simulated profile is not a verified
printer setup. Actual printer, adhesion, commercial slicer toolpaths, physical fit,
thermal creep and physical load testing remain unverified. No print was started.

## Verification

Inspected every panel of build/views.png: eight azimuths, top and bottom. Both
countersinks, the continuous floor, open channel and end stops are present.

Render command, exit 0:

```text
openscad -o gold/e05_appletv_wall_holder/part.stl gold/e05_appletv_wall_holder/part.scad
Status: NoError
Vertices: 620
Facets: 1244
```

The first solid union produced degenerate triangles at coincident stop and rail
edges. The positive 0.2 mm overlap corrected this in the source. The final STL
was regraded after rendering. Independent topology command, exit 0:

```text
python3 /home/baney75/.agents/skills/3d-printing/scripts/check-stl.py gold/e05_appletv_wall_holder/part.stl
PASS: topology_closed=true triangles=1244 degenerate=0 boundary_edges=0 nonmanifold_edges=0 bbox=101.6x98.4x35.3
```

Trimesh independently reads one connected watertight component, volume
65075.35 mm^3. The spec and grader were not edited.

Final grade command, exit 0:

```text
uv run python gold/grade.py evals/engineering/e05_appletv_wall_holder.json gold/e05_appletv_wall_holder
{
 "pass": true,
 "why": []
}
```
