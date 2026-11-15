// fan_guard: grille for a square PC fan, in four styles. Flat on the bed, no supports.
use <lib/stone.scad>

size = 120;          // fan size, mm: 40, 50, 60, 70, 80, 92, 120 or 140
thickness = 3;       // plate thickness, mm
style = "rings";     // rings | honeycomb | spiral | grid
opening = 0;         // round opening diameter, mm; 0 = auto
hole_spacing = 0;    // screw hole spacing, mm; 0 = the standard for this fan size
hole_d = 0;          // screw hole diameter, mm; 0 = auto
corner_r = 5;        // outer corner radius, mm
rings = 3;           // rings style: number of rings
ring_w = 2;          // rings style: ring width, mm
ring_pitch = 0;      // rings style: distance between rings, mm; 0 = auto
spokes = 4;          // rings style: number of spokes
spoke_w = 3;         // rings style: spoke width, mm
cell = 9;            // honeycomb and grid: cell size, mm
bar_w = 1.6;         // honeycomb and grid: bar width, mm
blades = 11;         // spiral style: number of blades
blade_w = 2.4;       // spiral style: blade width, mm
blade_sweep = 70;    // spiral style: how far each blade curves, degrees
hub_d = -1;          // center disc diameter, mm; -1 = auto, 0 = none
edge = 0.8;          // rounding on the top edges, mm
quality = 96;        // circle smoothness

$fn = quality;

function std_spacing(s) =
    s >= 140 ? 124.5 : s >= 120 ? 105 : s >= 92 ? 82.5 : s >= 80 ? 71.5 :
    s >= 70 ? 61.5 : s >= 60 ? 50 : s >= 50 ? 40 : s >= 40 ? 32 : s * 0.8;

op_d = opening > 0 ? opening : size - max(5, size / 12);
op_r = op_d / 2;
sp = hole_spacing > 0 ? hole_spacing : std_spacing(size);
hd = hole_d > 0 ? hole_d : (size <= 60 ? 3.4 : 4.3);
hub = hub_d >= 0 ? hub_d : (style == "spiral" ? op_d * 0.22 : style == "rings" ? 0 : op_d * 0.16);
pitch = ring_pitch > 0 ? ring_pitch : round(op_r / (rings + 0.7));
inner_edge = min(edge, thickness / 3);

assert(op_d < size - 2, "opening must be smaller than the fan size");
assert(sp / 2 * sqrt(2) - hd / 2 > op_r + 0.8, "the screw holes cut into the opening: make opening smaller");

module hexagon(af) { circle(d = af / cos(30), $fn = 6); }

module grille2d(r_out) {
    intersection() {
        circle(r = r_out);
        union() {
            if (style == "rings") {
                for (i = [1:rings]) difference() {
                    circle(r = i * pitch + ring_w / 2);
                    circle(r = i * pitch - ring_w / 2);
                }
                for (i = [0:max(spokes, 1) - 1]) if (spokes > 0)
                    rotate(i * 360 / spokes) translate([0, -spoke_w / 2]) square([op_r + 2, spoke_w]);
            }
            if (style == "honeycomb") difference() {
                circle(r = op_r + 2);
                dx = cell + bar_w;
                dy = dx * sqrt(3) / 2;
                n = ceil(op_r / dy) + 1;
                for (j = [-n:n], i = [-n:n])
                    translate([(i + (j % 2) / 2) * dx, j * dy]) rotate(30) hexagon(cell);
            }
            if (style == "grid") difference() {
                circle(r = op_r + 2);
                p = cell + bar_w;
                n = ceil(op_r / p) + 1;
                rotate(45) for (i = [-n:n], j = [-n:n])
                    translate([i * p, j * p]) square(cell, center = true);
            }
            if (style == "spiral") {
                r0 = max(hub / 2 - blade_w, 1);
                for (b = [0:blades - 1]) rotate(b * 360 / blades)
                    for (k = [0:15]) hull() for (t = [k / 16, (k + 1) / 16]) {
                        r = r0 + t * (op_r + 1.5 - r0);
                        a = blade_sweep * pow(t, 0.8);
                        translate([r * cos(a), r * sin(a)]) circle(d = blade_w, $fn = 16);
                    }
                difference() { circle(r = op_r * 0.62 + blade_w * 0.4); circle(r = op_r * 0.62 - blade_w * 0.4); }
            }
            if (hub > 0) circle(d = hub);
        }
    }
}

union() {
    difference() {
        soft_slab(thickness, top = edge, bottom = 0.4) rrect(size, size, corner_r);
        translate([0, 0, -1]) cylinder(r = op_r, h = thickness + 2);
        translate([0, 0, thickness - inner_edge])
            cylinder(r1 = op_r, r2 = op_r + inner_edge + 0.01, h = inner_edge + 0.01);
        for (sx = [-1, 1], sy = [-1, 1])
            translate([sx * sp / 2, sy * sp / 2, 0]) hole(hd, thickness, 0.5);
    }
    // bars inside the opening get the rounded top; where they reach into the frame they stop
    // below the opening chamfer, so no sliver pokes through it
    soft_extrude(thickness, r = min(edge, 0.6)) grille2d(op_r - 0.01);
    linear_extrude(thickness - inner_edge) difference() { grille2d(op_r + 1); circle(r = op_r - 0.5); }
}
