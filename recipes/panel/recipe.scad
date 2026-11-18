// panel: faceplate with a row of cutouts, screw holes and an optional label.
use <lib/stone.scad>

w = 60;              // width along X, mm
d = 40;              // height along Y, mm
thickness = 3;       // plate thickness, mm
corner_r = 3;        // outer corner radius, mm
cutouts = 2;         // number of cutouts in a row (0 = none)
cut_shape = "square";// square | rounded | round
cut_w = 16;          // cutout width, mm (diameter for round)
cut_h = 16;          // cutout height, mm
cut_pitch = 0;       // distance between cutout centers, mm; 0 = auto
cut_y = 0;           // cutout row center along Y, mm
holes = "ends";      // ends (left and right) | top_bottom | corners | none
hole_d = 3.4;        // screw hole diameter, mm (3.4 fits M3)
hole_inset = 5;      // hole center distance from the edge, mm
countersink = false; // countersink the screw holes for flat head screws
label = "";          // text on the plate ("" = none)
label_size = 5;      // text height, mm
label_y = -99;       // text center along Y, mm; -99 = auto, under the cutouts
label_style = "raised"; // raised | engraved
edge = 0.8;          // top edge rounding, mm
quality = 96;        // circle smoothness

$fn = quality;
pitch = cut_pitch > 0 ? cut_pitch : cut_w + 8;
ly = label_y > -99 ? label_y : (cut_y - cut_h / 2 - d / 2) / 2;
depth = 0.6;

assert(cutouts == 0 || (cutouts - 1) * pitch + cut_w < w - 2, "the cutouts do not fit across the plate");
assert((cut_shape == "round" ? cut_w : cut_h) < d - 2, "the cutouts do not fit along the plate height");

module cut2d() {
    if (cut_shape == "round") circle(d = cut_w);
    else if (cut_shape == "rounded") rrect(cut_w, cut_h, min(cut_w, cut_h) / 5);
    else square([cut_w, cut_h], center = true);
}

hole_pos = holes == "ends" ? [[-(w / 2 - hole_inset), 0], [w / 2 - hole_inset, 0]]
         : holes == "top_bottom" ? [[0, -(d / 2 - hole_inset)], [0, d / 2 - hole_inset]]
         : holes == "corners" ? [for (sx = [-1, 1], sy = [-1, 1]) [sx * (w / 2 - hole_inset), sy * (d / 2 - hole_inset)]]
         : [];

difference() {
    union() {
        soft_slab(thickness, top = edge, bottom = 0.4) rrect(w, d, corner_r);
        if (label != "" && label_style == "raised")
            translate([0, ly, thickness - 0.01]) soft_extrude(depth + 0.01, r = 0.3, steps = 2) label2d(label, label_size);
    }
    for (i = [0:max(cutouts, 1) - 1]) if (cutouts > 0)
        translate([(i - (cutouts - 1) / 2) * pitch, cut_y, 0]) {
            through(thickness) cut2d();
            c = min(0.5, thickness / 4);
            translate([0, 0, thickness - c]) linear_extrude(c + 0.01, scale = 1) offset(delta = c) cut2d();
        }
    for (p = hole_pos) translate(p)
        if (countersink) csk_hole(hole_d, hole_d * 2, thickness); else hole(hole_d, thickness, 0.5);
    if (label != "" && label_style == "engraved")
        translate([0, ly, thickness - depth]) linear_extrude(depth + 1) label2d(label, label_size);
}
