Reference design by GPT-6.1 Sol, smoothstone gold set. Copied as made.

# iPhone 17 Pro portrait desk holder

A single PLA stand for the bare phone in the specified product frame: screen toward -y, back toward +y, height along +z. The raised cradle has a low front lip, two side guides, a backrest and a rounded foot. A cable can enter from the front without threading a connector through a closed hole. Units are millimeters.

## Product and fit

The body is the spec's 71.85 x 8.75 x 150.01 enclosing box. Its zero corner radius means an enclosing box, not a claim that the real phone has sharp corners. Every product dimension and bottom feature is named at the top of `part.scad`, with its exact spec key. The source is Apple's drawing as cited by the supplied spec:

https://developer.apple.com/download/files/accessories/dimensional-drawings/iphone-17-pro.pdf

The cradle opening is 72.45 wide by 9.35 deep. Clearance is 0.30 per side, halfway through the grader's 0.15 to 0.45 PLA slip band. The nominal product frame is translated 32.00 up, with no rotation. Its bottom is 0.30 above the shelf at z = 31.70. Under gravity the phone settles that last 0.30 onto the shelf. An extra check at the settled position confirms clear feature paths too. This is sized for the supplied bare body; a protective phone case is outside this fit.

The front lip ends at z = 38.00, the side guides at 50.00, and the backrest at 82.00. Their rises above the nominal phone bottom are respectively 6, 18 and 50. The lip keeps the lower edge in the cradle, the taller sides guide insertion, and the lower-third backrest limits rocking while leaving the upper two thirds free. Nothing hooks over the phone, so insertion and removal are vertical.

## Walls, support and foot

The side and front walls are 3.2 thick, equivalent to eight nominal 0.4 mm lines. The rear spine, foot and front edge of the shelf are 4.0 thick. Those dimensions provide continuous material around the narrow openings without relying on fine detail. They are geometry dimensions, not a prescription for the slicer's wall count.

The shelf's underside slopes 45 degrees down toward the rear spine. At its front the shelf is 4.0 thick; it thickens toward its root. This makes the ledge grow from the spine during an upright print, instead of starting as a horizontal roof. The two acoustic openings leave 3.745 and 3.755 wide webs next to the central cable opening. The grader's sampled minimum wall is 3.20.

The foot is 85.85 x 70 x 4, centered on the phone's thickness centerline. Its 7 mm projection past each body side leaves 3.5 mm beyond the cradle walls. The 70 mm depth gives at least 30.625 mm from either face of the body to the front or rear edge of the support polygon. The front cable notch separates the front toes, which remain connected behind it through the foot and spine. The specified body's entire vertical projection lies inside that support polygon. No phone mass, center of mass, cable force or tipping-force rating is invented.

The 6 mm foot corner radius removes sharp desk corners while retaining a flat bed face. The backrest's upper corners use a smaller 3 mm radius to soften exposed corners without rounding the fitted opening. The 64-segment circles resolve these small radii without excessive mesh size. The 0.02 boolean overlap prevents coincident joints; it is not a fit allowance.

## USB-C and acoustic access

Bottom-face coordinates use x = 71.85 - u, y = v. Consequently the USB-C center is x = 35.92, y = 4.375; the acoustic group centers are x = 19.91 and 51.94, both at y = 4.375. These are taken from the spec, including its face convention, rather than transcribed from a differently oriented bottom view.

The cable slot is 13.45 wide: Apple's 12.45 connector keepout plus 0.50 on each side. It extends from the front of the foot to y = 9.05, beyond the connector's rear keepout edge at y = 7.675. It passes through the front lip, shelf and foot. There is no roof over this opening. The 32 mm nominal phone elevation allows the published 14 mm mating-connector length and another 18 mm to the desk plane. The open front permits the cable to turn outward; that allowance is not a claim about an unspecified cable's minimum bend radius.

Each acoustic opening is 11.08 x 2.06: the published 10.08 x 1.06 group rectangle plus 0.50 on every edge. The slots run vertically through the inclined shelf and exhaust into the air beneath it. The foot is below their complete checked paths. Neither group is covered by a blind recess.

The grader measured all three paths to 15.33 mm, longer than the USB-C feature's 14 mm minimum, with 0.00 mm3 blocked. A separate check after the phone settles also measured 0.00 mm3 in each 14 mm feature path. The settled body's contact boolean has a residual volume of 0.00008232 mm3 at the coincident shelf plane from float32 geometry conversion. The verification allows 0.001 mm3 for that contact skin, equivalent to less than 0.000002 mm over the bottom face. The nominal frame has exactly 0.00 mm3 body intersection.

## Retention and strain

Retention is `none`, exactly as requested. Gravity, the shelf and the shallow perimeter guides locate the phone; no interference, snap catch or screw is claimed. Required elastic assembly deflection is zero, so imposed assembly strain is 0%. The cantilever snap equation, strain = 1.5 y t / L^2, is inapplicable because this stand has no snap arm. No fictional root, arm length or strain calculation is entered in `engineering.json`. Zero imposed assembly strain does not mean zero stress under use.

The spec has safety = 2 but supplies no load_n, support face, attachment or part-hole pattern. Its grader therefore does not calculate strength or support-quarter compliance. The extra support diagnostic still checks -z and finds bearing in all four quarters: 116.1, 129.4, 116.1 and 129.4 mm2. No strength rating is inferred from that result.

## Printing and inspection

Print in the exported orientation: the foot's flat sole is at z = 0 and the backrest grows along +z. No reorientation is required. The upright spine, 45 degree underside, vertical acoustic bores and open cable channel avoid support roofs. The intended process is PLA FDM with a nominal 0.4 mm nozzle and 0.2 mm layers, matching the grader's simulation defaults.

The mesh is one connected, watertight solid with consistent winding. It has 560 triangles, no degenerate triangles, no boundary edges, no non-manifold edges, and bounds 85.85 x 70 x 82. Its solid geometric volume is 56,915.42 mm3; actual printed material depends on the slicer.

Stone's layer simulation inspected 410 layers and reported zero problems, including zero floating islands and zero ledge warnings. First-layer area was 5,445.1 mm2. It also reports 6.2 mm2 of cross-sectional area dropped in total across all layers by its minimum-feature raster filter; that aggregate is recorded rather than presented as zero. No functional feature is designed below 3.2 mm material thickness.

Front, side, rear, top and three-quarter OpenSCAD renders were inspected. `build/assembly.png` shows the specified enclosing phone box in the cradle; it is a preview only and is excluded from `part.stl`.

The printer's actual nozzle, filament condition, slicer profile, adhesion and physical print remain unverified. No machine-specific slicer or physical print was run. Support-free printing is the geometric design intent, supported by the clean layer simulation.

## Verification and final grade

From the repository root:

```sh
openscad -o gold/e06_iphone_desk_holder/part.stl gold/e06_iphone_desk_holder/part.scad
uv run python gold/grade.py evals/engineering/e06_iphone_desk_holder.json gold/e06_iphone_desk_holder
uv run python gold/e06_iphone_desk_holder/build/verify.py
python3 /home/baney75/.codex/skills/3d-printing/scripts/check-stl.py gold/e06_iphone_desk_holder/part.stl
```

All commands completed successfully. The independent verification also requires one connected solid, zero nominal body intersection, negligible settled contact skin, clear settled feature paths, all four supported quarters, and an empty slicer problem list.

Measured bottom coverage outside the feature masks is 96.3%, with median gap 0.300 mm. Screen-face obstruction is 3.4%. The grader sampled 52,558 body points at 2.04 points per mm2. No spec or grader change was needed.

Final output of the requested grade command:

```json
{
 "pass": true,
 "why": []
}
```

Evidence: `build/grade.txt`, `build/measurements.json`, `build/mesh-audit.json`, `build/slicer.json`, `build/verification.txt`, `build/topology.txt` and `build/render.log`. The complete engineering declaration is `build/engineering.json`.
