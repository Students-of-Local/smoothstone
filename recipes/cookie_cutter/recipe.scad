// cookie_cutter: cutter in the shape of a picture outline. The cutting edge tapers to a thin
// wall at the top; a flange on the bed makes it stiff and comfortable to press.
use <lib/stone.scad>

image = "";          // picture outline from stone image (svg, holes filled)
size = 80;           // cutter width, mm
height = 14;         // cutter height, mm
edge_wall = 0.9;     // wall at the cutting edge, mm
base_wall = 2;       // wall at the base, mm
flange = 4;          // flange width outside the wall, mm
flange_t = 1.6;      // flange thickness, mm
smooth = 1.5;        // drops strokes thinner than twice this (whiskers, hair), mm
quality = 48;        // circle smoothness

$fn = quality;
steps = 8;

assert(image != "", "run stone image first so the picture can be used");

// opening: shrink then grow back, so thin strokes that could not cut dough disappear
module shape() offset(r = smooth) offset(r = -smooth) resize([size, 0], auto = true) import(image, center = true);

// with no flange the bare wall is the whole first layer: chamfer it less, so it keeps its grip
bed_chamfer(flange > 0 ? 0.4 : min(0.4, 0.15 * base_wall)) union() {
    linear_extrude(flange_t) difference() {
        offset(r = base_wall + flange) shape();
        shape();
    }
    // wall: thick at the base, thin at the top, in steps that all face up
    for (i = [0:steps - 1]) {
        z0 = flange_t + (height - flange_t) * i / steps;
        w = base_wall + (edge_wall - base_wall) * (i + 1) / steps;
        translate([0, 0, z0 - 0.01]) linear_extrude((height - flange_t) / steps + 0.01)
            difference() { offset(r = w) shape(); shape(); }
    }
}
