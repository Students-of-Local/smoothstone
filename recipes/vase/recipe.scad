// vase: parametric vase with a smooth profile and a surface style. Hollow by default; set
// solid = true to print it in spiral vase mode instead.
use <lib/vessel.scad>

height = 150;        // mm
base_d = 70;         // diameter at the bottom, mm
mid_d = 105;         // diameter at the widest point, mm
top_d = 60;          // diameter at the top, mm
belly_at = 0.35;     // where the widest point is, 0 to 1 of the height
style = "twisted";   // smooth | ribbed | twisted | faceted | wave
sides = -1;          // polygon sides, 0 = round; -1 = set by style
ribs = -1;           // number of ribs, 0 = none; -1 = set by style
rib_depth = -1;      // rib depth, mm; -1 = set by style
twist = -1;          // turn from bottom to top, degrees; -1 = set by style
wall = 2;            // wall thickness, mm
floor = 2.4;         // floor thickness, mm
solid = false;       // true: a solid body for spiral vase mode
quality = 180;       // points around

S = style == "ribbed"  ? [0, 28, 1.6, 0, 0, 0]
  : style == "twisted" ? [0, 14, 3.5, 140, 0, 0]
  : style == "faceted" ? [9, 0, 0, 72, 0, 0]
  : style == "wave"    ? [0, 18, 2.2, 0, 14, 2]
  : [0, 0, 0, 0, 0, 0];
sd = sides >= 0 ? sides : S[0];
rb = ribs >= 0 ? ribs : S[1];
rd = rib_depth >= 0 ? rib_depth : S[2];
tw = twist >= 0 ? twist : S[3];

assert(belly_at > 0.05 && belly_at < 0.95, "belly_at must be between 0.05 and 0.95");
assert(solid || min(base_d, top_d) > 2 * wall + 2 * rd + 4, "the vase is too narrow for this wall and rib depth");

vessel(height, base_d, mid_d, top_d, belly_at, sd, rb, rd, tw, S[4], S[5],
       wall, floor, solid, 0, quality, max(60, round(height / 1.5)));
