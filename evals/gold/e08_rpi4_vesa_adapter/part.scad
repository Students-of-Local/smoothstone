// Reference design by GPT-6.1 Sol, smoothstone gold set (e08_rpi4_vesa_adapter). Copied as made; the recipes adapt it.
// All dimensions in mm. Product and pattern values from the engineering spec.
product_w = 85.0; // product.body.w
product_d = 56.0; // product.body.d
product_h = 16.0; // product.body.h
product_corner_r = 3.0; // product.body.corner_r
front_left_uv = [81.5, 3.5]; // product.features.mount_hole_front_left.c
front_right_uv = [23.5, 3.5]; // product.features.mount_hole_front_right.c
back_left_uv = [81.5, 52.5]; // product.features.mount_hole_back_left.c
back_right_uv = [23.5, 52.5]; // product.features.mount_hole_back_right.c
board_hole_d = 2.7; // product.features.*.size
board_pad_d = 6.0; // product.features.*.pad
vesa_hole_d = 4.5; // expect.part_holes.vesa_75.d
vesa_pattern = [[-37.5,-37.5],[37.5,-37.5], // expect.part_holes.vesa_75.pattern
                [37.5,37.5],[-37.5,37.5]]; // expect.part_holes.vesa_75.pattern
min_board_gap = 2.5; // expect.min_gap.-z

// Design dimensions: metal standoffs locate the board 10 mm above the plate.
plate_w = 95; plate_d = 92; plate_t = 4; plate_r = 8;
board_origin = [5,18,14];
standoff_hole_d = 2.9; // M2.5 medium clearance
sink_d = 5.5; sink_depth = (sink_d-standoff_hole_d)/2; // 90 degree flat head, 45 degree walls
vesa_center = [47.5,46];
vent_size = [64,34]; vent_r = 6; // leaves the mounting lands connected
eps = 0.02; // extends cutters past faces
$fn = 96; // maximum radial facet error under 0.005 mm at R8

module rounded_rect(size, radius) {
    offset(r=radius) square([size[0]-2*radius,size[1]-2*radius],center=true);
}
module through_at(p,d) {
    translate([p[0],p[1],-eps]) cylinder(d=d,h=plate_t+2*eps);
}
function board_xy(uv) = [board_origin[0]+product_w-uv[0],board_origin[1]+uv[1]];
board_holes = [for (uv=[front_left_uv,front_right_uv,back_left_uv,back_right_uv]) board_xy(uv)];

difference() {
    translate([plate_w/2,plate_d/2,0]) linear_extrude(height=plate_t)
        rounded_rect([plate_w,plate_d],plate_r);
    for (p=board_holes) {
        through_at(p,standoff_hole_d);
        translate([p[0],p[1],0]) cylinder(d1=sink_d,d2=standoff_hole_d,h=sink_depth);
    }
    for (p=vesa_pattern) through_at([vesa_center[0]+p[0],vesa_center[1]+p[1]],vesa_hole_d);
    translate([vesa_center[0],vesa_center[1],-eps]) linear_extrude(height=plate_t+2*eps)
        rounded_rect(vent_size,vent_r);
}
