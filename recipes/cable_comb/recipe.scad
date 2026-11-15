// cable_comb: bar with a row of slots that hold cables side by side. Slots have a
// lead-in chamfer and an optional grip, so cables click in and stay.
use <lib/stone.scad>

length = 100;        // bar length along X, mm
depth = 12;          // bar depth along Y, mm (slots open on the +Y side)
height = 6;          // bar height, mm
slots = 8;           // number of slots
slot_w = 6.2;        // slot width, mm (cable diameter plus 0.2 to 0.5)
slot_depth = 8;      // how deep each slot goes into the bar, mm
pitch = 0;           // distance between slot centers, mm; 0 = auto
lead_in = 0.8;       // chamfer at each slot mouth, mm
grip = 0;            // narrows the slot mouth by this much so cables click in, mm
round_bottom = true; // round the inner end of each slot
edge = 0.8;          // top edge rounding, mm
corner_r = 2;        // bar corner radius, mm
quality = 64;        // circle smoothness

$fn = quality;
p = pitch > 0 ? pitch : (slots > 1 ? (length - 16) / (slots - 1) : 0);
y_top = depth / 2;
y_bot = depth / 2 - slot_depth;

assert(slot_depth < depth - 1.2, "slot_depth must leave at least 1.2 mm of bar behind the slots");
assert(slots < 2 || p > slot_w + 1.2, "slots overlap: make pitch bigger or slot_w smaller");
assert((slots - 1) * p + slot_w < length - 2, "the slots do not fit along the bar");

module slot2d() {
    r = slot_w / 2;
    neck = slot_w - grip;
    union() {
        if (round_bottom) {
            translate([0, y_bot + r]) circle(r = r);
            translate([-r, y_bot + r]) square([slot_w, slot_depth - r - lead_in - (grip > 0 ? 1.2 : 0) + 0.01]);
        } else translate([-r, y_bot]) square([slot_w, slot_depth - lead_in - (grip > 0 ? 1.2 : 0) + 0.01]);
        // the neck: slot_w, or narrower when grip > 0
        translate([-neck / 2, y_top - lead_in - (grip > 0 ? 1.2 : 0)]) square([neck, (grip > 0 ? 1.2 : 0) + 0.02]);
        // lead-in: a funnel from the neck out to the bar face
        polygon([[-neck / 2, y_top - lead_in], [neck / 2, y_top - lead_in],
                 [neck / 2 + lead_in, y_top + 0.01], [-neck / 2 - lead_in, y_top + 0.01]]);
        translate([-neck / 2 - lead_in, y_top]) square([neck + 2 * lead_in, 1]);
    }
}

soft_extrude(height, r = edge) difference() {
    rrect(length, depth, corner_r);
    for (i = [0:slots - 1]) translate([(i - (slots - 1) / 2) * p, 0]) slot2d();
}
