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
sink = base == "none" ? 0 : min(1.2, bh / 3);

assert(figure != "", "figure needs photos: run stone find \"<who>\" or stone image <photo>, then stone build");
assert(fh > 15, "height is too small for the plinth: make height bigger or base_h smaller");

// a lip at the bed, a drum above it with chamfered edges, the name raised on the drum's front
lip = min(2.4, bh / 4);
c = min(1.2, bh / 8);
band = bh - lip - c;                      // flat height of the drum's side
// the name's width per mm of letter height
tm = name != "" ? textmetrics(name, size = 10, font = F) : undef;
nw = is_undef(tm) ? len(name) * 0.7 : tm.size[0] / 10;
// the tallest letters the side takes; the plinth is wide enough for them (letters are at most
// 0.11 of it), and a hex, which lays the name flat on its front face, as wide as the drum
// radius, has room for the whole name with c clear at each corner
ts_side = min(band * 0.72, 10);
bd = base_d > 0 ? base_d : max(30, fh * 0.68 + 8, name == "" ? 0 : ts_side / 0.11,
    base == "hex" ? 2 * (nw * ts_side + 3 * c) : len(name) * fh * 0.075 + 14);
dr = bd / 2 - c;                          // drum radius (a hex's corners)

module plinth() {
    // a hex turns a face, not a corner, to the front (-Y)
    rotate_extrude($fn = base == "hex" ? 6 : $fn) polygon([
        [0, 0], [bd / 2 - c / 2, 0], [bd / 2, c / 2], [bd / 2, lip - c / 2], [dr, lip],
        [dr, bh - c], [dr - c, bh], [0, bh]]);
}

module name_text(t, size) soft_extrude(1.2, r = 0.3, steps = 2, bottom = 0)
    text(t, size = size, font = F, halign = "center", valign = "center");

module plinth_name() {
    n = len(name);
    by_h = band * 0.72;  // ts_side, unless the font cap is the limit
    by_d = min(bd * 0.11, base == "hex" ? (dr - 2 * c) / max(nw, 0.01) : 1e9);
    ts = min(by_h, by_d, 10);
    zc = lip + band / 2;
    // for the stroke check: [height, font, the setting that grows the letters, its value]. At
    // the 10 mm cap only the font is left to change.
    lim = ts >= 10 ? "font" : ts >= by_h ? "base_h" : "base_d";
    echo(stone_text = [ts, font, lim, lim == "font" ? 0 : lim == "base_h" ? bh : bd]);
    if (base == "hex") {
        // flat on the front face, 0.3 mm into it, 0.9 mm proud
        translate([0, -(dr * cos(30) - 0.3), zc]) rotate([90, 0, 0]) name_text(name, ts);
    } else {
        // one letter at a time around the drum
        step = min(160 / max(n, 1), ts * 0.86 / dr * 180 / PI);
        for (i = [0 : n - 1]) {
            a = -90 - ((n - 1) / 2 - i) * step;
            rotate([0, 0, a + 90]) translate([0, -(dr - 0.3), zc]) rotate([90, 0, 0]) name_text(name[i], ts);
        }
    }
}

module figure_mesh() translate([0, 0, bh - sink]) rotate([0, 0, spin]) scale([fh + sink, fh + sink, fh + sink]) import(figure);

union() {
    if (base != "none") { plinth(); if (name != "") plinth_name(); figure_mesh(); }
    // standing on its own feet, the figure gets the bed chamfer the plinth has
    else bed_chamfer() figure_mesh();
}
