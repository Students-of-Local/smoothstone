// phone_case: a fitted case for the iPhone 17, 17 Pro, 17 Pro Max or Air, built from Apple's
// dimensional drawings (devices.json -> devices.scad). Prints lying on its back, no supports:
// every slot ceiling climbs at least 45 degrees through the wall, and the screen lip is a
// 45 degree chamfer. One body with a flat back.
use <lib/stone.scad>

phone = "iphone_17_pro";   // iphone_17 | iphone_17_pro | iphone_17_pro_max | iphone_air
material = "rigid";        // rigid (PLA, PETG, ABS: 0.25 mm room per side) | tpu (0.05 mm per side)
wall = 1.6;                // side wall outside the phone, mm
back = 1.4;                // back plate, mm (Apple: at most 2.1)
lip = 0.8;                 // how far the rim stands above the screen, mm
buttons = "cutout";        // cutout = open slots | cover = covers you press through
camera_margin = 1.0;       // room around the camera plateau, mm
text = "";                 // engraved on the back; empty for none
text_size = 0;             // letter height, mm; 0 = fit the width
font = "sans";             // sans | serif | mono
slice = 0;                 // 0 = whole case; above 0 = only the top this many mm, a fit-test ring
quality = 48;              // circle smoothness

include <devices.scad>

$fn = quality;
F = font == "serif" ? "Liberation Serif:style=Bold" : font == "mono" ? "Liberation Mono:style=Bold" : "Liberation Sans:style=Bold";

c = material == "tpu" ? 0.05 : 0.25;   // room between phone and case, per side
W = DEV_W;
H = DEV_H;
T = DEV_T;
Htot = back + T + lip;                 // case height
f = DEV_FLOOR_F;                       // floor-to-wall chamfer that clears the back edge
z_lip = back + T / 2 + DEV_LIP_Z;      // the lip turns inward from here, clear of the front edge
tip = 0.35;                            // the lip ends in a short upright face, not a knife edge
reach = min((Htot - 0.2 - tip - z_lip) * 0.98, min(DEV_ACTIVE_IN, DEV_FLAT_IN) - 0.6 + c);
z_lip_end = z_lip + reach / 0.98;      // slope a little steeper than 45 degrees
K = 1.05;                              // ceiling climb per mm of depth in every slot (over 1 = under 45 degrees)
wall_out = c + wall;                   // phone surface to outside of the wall
WV = c + 0.2;                          // low point of port slots: just inside the wall, so its inner edge is blunt

assert(z_lip < Htot - 0.6, "lip too low to hold the phone: raise lip");
assert(back <= 2.1, "Apple allows at most 2.1 mm on the back");

// Geometry is built as polyhedron lofts through exact profile rings, not hulls of thin slabs:
// the hull of two matching convex rings is the same solid, without the hairline slivers that
// break the STL when it is written in float32.

// Offset a convex counterclockwise polygon by d (miter at each vertex; the outline is dense).
function off_pts(P, d) = let(m = len(P)) [for (i = [0:m - 1]) let(
    a = P[(i - 1 + m) % m], p = P[i], b = P[(i + 1) % m],
    e1 = (p - a) / norm(p - a), e2 = (b - p) / norm(b - p),
    n1 = [e1[1], -e1[0]], n2 = [e2[1], -e2[0]],
    mn = (n1 + n2) / norm(n1 + n2))
    p + mn * d / (mn * n1)];

module phone2d(d = 0) { polygon(off_pts(DEV_OUTLINE, d)); }

// Rounded rectangle as points, counterclockwise; r below 0.05 gives sharp corners.
function rr_pts(u0, u1, v0, v1, r, n = 8) = let(
    rr = min(r, (u1 - u0) / 2 - 0.001, (v1 - v0) / 2 - 0.001),
    sharp = rr < 0.05, k = sharp ? 0 : n, rad = sharp ? 0 : rr)
    [for (q = [0:3]) let(cx = (q == 0 || q == 3) ? u1 - rad : u0 + rad, cy = q < 2 ? v1 - rad : v0 + rad)
        for (j = [0:k]) let(a = 90 * q + (k == 0 ? 45 : 90 * j / k))
            [cx + rad * cos(a), cy + rad * sin(a)]];

// Segments per quarter so a chord sags at most 0.01 mm from the true arc (the camera corners are R12 and up).
function arc_n(r) = r < 0.05 ? 1 : max(4, ceil(90 / (2 * acos(1 - min(0.01 / r, 1)))));
module rr2(u0, u1, v0, v1, r) { polygon(rr_pts(u0, u1, v0, v1, r, arc_n(r))); }

// Solid through rings of equal length, each [z, [[x, y], ...]] counterclockwise, z increasing.
module stack(rings) {
    m = len(rings[0][1]);
    n = len(rings);
    polyhedron(
        points = [for (r = rings) for (p = r[1]) [p[0], p[1], r[0]]],
        faces = concat(
            [[for (j = [0:m - 1]) j]],
            [[for (j = [m - 1:-1:0]) (n - 1) * m + j]],
            [for (i = [0:n - 2], j = [0:m - 1]) [i * m + j, (i + 1) * m + j, (i + 1) * m + (j + 1) % m, i * m + (j + 1) % m]]),
        convexity = 4);
}

// The same, stacked outward through a wall: rings are [w, profile in (u, z)], w increasing.
// rotate maps (u, z, -w) to (u, w, z).
module wall_stack(rings) {
    rotate([90, 0, 0]) stack([for (i = [len(rings) - 1:-1:0]) [-rings[i][0], rings[i][1]]]);
}

// One profile of a wall cut at depth w (w = 0 at the phone's surface, outward +).
// Ceiling: zc + h/2 + kt * |w - wv| (a V with its low point at wv). Floor: drops kb per mm past wv.
// At the last profile (ext), a floor or ceiling within 0.8 mm of the bed or the top runs out through it.
function cut_ring(w, L, h, zc, r, wv, kt, kb, e, ext = false) = let(
    d = w - wv,
    t0 = zc + h / 2 + kt * abs(d),
    b0 = zc - h / 2 - kb * max(d, 0),
    t = ext && t0 > Htot - 0.8 ? Htot + 1 : t0,
    b = ext && b0 < 0.8 ? -1 : b0,
    hl = L / 2 + e * max(d, 0))
    [w, rr_pts(-hl, hl, b, t, r, max(4, round(quality / 8)))];

// A slot through the wall, in the wall's own frame: u along the wall, w outward, z up.
// It starts past the lip's inner edge (w0), so a slot that rises through the lip takes all of it, not leaving a fin.
module wall_cut(L, h, zc, r, wv, kt = K, kb = 0, e = 0.6, w0 = undef, w1 = undef) {
    wi = is_undef(w0) ? min(-0.5, c - reach - 0.3) : w0;
    we = is_undef(w1) ? wall_out + 1 : w1;
    rr = min(r, h / 2);
    wall_stack(concat(
        wi < wv ? [cut_ring(wi, L, h, zc, rr, wv, kt, kb, e)] : [],
        [cut_ring(wv, L, h, zc, rr, wv, kt, kb, e)],
        we > wv ? [cut_ring(we, L, h, zc, rr, wv, kt, kb, e, true)] : []));
}

// A flat-sided channel through the wall that climbs K per mm outward (slits, never a flat ceiling).
module climb_cut(u0, u1, v0, v1, wa, wb) {
    wall_stack([[wa, rr_pts(u0, u1, v0, v1, 0)], [wb, rr_pts(u0, u1, v0 + K * (wb - wa), v1 + K * (wb - wa), 0)]]);
}

// Put a wall-frame child on a wall of the phone: side -1 = left (Action, volume), 1 = right,
// "bottom" and "top" take an X position.
module on_side(side, y) { translate([side * W / 2, y, 0]) rotate(side < 0 ? 90 : -90) children(); }
module on_bottom(x) { translate([x, -H / 2, 0]) rotate(180) children(); }

module cavity() {
    stack([
        [back, off_pts(DEV_OUTLINE, c - f)],
        [back + f, off_pts(DEV_OUTLINE, c)],
        [z_lip, off_pts(DEV_OUTLINE, c)],
        [z_lip_end, off_pts(DEV_OUTLINE, c - reach)],     // the lip's underside, steeper than 45 degrees
        [Htot - 0.2, off_pts(DEV_OUTLINE, c - reach)],    // upright tip
        [Htot + 0.01, off_pts(DEV_OUTLINE, c - reach + 0.21)],
    ]);
}

module shell() {
    t = 1.0;   // rounded top edge
    b = 0.6;   // 45 degree chamfer at the bed, so the first layer does not flare
    stack(concat(
        [[0, off_pts(DEV_OUTLINE, wall_out - b)], [b, off_pts(DEV_OUTLINE, wall_out)]],
        [for (i = [0:6]) let(a = 90 * i / 6) [Htot - t + t * sin(a), off_pts(DEV_OUTLINE, wall_out - t * (1 - cos(a)))]]));
}

// Camera: the plateau (or Apple's dimensioned area around it) plus the margin, kept inside the cavity.
module camera2d() {
    intersection() {
        offset(r = camera_margin) hull() {
            for (q = DEV_CAM_RECTS) rr2(q[0], q[1], q[2], q[3], q[4]);
            for (q = DEV_CAM_CIRCLES) translate([q[0], q[1]]) circle(d = q[2]);
        }
        phone2d(c + 0.05);  // 0.05 into the wall, so its sides never lie on the cavity's
    }
}

module camera_cut() {
    translate([0, 0, -1]) linear_extrude(back + f + 1.3) camera2d();
    hull() {  // soft outside edge, steeper than 45 degrees
        translate([0, 0, -1]) linear_extrude(1.0) offset(delta = 0.3) camera2d();
        translate([0, 0, 0.4]) linear_extrude(0.01) camera2d();
    }
}

module button_cuts() {
    for (b = DEV_BUTTONS) {
        side = b[0]; y = b[1]; len = b[2]; bw = b[3]; zc = back + b[4]; prot = b[5];
        on_side(side, y) {
            if (buttons == "cutout") wall_cut(len + 1, bw + 1, zc, (bw + 1) / 2, prot);
            else cover_cut(len, bw, zc, prot);
        }
    }
    // Camera Control is always open: Apple's keepout, flaring 55 degrees from the surface. The low
    // point sits just inside the wall (wv), grown by the flare, so the keepout holds at every depth
    // and the inner top edge is 135 degrees, not a 45 degree knife edge.
    cc = DEV_CAMERA_CONTROL;
    g = cc[7] * WV;
    on_side(1, cc[0]) wall_cut(cc[4] + 2 * g, 2 * cc[5] + 2 * g, back + cc[3], cc[6] + g, WV, cc[7], cc[7], cc[7]);
}

// Cover: a pocket for the button behind the wall; on rigid cases the wall over it is a tab
// cut free on three sides (slits that climb through the wall) and hinged at the far end.
module cover_cut(len, bw, zc, prot) {
    wv = prot + 0.05;
    h = bw + 1;
    wall_cut(len + 1, h, zc, h / 2, wv, w1 = wv);
    if (material != "tpu") {
        lt = len + 1.6;  // ends stay clear of the next button's slits (Air: 3 mm between buttons)
        vb = zc - h / 2;
        vt = zc + h / 2 + (wv - c) * K;
        climb_cut(-lt / 2 - 0.6, lt / 2, vt, vt + 0.6, c - 0.3, wall_out + 0.3);
        climb_cut(-lt / 2 - 0.6, lt / 2, vb - 0.6, vb, c - 0.3, wall_out + 0.3);
        climb_cut(-lt / 2 - 0.6, -lt / 2, vb - 0.6, vt + 0.6, c - 0.3, wall_out + 0.3);
    }
}

module cover_pads() {
    for (b = DEV_BUTTONS) {
        side = b[0]; y = b[1]; len = b[2]; bw = b[3]; zc = back + b[4]; prot = b[5];
        h = bw + 1;
        zp = material != "tpu" ? zc + ((prot + 0.05 - c) * K) / 2 + K * wall : zc;
        on_side(side, y) wall_stack([
            [wall_out - 0.2, rr_pts(-len / 2, len / 2, zp - bw / 2, zp + bw / 2, bw / 2)],
            [wall_out + 0.3, rr_pts(-len / 2 + 0.35, len / 2 - 0.35, zp - bw / 2 + 0.35, zp + bw / 2 - 0.35, bw / 2 - 0.35)]]);
    }
}

module bottom_cuts() {
    u = DEV_USB;  // [x, z, either-face spread, keepout w, keepout h, keepout r]
    on_bottom(u[0]) wall_cut(u[3] + 1, u[4] + 1 + 2 * u[2], back + u[1], u[5] + 0.5, WV);
    d = DEV_PORT_D;
    for (g = DEV_PORTS) on_bottom((g[0] + g[1]) / 2)
        wall_cut(g[1] - g[0] + d + 1, d + 1 + 2 * DEV_PORT_AMB, back + DEV_PORT_Z, (d + 1) / 2 + DEV_PORT_AMB, WV);
}

// Receiver: take the lip away over the earpiece slot, with 45 degree ends.
module receiver_cut() {
    r = DEV_RECEIVER;  // [from top, to, length]
    hl = r[2] / 2 + 0.5;
    y0 = H / 2 - r[1] - 0.5;
    hull() {
        translate([-hl, y0, z_lip]) cube([2 * hl, H / 2 + c - y0, 0.01]);
        translate([-hl - (Htot + 1 - z_lip), y0, Htot + 1]) cube([2 * hl + 2 * (Htot + 1 - z_lip), H / 2 + c - y0, 0.01]);
    }
}

// Text: a V-sided groove in the back, read from behind, so the first layer bridges nothing wide.
module text_cut() {
    s = min(0.45, (back - 0.6) / 1.25);
    ts = text_size > 0 ? text_size : min(10, W * 0.6 / max(1, len(text)) * 1.5);
    translate([0, -H * 0.24, -0.01]) mirror([1, 0, 0]) minkowski() {
        linear_extrude(0.01) offset(delta = -s) label2d(text, ts, F);
        cylinder(r1 = s, r2 = 0, h = s * 1.25, $fn = 12);
    }
}

module case() {
    difference() {
        union() {
            shell();
            if (buttons == "cover") cover_pads();
        }
        cavity();
        camera_cut();
        button_cuts();
        bottom_cuts();
        receiver_cut();
        if (text != "") text_cut();
    }
}

// Fit-test ring: the top slice mm of the walls and lip, without the back plate.
ring = min(slice, Htot);
if (slice > 0) {
    bed_chamfer() translate([0, 0, ring - Htot]) difference() {
        intersection() {
            case();
            translate([-W, -H, Htot - ring]) cube([2 * W, 2 * H, ring + 1]);
        }
        translate([0, 0, -1]) linear_extrude(back + f + 1.3) phone2d(c + 0.05);
    }
} else case();
