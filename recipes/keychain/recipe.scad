// keychain: name tag from text, or a charm from a picture outline, with a key ring tab.
use <lib/stone.scad>

text = "";           // text for a name tag; when empty, the picture is used
image = "";          // picture outline from stone image (svg)
size = 50;           // artwork width, mm
thickness = 2.4;     // back plate thickness, mm
relief = 1.2;        // how far the artwork stands above the back, mm
border = 2.5;        // back plate margin around the artwork, mm
ring_d = 5;          // key ring hole diameter, mm
font = "sans";       // sans | serif | mono
quality = 48;        // circle smoothness

$fn = quality;
F = font == "serif" ? "Liberation Serif:style=Bold" : font == "mono" ? "Liberation Mono:style=Bold" : "Liberation Sans:style=Bold";

assert(text != "" || image != "", "give text, or run stone image first so the picture can be used");

module art() {
    if (text != "") resize([size, 0], auto = true) text(text, size = 10, font = F, halign = "center", valign = "center");
    else resize([size, 0], auto = true) import(image, center = true);
}

// back plate: the artwork grown by the border, with gaps between letters closed
module back() offset(r = border) offset(r = -3) offset(r = 3) art();

ring_x = -size / 2 - border - ring_d / 2 - 1.5;

module plate2d() {
    back();
    // ring tab: hulled onto the leftmost strip of the back, so it always joins smoothly
    hull() {
        translate([ring_x, 0]) circle(d = ring_d + 5);
        intersection() {
            back();
            translate([-size / 2 - border - 1, -size * 2]) square([size * 0.08 + border + 1, size * 4]);
        }
    }
}

difference() {
    union() {
        soft_extrude(thickness, r = 0.6) plate2d();
        translate([0, 0, thickness - 0.01]) soft_extrude(relief + 0.01, r = 0.4, steps = 3, bottom = 0) art();
    }
    translate([ring_x, 0, 0]) hole(ring_d, thickness, 0.5);
}
