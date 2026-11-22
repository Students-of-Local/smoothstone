Reference design by GPT-6.1 Sol, smoothstone gold set. Copied as made.

# Raspberry Pi 4 VESA 75 adapter

This is a single PETG plate carrying a Raspberry Pi 4 Model B above a VESA 75 monitor mount. Its STL coordinates are millimeters. The 95 mm width is the 85 mm board width plus a 5 mm margin on each side. The 92 mm depth is the 75 mm VESA spacing plus an 8.5 mm margin at each end. The 8 mm outer corner radius rounds the corners while fitting inside that margin. The centered 64 x 34 mm opening has 6 mm rounded corners and leaves 15.5 mm side rails and 29 mm end lands. The 4 mm plate thickness provides frame stiffness and leaves a 2.7 mm web above each countersink. This spec states no design load, so no load capacity is claimed.

The product frame and feature dimensions come from the spec and the [Raspberry Pi mechanical drawing](https://datasheets.raspberrypi.com/rpi4/raspberry-pi-4-mechanical-drawing.pdf). The board envelope is 85 x 56 x 16 mm, with 3 mm corner radii. The 16 mm height is the drawing's tallest component dimension; the drawing does not establish whether it includes PCB thickness. The board hole centers in product x and y are (3.5, 3.5), (61.5, 3.5), (3.5, 52.5), and (61.5, 52.5). The product's -z face views u from the opposite direction to x. The four nominal board holes are 2.7 mm diameter with 6 mm bearing pads. The plate places the board origin at (5, 18, 14), with the plate top at z=4.

The four plate holes for board retention are 2.9 mm diameter for M2.5 clearance, arranged 58 x 49 mm. Four separate 10 mm high M2.5 female to female metal standoffs hold the board above the plate. Their board bearing faces must fit within the specified 6 mm diameter pads. The top of the plate is therefore 10 mm below the board underside, exceeding the 2.5 mm clearance requested outside those pads by 7.5 mm. The printed part itself has no walls around the board, and its component side is open. The spec does not give the full board underside profile; check actual leads and standoffs before assembly.

Each board hole has a 90 degree countersink on the monitor side, 5.5 mm diameter at z=0, tapering to 2.9 mm at z=1.3. Its sloping walls are 45 degrees and the straight bore continues for 2.7 mm to the plate top. The sink holds an M2.5 x 8 mm 90 degree flat head screw with a head diameter no greater than 5.0 mm, measured before use. A 5.0 mm head seats 0.25 mm below the plate underside: (5.5 - 5.0) / 2 = 0.25 mm. Its tip then reaches z=8.25, giving 8.25 - 4 = 4.25 mm engagement in the 10 mm standoff. Select the upper board screws for the actual board thickness so that they engage 2.5 to 3.5 mm. Their combined penetration is 6.75 to 7.75 mm, leaving 2.25 to 3.25 mm between tips. Confirm actual screw head shape, lengths and thread depths before assembly; these dimensions are a hardware envelope, not a claim about a particular screw standard. Use appropriate small washers or heads within the board's 6 mm pads and tighten gently.

This is screw retention, not a snap. The snap strain equation 1.5 y t / L^2 does not apply because there is no snap arm, catch, or flexing deflection. The relevant clearance calculation is 2.9 - 2.5 = 0.4 mm diametral clearance, or 0.2 mm per side at nominal dimensions. It gives room for the M2.5 shank in the plate; printed hole sizes should be checked on the actual printer. The metal standoff provides the thread. No screw strain or strength rating is calculated.

The four VESA holes are 4.5 mm diameter on a 75 x 75 mm square, centered at (47.5, 46), as specified from [VESA FDMI](https://glenwing.github.io/docs/VESA-FDMI-1.1.pdf) and ISO 273 medium clearance. Their nearest outer edge ligament is 8.5 - 2.25 = 6.25 mm. Their centers lie at least 9.5 mm beyond the board's y envelope: an 8.2 mm diameter head has 9.5 - 4.1 = 5.4 mm clearance to that envelope. The nearest board bore is 7.5 - 1.45 = 6.05 mm from the ventilation opening, and its countersink mouth is 7.5 - 2.75 = 4.75 mm from it. Fasten the standoffs to the loose plate from the underside, check the flat heads are below its monitor face, mount the plate to the monitor, then place and fasten the board. Use M4 screws whose thread engagement meets the monitor manufacturer's limits. A separate monitor arm may require longer screws and extra clearance; it has not been checked with this part.

Print with the broad z=0 face on the bed. The straight vertical holes and 45 degree countersinks are intended to print without supports. The repository's synthetic slicer passed with its 0.4 mm nozzle and 0.2 mm layer assumptions, with no reported problems. Actual material, nozzle, slicer profile, adhesion, hole accuracy and support needs remain unverified; inspect a slicer preview and test the fit before use. No physical print or device fit has been tested.

The exported mesh is one connected watertight body. The independent topology checker reports 4,676 triangles, zero degenerate triangles, zero boundary edges, zero nonmanifold edges, and a 95 x 92 x 4 mm bounding box. Direct mesh rays read all four board bores at 2.9 mm and all four VESA bores at 4.5 mm. Near the sink endpoints they read 5.48 mm at z=0.01 and 2.92 mm at z=1.29, matching the 5.5 mm mouth and 1.3 mm depth. The straight axial web above each sink is 2.7 mm; rays immediately beside the bores measure approximately 2.7001 mm. The grader's sampled minimum wall is 4.0 mm, a sampling result that does not prove the 2.7 mm web by itself. Its hole tests report zero bore obstruction and at least 96.4% bearing-ring coverage at each board hole. Full measurements are in `build/measurements.json`.

Final grade:

```text
$ uv run python gold/grade.py evals/engineering/e08_rpi4_vesa_adapter.json gold/e08_rpi4_vesa_adapter
{
 "pass": true,
 "why": []
}
```
