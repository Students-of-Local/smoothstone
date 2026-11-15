// _demo: rounded plate with one through hole. Test recipe for stone, plain OpenSCAD.
w = 60;          // plate width along X, mm
d = 40;          // plate depth along Y, mm
h = 4;           // plate thickness, mm
corner_r = 4;    // corner radius, mm
hole_d = 6;      // hole diameter, mm (0 = no hole)
hole_place = "center"; // center | left
chamfer = true;  // 0.6 mm chamfer on the top edge
quality = 48;    // circle segments

$fn = quality;
c = chamfer ? min(0.6, h / 3) : 0;

assert(corner_r * 2 < min(w, d), "corner_r must be less than half of w and d");
assert(hole_d < min(w, d) - 4, "hole_d must leave 2 mm of plate around the hole");

module rounded_rect(x, y, r) {
    rr = max(r, 0.01);
    hull() for (sx = [-1, 1], sy = [-1, 1])
        translate([sx * (x / 2 - rr), sy * (y / 2 - rr)]) circle(r = rr);
}

module body() {
    hull() {
        linear_extrude(h - c) rounded_rect(w, d, corner_r);
        if (c > 0)
            translate([0, 0, h - c]) linear_extrude(c) rounded_rect(w - 2 * c, d - 2 * c, max(corner_r - c, 0.01));
    }
}

hole_x = hole_place == "left" ? -w / 2 + hole_d / 2 + max(corner_r, 4) : 0;

difference() {
    body();
    if (hole_d > 0)
        translate([hole_x, 0, -1]) cylinder(d = hole_d, h = h + 2);
}
