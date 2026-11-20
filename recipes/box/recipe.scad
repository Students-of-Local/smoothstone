// box: rounded box with a press-fit lid, printed side by side. The lid prints upside down
// so its lip needs no support.
use <lib/stone.scad>

w = 80;              // outside width, mm
d = 60;              // outside depth, mm
h = 40;              // outside height of the box without the lid, mm
wall = 2;            // wall thickness, mm
floor = 2;           // floor thickness, mm
corner_r = 8;        // outside corner radius, mm
lid_h = 3;           // lid plate thickness, mm
lip_h = 5;           // how far the lid lip reaches into the box, mm
fit = 0.25;          // gap between lid lip and box wall, mm (bigger = looser)
label = "";          // text raised on the lid ("" = none)
label_size = 10;     // text height, mm
part = "both";       // both | box | lid
quality = 64;        // circle smoothness

$fn = quality;
gap = 6;

assert(corner_r > wall, "corner_r must be bigger than wall");

module box_body() difference() {
    soft_slab(h, top = 0.6, bottom = 0.4) rrect(w, d, corner_r);
    translate([0, 0, floor]) linear_extrude(h) rrect(w - 2 * wall, d - 2 * wall, corner_r - wall);
}

// lid printed upside down: top plate on the bed, lip pointing up
module lid() union() {
    soft_slab(lid_h, top = 0.01, bottom = 0.6) rrect(w, d, corner_r);
    translate([0, 0, lid_h - 0.01]) difference() {
        lw = w - 2 * wall - 2 * fit;
        ld = d - 2 * wall - 2 * fit;
        lr = corner_r - wall - fit;
        soft_extrude(lip_h, r = 0.5, bottom = 0) rrect(lw, ld, lr);
        translate([0, 0, -1]) linear_extrude(lip_h + 2) rrect(lw - 2 * 1.6, ld - 2 * 1.6, max(lr - 1.6, 0.5));
    }
    // the label is on the outside of the lid, which is face down while printing, so it is
    // engraved, mirrored to read right when the lid is turned over
}

module lid_with_label() {
    // the letters, for the stroke check: [height, font, the setting that grows them, its value]
    if (label != "") echo(stone_text = [label_size, "sans", "label_size", label_size]);
    lid_engraved();
}

module lid_engraved() difference() {
    lid();
    if (label != "") translate([0, 0, -0.01]) linear_extrude(0.6) mirror([1, 0]) label2d(label, label_size);
}

if (part == "box") box_body();
if (part == "lid") lid_with_label();
if (part == "both") {
    translate([-(w + gap) / 2, 0, 0]) box_body();
    translate([(w + gap) / 2, 0, 0]) lid_with_label();
}
