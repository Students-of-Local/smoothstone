// Reference design by GPT-6.1 Sol, smoothstone gold set (e07_mac_mini_mount). Copied as made; the recipes adapt it.
// Millimeters. Product coordinates: x width, y front to back, z upward.
body_w = 127.0;       // product.body.w
body_d = 127.0;       // product.body.d
body_h = 50.0;        // product.body.h
body_corner_r = 0.0;  // product.body.corner_r: enclosing box, no published radius
design_load = 20;     // expect.load_n, N
safety = 2;           // expect.safety

// Design values, not measurements of the computer. Reasons are in NOTES.md.
gap = 0.30;
side = 3.20;
roof = 6.40;
rail_t = 4.80;
rail_in = 14.0;
front = -7.50;
rear = body_d + gap + 3.2;
edge_chamfer = 1.20;
snap_t = 2.40;
snap_w = 7.20;
snap_root_x = -0.20;
snap_tip_x = 28.0;
snap_l = snap_tip_x - snap_root_x;
snap_rise = 3.20;
snap_tip_land = 4.0;
snap_ramp = 3.20;
snap_rear = front + snap_w;
rail_front = snap_rear + 1.50;
bore_d = 4.50;        // expect.attach.screw M4: ISO 273 medium, cited in spec
head_d = 9.00;        // 8.2 mm grader pan head + 0.4 mm radial allowance
head_depth = 3.80;    // 3.1 mm grader pan head + 0.7 mm axial allowance
hole_x = [24.0, body_w - 24.0];
hole_y = [32.0, body_d - 32.0];
$fn = 64;
eps = 0.02;

xmin = -gap-side;
xmax = body_w+gap+side;
zmin = -gap-rail_t;
zmax = body_h+gap+roof;

// Extrude a polygon in product x,z along product +y.
module along_y(points, y0, length) {
    translate([0,y0,0]) rotate([-90,0,0])
        linear_extrude(height=length)
            polygon([for (p=points) [p[0],-p[1]]]);
}

// 45 degree outer corners only. The product's sharp enclosing box stays clear.
module outside_envelope() {
    c = edge_chamfer;
    along_y([[xmin+c,zmin],[xmax-c,zmin],[xmax,zmin+c],
             [xmax,zmax-c],[xmax-c,zmax],[xmin+c,zmax],
             [xmin,zmax-c],[xmin,zmin+c]], front, rear-front);
}

// Horizontal printed bores have a 45 degree crown, with a full circular core.
// The roof of the teardrop points along product +y, which is print +Z.
module teardrop(d, z0, depth, x, y) {
    r = d/2;
    translate([x,y,z0]) linear_extrude(height=depth) union() {
        circle(d=d);
        polygon([[-r/sqrt(2),r/sqrt(2)], [0,r*sqrt(2)],
                 [r/sqrt(2),r/sqrt(2)]]);
    }
}

module left_rail() {
    // Start at the wall, then grow inward at 45 degrees after the snap relief.
    // An abrupt full-width rail here would need support above the release slot.
    translate([0,0,zmin]) linear_extrude(height=rail_t)
        polygon([[xmin-eps,rail_front],[-gap-eps,rail_front],
                 [rail_in,rail_front+rail_in+gap+eps],
                 [rail_in,rear+eps],[xmin-eps,rear+eps]]);
}

module shell() {
    difference() {
        intersection() {
            outside_envelope();
            union() {
                translate([xmin,front,zmin])
                    cube([side,rear-front,zmax-zmin]);
                translate([body_w+gap,front,zmin])
                    cube([side,rear-front,zmax-zmin]);
                translate([xmin,front,body_h+gap])
                    cube([xmax-xmin,rear-front,roof]);
                // Leave 1.5 mm air behind the front snap beams.
                left_rail();
                translate([body_w,0,0]) mirror([1,0,0]) left_rail();
            }
        }
        for (x=hole_x, y=hole_y) {
            teardrop(bore_d,body_h+gap-eps,roof+2*eps,x,y);
            teardrop(head_d,body_h+gap-eps,head_depth+eps,x,y);
        }
    }
}

module left_snap() {
    // Root joins the side wall at x=-gap; its center at -0.2 is inside the arm.
    translate([-gap-eps,front,-gap-snap_t])
        cube([snap_tip_x+gap+eps,snap_w,snap_t]);
    // Lead-in from the front, then a flat catch land and a square release face.
    // At the arm centerline the full rise is present, as measured by the grader.
    translate([snap_tip_x-snap_tip_land,0,0]) rotate([0,90,0])
        linear_extrude(height=snap_tip_land)
            polygon([[gap+eps,front],[gap+eps,front+snap_w+eps],
                     [gap-snap_rise,front+snap_w+eps],
                     [gap-snap_rise,front+snap_ramp]]);
}

module rear_stops() {
    // Grow 1 mm upward per 1 mm of print height. No unsupported rear shelf.
    for (x=[0,body_w-rail_in])
        translate([x,0,0]) rotate([0,90,0])
            linear_extrude(height=rail_in)
                polygon([[gap+eps,body_d+gap-eps],[gap+eps,rear],
                         [gap-snap_rise,rear]]);
}

module product_mount() {
    union() {
        shell();
        left_snap();
        translate([body_w,0,0]) mirror([1,0,0]) left_snap();
        rear_stops();
    }
}

// Final STL is already in print orientation, front end on the bed.
// Product [x,y,z] -> STL [x+3.5, 56.7-z, y+7.5]. Proper rotation, no mirror.
translate([-xmin,zmax,-front]) rotate([90,0,0]) product_mount();
