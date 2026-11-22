// Shared helpers for the product recipes (round_case, product_holder, product_mount, board_plate,
// knob). A product row comes from lib/catalog.scad; its frame is evals/README.md's: x width,
// y depth, z height, origin at the body's min corner. Load with: use <lib/product.scad>

// A side face's frame, as in the README table: u along the face, v up, n out of the product.
function face_m(f, W, D) =
    f == "-y" ? [[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0]] :
    f == "+y" ? [[-1, 0, 0, W], [0, 0, 1, D], [0, 1, 0, 0]] :
    f == "+x" ? [[0, 0, 1, W], [1, 0, 0, 0], [0, 1, 0, 0]] :
                [[0, 0, -1, 0], [-1, 0, 0, D], [0, 1, 0, 0]];
function face_n(f) = f == "-y" ? [0, -1, 0] : f == "+y" ? [0, 1, 0] : f == "+x" ? [1, 0, 0] :
                     f == "-x" ? [-1, 0, 0] : f == "+z" ? [0, 0, 1] : [0, 0, -1];
function face_pt(f, u, v, n, W, D) = let(m = face_m(f, W, D)) [for (r = m) r[0] * u + r[1] * v + r[2] * n + r[3]];
// a side face's length along u
function face_len(f, W, D) = (f == "-y" || f == "+y") ? W : D;

module on_face(f, W, D) multmatrix(concat(face_m(f, W, D), [[0, 0, 0, 1]])) children();

function has(list, x) = len([for (e = list) if (e == x) 1]) > 0;
function clamp(x, lo, hi) = min(max(x, lo), hi);

// Every feature the maker locates on a side face, as its plug (or opening) plus `margin`, cut
// from n0 out to n1 along the face's normal. Mounting holes are left alone. square = true cuts a
// round feature as its square too: for a wall printed on its side, where a sliver left between a
// round window and its neighbor would start in the air.
module side_windows(FEATS, faces, W, D, n0, n1, margin = 0.5, square = false) {
    for (f = FEATS) if (f[1] != "hole" && has(faces, f[2])) on_face(f[2], W, D) {
        sw = max(f[5], f[7]) + 2 * margin;
        sh = max(f[6], f[8]) + 2 * margin;
        if (f[9] && !square) translate([f[3], f[4], n0]) cylinder(d = sw, h = n1 - n0);
        else translate([f[3] - sw / 2, f[4] - sh / 2, n0]) cube([sw, sh, n1 - n0]);
    }
}

// A product-frame point and direction moved into the part's STL coordinates by a rigid 4x4 matrix.
function xf_pt(M, p) = [for (i = [0:2]) M[i][0] * p[0] + M[i][1] * p[1] + M[i][2] * p[2] + M[i][3]];
function xf_dir(M, d) = [for (i = [0:2]) M[i][0] * d[0] + M[i][1] * d[1] + M[i][2] * d[2]];

// A 90 degree countersunk clearance hole along +z from z = 0 (the mouth, against the wall or desk)
// through a wall t thick, the head's seat at z = t (the side toward the product): for an ISO 7046
// flat head screw, whose head then sits flush below the wall's inner face.
module csk_through(bore, head_d, t) {
    translate([0, 0, -1]) cylinder(d = bore, h = t + 2);
    depth = (head_d - bore) / 2;
    translate([0, 0, t - depth]) cylinder(d1 = bore, d2 = head_d + 0.2, h = depth + 0.01);
    translate([0, 0, t]) cylinder(d = head_d + 0.2, h = 0.5);
}

// ISO 273 medium clearance holes (https://mechcodex.com/reference/metric-clearance-hole-sizes,
// a chart of the sold standard), mm.
function iso273_medium(m) = m == 2 ? 2.4 : m == 2.5 ? 2.9 : m == 3 ? 3.4 : m == 4 ? 4.5 : m == 5 ? 5.5 : 6.6;
