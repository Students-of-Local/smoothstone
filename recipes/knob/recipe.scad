// knob: a push on knob for the shaft of a real part from the catalog (a potentiometer, an
// encoder), built from the maker's published shaft size. The knob presses onto the shaft: its bore
// is a hair smaller than the shaft, and four slotted fingers around it, freed from the knob's body
// by a ring of relief, flex outward so the press holds without splitting the knob. The bore eases
// in gradually from the face so the fingers bend instead of the shaft shaving the bore. A D shaft
// gets a matching flat in the bore. A groove on the side marks the knob's position. Prints face
// down, the bore open upward, no supports.
// Reference design by GPT-6.1 Sol, smoothstone gold set (evals/gold/e09_pot_knob): the
// fingers, the relief ring, the eased bore profile and the index groove are its geometry, sized
// here from the shaft.
use <lib/product.scad>
include <lib/catalog.scad>

product = "bourns_ptv09a_4020s_b103"; // a catalog slug
material = "PLA";      // PLA | PETG
diameter = 18;         // knob outside diameter, mm (at least the shaft plus 10)
press = 0.06;          // how much smaller the bore is than the shaft, per side, mm
quality = 144;         // circle smoothness

$fn = quality;
R = catalog_row(product);
assert(len(R) > 0, str("no product named ", product, " in the catalog; set product to a catalog name"));
SHAFT = R[7];
assert(len(SHAFT) > 0, str(product, " has no shaft for a knob"));
SD = R[1][0];                 // shaft diameter
L = R[1][2];                  // the shaft's length the knob covers
FLAT = SHAFT[1];              // across flats, 0 for a round or knurled shaft
outer_r = max(diameter / 2, SD / 2 + 5);
face = 2.2;                   // the knob's solid face, the fingers' root
tip_gap = 0.8;                // room above the shaft's end
height = face + tip_gap + L;  // the shaft's entry flush with the rim
edge = 0.7;                   // outside edges eased
bore_r = SD / 2 - press;
finger_wall = 1.5;            // the fingers' radial section
relief = 0.8;                 // room for the fingers to flex outward
slot_width = 0.6;             // wider than one 0.4 mm line, so the slicer leaves it open
relief_start = face + 0.3;    // solid material ties the fingers to the face
lead_depth = 0.4;             // a chamfered entry over two layers
lead_radial = 0.15;
root_r = SD / 2 + 0.02;       // clear at the fingers' root, so they are not forced out there
band_start = height - 2.1;    // the fingers grip only in a 1.7 mm band near the mouth
steps = 54;
function bend(u) = u * u * (3 - u) / 2;
eps = 0.01;

module bore() {
    intersection() {
        rotate_extrude() polygon(concat(
            [[0, face], [SD / 2 + 0.1, face], [root_r, relief_start]],
            [for (i = [1:steps]) [root_r - (root_r - bore_r) * bend(i / steps),
                                  relief_start + (band_start - relief_start) * i / steps]],
            [[bore_r, height - lead_depth], [bore_r + lead_radial, height], [0, height]]));
        // a D shaft: the bore's flat at the shaft's flat, the knob turns with it
        if (FLAT > 0) translate([-SD, -SD, face - 1]) cube([2 * SD, SD + (FLAT - SD / 2), height]);
    }
}

module knob() {
    difference() {
        rotate_extrude() polygon([[0, 0], [outer_r - edge, 0], [outer_r, edge],
                                  [outer_r, height - edge], [outer_r - edge, height], [0, height]]);
        bore();
        translate([0, 0, relief_start]) difference() {
            cylinder(r = bore_r + finger_wall + relief, h = height - relief_start + eps);
            translate([0, 0, -eps]) cylinder(r = bore_r + finger_wall, h = height - relief_start + 3 * eps);
        }
        // four slots between the fingers from just inside the bore, a D flat's middle on a finger
        for (a = [45:90:315]) rotate([0, 0, FLAT > 0 ? a : a - 45])
            translate([bore_r - 0.1, -slot_width / 2, relief_start])
                cube([finger_wall + relief + 0.1 + eps, slot_width, height]);
        // the index groove, 0.35 mm deep, along the side
        translate([outer_r - 0.35, -0.55, 1.4]) cube([1, 1.1, height - 2.8]);
    }
}

knob();

// The shaft's frame: its tip down into the bore, its min corner at the knob's axis minus its radius.
M = [[1, 0, 0, -SD / 2], [0, -1, 0, SD / 2], [0, 0, -1, height], [0, 0, 0, 1]];
GRIP = -press / 2;            // the fingers' mean grip over the shaft's side
echo(stone_eng = [
    ["frame", M],
    ["clearance", [["+x", GRIP], ["-x", GRIP], ["+y", GRIP], ["-y", GRIP], ["+z", tip_gap]]],
    ["retention", [["type", "friction"], ["gap", -press]]]
]);
