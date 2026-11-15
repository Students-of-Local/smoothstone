// planter: plant pot with a drain hole and an optional matching saucer.
use <lib/vessel.scad>

height = 90;         // pot height, mm
top_d = 110;         // diameter at the rim, mm
base_d = 80;         // diameter at the bottom, mm
style = "faceted";   // smooth | ribbed | twisted | faceted | wave
sides = -1;          // polygon sides, 0 = round; -1 = set by style
ribs = -1;           // number of ribs, 0 = none; -1 = set by style
rib_depth = -1;      // rib depth, mm; -1 = set by style
twist = -1;          // turn from bottom to top, degrees; -1 = set by style
wall = 2.4;          // wall thickness, mm
floor = 3;           // floor thickness, mm
drain_d = 12;        // drain hole diameter, mm (0 = none)
part = "pot";        // pot | saucer | both
saucer_h = 14;       // saucer height, mm
quality = 180;       // points around

S = style == "ribbed"  ? [0, 32, 1.6, 0, 0, 0]
  : style == "twisted" ? [0, 12, 3, 90, 0, 0]
  : style == "faceted" ? [10, 0, 0, 36, 0, 0]
  : style == "wave"    ? [0, 20, 2, 0, 10, 1.5]
  : [0, 0, 0, 0, 0, 0];
sd = sides >= 0 ? sides : S[0];
rb = ribs >= 0 ? ribs : S[1];
rd = rib_depth >= 0 ? rib_depth : S[2];
tw = twist >= 0 ? twist : S[3];
mid_d = (base_d + top_d) / 2;
gap = 3;

assert(drain_d < base_d - 2 * wall - 10, "drain_d is too big for the base");

module pot() vessel(height, base_d, mid_d, top_d, 0.5, sd, rb, rd, tw, S[4], S[5],
                    wall, floor, false, drain_d, quality, max(60, round(height / 1.5)));

// saucer: shallow dish that the pot base sits in, same style, 6 mm wider than the base
module saucer() {
    sb = base_d + 12;
    vessel(saucer_h, sb, sb + 4, sb + 8, 0.5, sd, rb, min(rd, 1.2), 0, 0, 0,
           2, 2, false, 0, quality, 24);
}

if (part == "pot") pot();
if (part == "saucer") saucer();
if (part == "both") {
    translate([-(top_d / 2 + gap / 2), 0, 0]) pot();
    translate([base_d / 2 + 10 + gap / 2, 0, 0]) saucer();
}
