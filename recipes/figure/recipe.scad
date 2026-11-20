// figure: a 3D figure lifted from photos, standing on a display plinth with its name on the front.
use <lib/stone.scad>

figure = "";          // unit-height mesh from stone build (stone find or stone image first)
height = 90;          // total height with the plinth, mm
base = "round";       // round | hex | none
base_d = 0;           // plinth diameter, mm (0 = fits the figure)
base_h = 0;           // plinth height, mm (0 = 12 with a name, 8 without)
name = "";            // raised along the front of the plinth ("" = none)
font = "sans";        // sans | serif | mono
spin = 0;             // turn the figure on the plinth, degrees
quality = 96;         // circle smoothness

$fn = quality;
F = font == "serif" ? "Liberation Serif:style=Bold" : font == "mono" ? "Liberation Mono:style=Bold" : "Liberation Sans:style=Bold";
bh = base == "none" ? 0 : base_h > 0 ? base_h : name == "" ? 8 : 12;
fh = height - bh;                         // figure height
bd = base_d > 0 ? base_d : max(30, fh * 0.68 + 8, len(name) * fh * 0.075 + 14);
sink = base == "none" ? 0 : min(1.2, bh / 3);

assert(figure != "", "figure needs photos: run stone find \"<who>\" or stone image <photo>, then stone build");
assert(fh > 15, "height is too small for the plinth: make height bigger or base_h smaller");

// a lip at the bed, a drum above it with chamfered edges, the name raised on the drum's front
lip = min(2.4, bh / 4);
c = min(1.2, bh / 8);
dr = bd / 2 - c;                          // drum radius

module plinth() {
    sides = base == "hex" ? 6 : $fn;
    rotate([0, 0, base == "hex" ? 30 : 0]) rotate_extrude($fn = sides) polygon([
        [0, 0], [bd / 2 - c / 2, 0], [bd / 2, c / 2], [bd / 2, lip - c / 2], [dr, lip],
        [dr, bh - c], [dr - c, bh], [0, bh]]);
}

module arc_name() {
    n = len(name);
    band = bh - lip - c;                  // flat height of the drum's side
    ts = min(band * 0.72, bd * 0.11, 10);
    zc = lip + band / 2;
    rr = base == "hex" ? dr * cos(30) : dr;  // the flat face of a hex, or the drum
    step = min(160 / max(n, 1), ts * 0.86 / rr * 180 / PI);
    for (i = [0 : n - 1]) {
        a = -90 - ((n - 1) / 2 - i) * step;
        rotate([0, 0, a + 90]) translate([0, -(rr - 0.3), zc]) rotate([90, 0, 0])
            soft_extrude(1.2, r = 0.3, steps = 2, bottom = 0)
                text(name[i], size = ts, font = F, halign = "center", valign = "center");
    }
}

union() {
    if (base != "none") { plinth(); if (name != "") arc_name(); }
    translate([0, 0, bh - sink]) rotate([0, 0, spin]) scale([fh + sink, fh + sink, fh + sink]) import(figure);
}
