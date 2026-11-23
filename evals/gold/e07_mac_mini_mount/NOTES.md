Reference design by GPT-6.1 Sol, smoothstone gold set. Copied as made.

PETG under-desk cradle for the 2024 M4 Mac mini, designed for the spec's 20 N downward load and safety factor of 2. It is one continuous solid. A roof screws against the desk, side walls wrap the computer, and two bottom rails carry its weight. Two front release tabs and two fixed rear stops prevent sliding out. Front and rear port faces remain open.

All dimensions are millimeters. Product coordinates are the spec's x width, y front to back, z upward. The computer's enclosing box is 127 x 127 x 50, from `product.body.w`, `.d`, and `.h`. `product.body.corner_r` is 0 because Apple publishes no radius. The source is [Apple's technical specification](https://support.apple.com/en-us/121555), as cited for each number in the engineering spec. No unpublished chassis, port, button, foot, or corner dimensions were inferred.

The final STL is already rotated for printing. Product coordinates map to STL coordinates as:

```text
X = x + 3.5
Y = 56.7 - z
Z = y + 7.5
```

This is a proper rotation and translation. Its bounds are [0,0,0] to [134,61.8,138]. In service the computer is right side up, with the roof above it against the desk. Print Z is the computer's front-to-back direction.

Dimension choices:

| Feature | Value | Reason |
| --- | --- | --- |
| Nominal gap | 0.30 per side | Middle of the grader's 0.15 to 0.45 PETG slip range. Gives a 127.60 inside width and 50.60 between roof and rails. The computer settles onto the rails under weight; total vertical play is 0.60. |
| Side walls | 3.20 | Eight nominal 0.4 mm nozzle widths; gives a stiff continuous hanger and substantial material around the tab roots. |
| Roof | 6.40 | Accommodates a 3.80 deep head pocket while retaining a 2.60 web to the desk. Hardware seats and handling stiffness govern this dimension. |
| Bottom rails | 4.80 thick, 14.0 inboard | Broad bearing along both sides, support in all four quarters, and a 99 mm wide central underside opening. The tabs carry no sustained computer weight. |
| Rail entry | Starts at y=1.20, grows to full width by y=15.52 | Leaves 1.50 nominal clearance behind the front tabs, then grows inward at 45 degrees so the relief does not create an unsupported shelf. |
| Exterior chamfers | 1.20 | Removes sharp long outside corners while preserving the rectangular product cavity. No guessed body radius. |
| Front extension | 7.50 | Fits a 7.20 wide release tab entirely ahead of the product, with its rear face 0.30 clear of the body. |
| Rear extension | Ends at y=130.50 | Allows the 3.20 rise of the fixed rear stops at 45 degrees, starting just outside the product. |
| Snap arm | 2.40 thick, 7.20 wide, 28.20 measured length | A compliant beam with its length and bending thickness in the print plane. The width accommodates a support-free catch ramp and a flat land. |
| Snap catch | 3.20 rise; 4.0 long tip land; 3.20 ramp run | Positive stop above the bottom edge, an accessible pad for release, and a 45 degree insertion ramp. The beam centerline reaches the full catch rise. |
| Screw bores | 4.50 circular core | ISO 273 medium M4 clearance, from the spec's attachment source. Teardrop crowns preserve the circular bore and close at 45 degrees in print orientation. |
| Head pockets | 9.00 circular core, 3.80 deep | Clears the grader's 8.20 diameter x 3.10 high pan head by 0.40 radially and 0.70 axially. The seated head stays about 1 mm above the nominal computer top. |
| Screw centers | x=24,103; y=32,95 | Four screws share attachment and resist rotation. Positions are symmetric about the body center. Moving them inside the rail toes permits straight screwdriver access from below. |
| Tessellation and overlap | 64 circle facets; 0.02 boolean overlap | Maximum radial chord error of the 9 mm pocket is about 0.006 mm. Small overlaps prevent coincident-face rounding artifacts in OpenSCAD's manifold backend. They are outside the product cavity. |

The rear stops are ramps outside the body, rather than a transverse bar across its ports. At nominal product height the bottom edge meets them at about y=127.60. With the product seated 0.30 lower, contact is at about y=127.30. Together with the front catches, this gives roughly 0.6 to 0.9 mm of axial play, depending on seating. The 0.02 mm catch overlap slightly reduces those nominal numbers.

Retention calculation uses the grader's constant-section cantilever equation:

```text
strain = 1.5 * deflection * thickness / length^2
       = 1.5 * 3.2 * 2.4 / 28.2^2
       = 0.0144862 = 1.4486%
PETG permitted strain = 3.0%
```

The left tab is declared in `engineering.json`; the right tab is its mirror. The mesh measures a 2.400 mm root thickness, 7.200 mm root width, 28.200 mm arm length, and 3.200 mm catch rise. Its declared root is [3.3,58.2,3.6] in STL coordinates. At 0.5 mm behind it, the arm joins the wider side wall. The entire forward arm has free sides. Even 3.50 mm of release deflection would give about 1.585% nominal strain. This is an elastic sizing calculation, not a fatigue-life measurement.

Install the empty cradle first, using four 4 mm pan-head screws suited to the desk material and its available depth. The part does not specify screw length or desk pullout strength. A 6 mm diameter driver shaft has a clear path to every recessed seat; a 10 mm diameter guide envelope is clear through the bottom opening to the roof's inner face. Depress both front pads downward, slide the computer in from the front, then release the pads. To remove it, support its weight, depress both pads and slide forward. The catches do not require a guessed port location or a screw into the computer.

The load goes from the two rails through the side walls and roof to the attachment screws. The declared section lies in the roof at product [18,63.5,53.5], or STL [21.5,3.2,71]. The mesh measures 138.00 along its width direction and 6.40 along the load. Its measured moment divided by the whole 20 N load is 5.59 mm. The declared 6.0 mm arm rounds upward conservatively. The rectangular-section stress is 0.13 MPa. The grader also sweeps the load path and finds a worse cut at 0.39 MPa. Both are below the PETG allowable 47 / 2 = 23.5 MPa. The stress directions lie in the print plane. These are the grader's static strength calculations; they do not establish creep life or desk anchorage strength.

Measured fit uses 118,664 product samples at 2.04 per square mm. Side gaps and top median gap are 0.300. Both sides are 100% covered and the top is 98.3% covered, exceeding the required 80%. Front obstruction is 0.4% and rear obstruction is 1.2%, below the 10% limit. Bottom bearing areas are 769.3, 891.8, 769.3 and 891.8 square mm in the four quarters, each above the 4 square mm threshold. The full enclosing product box has zero solid intersection with the mesh.

All four screw mouths lie on the outer desk plane. Each bore is clear through the seat web, and every pan head clears both part and product. The screw pattern is 79 x 63, with 101.0 mm diagonal spread, exceeding one quarter of the 138 mm maximum extent, or 34.5 mm. The grader reads about 2.59 mm seat thickness, reflecting its small ray offsets around the nominal 2.60 mm web.

Print with the supplied STL orientation, front end on the bed at Z=0. Keep that orientation for the layer directions assumed above. The main channel grows along its length, so there is no 127 mm roof bridge. The front tabs start on the bed, their catch ramps are 45 degrees, the rail entries grow at 45 degrees, and the rear stops grow at 45 degrees. Screw and counterbore crowns are teardrops. Supports are unnecessary in the synthetic slice check. A removable exterior brim can help adhesion without filling the release gaps; actual adhesion settings depend on the plate and PETG.

Synthetic print verification assumes a 0.4 mm nozzle and 0.2 mm layers. The actual printer, nozzle, PETG profile, adhesion, production slicer preview, physical fit, thermal behavior, sustained-load creep and physical print remain unverified. Apple's spec gives no feature positions; the broad bottom opening preserves access over the center, but no claim is made about a particular power-button or vent position.

Reproducible checks, from the repository root:

```sh
openscad -o gold/e07_mac_mini_mount/part.stl gold/e07_mac_mini_mount/part.scad
uv run python gold/grade.py evals/engineering/e07_mac_mini_mount.json gold/e07_mac_mini_mount
uv run python gold/e07_mac_mini_mount/build/audit.py --slice
python3 /home/baney75/.agents/skills/3d-printing/scripts/check-stl.py gold/e07_mac_mini_mount/part.stl
```

The topology audit passes: 1,822 triangles, zero degenerate triangles, zero boundary edges and zero nonmanifold edges. Trimesh reports one watertight component. The grader's wall statistic is 3.1999 mm; this is a sampled percentile, not the absolute minimum. The separate mesh probes verify the intentionally thinner 2.40 mm tabs and approximately 2.60 mm screw webs, both above the 1.20 mm floor. Renders were inspected from outside, inside and along the open end. An independent checker repeated the solid, frame, snap, screw-head, product-intersection and driver-path measurements without finding a failure.

`build/measurements.json` records mesh measurements and SHA-256 fingerprints of the SCAD, STL and engineering metadata. `build/slicer.json` records the full synthetic slice result, including warnings. `build/grade.json` records the requested grader output. The spec and grader were not edited.

Final synthetic slice output:

```text
690 layers of 0.2 mm, 0.4 mm nozzle; first layer 1345.9 mm2; 19.2 mm2 too thin to print
PASS slices cleanly
```

There are zero reported problems, including zero ledge warnings. The dropped-area number is summed cross-sectional area across the layers, equivalent to 3.84 cubic mm at this layer height, not a 19.2 square mm hole in the part.

Final grade command, exit 0:

```sh
uv run python gold/grade.py evals/engineering/e07_mac_mini_mount.json gold/e07_mac_mini_mount
```

Final grade output:

```json
{
 "pass": true,
 "why": []
}
```
