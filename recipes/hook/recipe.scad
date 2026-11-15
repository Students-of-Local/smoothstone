// hook: wall hook with two countersunk screw holes. Prints lying on its side, so the
// curve has no overhang and the layers carry the load.
use <lib/stone.scad>

width = 20;          // hook width, mm (the print height)
back_h = 70;         // back plate height, mm
reach = 30;          // inside width of the hook curve, mm
tip = 14;            // how far the tip rises past the curve, mm
thickness = 7;       // bar thickness, mm
holes = 2;           // screw holes in the back plate (0, 1 or 2)
screw_d = 4.2;       // screw hole diameter, mm
edge = 1.2;          // rounding on the top edges, mm
quality = 64;        // circle smoothness

$fn = quality;
t = thickness;
R = reach / 2 + t / 2;
arc = [for (a = [180:10:360]) [R + R * cos(a), R + R * sin(a)]];
path = concat([[0, back_h]], arc, [[2 * R, R + tip]]);

assert(holes < 2 || back_h > 2 * R + 20, "back_h is too short for two holes: make it taller");

hole_v = holes == 1 ? [back_h - 10] : holes == 2 ? [back_h - 10, 2 * R + 6] : [];

translate([-R, -(back_h) / 2, 0]) difference() {
    soft_extrude(width, r = edge) stroke2d(path, t);
    // screws go through the plate along X; teardrop so the hole prints on its side
    for (v = hole_v) translate([0, v, width / 2]) {
        rotate([0, 90, 0]) rotate(90) linear_extrude(t + 2, center = true) teardrop2d(screw_d);
        // countersink on the hook side
        translate([t / 2 - (screw_d * 1.9 - screw_d) / 2, 0, 0]) rotate([0, 90, 0])
            cylinder(d1 = screw_d, d2 = screw_d * 1.9 + 0.02, h = (screw_d * 1.9 - screw_d) / 2 + 0.01);
    }
}
