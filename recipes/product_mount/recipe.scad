// product_mount: a mount that hangs a real product from the catalog under a desk or shelf, built
// from the maker's published sizes (recipes/lib/catalog.scad). A roof screws up into the desk
// (pan head screws in counterbores, driven from below between the rails), side walls wrap the
// product, and two rails under its bottom carry its weight in all four quarters. Its front and
// back stay open for ports; two snap tabs at the front and two fixed stops at the back keep it
// from sliding out: press the tabs down and slide it out the front. Prints standing on its front
// end, so the walls, roof and rails grow along their length and bend in the layers.
// Reference design by GPT-6.1 Sol, smoothstone gold set (evals/gold/e07_mac_mini_mount): the
// channel, rails, counterbores with teardrop crowns, front snap tabs and rear stops are its
// geometry, sized here from the product.
use <lib/stone.scad>
use <lib/product.scad>
include <lib/catalog.scad>

product = "mac_mini_m4_2024"; // a catalog slug
material = "PETG";     // PETG | PLA
clearance = 0.3;       // per side, mm
wall = 3.2;            // side walls, mm
load = 20;             // N the mount is designed to carry
screw = 4;             // desk screw size, M (4 = M4), pan head
tabs = true;           // snap tabs at the front that stop the product sliding out
quality = 64;          // circle smoothness

$fn = quality;
R = catalog_row(product);
assert(len(R) > 0, str("no product named ", product, " in the catalog; set product to a catalog name"));
W = R[1][0];
D = R[1][1];
H = R[1][2];
FEATS = R[6];
OPEN = R[4];
gap = clearance;
side = wall;
roof = 6.4;            // 3.8 mm head pocket over a 2.6 mm web
rail_t = 4.8;
rail_in = clamp(0.11 * W, 6, 14);
front = tabs ? -7.5 : -3.2;
rear = D + gap + 3.2;
edge_chamfer = 1.2;
LIMIT = material == "PLA" ? 0.02 : 0.03;   // the snap strain limit (evals/engineering_grade.py)
snap_t = 2.4;
snap_w = 7.2;
snap_root_x = -0.2;
snap_tip_x = min(28, W / 2 - 4);
snap_l = snap_tip_x - snap_root_x;
// the catch's rise: 3.2 mm, or less when the tab is short, so the strain 1.5 y t / L^2 stays at
// 75% of the limit
snap_rise = min(3.2, floor(0.75 * LIMIT * snap_l * snap_l / (1.5 * snap_t) * 10) / 10);
snap_tip_land = 4.0;
snap_ramp = min(3.2, snap_rise);
snap_rear = front + snap_w;
rail_front = tabs ? snap_rear + 1.5 : 0;
bore_d = iso273_medium(screw);
head_d = 2 * screw + 1;        // 8.2 mm pan head (DIN 7981 ST4.2) plus room
head_depth = screw - 0.2;      // 3.1 mm pan head plus room
hx = [rail_in + 10, W - rail_in - 10];
hole_x = hx[1] - hx[0] >= 10 ? hx : [W / 2];
hole_y = [0.25 * D, 0.75 * D];
eps = 0.02;
assert(!tabs || snap_rise >= 1, "the product is too narrow for snap tabs: set tabs=false");

xmin = -gap - side;
xmax = W + gap + side;
zmin = -gap - rail_t;
zmax = H + gap + roof;

// a polygon in product x,z extruded along product +y
module along_y(points, y0, length) {
    translate([0, y0, 0]) rotate([-90, 0, 0]) linear_extrude(height = length) polygon([for (p = points) [p[0], -p[1]]]);
}

module outside_envelope() {
    c = edge_chamfer;
    along_y([[xmin + c, zmin], [xmax - c, zmin], [xmax, zmin + c], [xmax, zmax - c], [xmax - c, zmax],
             [xmin + c, zmax], [xmin, zmax - c], [xmin, zmin + c]], front, rear - front);
}

// a horizontal bore as printed: its crown a 45 degree point toward product +y (print up)
module teardrop(d, z0, depth, x, y) {
    r = d / 2;
    translate([x, y, z0]) linear_extrude(height = depth) union() {
        circle(d = d);
        polygon([[-r / sqrt(2), r / sqrt(2)], [0, r * sqrt(2)], [r / sqrt(2), r / sqrt(2)]]);
    }
}

// a rail under the product's bottom: from the wall, growing in at 45 degrees behind the tab
module left_rail() {
    translate([0, 0, zmin]) linear_extrude(height = rail_t)
        polygon([[xmin - eps, rail_front], [-gap - eps, rail_front], [rail_in, rail_front + rail_in + gap + eps],
                 [rail_in, rear + eps], [xmin - eps, rear + eps]]);
}

module shell() {
    difference() {
        intersection() {
            outside_envelope();
            union() {
                translate([xmin, front, zmin]) cube([side, rear - front, zmax - zmin]);
                translate([W + gap, front, zmin]) cube([side, rear - front, zmax - zmin]);
                translate([xmin, front, H + gap]) cube([xmax - xmin, rear - front, roof]);
                left_rail();
                translate([W, 0, 0]) mirror([1, 0, 0]) left_rail();
            }
        }
        for (x = hole_x, y = hole_y) {
            teardrop(bore_d, H + gap - eps, roof + 2 * eps, x, y);
            teardrop(head_d, H + gap - eps, head_depth + eps, x, y);
        }
        // features the maker locates on a side: their plug's path through the wall, square, as
        // the wall prints on its side
        side_windows(FEATS, ["+x", "-x"], W, D, gap - 1, gap + side + 1, square = true);
    }
}

// a tab under the front of the product's bottom, rooted in the side wall, its catch rising in front
module left_snap() {
    translate([-gap - eps, front, -gap - snap_t]) cube([snap_tip_x + gap + eps, snap_w, snap_t]);
    translate([snap_tip_x - snap_tip_land, 0, 0]) rotate([0, 90, 0]) linear_extrude(height = snap_tip_land)
        polygon([[gap + eps, front], [gap + eps, front + snap_w + eps], [gap - snap_rise, front + snap_w + eps],
                 [gap - snap_rise, front + snap_ramp]]);
}

// fixed stops behind the product, rising at 45 degrees from the rails
module rear_stops() {
    for (x = [0, W - rail_in]) translate([x, 0, 0]) rotate([0, 90, 0]) linear_extrude(height = rail_in)
        polygon([[gap + eps, D + gap - eps], [gap + eps, rear], [gap - 3.2, rear]]);
}

module product_mount() {
    union() {
        shell();
        if (tabs) {
            left_snap();
            translate([W, 0, 0]) mirror([1, 0, 0]) left_snap();
        }
        rear_stops();
    }
}

// In print orientation, front end on the bed: product [x, y, z] -> part [x - xmin, zmax - z, y - front].
M = [[1, 0, 0, -xmin], [0, 0, -1, zmax], [0, 1, 0, -front], [0, 0, 0, 1]];
bed_chamfer() translate([-xmin, zmax, -front]) rotate([90, 0, 0]) product_mount();

// The roof carries the load from the rails to the screws: its section lies between a rail's
// inner edge and the first screw's head pocket, along the whole mount, the arm the product's
// half width plus the wall (more than any share's way to its screw).
sec_x = (rail_in + hole_x[0] - head_d / 2) / 2;
echo(stone_eng = concat([
    ["frame", M],
    ["clearance", gap],
    ["load", [["n", load], ["dir", "-z"], ["arm", W / 2 + gap + side], ["b", rear - front], ["h", roof],
              ["across_layers", false],
              ["section", [["at", xf_pt(M, [sec_x, D / 2, H + gap + roof / 2])], ["b_dir", xf_dir(M, [0, 1, 0])],
                           ["h_dir", xf_dir(M, [0, 0, 1])]]]]],
    ["attach", [["holes", [for (x = hole_x, y = hole_y) [["at", xf_pt(M, [x, y, zmax])]]]]]]],
    tabs ? [["retention", [["type", "snap"], ["y", snap_rise], ["t", snap_t], ["L", snap_l], ["w", snap_w],
                            ["at", xf_pt(M, [snap_root_x, front + snap_w / 2, -gap - snap_t / 2])],
                            ["t_dir", xf_dir(M, [0, 0, 1])], ["L_dir", [1, 0, 0]]]]]
         : [["retention", [["type", "none"]]]]
));
