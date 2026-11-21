// smoothstone shared helpers. Plain OpenSCAD, so every recipe stays fast and readable.
// Recipes load this with: use <lib/stone.scad>

// 2D rounded rectangle centered on the origin.
module rrect(w, d, r) {
    rr = max(min(r, w / 2 - 0.01, d / 2 - 0.01), 0.01);
    hull() for (sx = [-1, 1], sy = [-1, 1])
        translate([sx * (w / 2 - rr), sy * (d / 2 - rr)]) circle(r = rr);
}

// Extrude a CONVEX 2D child with a small bottom chamfer (keeps the first layer from
// flaring out) and a rounded top edge. True slopes, made with hull().
module soft_slab(h, top = 0.8, bottom = BED_CHAMFER, steps = 6) {
    t = min(top, h / 2);
    b = min(bottom, h / 4);
    hull() {
        if (b > 0) linear_extrude(0.01) offset(delta = -b) children();
        translate([0, 0, b]) linear_extrude(max(h - b - t, 0.01)) children();
        if (t > 0) for (i = [1:steps]) {
            a = 90 * i / steps;
            translate([0, 0, h - t + t * sin(a) - 0.01])
                linear_extrude(0.01) offset(delta = -t * (1 - cos(a))) children();
        }
    }
}

// Bed-edge chamfer: how far the first layer is inset, mm. The first layer squashes out by
// about this much (elephant foot), so a part with no inset prints with a lip at the bed.
BED_CHAMFER = 0.4;

// Extrude ANY 2D child (grilles, text, outlines) with a 45 degree bottom chamfer and a
// rounded top edge, both built from thin layers that step inward. The top ledges face up;
// the bottom steps are BED_CHAMFER / 4 wide, finer than any layer, so a slicer reads a slope.
// Use bottom = 0 when the extrusion stands on another part instead of the bed.
module soft_extrude(h, r = 0.5, steps = 4, bottom = BED_CHAMFER) {
    rr = max(min(r, h / 2), 0);
    b = max(min(bottom, h / 4), 0);
    if (b > 0) for (i = [0:3])
        translate([0, 0, b * i / 4]) linear_extrude(b / 4 + 0.001) offset(delta = -b * (4 - i) / 4) children();
    translate([0, 0, b]) linear_extrude(h - rr - b + 0.001) children();
    if (rr > 0) for (i = [1:steps]) {
        a0 = 90 * (i - 1) / steps;
        a1 = 90 * i / steps;
        translate([0, 0, h - rr + rr * sin(a0)])
            linear_extrude(rr * (sin(a1) - sin(a0)) + 0.001)
                offset(delta = -rr * (1 - cos((a0 + a1) / 2))) children();
    }
}

// Give ANY 3D child resting on z = 0 the same 45 degree bed chamfer: the slice just above the
// bed sets the outline, and each step below b cuts away a band outside it. For parts not made
// with soft_extrude or soft_slab (cylinders, gears, height maps).
module bed_chamfer(b = BED_CHAMFER) {
    if (b <= 0) children();
    else difference() {
        children();
        for (i = [0:3]) translate([0, 0, i == 0 ? -1 : b * i / 4])
            linear_extrude(b / 4 + (i == 0 ? 1 : 0) + 0.001) difference() {
                square(4000, center = true);
                offset(delta = -b * (4 - i) / 4) projection(cut = true) translate([0, 0, -0.01]) children();
            }
    }
}

// Through hole with a chamfered top edge. Subtract it.
module hole(d, h, c = 0.5) {
    translate([0, 0, -1]) cylinder(d = d, h = h + 2);
    if (c > 0) translate([0, 0, h - c]) cylinder(d1 = d, d2 = d + 2 * c + 0.02, h = c + 0.01);
}

// Countersunk hole for a flat head screw (90 degree head), head at the top. Subtract it.
module csk_hole(d, head_d, h) {
    translate([0, 0, -1]) cylinder(d = d, h = h + 2);
    depth = (head_d - d) / 2;
    translate([0, 0, h - depth]) cylinder(d1 = d, d2 = head_d + 0.02, h = depth + 0.01);
    translate([0, 0, h]) cylinder(d = head_d + 0.02, h = 1);
}

// Through slot with straight walls: a 2D shape cut all the way through. Subtract it.
module through(h) { translate([0, 0, -1]) linear_extrude(h + 2) children(); }

// Text, centered, as 2D.
module label2d(txt, size, font = "Liberation Sans:style=Bold", spacing = 1) {
    text(txt, size = size, font = font, halign = "center", valign = "center", spacing = spacing);
}

// 2D stroke along a path: round joins and round ends, width w. Good for hooks and stands.
module stroke2d(pts, w) {
    for (i = [0:len(pts) - 2]) hull() {
        translate(pts[i]) circle(d = w);
        translate(pts[i + 1]) circle(d = w);
    }
}

// 2D teardrop pointing +Y: a round hole that prints lying on its side without support.
module teardrop2d(d) {
    circle(d = d);
    rotate(45) square(d / 2);
}
