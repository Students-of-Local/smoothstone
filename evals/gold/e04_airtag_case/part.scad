// Reference design by GPT-6.1 Sol, smoothstone gold set (e04_airtag_case). Copied as made; the recipes adapt it.
// Product-frame dimensions, mm. All refer to evals/engineering/e04_airtag_case.json.
tag_w = 31.87;                  // product.body.w
tag_d = 31.87;                  // product.body.d
tag_h = 7.98;                   // product.body.h
tag_corner_r = 15.935;          // product.body.corner_r
tag_profile = [                // [radius, height], mm
    [0,0],          // product.body.profile[0]
    [15.935,0],     // product.body.profile[1]
    [15.935,4.98],  // product.body.profile[2]
    [15.805,5.67],  // product.body.profile[3]
    [15.355,6.18],  // product.body.profile[4]
    [14.705,6.55],  // product.body.profile[5]
    [13.965,6.82],  // product.body.profile[6]
    [13.185,7.03],  // product.body.profile[7]
    [12.385,7.2],   // product.body.profile[8]
    [11.575,7.33],  // product.body.profile[9]
    [10.755,7.44],  // product.body.profile[10]
    [9.935,7.54],   // product.body.profile[11]
    [9.105,7.62],   // product.body.profile[12]
    [8.285,7.69],   // product.body.profile[13]
    [7.455,7.75],   // product.body.profile[14]
    [6.635,7.81],   // product.body.profile[15]
    [5.805,7.85],   // product.body.profile[16]
    [4.975,7.89],   // product.body.profile[17]
    [4.155,7.92],   // product.body.profile[18]
    [3.325,7.95],   // product.body.profile[19]
    [2.495,7.95],   // product.body.profile[20]
    [1.665,7.96],   // product.body.profile[21]
    [0.835,7.97],   // product.body.profile[22]
    [0,7.98]        // product.body.profile[23]
];
speaker_c = [15.935,15.935];    // product.features[0].c, in product +z face
speaker_size = [25.75,25.75];   // product.features[0].size, circular diameter

// Designer choices. The matching calculations and process assumptions are in NOTES.md.
gap = 0.15;                    // Midpoint of the specified PETG snug fit range.
wall = 1.6;                    // Four nominal 0.4 mm extrusion widths.
tag_z = wall + gap;            // Floor top 1.6, tag bottom 1.75.
speaker_extra = 0.20;          // Radial manufacturing allowance on the keepout.
split = 0.70;                  // Clear seam between independently opening half shells.
foot_chamfer = 0.35;           // A 45 degree bed edge, smaller than the floor thickness.

hinge_r = 11.5;                // 36.13 mm path reduces opening strain, adding only 4 mm length.
hinge_t = 1.4;                 // About 1.80% inner-fiber strain at 50 degrees opening.
hinge_y = -18.0;
hinge_h = wall;
hinge_join_y = -12.5;           // The stem enters the floor at radius 16.99, below the tag.

arm_root_x = -7;
arm_end_x = 7;
arm_y = 18.90;
arm_t = 1.4;
arm_h = 6.8;
catch_y = 0.8;
catch_shoulder_x = 5.6;
catch_flat_x = 6.0;
receiver_x = 5.3;               // 0.30 axial latch play before the shoulder bears.
receiver_y = 17.9;              // 0.50 radial engagement with the catch.

$fn = 192;                     // Maximum circular sag at R17.685 is 0.0024 mm.
component = "all";             // Verification exports: left, right or product.
outer_r = tag_w/2 + gap + wall;
root_face = arm_y-arm_t/2;

// Offset each published straight segment along its normal. Adjacent lines meet at
// their miter, preserving the specified normal gap without tiny circular join faces.
function outward(a,b) = let(e=b-a) [e[1],-e[0]]/norm(e);
function offset_vertex(i,o) =
    let(n=len(tag_profile), p=tag_profile[i],
        a=outward(tag_profile[(i+n-1)%n],p),
        b=outward(p,tag_profile[(i+1)%n]),
        q=p+o*(a+b)/(1+a*b)) [max(0,q[0]),q[1]];
function offset_profile(o) = [for(i=[0:len(tag_profile)-1]) offset_vertex(i,o)];
function outer_profile() = concat(
    [[0,-tag_z],[outer_r-foot_chamfer,-tag_z],
     [outer_r,-tag_z+foot_chamfer]],
    [for(i=[2:len(tag_profile)-1]) offset_vertex(i,gap+wall)]);

module round_shell() {
    difference() {
        translate([0,0,tag_z]) rotate_extrude(convexity=10) polygon(outer_profile());
        translate([0,0,tag_z]) rotate_extrude(convexity=10) polygon(offset_profile(gap));
        translate([speaker_c[0]-tag_w/2,speaker_c[1]-tag_d/2,tag_z])
            cylinder(h=tag_h+wall+2,r=speaker_size[0]/2+speaker_extra);
        translate([-split/2,-outer_r-1,-1])
            cube([split,2*outer_r+2,tag_z+tag_h+wall+2]);
    }
}

module rear_flexure() {
    linear_extrude(height=hinge_h) union() {
        difference() {
            translate([0,hinge_y]) difference() {
                circle(r=hinge_r+hinge_t/2);
                circle(r=hinge_r-hinge_t/2);
            }
            translate([-hinge_r-hinge_t,hinge_y])
                square([2*(hinge_r+hinge_t),2*(hinge_r+hinge_t)]);
        }
        for (side=[-1,1]) hull() {
            translate([side*hinge_r,hinge_y]) circle(d=hinge_t);
            translate([side*hinge_r,hinge_join_y]) circle(d=hinge_t);
        }
    }
}

module latch_arm() {
    // The arm has its whole lower edge on the bed. It bends in the strong xy plane.
    translate([arm_root_x-0.4,root_face,0])
        cube([arm_end_x-arm_root_x+0.4,arm_t,arm_h]);
    linear_extrude(height=arm_h)
        polygon([[catch_shoulder_x,root_face+0.05],
                 [catch_shoulder_x,root_face-catch_y],
                 [catch_flat_x,root_face-catch_y],
                 [arm_end_x,root_face+0.05]]);
    // Left root pedestal is taller than the free arm, and joins the left half only.
    linear_extrude(height=8.0) hull() {
        translate([arm_root_x-0.81,16.0]) circle(r=0.8);
        translate([arm_root_x-0.81,arm_y]) circle(r=0.8);
    }
}

module latch_receiver() {
    // Right receiver lies behind the catch's square shoulder, separated by 0.30 mm.
    // Its top-view chamfer guides the latch outward while the halves close.
    linear_extrude(height=arm_h)
        polygon([[3.5,16.0], [receiver_x,16.0],
                 [receiver_x,receiver_y], [4.8,receiver_y], [3.5,17.3]]);
}

module shell_half(side) {
    intersection() {
        round_shell();
        translate([side<0 ? -50 : 0,-50,-1]) cube([50,100,30]);
    }
}

if(component=="left") union() { shell_half(-1); latch_arm(); }
else if(component=="right") union() { shell_half(1); latch_receiver(); }
else if(component=="product")
    translate([0,0,tag_z]) rotate_extrude(convexity=10) polygon(tag_profile);
else union() {
    round_shell();
    rear_flexure();
    latch_arm();
    latch_receiver();
}
