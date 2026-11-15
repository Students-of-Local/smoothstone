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
module soft_slab(h, top = 0.8, bottom = 0.4, steps = 6) {
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

// Extrude ANY 2D child (grilles, text, outlines) with a rounded top edge built from
// thin layers that step inward. Every ledge faces up, so nothing overhangs.
module soft_extrude(h, r = 0.5, steps = 4) {
    rr = max(min(r, h / 2), 0);
    if (rr <= 0) linear_extrude(h) children();
    else {
        linear_extrude(h - rr + 0.001) children();
        for (i = [1:steps]) {
            a0 = 90 * (i - 1) / steps;
            a1 = 90 * i / steps;
            translate([0, 0, h - rr + rr * sin(a0)])
                linear_extrude(rr * (sin(a1) - sin(a0)) + 0.001)
                    offset(delta = -rr * (1 - cos((a0 + a1) / 2))) children();
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
