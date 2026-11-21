// lithophane: a photo that appears when light shines through it. Thin where the photo is
// bright, thick where it is dark, in a frame. Stands upright on a foot by default, which is
// also the best way to print it.
use <lib/stone.scad>

image = "";          // height map from stone image (png)
width = 100;         // picture width, mm (the frame adds to it)
min_t = 0.8;         // thickness at white, mm
max_t = 3.2;         // thickness at black, mm
frame = 4;           // frame width, mm
frame_t = 5;         // frame thickness, mm
stand = true;        // print upright on a foot; false prints flat on its back
foot = 24;           // foot depth when standing, mm
quality = 48;        // circle smoothness

$fn = quality;
k = (max_t - min_t) / 100;

assert(image != "", "run stone image first so the picture can be used");
assert(max_t > min_t + 0.4, "max_t must be at least 0.4 mm more than min_t");
assert(frame_t >= max_t, "frame_t must be at least max_t");

// surface(invert = true) gives heights from 0 (black) down to -100 (white) over a base at -101.
// stone image stretches the picture to the full range, so after the resize and the lift by
// max_t, black is max_t thick and white min_t. Not centered: x from -width/2 and y from 0 up,
// so the bottom edge is known without knowing the picture height.
module photo() translate([-width / 2, 0, max_t])
    resize([width, 0, 101 * k], auto = [false, true, false]) surface(file = image, invert = true);

module footprint() projection() photo();

module framed() union() {
    photo();
    linear_extrude(min_t + 0.01) footprint();
    linear_extrude(frame_t) difference() { offset(r = frame) offset(delta = -0.01) footprint(); offset(delta = -0.01) footprint(); }
}

if (!stand) bed_chamfer() framed();
else union() {
    // upright: the bottom frame edge rests on the foot; the photo faces -Y
    translate([0, frame_t / 2, 3 + frame - 0.01]) rotate([90, 0, 0]) framed();
    soft_slab(3, top = 1, bottom = 0.4) rrect(width + 2 * frame, foot, 3);
}
