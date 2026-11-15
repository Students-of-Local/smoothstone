// gridfinity_bin: storage bin for the Gridfinity system (42 mm grid, 7 mm height units),
// with the standard base, stacking lip, dividers, a front scoop and a label shelf.
use <lib/stone.scad>

grid_x = 2;          // width in grid units (42 mm each)
grid_y = 1;          // depth in grid units
units = 3;           // height in 7 mm units
div_x = 0;           // dividers across X (makes div_x + 1 compartments)
div_y = 0;           // dividers across Y
scoop = true;        // rounded inside front edge, easy to scoop small parts out
label = true;        // label shelf along the back wall
lip = true;          // stacking lip on top
wall = 1.2;          // wall thickness, mm
magnets = false;     // 6 x 2 mm magnet pockets under each cell
quality = 48;        // circle smoothness

$fn = quality;
P = 42;
W = grid_x * P - 0.5;
D = grid_y * P - 0.5;
R = 3.75;
B = 4.75;                    // base profile height
H = units * 7;               // top of the walls
FLOOR = B + 1.2;
LIP = 4.4;
TOP = H + (lip ? LIP : 0);

assert(H > FLOOR + 3, "units must be at least 2");

// one base foot: 0.8 mm 45 deg chamfer, 1.8 mm straight, 2.15 mm 45 deg chamfer
module foot() {
    s0 = 41.5 - 2 * (0.8 + 2.15);
    hull() {
        linear_extrude(0.01) rrect(s0, s0, 0.8);
        translate([0, 0, 0.8]) linear_extrude(1.8) rrect(s0 + 1.6, s0 + 1.6, 1.6);
        translate([0, 0, B - 0.01]) linear_extrude(0.01) rrect(41.5, 41.5, R);
    }
}

// the hollow inside, with the stacking lip profile cut from the top of the walls
module cavity() {
    inr = max(R - wall, 0.6);
    // straight inside up to where the lip support starts
    sup = lip ? 3.2 - wall : 0;
    z_lip = H - sup;
    translate([0, 0, FLOOR]) linear_extrude(z_lip - FLOOR + 0.01) rrect(W - 2 * wall, D - 2 * wall, inr);
    if (lip) {
        // inset from the outer edge at each height, read from the bottom of the lip support up
        prof = [[z_lip, wall], [H, 3.2], [H + 1.9, 1.3], [H + 1.9 + 1.8, 1.3], [TOP, 0.6], [TOP + 1, 0.6]];
        for (i = [0:len(prof) - 2]) hull() for (p = [prof[i], prof[i + 1]])
            translate([0, 0, p[0]]) linear_extrude(0.01) rrect(W - 2 * p[1], D - 2 * p[1], max(R - p[1], 0.5));
    } else translate([0, 0, H - 0.01]) linear_extrude(1) rrect(W - 2 * wall, D - 2 * wall, inr);
}

module body() {
    difference() {
        union() {
            for (i = [0:grid_x - 1], j = [0:grid_y - 1])
                translate([(i - (grid_x - 1) / 2) * P, (j - (grid_y - 1) / 2) * P, 0]) foot();
            translate([0, 0, B - 0.01]) linear_extrude(TOP - B + 0.01) rrect(W, D, R);
        }
        cavity();
        if (magnets) for (i = [0:grid_x - 1], j = [0:grid_y - 1], sx = [-1, 1], sy = [-1, 1])
            translate([(i - (grid_x - 1) / 2) * P + sx * 13, (j - (grid_y - 1) / 2) * P + sy * 13, -0.01])
                cylinder(d = 6.5, h = 2.4);
    }
}

iw = W - 2 * wall;
id = D - 2 * wall;
top_in = H - (lip ? 3.2 - wall : 0);   // highest point inside that is still straight wall

union() {
    body();
    // dividers, full height of the straight wall
    for (i = [1:div_x]) if (div_x > 0)
        translate([-iw / 2 + i * iw / (div_x + 1) - 0.6, -id / 2, FLOOR - 0.01]) cube([1.2, id, top_in - FLOOR]);
    for (j = [1:div_y]) if (div_y > 0)
        translate([-iw / 2, -id / 2 + j * id / (div_y + 1) - 0.6, FLOOR - 0.01]) cube([iw, 1.2, top_in - FLOOR]);
    // scoop: a quarter-round fill along the inside of the front wall
    if (scoop) {
        sr = min(top_in - FLOOR, id / 2, 14);
        translate([0, -id / 2, FLOOR - 0.01]) rotate([0, 90, 0])
            linear_extrude(iw, center = true) difference() {
                translate([-sr, 0]) square(sr);
                translate([-sr, sr]) circle(r = sr);
            }
    }
    // label shelf: 45 degree support under a flat shelf on the back wall
    if (label) {
        lw = min(12, id / 3);
        translate([0, id / 2, top_in]) rotate([0, 90, 0])
            linear_extrude(iw, center = true) polygon([[0, 0], [0, -lw], [lw, 0]]);
    }
}
