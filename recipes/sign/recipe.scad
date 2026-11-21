// sign: plaque with raised text, a raised rim and optional picture and hanging holes.
use <lib/stone.scad>

text = "HELLO";      // the words on the sign
w = 160;             // sign width, mm
h = 50;              // sign height, mm
thickness = 4;       // plate thickness, mm
relief = 1.6;        // how far text and rim stand up, mm
rim = 2.5;           // raised rim width, mm (0 = none)
text_size = 0;       // letter height, mm; 0 = as big as fits
font = "sans";       // sans | serif | mono
icon = "";           // picture outline from stone image, shown left of the text ("" = none)
holes = "top";       // top | none
corner_r = 6;        // corner radius, mm
quality = 64;        // circle smoothness

$fn = quality;
F = font == "serif" ? "Liberation Serif:style=Bold" : font == "mono" ? "Liberation Mono:style=Bold" : "Liberation Sans:style=Bold";
m = rim + 5;                       // margin inside the rim
ih = h - 2 * m;                    // icon and text box height
slot = icon != "" ? ih * 1.25 : 0; // room for the icon
tw_avail = w - 2 * m - slot - (holes == "top" ? 0 : 0);
tm = textmetrics(text, size = 10, font = F);
t10 = is_undef(tm) ? [len(text) * 6.8, 10] : tm.size;
fit = min(tw_avail / t10[0], ih / t10[1]) * 10;
ts = text_size > 0 ? text_size : fit * 0.95;
hy = holes == "top" ? 4 : 0;       // nudge the art down when there are holes

// the letters, for the stroke check: [height, font, the setting that grows them, its value].
// Fitted letters grow with the side that limits them.
wide = tw_avail / t10[0] <= ih / t10[1];
if (text != "") echo(stone_text = [ts, font, text_size > 0 ? "text_size" : wide ? "w" : "h",
                                   text_size > 0 ? text_size : wide ? w : h]);

assert(h > 2 * m + 6, "the sign is too short for the rim: make h bigger");

module words() translate([slot / 2, -hy / 2]) text(text, size = ts, font = F, halign = "center", valign = "center");

difference() {
    union() {
        soft_slab(thickness, top = 0.8, bottom = 0.4) rrect(w, h, corner_r);
        translate([0, 0, thickness - 0.01]) soft_extrude(relief + 0.01, r = 0.4, steps = 3, bottom = 0) {
            words();
            if (rim > 0) difference() { rrect(w - 2, h - 2, corner_r - 1); rrect(w - 2 - 2 * rim, h - 2 - 2 * rim, corner_r - 1 - rim); }
            if (icon != "") translate([-w / 2 + m + slot / 2, -hy / 2]) resize([0, ih - hy], auto = true) import(icon, center = true);
        }
    }
    if (holes == "top") for (sx = [-1, 1]) translate([sx * (w / 2 - m - 2), h / 2 - m + 1, 0]) hole(4.2, thickness, 0.5);
}
