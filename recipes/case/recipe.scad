// case: open-front enclosure with one display/button window and one side port cutout.
// Printed lying on its back, so the walls grow straight up and no support is needed.
// The four screw posts sit in the back corners with the holes facing forward (-Y).
// The front closes with a separate cover part. It prints upside down (outer face on the bed), drops
// onto the front rim and snaps shut: two cantilever hooks on the cover's rim, both on the -X wall, rise
// into two catch pockets cut into that wall (snap_hook, recipes/lib/stone.scad); the rim's fit holds
// the +X side. close=none leaves the case open and prints
// the body alone; the screw posts stay as an option (post_d).
use <lib/stone.scad>

w = 80;               // outside width, mm
d = 60;               // outside depth, mm
h = 30;               // outside height, mm
wall = 2.5;           // wall thickness, mm
floor = 2.5;          // back wall thickness, mm
corner_r = 6;         // outside corner radius, mm
win_w = 50;           // window width, mm (0 = no window)
win_h = 20;           // window height, mm
win_z = 5;            // window bottom edge above the inside floor, mm
port_w = 12;          // port cutout width, mm (0 = no port)
port_h = 8;           // port cutout height, mm
port_z = 4;           // port cutout bottom edge above the inside floor, mm
post_d = 6;           // screw post diameter, mm (0 = no posts)
post_hole_d = 2.6;    // screw hole diameter, mm (2.6 fits an M3 screw)
close = "snap";       // snap | none: a snap-on cover, or the body alone
part = "both";        // both | body | cover
clr = 0.25;           // cover-to-wall clearance per side, mm (FDM 0.2-0.3)
cover_t = 2.5;        // cover plate thickness, mm
material = "PLA";     // PLA | PETG | TPU (the snap strain limit)
quality = 64;         // circle smoothness

$fn = quality;

assert(wall >= 1.6, "wall must be at least 1.6 mm");
assert(win_w <= w - 2 * wall - 4, "window is wider than the case allows");
assert(win_z + win_h <= h - wall - 2, "window is taller than the case allows");
assert(port_h <= h - 2 * wall - 2, "port cutout is taller than the case allows");
assert(post_d == 0 || post_d >= post_hole_d + 1.2, "screw post is too thin for its hole");
assert(clr >= 0.1 && clr <= 0.4, "cover clearance must be 0.1 to 0.4 mm per side");
assert(cover_t >= 1.6, "cover plate must be at least 1.6 mm");

inner_w = w - 2 * wall;
inner_d = d - 2 * wall;
inner_h = h - 2 * wall;
SNAP = close == "snap";
eps = 0.01;
// hook arm length: the arm plus its catch and ramp has to end exactly at the cover's top (h), so the
// cover stays the size the recipe claims.
hook_t = 1.2;         // the arm's thickness: the snap_hook arm is a real arm, not a catch bump
hook_w = 6;
hook_bite = 0.8;      // how far the catch reaches into the wall; wall - bite must stay >= 1.6 mm
hook_rise = hook_bite + 0.5;
// the catch's ledge: the solid wall the catch's flat face bears on, under it. The hook stops short of
// the plate by this much so the ramp's foot lands on the ledge, not the plate.
hook_ledge = 2.5;     // solid wall left under the catch's flat face: the pocket's floor
// the catch's flat face sits hook_ledge above the pocket's floor, and the ramp runs from the floor
// up to the catch, so the cover springs in and the catch bears on the ledge on the way out
hook_L = h - cover_t - hook_t - hook_rise * 1.732 - hook_ledge;
// snap_hook grows along +Y from its root; rotate it +90 about X so it stands up along +Z.
// The rim's inner face pulls in at the corners (it is an rrect), so a hook at this y sits on that
// curve, not on the straight edge x = -inner_w / 2 + clr. rim_in is the rim's inner face at the hook.
hook_y = inner_d / 2 - clr - hook_w / 2 - 1.5;
rim_r = max(corner_r - wall - clr, 0.5);
rim_in = inner_w / 2 - 2 * clr - rim_r + rim_r * sqrt(max(
    1 - pow((abs(hook_y) - (inner_d / 2 - 2 * clr - rim_r)) / rim_r, 2), 0));
HOOKS = [for (y = [-1, 1]) [-(rim_in - clr), y * hook_y]];
// the catch's pocket: a window in the wall, hook_w wide, from the ramp's foot to just above the
// catch's top, and from wall-deep inside the wall's inner face (it curves in at the corner) out past
// the catch's tip; case_body cuts it from the shell only. The catch springs into it and
// bears on the solid wall above it when the cover is pulled off. It reaches the outer face but never
// the back plate. The cover turns over when it goes on, so the window takes the catch either way.
module catch_pocket() {
    tip = rim_in - clr + hook_rise;
    floor_z = h - hook_L - hook_t - hook_rise * 1.732 - clr;
    top_z = h - hook_L + clr;
    for (p = HOOKS)
        translate([-tip, p[1] - hook_w / 2, floor_z])
            cube([tip - (inner_w / 2 - wall) + 0.02, hook_w, top_z - floor_z + eps]);
}
// the window's and the port's cut boxes, shared by the case body and the cover (so a cover hook on a
// wall that has a cutout is trimmed by the same box instead of floating inside the cut)
module win_box() {
    if (win_w > 0 && win_h > 0)
        translate([-win_w / 2, 0, wall + win_z]) cube([win_w, 3 * d, win_h]);
}
module port_box() {
    if (port_w > 0 && port_h > 0)
        translate([w / 2 - 1, 0, wall + port_z]) cube([3 * w, port_w, port_h]);
}

module shell() difference() {
    // outside: back face on the bed at z = 0
    linear_extrude(h) rrect(w, d, corner_r);
    // cavity opens toward the top
    translate([0, 0, floor])
        linear_extrude(h) rrect(inner_w, inner_d, max(corner_r - wall, 0.5));
    // the open front, cut straight through: without it the shell has a hollow inside that manifold
    // reads as separate bodies (the front face is solid)
    translate([0, 0, floor])
        linear_extrude(h) rrect(inner_w - 2 * wall, inner_d - 2 * wall, max(corner_r - 2 * wall, 0.5));
}

module window_cut() win_box();
module port_cut() port_box();

// posts stand on the inside floor (not the outer back face) and stop exactly at the inside rim, so
// they fuse into the walls: a free-standing post reads as a separate body and fails the one-piece check
module posts() {
    if (post_d > 0) {
        for (x = [-1, 1], y = [-1, 1])
            translate([x * (inner_w / 2 - post_d / 2 - 0.5),
                       y * (inner_d / 2 - post_d / 2 - 0.5),
                       floor - 1]) {
                cylinder(d = post_d, h = h - floor);
            }
    }
}

module post_holes() {
    if (post_d > 0 && post_hole_d > 0) {
        for (x = [-1, 1], y = [-1, 1])
            translate([x * (inner_w / 2 - post_d / 2 - 0.5),
                       y * (inner_d / 2 - post_d / 2 - 0.5),
                       floor - 0.5])
                cylinder(d = post_hole_d, h = h + 1);
    }
}

// the rim would run straight through the screw posts, so each post gets a notch of its own size plus
// the cover clearance. The notch stops short of the wall (it only takes the rim's own thickness)
module post_notches() {
    if (post_d > 0) {
        for (x = [-1, 1], y = [-1, 1])
            translate([x * (inner_w / 2 - post_d / 2 - 0.5),
                       y * (inner_d / 2 - post_d / 2 - 0.5),
                       cover_t - eps])
                cylinder(d = post_d + 2 * clr + 0.4, h = h);
    }
}

module case_body() {
    difference() {
        union() {
            // the catch pockets cut the shell only: they reach wall-deep inside the wall's face to
            // clear it where it curves into the corner, and the screw posts there must stay whole
            difference() { shell(); if (SNAP) catch_pocket(); }
            posts();
        }
        window_cut();
        port_cut();
        post_holes();
    }
}

// the cover: a plate the size of the front, a rim that drops into the opening (clr per side), and a
// hook standing on each rim corner. Printed upside down: outer face on the bed, rim and hooks up.
// A hook on a wall that has a cutout would stand inside the cut and be a separate piece; trimming
// it by the same cut box makes it share a face with the rim, so it stays one body.
// The rim is the plate's own wall (wall thick), so the hooks hang off the plate's edge and need no
// thin rim of their own.
module cover() {
    difference() {
        union() {
            linear_extrude(cover_t) rrect(w, d, corner_r);
            translate([0, 0, cover_t - eps]) linear_extrude(h - cover_t)
                rrect(inner_w - 2 * clr, inner_d - 2 * clr, max(corner_r - wall - clr, 0.5));
            if (SNAP) for (p = HOOKS)
                translate([p[0], p[1], cover_t - eps])
                    rotate([90, 0, 0])
                        snap_hook(L = hook_L, t = hook_t, w = hook_w, rise = hook_rise);
        }
        translate([0, 0, cover_t - eps]) linear_extrude(h)
            rrect(inner_w - 2 * clr - 2 * wall, inner_d - 2 * clr - 2 * wall,
                  max(corner_r - 2 * wall - clr, 0.5));
        // the arm slots: cut the rim either side of each hook so the hook is a free cantilever that can
        // bend when its ramp rides over the rim. One slot per side of each hook, 2*clr wide, through the
        // rim's own wall (from its outer face in to its inner face) and its full height.
        if (SNAP) for (p = HOOKS) for (s = [-1, 1])
            translate([-(inner_w - 2 * clr) / 2 - 1, p[1] + s * hook_w / 2 + (s < 0 ? -2 * clr : 0), cover_t - eps])
                cube([2 * wall + 2, 2 * clr, h - cover_t + 1]);
        win_box();
        port_box();
        post_notches();
    }
}

// the cover as it prints: outer face on the bed, plate at z = 0, rim and hooks growing up from it.
module cover_on_bed() cover();

// bed_chamfer: both parts print on a flat face, so their bottom edges are chamfered for elephant foot
if (!SNAP || part == "body") bed_chamfer() case_body();
if (SNAP && part == "cover") bed_chamfer() cover_on_bed();
if (SNAP && part == "both") {
    bed_chamfer() case_body();
    translate([w + 6, 0, 0]) bed_chamfer() cover_on_bed();
}
