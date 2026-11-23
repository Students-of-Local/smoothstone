// Reference design by GPT-6.1 Sol, smoothstone gold set (e09_pot_knob). Copied as made; the recipes adapt it.
// Product frame, millimeters, from evals/engineering/e09_pot_knob.json.
shaft_w = 6.0;        // product.body.w
shaft_d = 6.0;        // product.body.d
knurl_length = 7.0;   // product.body.h
shaft_corner_r = 3.0; // product.body.corner_r

// Remaining dimensions are design choices in millimeters.
$fn = 144;                  // Bore chord error below 0.001 mm.
outer_r = 9.0;              // Finger grip with room for the compliant sleeve.
face = 2.2;                 // Continuous printable face and finger root.
gap_to_tip = 0.8;           // Clearance above the shaft end, within expect.face_gap.+z.
height = face + gap_to_tip + knurl_length; // Shaft entry flush with the rim.
edge = 0.7;                 // Eases the outside edges.
interference = 0.06;        // Maximum radial press at the distal band.
bore_r = shaft_w/2 - interference;
finger_wall = 1.5;          // Radial band section for compliant retention.
relief = 0.8;               // Room for fingers to deflect outward.
slot_width = 0.6;           // Separation larger than a nominal 0.4 mm line.
relief_start = face + 0.3;  // Uncut material ties fingers to the face.
lead_depth = 0.4;           // One chamfered entry over two nominal layers.
lead_radial = 0.15;         // Helps start insertion while preserving mouth wall.
root_r = shaft_w/2 + 0.02; // Clearance at the root avoids forcing it outward.
band_start = 7.9;           // Provides 5.4 mm compliant length and 1.7 mm band.
profile_steps = 54;         // Samples the gradual axial relief at 0.1 mm intervals.
function bend(u) = u*u*(3-u)/2;

// A flat face on the build plate and an open bore upward in the STL.
difference() {
    rotate_extrude()
        polygon([[0,0], [outer_r-edge,0], [outer_r,edge],
                 [outer_r,height-edge], [outer_r-edge,height], [0,height]]);
    // The gradual bore relief delays shaft contact until the fingers can bend.
    rotate_extrude() polygon(concat(
        [[0,face], [shaft_w/2+0.1,face], [root_r,relief_start]],
        [for (i=[1:profile_steps])
            [root_r-(root_r-bore_r)*bend(i/profile_steps),
             relief_start+(band_start-relief_start)*i/profile_steps]],
        [[bore_r,height-lead_depth], [bore_r+lead_radial,height],
         [0,height]]));
    // Annular relief leaves four independently deflecting, rooted fingers.
    // The 0.01 and 0.02 mm overruns keep boolean cuts free of coplanar faces.
    translate([0,0,relief_start]) difference() {
        cylinder(r=bore_r+finger_wall+relief, h=height-relief_start+0.01);
        cylinder(r=bore_r+finger_wall, h=height-relief_start+0.02);
    }
    for (a=[0:90:270])
        rotate([0,0,a]) translate([0,-slot_width/2,relief_start])
            cube([bore_r+finger_wall+relief+0.01,slot_width,height-relief_start+0.01]);
    // Index groove: 0.35 mm deep and 1.1 mm wide, spanning the visible side.
    // The 1.0 mm cutter reaches past the exterior; 1.4 and 7.2 mm keep it clear of the rims.
    translate([outer_r-0.35,-0.55,1.4]) cube([1.0,1.1,7.2]);
}
