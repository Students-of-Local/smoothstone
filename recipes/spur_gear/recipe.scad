// spur_gear: involute spur, helical or herringbone gear (BOSL2) with a hub, a bore with a
// flat for a D shaft, and lightening holes.
include <BOSL2/std.scad>
include <BOSL2/gears.scad>
use <lib/stone.scad>

teeth = 30;          // number of teeth
module_mm = 2;       // gear module, mm (tooth size; meshing gears need the same module)
thickness = 8;       // gear thickness, mm
style = "herringbone"; // spur | helical | herringbone
helix = 25;          // helix angle for helical and herringbone, degrees
bore = 5.2;          // shaft hole diameter, mm (0 = none)
d_flat = true;       // flat in the bore for a D shaft
hub_d = 16;          // hub diameter, mm (0 = no hub)
hub_h = 4;           // hub height above the gear, mm
holes = 6;           // lightening holes (0 = none)
quality = 64;        // circle smoothness

$fn = quality;
pr = pitch_radius(mod = module_mm, teeth = teeth);
root = pr - 1.25 * module_mm;
inner = max(hub_d / 2, bore / 2 + 2);
r_fit = (root - inner - 4) / 2;                      // fits between hub and rim
hole_c = inner + 2 + r_fit;
hole_r = min(r_fit, hole_c * sin(180 / max(holes, 1)) - 2.5);  // leaves spokes at least 5 mm wide

assert(bore < root * 2 - 4, "bore is too big for this gear");

// the chamfer insets every tooth flank at the bed too: a first layer that flares binds the mesh
bed_chamfer() difference() {
    union() {
        spur_gear(mod = module_mm, teeth = teeth, thickness = thickness,
                  helical = style == "spur" ? 0 : helix, herringbone = style == "herringbone",
                  shaft_diam = 0, anchor = BOTTOM);
        if (hub_d > 0) cyl(d = hub_d, h = thickness + hub_h, anchor = BOTTOM, chamfer2 = 0.6);
    }
    if (bore > 0) down(1) difference() {
        cylinder(d = bore, h = thickness + hub_h + 2);
        if (d_flat) translate([bore / 2 - bore * 0.1, -bore, 0]) cube([bore, 2 * bore, thickness + hub_h + 2]);
    }
    if (holes > 0 && hole_r > 2.5)
        for (i = [0:holes - 1]) rotate(i * 360 / holes) translate([hole_c, 0, -1])
            cylinder(r = hole_r, h = thickness + 2);
}
