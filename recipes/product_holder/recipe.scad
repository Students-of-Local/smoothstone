// product_holder: an open top cradle that holds a real product from the catalog on a desk or on a
// wall, built from the maker's published sizes (recipes/lib/catalog.scad). The product drops in
// from above. It wraps the product's bottom and sides at the clearance; a face the maker says
// must stay clear (a screen, ports the maker does not locate) gets only a low stop, under 5% of
// its height. A product lying flat gets walls to its full height; one standing upright gets low
// side guides and a backrest a third of its height. Features the maker locates underneath (a
// charging port, speaker holes) raise the product on a shelf over a foot, with the port's plug
// path and a cable slot open to the front. On a wall, two countersunk screws go through a wall of
// the cradle (its back, or a side when the back must stay clear), and the floor is sized for the
// load hanging off them. Prints on its floor, no supports.
// Reference designs by GPT-6.1 Sol, smoothstone gold set (evals/gold/e05_appletv_wall_holder and
// e06_iphone_desk_holder): the wall cradle, its countersinks and stops, and the raised shelf with
// its 45 degree underside, backrest and cable slot are their geometry, sized here from the product.
use <lib/stone.scad>
use <lib/product.scad>
include <lib/catalog.scad>

product = "apple_tv_4k_3rd_gen"; // a catalog slug
mount = "desk";        // desk | wall
material = "PLA";      // PLA | PETG
clearance = 0.3;       // per side, mm
wall = 3.2;            // side walls, mm (a wall that takes screws is at least 4)
load = 20;             // N the holder is designed to carry on a wall
screw = 4;             // wall screw size, M (4 = M4)
quality = 64;          // circle smoothness

$fn = quality;
R = catalog_row(product);
assert(len(R) > 0, str("no product named ", product, " in the catalog; set product to a catalog name"));
W = R[1][0];
D = R[1][1];
H = R[1][2];
OPEN = R[4];
FEATS = R[6];
C = clearance;
SIDES = ["+x", "-x", "+y", "-y"];
function open_face(f) = has(OPEN, f);

upright = H > max(W, D);
STOP = clamp(0.05 * H, 1.5, 6);          // a stop on an open face, above the product's bottom
STOP_T = 2.4;                             // its thickness, six 0.4 mm lines
// the side that goes against the wall: the back, else a side the maker does not need clear
ATTACH = mount != "wall" ? "" :
    !open_face("+y") ? "+y" : !open_face("-x") ? "-x" : !open_face("+x") ? "+x" : "";
assert(mount != "wall" || ATTACH != "", "every side of this product must stay clear: no wall to screw through");
BORE = iso273_medium(screw);
HEAD = 2 * screw + 1;                     // ISO 7046 flat head (8.4 for M4) plus room
SINK = (HEAD - BORE) / 2;                 // the countersink's depth
TA = max(wall, SINK + 1.75);              // a wall that takes screws keeps 1.75 mm of straight bore
function t(f) = open_face(f) ? STOP_T : f == ATTACH ? TA : wall;
// how high each side rises above the product's bottom
function rise(f) = open_face(f) ? STOP :
    !upright ? H : f == "+y" ? clamp(H / 3, 20, 80) : clamp(0.12 * H, 10, 30);

// Underneath: a port's plug path (its depth) or a vent's opening needs air below the product.
UNDER = [for (f = FEATS) if (f[2] == "-z" && f[1] != "hole") f];
PORTS = [for (f = UNDER) if (f[10] > 0) f];
RISER = len(UNDER) == 0 ? 0 : len(PORTS) > 0 ? max([for (f = PORTS) f[10]]) + 18 : wall + 12;
FLOOR = mount == "wall" ? max(wall, 4) : wall;
SHELF_T = 4;                              // the raised shelf at its front, and the backrest
BASE_T = 4;                               // the foot under a raised shelf
Z0 = RISER > 0 ? RISER : C + FLOOR;       // the product's bottom above the bed

XL = -C - t("-x");
XR = W + C + t("+x");
YF = -C - t("-y");
YB = D + C + (RISER > 0 ? SHELF_T : t("+y"));
FOOT_D = max(D + 2 * C + 2 * wall + 20, 0.47 * H);
FOOT_Y0 = min(D / 2 - FOOT_D / 2, YF);
FOOT_Y1 = max(D / 2 + FOOT_D / 2, YB);

// the cable slot under each port: its plug plus 0.5 mm a side, open to the front
SLOTS = [for (f = PORTS) [W - f[3] - max(f[5], f[7]) / 2 - 0.5, W - f[3] + max(f[5], f[7]) / 2 + 0.5,
                          f[4] + max(f[6], f[8]) / 2 + 0.5]];

module walls_flat() {
    // floor
    translate([XL, YF, -C - FLOOR]) cube([XR - XL, YB - YF, FLOOR + 0.01]);
    for (f = SIDES) {
        top = rise(f);
        if (f == "-x") translate([XL, YF, -C - FLOOR]) cube([t(f), YB - YF, C + FLOOR + top]);
        if (f == "+x") translate([XR - t(f), YF, -C - FLOOR]) cube([t(f), YB - YF, C + FLOOR + top]);
        if (f == "-y") translate([XL, YF, -C - FLOOR]) cube([XR - XL, t(f), C + FLOOR + top]);
        if (f == "+y") translate([XL, YB - t(f), -C - FLOOR]) cube([XR - XL, t(f), C + FLOOR + top]);
    }
}

// a raised shelf grown from the backrest, its underside at 45 degrees, over a foot
module walls_raised() {
    shelf_z = -C;
    translate([XL - 3.5, FOOT_Y0, -Z0]) linear_extrude(BASE_T)
        offset(r = 4) offset(delta = -4) square([XR - XL + 7, FOOT_Y1 - FOOT_Y0]);
    // backrest, from the foot up
    translate([XL, D + C, -Z0 + BASE_T - 0.01]) cube([XR - XL, SHELF_T, Z0 - BASE_T + rise("+y") + 0.01]);
    // the shelf, clipped above the foot
    intersection() {
        multmatrix([[0, 0, 1, XL], [1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1]]) linear_extrude(XR - XL)
            polygon([[YF, shelf_z - SHELF_T], [YF, shelf_z], [YB, shelf_z], [YB, shelf_z - SHELF_T - (YB - YF)]]);
        translate([XL - 1, YF - 1, -Z0 + BASE_T - 0.02]) cube([XR - XL + 2, YB - YF + 2, Z0]);
    }
    // front lip and side guides on the shelf
    translate([XL, YF, shelf_z - 0.02]) cube([XR - XL, t("-y"), C + rise("-y") + 0.02]);
    translate([XL, YF, shelf_z - 0.02]) cube([t("-x"), YB - YF, C + rise("-x") + 0.02]);
    translate([XR - t("+x"), YF, shelf_z - 0.02]) cube([t("+x"), YB - YF, C + rise("+x") + 0.02]);
}

// the attach holes: two, along the attach wall at a fifth of its length from each end, half way
// up the part of the wall that covers the product
function attach_holes() =
    ATTACH == "" ? [] :
    let(L = face_len(ATTACH, W, D), v = min(rise(ATTACH), H) / 2)
    [for (u = [0.2 * L, 0.8 * L]) [u, v]];

module attach_cuts() {
    if (ATTACH != "") for (h = attach_holes()) on_face(ATTACH, W, D)
        translate([h[0], h[1], C + t(ATTACH)]) mirror([0, 0, 1]) csk_through(BORE, HEAD, t(ATTACH));
}

module holder() {
    difference() {
        if (RISER > 0) walls_raised(); else walls_flat();
        // the product's own room, so nothing above stands inside it
        translate([-C, -C, -C]) cube([W + 2 * C, D + 2 * C, H + 50]);
        side_windows(FEATS, [for (f = SIDES) if (!open_face(f)) f], W, D, C - 1, C + max(TA, wall) + 1);
        for (s = SLOTS) translate([s[0], FOOT_Y0 - 1, -Z0 - 1]) cube([s[1] - s[0], s[2] - FOOT_Y0 + 1, Z0 + H]);
        for (f = UNDER) if (f[10] <= 0) {
            sw = max(f[5], f[7]) + 1;
            sh = max(f[6], f[8]) + 1;
            translate([W - f[3] - sw / 2, f[4] - sh / 2, RISER > 0 ? -Z0 + BASE_T + 0.02 : -Z0 - 1]) cube([sw, sh, Z0 + 1]);
        }
        attach_cuts();
    }
}

// the part with the bed at z = 0 and its min corner at the origin
OX = -XL + (RISER > 0 ? 3.5 : 0);
OY = RISER > 0 ? -FOOT_Y0 : -YF;
M = [[1, 0, 0, OX], [0, 1, 0, OY], [0, 0, 1, Z0], [0, 0, 0, 1]];
bed_chamfer() translate([OX, OY, Z0]) holder();

// The load on a wall: the floor (or shelf) cantilevers out from the attach wall. Its section
// is cut 0.5 mm in from the wall's inner face, the arm to the product's middle plus 1 mm.
// The section's width b along the wall: the longest unbroken run of the floor there.
function sorted(v) = len(v) <= 1 ? v : let(p = v[0][0])
    concat(sorted([for (e = v) if (e[0] < p) e]), [for (e = v) if (e[0] == p) e], sorted([for (e = v) if (e[0] > p) e]));
CUTS = ATTACH == "+y" || ATTACH == "" ? sorted([for (s = SLOTS) [s[0], s[1]]]) : [];
RUNS = let(edges = concat([XL], [for (c = CUTS) each [c[0], c[1]]], [XR]))
    [for (i = [0:2:len(edges) - 1]) [edges[i], edges[i + 1]]];
RUN = let(best = max([for (r = RUNS) r[1] - r[0]])) [for (r = RUNS) if (r[1] - r[0] == best) r][0];
SEC_H = RISER > 0 ? SHELF_T : FLOOR;
SEC_Z = RISER > 0 ? -C - SHELF_T / 2 : -C - FLOOR / 2;
SEC = ATTACH == "-x" ? [[-C + 0.5, D / 2, SEC_Z], [0, 1, 0], YB - YF, W / 2 + C + 1] :
      ATTACH == "+x" ? [[W + C - 0.5, D / 2, SEC_Z], [0, 1, 0], YB - YF, W / 2 + C + 1] :
                       [[(RUN[0] + RUN[1]) / 2, D + C - 0.5, SEC_Z], [1, 0, 0], RUN[1] - RUN[0] - 0.4, D / 2 + C + 1];

echo(stone_eng = concat([
    ["frame", M],
    ["clearance", C],
    ["retention", [["type", "none"]]]],
    ATTACH == "" ? [] : [
    ["load", [["n", load], ["dir", "-z"], ["arm", SEC[3]], ["b", SEC[2]], ["h", SEC_H], ["across_layers", false],
              ["section", [["at", xf_pt(M, SEC[0])], ["b_dir", SEC[1]], ["h_dir", [0, 0, 1]]]]]],
    ["attach", [["holes", [for (h = attach_holes()) [["at", xf_pt(M, face_pt(ATTACH, h[0], h[1], C + t(ATTACH), W, D))]]]]]]]
));
