// Reference design by GPT-6.1 Sol, smoothstone gold set (e05_appletv_wall_holder). Copied as made; the recipes adapt it.
// Apple TV product frame: x width, y toward ports, z up. All lengths mm.
product_w = 93.0;   // spec: product.body.w, product.body_sources.w
product_d = 93.0;   // spec: product.body.d, product.body_sources.d
product_h = 31.0;   // spec: product.body.h, product.body_sources.h
product_r = 0.0;    // spec: product.body.corner_r, enclosing box, not a measured radius
design_load = 10;   // spec: expect.load_n, N along product -z
design_safety = 2;  // spec: expect.safety
screw_d = 4;       // spec: expect.attach.screw, M4
minimum_screws = 2; // spec: expect.attach.min

// Design allowances, not product dimensions.
clearance = 0.30;  // Midpoint of the grader's PLA slip band, per side.
wall = 4.0;        // Stiff wall and floor, ten nominal 0.4 mm lines.
stop_wall = 2.4;   // Six nominal lines at the two low end stops.
stop_rise = 1.8;   // 1.5 mm above the nominal product bottom, <10% of its face.
edge = 0.6;        // 45 degree exterior foot chamfer and insertion lead.
bore = 4.5;        // ISO 273 M4 medium clearance, spec expect.attach.source.
head_d = 9.0;      // 8.4 mm ISO 7046 head plus 0.6 mm diametral allowance.
hole_inset = 18.5; // 56 mm pitch, ample edge distance on the 93 mm body.
hole_z = wall + clearance + product_h/2;

product_origin = [wall + clearance, stop_wall + clearance, wall + clearance];
outer_w = product_w + 2*(wall + clearance);
outer_d = product_d + 2*(stop_wall + clearance);
top = product_origin[2] + product_h;
left_in = wall;
right_in = outer_w - wall;
$fn = 96; // Sub-0.005 mm radial faceting error on the countersink.

// The entire U is one extrusion. No seam at either cantilever root.
// Its lower corners and upper edges are chamfered without thinning the floor.
module cradle() {
    translate([0,outer_d,0]) rotate([90,0,0])
        linear_extrude(height=outer_d, convexity=6)
            polygon([
                [edge,0], [outer_w-edge,0], [outer_w,edge],
                [outer_w,top-edge], [outer_w-edge,top],
                [right_in+edge,top], [right_in,top-edge],
                [right_in,wall], [left_in,wall],
                [left_in,top-edge], [left_in-edge,top],
                [edge,top], [0,top-edge], [0,edge]
            ]);
}

// Lips prevent sliding out along y while keeping the IR and port faces open.
// Their top is beveled outward, away from the product's enclosing box.
module front_stop() {
    // Positive overlap into both rails avoids coincident union faces.
    translate([left_in-0.2,0,0]) rotate([90,0,90])
        linear_extrude(height=right_in-left_in+0.4, convexity=4)
            polygon([[0,wall-1], [stop_wall,wall-1],
                     [stop_wall,wall+stop_rise-edge],
                     [stop_wall-edge,wall+stop_rise],
                     [0,wall+stop_rise]]);
}

module mounting_hole(y) {
    // Mouth x=0 is the wall-contact plane. Head faces the cradle.
    translate([-0.1,y,hole_z]) rotate([0,90,0])
        cylinder(h=wall+0.2,d=bore);
    sink_depth = (head_d-bore)/2; // 90 degree flat head seat.
    translate([wall-sink_depth,y,hole_z]) rotate([0,90,0])
        cylinder(h=sink_depth+0.1,d1=bore,d2=head_d+0.2);
}

difference() {
    union() {
        cradle();
        front_stop();
        translate([0,outer_d,0]) mirror([0,1,0]) front_stop();
    }
    for (y = [product_origin[1]+hole_inset,
              product_origin[1]+product_d-hole_inset]) mounting_hole(y);
}
