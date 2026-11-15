// relief: a picture carved in relief on a plaque, bright parts high and dark parts low,
// with a rounded frame. Flat on the bed.
use <lib/stone.scad>

image = "";          // height map from stone image (png)
width = 100;         // picture width, mm
depth = 2.5;         // relief depth, mm
base_t = 2.4;        // plaque thickness under the relief, mm
frame = 5;           // frame width, mm
invert = false;      // true: dark parts high
quality = 48;        // circle smoothness

$fn = quality;
k = depth / 100;

assert(image != "", "run stone image first so the picture can be used");

// surface() heights run 0 to 100 over a base at -1, or 0 to -100 over -101 when inverted;
// stone image stretches the picture to the full range, so both land on base_t to base_t + depth
module art() translate([-width / 2, 0, base_t + (invert ? 100 * k : 0)])
    resize([width, 0, 101 * k], auto = [false, true, false]) surface(file = image, invert = invert);

module footprint() projection() art();

union() {
    art();
    linear_extrude(base_t + 0.01) footprint();
    // frame: a rounded rim, a little taller than the highest relief
    soft_extrude(base_t + depth + 0.6, r = 1.2) difference() {
        offset(r = frame) offset(delta = -0.01) footprint();
        offset(delta = -0.01) footprint();
    }
    linear_extrude(base_t) offset(r = frame) offset(delta = -0.01) footprint();
}
