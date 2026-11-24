// fit_coupon: a clearance test print. A plate with one hole per clearance step for a single test
// peg, labeled 0 to 5 (tenths of a mm per side), a 10 mm hole to measure, and a 20 mm square block
// that carries the peg. The person tries the peg in each hole: the tightest hole it slides in is
// this printer's slide clearance (stone fit calibrate slide=0.2). Calipers on the square and the
// 10 mm hole give its outer and hole error (square=20.12 hole=9.78).
use <lib/stone.scad>

peg_d = 6;           // test peg diameter, mm
steps = 6;           // holes, one per step from 0 clearance up
step = 0.1;          // each hole is this much roomier than the last, per side, mm
thickness = 4;       // hole plate thickness, mm
square = 20;         // square block side, mm
ref_d = 10;          // the hole to measure, mm
label_size = 6;      // label height, mm
quality = 96;        // circle smoothness

$fn = quality;
pitch = peg_d + 2 * step * (steps - 1) + 4;
w = steps * pitch + ref_d + 8;
d = 2 * label_size + peg_d + 2 * step * (steps - 1) + 6;
hy = d / 2 - (peg_d / 2 + step * (steps - 1)) - 3;   // test hole row
ly = hy - (peg_d / 2 + step * (steps - 1)) - 1 - label_size / 2;  // label row
x0 = -w / 2 + 3 + pitch / 2;
depth = 0.6;
peg_h = 10;
block_h = 5;

echo(stone_text = [label_size, "sans", "label_size", label_size]);
// what stone fit reads back: the peg, the holes and the measuring features, as built
echo(stone_fit_coupon = [peg_d, step, steps, ref_d, square, quality]);

// the hole plate
bed_chamfer() difference() {
    soft_slab(thickness, top = 0.6, bottom = 0) rrect(w, d, 3);
    for (i = [0:steps - 1]) translate([x0 + i * pitch, hy, 0]) hole(peg_d + 2 * i * step, thickness, 0.4);
    translate([w / 2 - 4 - ref_d / 2, 0, 0]) hole(ref_d, thickness, 0);
    for (i = [0:steps - 1]) translate([x0 + i * pitch, ly, thickness - depth])
        linear_extrude(depth + 1) label2d(str(i), label_size);
}

// the square block with the test peg standing on it
translate([0, -d / 2 - 6 - square / 2, 0]) bed_chamfer() union() {
    translate([-square / 2, -square / 2, 0]) cube([square, square, block_h]);
    translate([0, 0, block_h - 0.01]) {
        cylinder(d = peg_d, h = peg_h - 0.5 + 0.01);
        translate([0, 0, peg_h - 0.5]) cylinder(d1 = peg_d, d2 = peg_d - 1, h = 0.5);
    }
}
