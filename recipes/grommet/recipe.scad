// grommet: cover for a round cable hole in a desk, with a cable slot at the edge.
// Prints upside down: the top lip lies on the bed and the insert ring grows up from it,
// so nothing overhangs and the visible top is the smooth first layer.
use <lib/stone.scad>

hole_d = 60;         // diameter of the hole in the desk, mm
fit = 0.3;           // gap per side between the insert and the hole, mm
depth = 12;          // how far the insert goes into the hole, mm
lip = 5;             // how far the top lip reaches past the hole, mm
top_t = 2.4;         // top thickness, mm
wall = 2;            // insert wall thickness, mm
slot_w = 20;         // cable slot width, mm (0 = no slot)
slot_depth = 18;     // how far the slot reaches in from the edge, mm
quality = 128;       // circle smoothness

$fn = quality;
ins = hole_d - 2 * fit;
top_d = hole_d + 2 * lip;

assert(2 * wall < ins - 4, "wall is too thick for the hole: make it thinner");
assert(slot_w == 0 || slot_w < ins - 2 * wall, "slot_w is wider than the insert: make it narrower");
assert(slot_w == 0 || slot_depth > lip + wall, "slot_depth does not reach past the insert: make it longer");

difference() {
    union() {
        cylinder(d = top_d, h = top_t);
        translate([0, 0, top_t - 0.01]) difference() {
            cylinder(d = ins, h = depth + 0.01);
            translate([0, 0, -1]) cylinder(d = ins - 2 * wall, h = depth + 2);
        }
    }
    // the cable slot: from the edge inward, through the lip and the insert, rounded at its end
    if (slot_w > 0) translate([0, -top_d / 2 - 1, -1]) linear_extrude(top_t + depth + 2)
        hull() {
            translate([-slot_w / 2, 0]) square([slot_w, 0.1]);
            translate([0, slot_depth + 1 - slot_w / 2]) circle(d = slot_w);
        }
}
