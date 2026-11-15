// phone_stand: open triangle stand for a phone or small tablet, with a front lip and a
// cable slot. Prints lying on its side, so it needs no supports and the layers run the
// strong way.
use <lib/stone.scad>

width = 70;          // stand width, mm (the print height)
angle = 65;          // back rest angle from the table, degrees
rest = 95;           // back rest length, mm
phone_t = 0;         // phone thickness with its case, mm; the ledge is 2 mm more (0 = use ledge)
ledge = 14;          // room for the phone between lip and rest, mm, when phone_t is 0
lip = 9;             // front lip height, mm
thickness = 6;       // bar thickness, mm
cable_slot = 14;     // notch in the front lip for a charging cable, mm wide (0 = none)
edge = 1;            // rounding on the top edges, mm
quality = 48;        // circle smoothness

$fn = quality;
t = thickness;
gap = phone_t > 0 ? phone_t + 2 : ledge;
top = [gap + rest * cos(angle), rest * sin(angle)];
back = [top[0] + max(18, top[1] * 0.35), 0];
path = [[0, lip], [0, 0], back, top, [gap, 0]];

assert(gap > 4, "the ledge must be more than 4 mm");

module profile() { stroke2d(path, t); }

// lying on its side: the profile is in XY, the width is along Z; centered in X and Y
translate([-(back[0]) / 2, -(top[1]) / 2, 0]) difference() {
    soft_extrude(width, r = edge) profile();
    if (cable_slot > 0)
        // a notch down through the front lip to the ledge floor, so the plug can face forward
        translate([-t, t / 2, width / 2 - cable_slot / 2]) cube([2 * t, lip + t, cable_slot]);
}
