// round_case: a snap shut case for a round product in the catalog (a tracker tag, a puck), built
// from the maker's published profile (recipes/lib/catalog.scad). Two half shells follow the
// product's own profile at the clearance; a C shaped flexure joins them at the back and a
// cantilever latch closes the front, so the product goes in with the case opened, not forced
// past a rigid lip. Every feature the maker locates on the top stays open (the top opening
// clears the largest one); with none, a rim of `lip` mm holds the top edge. Prints flat on its
// floor, opening up, no supports.
// Reference design by GPT-6.1 Sol, smoothstone gold set (evals/gold/e04_airtag_case): the
// profile offset, split shells, rear C flexure and front latch are its geometry, sized here
// from the product's diameter instead of the AirTag's.
use <lib/stone.scad>
include <lib/catalog.scad>

product = "apple_airtag"; // a catalog slug: a round product
material = "PETG";        // PETG | PLA
clearance = 0.2;          // per side along the profile's normal, mm
wall = 1.6;               // shell and floor, mm
lip = 3;                  // how far the rim reaches in over the top edge when no top feature is located, mm
quality = 96;             // circle smoothness

$fn = quality;
R = catalog_row(product);
assert(len(R) > 0, str("no product named ", product, " in the catalog; set product to a catalog name"));
W = R[1][0];
D = R[1][1];
H = R[1][2];
assert(abs(W - D) < 0.01, str(product, " is not round (w ", W, ", d ", D, "): use product_holder or fitted_case"));
PROF = len(R[3]) > 2 ? R[3] : [[0, 0], [W / 2, 0], [W / 2, H], [0, H]];
FEATS = R[6];

gap = clearance;
tag_z = wall + gap;                 // the product's bottom above the bed
outer_r = W / 2 + gap + wall;
assert(outer_r >= 9, "the product is too small for a hinged case (under 15 mm across)");
foot_chamfer = 0.35;
split = 0.7;                        // the seam that frees the two half shells

OPEN = R[4];

// The top opening: the circle about the axis that clears every feature the maker locates on the
// top, plus 0.2 mm; with no top feature, a rim `lip` wide. A product whose top stays clear (open
// faces +z: a cup it sits down into) gets no rim at all: the opening is the cavity itself.
function reach(f) = norm([f[3] - W / 2, f[4] - D / 2]) +
    (f[9] ? max(f[5], f[7]) / 2 : norm([max(f[5], f[7]) / 2, max(f[6], f[8]) / 2]));
TOP = [for (f = FEATS) if (f[2] == "+z" && f[1] != "hole") reach(f)];
top_open = len([for (o = OPEN) if (o == "+z") 1]) > 0;
open_r = top_open ? W / 2 + gap + 0.01 : len(TOP) > 0 ? max(TOP) + 0.2 : W / 2 - lip;

// Rear flexure and front latch, scaled from the gold part's 17.685 mm outer radius.
hinge_t = 1.4;
hinge_r = 0.65 * outer_r;
hinge_y = -(outer_r + 0.315);
hinge_join_y = -sqrt(pow(outer_r - 0.7, 2) - hinge_r * hinge_r);
arm_t = 1.4;
arm_L = min(14, round(0.8 * outer_r));
arm_root_x = -arm_L / 2;
arm_end_x = arm_L / 2;
arm_y = outer_r + 1.215;
arm_h = min(6.8, tag_z + H * 0.85);
catch_y = 0.8;
catch_shoulder_x = arm_end_x - 1.4;
catch_flat_x = arm_end_x - 1.0;
receiver_x0 = arm_end_x - 3.5;
receiver_x = arm_end_x - 1.7;
receiver_y = arm_y - 1.0;
root_face = arm_y - arm_t / 2;
ped_y0 = sqrt(pow(outer_r, 2) - pow(arm_root_x - 0.81, 2)) - 0.6;
rcv_y0 = sqrt(pow(outer_r, 2) - pow(receiver_x, 2)) - 0.87;

// Offset each straight segment of the profile along its normal; neighbors meet at their miter.
function outward(a, b) = let(e = b - a) [e[1], -e[0]] / norm(e);
function offset_vertex(i, o) =
    let(n = len(PROF), p = PROF[i],
        a = outward(PROF[(i + n - 1) % n], p),
        b = outward(p, PROF[(i + 1) % n]),
        q = p + o * (a + b) / (1 + a * b)) [max(0, q[0]), q[1]];
function offset_profile(o) = [for (i = [0:len(PROF) - 1]) offset_vertex(i, o)];
function outer_profile() = concat(
    [[0, -tag_z], [outer_r - foot_chamfer, -tag_z], [outer_r, -tag_z + foot_chamfer]],
    [for (i = [2:len(PROF) - 1]) offset_vertex(i, gap + wall)]);

// a feature on a side or the bottom: its plug's box cut out along the face's normal
module side_windows() {
    for (f = FEATS) if (f[1] != "hole" && f[2] != "+z") {
        sw = max(f[5], f[7]) + 1;
        sh = max(f[6], f[8]) + 1;
        L = W;
        if (f[2] == "-z") translate([W - f[3] - W / 2, f[4] - D / 2, -tag_z - 1])
            if (f[9]) cylinder(d = sw, h = tag_z + 1.01); else translate([-sw / 2, -sh / 2, 0]) cube([sw, sh, tag_z + 1.01]);
        else {
            rz = f[2] == "-y" ? 0 : f[2] == "+x" ? 90 : f[2] == "+y" ? 180 : 270;
            rotate([0, 0, rz]) translate([f[3] - W / 2, 0, f[4]]) rotate([90, 0, 0])
                if (f[9]) cylinder(d = sw, h = L); else translate([-sw / 2, -sh / 2, 0]) cube([sw, sh, L]);
        }
    }
}

module round_shell() {
    difference() {
        translate([0, 0, tag_z]) rotate_extrude(convexity = 10) polygon(outer_profile());
        translate([0, 0, tag_z]) rotate_extrude(convexity = 10) polygon(offset_profile(gap));
        translate([0, 0, tag_z]) cylinder(h = H + wall + 2, r = open_r);
        translate([0, 0, tag_z]) side_windows();
        translate([-split / 2, -outer_r - 1, -1]) cube([split, 2 * outer_r + 2, tag_z + H + wall + 2]);
    }
}

module rear_flexure() {
    linear_extrude(height = wall) union() {
        difference() {
            translate([0, hinge_y]) difference() {
                circle(r = hinge_r + hinge_t / 2);
                circle(r = hinge_r - hinge_t / 2);
            }
            translate([-hinge_r - hinge_t, hinge_y]) square([2 * (hinge_r + hinge_t), 2 * (hinge_r + hinge_t)]);
        }
        for (side = [-1, 1]) hull() {
            translate([side * hinge_r, hinge_y]) circle(d = hinge_t);
            translate([side * hinge_r, hinge_join_y]) circle(d = hinge_t);
        }
    }
}

// The latch arm lies on the bed and bends in the layers; its catch faces the case.
module latch_arm() {
    translate([arm_root_x - 0.4, root_face, 0]) cube([arm_end_x - arm_root_x + 0.4, arm_t, arm_h]);
    linear_extrude(height = arm_h)
        polygon([[catch_shoulder_x, root_face + 0.05], [catch_shoulder_x, root_face - catch_y],
                 [catch_flat_x, root_face - catch_y], [arm_end_x, root_face + 0.05]]);
    // the root pedestal, taller than the arm, joins the left half only
    linear_extrude(height = arm_h + 1.2) hull() {
        translate([arm_root_x - 0.81, ped_y0]) circle(r = 0.8);
        translate([arm_root_x - 0.81, arm_y]) circle(r = 0.8);
    }
}

// the receiver on the right half, 0.3 mm behind the catch's square shoulder
module latch_receiver() {
    linear_extrude(height = arm_h)
        polygon([[receiver_x0, rcv_y0], [receiver_x, rcv_y0], [receiver_x, receiver_y],
                 [receiver_x - 0.5, receiver_y], [receiver_x0, receiver_y - 0.6]]);
}

// one 0.4 mm bed chamfer under everything, so the first layer does not flare (elephant foot)
bed_chamfer() union() {
    round_shell();
    rear_flexure();
    latch_arm();
    latch_receiver();
}

// What engineering.json says (smoothstone/fitted.py reads it from the build log).
echo(stone_eng = [
    ["frame", [[1, 0, 0, -W / 2], [0, 1, 0, -D / 2], [0, 0, 1, tag_z], [0, 0, 0, 1]]],
    ["clearance", gap],
    ["retention", [["type", "snap"], ["y", catch_y], ["t", arm_t], ["L", arm_L], ["w", arm_h],
                   ["at", [arm_root_x, arm_y, arm_h / 2]], ["t_dir", [0, -1, 0]], ["L_dir", [1, 0, 0]]]]
]);
