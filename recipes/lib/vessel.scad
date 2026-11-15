// Vessel generator shared by the vase and planter recipes. The outside is one polyhedron:
// a smooth profile (base, belly, top) times a surface pattern (ribs, facets, twist, waves).
// Hollow vessels subtract the same surface moved in by the wall thickness.

// profile radius at height fraction t: cosine ease from base to belly, then belly to top
function v_prof(t, rb, rm, rt, at) =
    t <= at ? rb + (rm - rb) * (1 - cos(180 * t / at)) / 2
            : rm + (rt - rm) * (1 - cos(180 * (t - at) / (1 - at))) / 2;

// regular polygon "radius" in direction a (n sides); round when n < 3
function v_poly(a, n) = n < 3 ? 1 : let (p = 360 / n) cos(180 / n) / cos((((a % p) + p) % p) - 180 / n);

// full outer radius at angle a, height fraction t
function v_r(a, t, rb, rm, rt, at, sides, ribs, rib_depth, twist, wave, waves) =
    let (
        ph = twist * t + wave * sin(360 * waves * t),
        base = v_prof(t, rb, rm, rt, at) * v_poly(a - ph, sides),
        rib = ribs > 0 ? rib_depth * (0.5 + 0.5 * cos(ribs * (a - ph))) : 0
    ) base + rib - (ribs > 0 ? rib_depth : 0);

// one closed surface as a polyhedron from z0 to z1 (radii from v_r minus inset)
module v_surface(h, z0, z1, inset, rb, rm, rt, at, sides, ribs, rib_depth, twist, wave, waves, na, nz, foot) {
    zs = concat(foot > 0 && z0 == 0 ? [0, foot] : [z0],
                [for (i = [1:nz]) z0 + (z1 - z0) * i / nz]);
    zz = [for (z = zs) if (!(foot > 0 && z0 == 0 && z > 0 && z < foot) || z == foot) z];
    pts = [for (z = zz) for (j = [0:na - 1])
        let (a = 360 * j / na,
             t = min(max(z, 0), h) / h,
             r = max(v_r(a, t, rb, rm, rt, at, sides, ribs, rib_depth, twist, wave, waves) - inset
                     - (foot > 0 && z < foot ? foot - z : 0), 0.5))
        [r * cos(a), r * sin(a), z]];
    nr = len(zz);
    c0 = nr * na;      // center of the bottom cap
    c1 = nr * na + 1;  // center of the top cap
    // OpenSCAD wants faces clockwise when seen from outside
    // caps are triangle fans around a center point, so they stay right for any star shape
    faces = concat(
        [for (j = [0:na - 1]) [c0, j, (j + 1) % na]],
        [for (j = [0:na - 1]) [c1, (nr - 1) * na + (j + 1) % na, (nr - 1) * na + j]],
        [for (i = [0:nr - 2]) for (j = [0:na - 1])
            let (a = i * na + j, b = i * na + (j + 1) % na, c = (i + 1) * na + (j + 1) % na, d = (i + 1) * na + j)
            each [[a, c, b], [a, d, c]]]);
    polyhedron(points = concat(pts, [[0, 0, zz[0]], [0, 0, zz[nr - 1]]]), faces = faces, convexity = 10);
}

module vessel(h, base_d, mid_d, top_d, belly_at, sides, ribs, rib_depth, twist, wave, waves,
              wall, floor, solid, drain_d, na, nz) {
    args = [base_d / 2, mid_d / 2, top_d / 2, belly_at, sides, ribs, rib_depth, twist, wave, waves];
    difference() {
        v_surface(h, 0, h, 0, args[0], args[1], args[2], args[3], args[4], args[5], args[6], args[7], args[8], args[9], na, nz, 0.5);
        if (!solid)
            v_surface(h, floor, h + 1, wall, args[0], args[1], args[2], args[3], args[4], args[5], args[6], args[7], args[8], args[9], na, nz, 0);
        if (!solid && drain_d > 0)
            translate([0, 0, -1]) cylinder(d = drain_d, h = floor + 2, $fn = 48);
    }
}
