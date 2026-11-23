// board_plate: a flat adapter plate that screws a circuit board from the catalog (a Raspberry Pi,
// a microcontroller board) to the back of a monitor or a wall through a VESA pattern, built from
// the maker's published hole positions (recipes/lib/catalog.scad). The board stands on bought
// metal standoffs over the plate; flat head screws come up through countersunk clearance holes
// from the plate's underside into the standoffs, so the plate's back stays flush against the
// monitor. The VESA holes take the monitor's M4 (VESA 75 and 100) screws, and a vent under the
// board's middle lets its heat out and saves plastic. Prints flat on its back, no supports.
// Reference design by GPT-6.1 Sol, smoothstone gold set (evals/gold/e08_rpi4_vesa_adapter): the
// plate, its countersunk board holes, the centered VESA pattern and the vent are its geometry,
// sized here from the board.
use <lib/stone.scad>
use <lib/product.scad>
include <lib/catalog.scad>

product = "raspberry_pi_4"; // a catalog slug
vesa = "75";           // 75 | 100: the VESA MIS-D pattern, mm square
material = "PETG";     // PETG | PLA
standoff = 10;         // the bought standoffs' length, mm
thickness = 4;         // plate thickness, mm
vent = true;           // an opening under the board's middle
quality = 96;          // circle smoothness

$fn = quality;
R = catalog_row(product);
assert(len(R) > 0, str("no product named ", product, " in the catalog; set product to a catalog name"));
W = R[1][0];
D = R[1][1];
FEATS = R[6];
// the board's mounting holes, on its underside: -z face u runs from +x to -x, v along y
HOLES = [for (f = FEATS) if (f[1] == "hole" && f[2] == "-z") [W - f[3], f[4], f[5]]];
assert(len(HOLES) >= 2, "this product has no mounting holes underneath for a plate");
// the screw that fits the board's smallest hole, and its ISO 273 medium clearance hole
SCREW = let(h = min([for (p = HOLES) p[2]])) h >= 3.2 ? 3 : h >= 2.7 ? 2.5 : 2;
BORE = iso273_medium(SCREW);
SINK = 2 * SCREW + 0.5;                   // an ISO 10642 flat head (4.7 for M2.5) plus room
SINK_DEPTH = (SINK - BORE) / 2;           // 90 degree countersink
V = vesa == "100" ? 100 : 75;
VESA_D = 4.5;                             // ISO 273 medium clearance for the M4 VESA screws
EDGE = 8.5;                               // plate around a VESA hole's center, and its corner radius
PW = max(W + 10, V + 2 * EDGE);
PD = max(D + 10, V + 2 * EDGE);
RC = 8;
// the board and the VESA pattern both centered on the plate
BX = (PW - W) / 2;
BY = (PD - D) / 2;
CX = PW / 2;
CY = PD / 2;
VESA = [for (s = [[-1, -1], [1, -1], [1, 1], [-1, 1]]) [CX + s[0] * V / 2, CY + s[1] * V / 2]];
BOARD = [for (p = HOLES) [BX + p[0], BY + p[1]]];
for (b = BOARD, v = VESA) assert(norm(b - v) >= (SINK + VESA_D) / 2 + 2,
    "a board hole lands on a VESA hole: this board needs another plate layout");
LAND = SINK / 2 + 2.5;                    // plate kept around a board hole
eps = 0.02;

module rounded(w, d, r) translate([r, r]) offset(r = r) square([w - 2 * r, d - 2 * r]);

// the vent: the board's footprint 6 mm in, less a land around every hole, corners rounded
module vent_shape() {
    offset(r = 3) offset(delta = -3) difference() {
        translate([BX + 6, BY + 6]) square([W - 12, D - 12]);
        for (b = BOARD) translate(b) circle(r = LAND + 1);
        for (v = VESA) translate(v) circle(r = VESA_D / 2 + 3);
    }
}

module plate() {
    difference() {
        linear_extrude(thickness) rounded(PW, PD, RC);
        for (b = BOARD) translate([b[0], b[1], 0]) {
            translate([0, 0, -eps]) cylinder(d = BORE, h = thickness + 2 * eps);
            translate([0, 0, -eps]) cylinder(d1 = SINK + 2 * eps, d2 = BORE, h = SINK_DEPTH + eps);
        }
        for (v = VESA) translate([v[0], v[1], -eps]) cylinder(d = VESA_D, h = thickness + 2 * eps);
        if (vent) translate([0, 0, -eps]) linear_extrude(thickness + 2 * eps) vent_shape();
    }
}

bed_chamfer() plate();

// The board's frame: its min corner over the plate at the standoffs' top.
M = [[1, 0, 0, BX], [0, 1, 0, BY], [0, 0, 1, thickness + standoff], [0, 0, 0, 1]];
echo(stone_eng = [
    ["frame", M],
    ["clearance", [["-z", standoff]]],
    ["retention", [["type", "screw"], ["size", str("M", SCREW)], ["method", "through"], ["hole_d", BORE],
                   ["holes", [for (b = BOARD) [["at", [b[0], b[1], thickness]], ["axis", [0, 0, -1]]]]]]],
    ["part_holes", [[str("vesa_", V), [["c", [CX, CY, 0]], ["u", [1, 0, 0]]]]]]
]);
