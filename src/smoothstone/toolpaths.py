"""Toolpaths without a slicer: what a slicer would print, from stone's own layer cut.

Each layer's cross-section (supports.cut) becomes, in the order OrcaSlicer prints a layer: support
lines under the regions stone supports found (when supports are on), the inner walls then the outer
(contours half a line, one and a half lines... in from the edge), gap fill where walls leave a
sliver, then infill: solid lines where the part is within the bottom or top shell layers of a
surface, a two-direction grid elsewhere. Widths, speeds, accelerations, shells and infill come from
the printer's slicer profile (OrcaSlicer's Creality K2 profile by default), and every move is timed
by the same planner as G-code (gcode.plan).

Each layer also keeps its modeled volume, so a test can hold the lines to it: walls, gap fill and
solid infill fill their area, the grid fills its density, support its line spacing.
"""

from __future__ import annotations

import math

import numpy as np

from . import gcode, refs, supports

FIL_AREA = math.pi * (1.75 / 2) ** 2  # mm2, 1.75 mm filament
# outline smoothing and simplifying, pixels (assumption: about a slicer's 0.0125 to 0.05 mm resolution
# once the 0.1 mm pixel staircase is gone; corners round by about SMOOTH_PX)
SMOOTH_PX = 1.5
SIMPLIFY_PX = 0.2


def spacing(width: float, height: float) -> float:
    """Center to center distance of neighbouring lines: a line is a rectangle with round ends, and
    each mm of it lays height x spacing of plastic (OrcaSlicer's flow model, refs slicer.flow_spacing)."""
    return width - height * (1.0 - math.pi / 4.0)


def profile(prof: dict | None = None) -> dict:
    """Widths, speeds, accelerations and shells for generated toolpaths: OrcaSlicer's K2 profile. Given a
    printer profile (its speeds), speeds, travel too, scale down and accelerations are capped for a slower
    printer (assumption: same proportions)."""
    prof = prof or {}
    v = lambda k: refs.get(k)["value"]  # noqa: E731
    sp, ac = dict(v("slicer.k2_speeds")), dict(v("slicer.k2_accels"))
    typical = float((prof.get("speeds") or {}).get("typical_print_mm_s") or sp["inner_wall"])
    cap = float((prof.get("speeds") or {}).get("max_accel_mm_s2") or v("slicer.k2_machine")["max_accel"])
    f = min(1.0, typical / sp["inner_wall"])
    speeds = {k: x * f for k, x in sp.items()}
    accels = {k: min(x, cap) for k, x in ac.items() if not k.startswith("jerk")}
    accels.update({"sparse_infill": accels["default"], "solid_infill": accels["default"]})
    return {"widths": v("slicer.k2_widths"), "speeds": speeds, "accels": accels, "shells": v("slicer.k2_shells"),
            "support": v("slicer.support_spacing"), "jerk": ac["jerk_walls"], "scaled": f < 1.0}


def _scan(region: np.ndarray, deg: float, spacing_px: float, offset_px: float = 0.0):
    """Straight lines across region at deg, spacing_px apart: (k, 2, 2) segments in pixel units
    (col, row), every other line reversed so the nozzle zigzags."""
    h, w = region.shape
    if not region.any():
        return np.zeros((0, 2, 2))
    t = math.radians(deg)
    d = np.array([math.cos(t), math.sin(t)])
    nrm = np.array([-d[1], d[0]])
    ys, xs = np.nonzero(region)
    u = xs * nrm[0] + ys * nrm[1]
    v = xs * d[0] + ys * d[1]
    ks = np.arange(math.ceil((u.min() - offset_px) / spacing_px), math.floor((u.max() - offset_px) / spacing_px) + 1)
    if not len(ks):
        return np.zeros((0, 2, 2))
    ts = np.arange(math.floor(v.min()) - 1, math.ceil(v.max()) + 2, 1.0)
    base = (ks * spacing_px + offset_px)[:, None, None] * nrm + ts[None, :, None] * d  # (lines, samples, 2)
    c = np.rint(base[..., 0]).astype(np.int64)
    r = np.rint(base[..., 1]).astype(np.int64)
    ok = (c >= 0) & (c < w) & (r >= 0) & (r < h)
    inside = np.zeros(c.shape, bool)
    inside[ok] = region[r[ok], c[ok]]
    pad = np.pad(inside, ((0, 0), (1, 1)))
    dd = np.diff(pad.astype(np.int8), axis=1)
    st, en = np.argwhere(dd == 1), np.argwhere(dd == -1)
    if not len(st):
        return np.zeros((0, 2, 2))
    line, a, b = st[:, 0], st[:, 1], en[:, 1] - 1
    p0 = base[line, a] - 0.5 * d  # a run of n samples covers n pixels of line
    p1 = base[line, b] + 0.5 * d
    seg = np.stack([p0, p1], 1)
    flip = (line % 2) == 1
    seg[flip] = seg[flip][:, ::-1]
    order = np.lexsort((np.where(flip, -a, a), line))
    return seg[order]


def _contours(mask: np.ndarray, smooth_px: float = SMOOTH_PX, simplify_px: float = SIMPLIFY_PX):
    """Closed polylines (col, row) around mask: outsides and holes alike. The pixel staircase is
    smoothed along the outline first, or every step would be a sharp corner the planner slows for."""
    import cv2
    from scipy.ndimage import gaussian_filter1d

    cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    out = []
    for c in cs:
        c = c[:, 0, :].astype(np.float64)
        if len(c) >= 8:
            c = gaussian_filter1d(c, smooth_px, axis=0, mode="wrap")
        c = cv2.approxPolyDP(c.astype(np.float32)[:, None, :], simplify_px, True)[:, 0, :].astype(float)
        if len(c) >= 2:
            out.append(np.vstack([c, c[:1]]))
    return out


def _paint(shape, polys, width_px: float) -> np.ndarray:
    """Pixels the lines cover at their width."""
    import cv2

    img = np.zeros(shape, np.uint8)
    t = max(1, int(round(width_px)))
    for p in polys:
        cv2.polylines(img, [np.rint(p).astype(np.int32)], False, 1, thickness=t)
    return img.astype(bool)


def generate(mesh, prof: dict, layer: float = 0.2, sup: dict | None = None, place=(0.0, 0.0)) -> gcode.Toolpath:
    """The part's toolpaths. prof: widths, speeds, accels (mm, mm/s, mm/s2 by feature), shells, jerk,
    max_feed. sup: supports.analyze(..., columns=True) on the same mesh and layer height, for support lines.
    place: mm added to x and y (the part's spot on the bed). Walls under two lines thick (about 0.8 mm, below
    any stone recipe's) come out as short infill dashes or a doubled line, not a slicer's one thin line."""
    import cv2
    from scipy import ndimage

    if abs(mesh.bounds[0][2]) > 1e-9:
        mesh = mesh.copy()
        mesh.apply_translation((0.0, 0.0, -float(mesh.bounds[0][2])))
    if sup and abs(sup["_grid"].layer - layer) > 1e-9:
        raise ValueError(f"supports were found at {sup['_grid'].layer} mm layers, not {layer}")
    grid, it = supports.cut(mesh, layer, sup["_grid"].px if sup else None)
    px = grid.px
    W, S, A, sh = prof["widths"], prof["speeds"], prof["accels"], prof["shells"]
    dens = sh["sparse_infill_density"] / 100.0
    n_walls = max(1, int(sh.get("wall_loops", 2)))
    sp = prof["support"]
    gap_layers = max(1, int(round(sp["top_z_distance"] / layer)))
    columns = (sup or {}).get("_columns", [])
    F = gcode.FEATURES.index
    rows: list[tuple] = []
    vol = {"expected": [], "generated": []}
    pos = [place[0] + grid.x(0), place[1] + grid.y(0), 0.0]
    ox, oy = place[0] + grid.lo[0] - grid.margin, place[1] + grid.lo[1] - grid.margin

    def xy(p):
        return ox + (p[..., 0] + 0.5) * px, oy + (p[..., 1] + 0.5) * px  # lines run through pixel centers

    def path(pts, feat, width, speed, accel, z, i):
        nonlocal pos
        x, y = xy(np.asarray(pts, float))
        if math.hypot(x[0] - pos[0], y[0] - pos[1]) > 1e-6:
            rows.append((pos[0], pos[1], z, x[0], y[0], z, 0.0, S["travel"], A["travel"], F("other"), 0.0, layer, i))
        seg = np.hypot(np.diff(x), np.diff(y))
        e = seg * spacing(width, layer) * layer / FIL_AREA
        for k in range(len(seg)):
            if seg[k] > 1e-6:
                rows.append((x[k], y[k], z, x[k + 1], y[k + 1], z, e[k], speed, accel, feat, width, layer, i))
        pos = [x[-1], y[-1], z]
        return float(seg.sum()) * spacing(width, layer) * layer

    masks: dict[int, np.ndarray] = {}
    src = iter(enumerate(it))
    loaded = -1
    for i in range(grid.n):
        while loaded < min(grid.n - 1, i + max(1, sh["top_shell_layers"])):
            k, m = next(src)
            masks[k] = m
            loaded = k
        for k in [k for k in masks if k < i - max(1, sh["bottom_shell_layers"])]:
            del masks[k]
        M = masks[i]
        z = (i + 1) * layer
        first = i == 0
        if pos[2] != z:
            rows.append((pos[0], pos[1], pos[2], pos[0], pos[1], z, 0.0, S["travel"], A["travel"], F("other"), 0.0, layer, i))
            pos[2] = z
        made = 0.0
        sup_area = 0.0
        wsup = W["first_layer"] if first else sp["line_width"]
        sup_fill = spacing(wsup, layer) / sp["base_pattern_spacing"]
        # i_top is the hanging layer; a gap of top_z_distance under it
        under = [(r, c, base) for _, i_top, r, c, base in columns if base.min() <= i < i_top - gap_layers]
        if under:
            sm = np.zeros(M.shape, bool)
            for r, c, base in under:
                sm[r[base <= i], c[base <= i]] = True
            if M.any():
                sm &= cv2.distanceTransform((~M).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE) * px > sp["object_xy_distance"]
            sup_area = float(sm.sum()) * px * px
            lab, n_isl = ndimage.label(sm)
            for k in range(1, n_isl + 1):  # each support island's lines centered on it
                isl = lab == k
                rows_k = np.flatnonzero(isl.any(1))
                mid, half = (rows_k[0] + rows_k[-1]) / 2.0, (rows_k[-1] - rows_k[0] + 1) / 2.0
                gap_px = sp["base_pattern_spacing"] / px
                odd, even = 2 * math.floor(half / gap_px) + 1, 2 * math.floor(half / gap_px + 0.5)
                shift = 0.0 if even == 0 or abs(odd - 2 * half / gap_px) <= abs(even - 2 * half / gap_px) else gap_px / 2
                for s in _scan(isl, 0.0, gap_px, (mid + shift) % gap_px):
                    made += path(s, F("support"), wsup, S["first_layer"] if first else S["support"],
                                 A["first_layer"] if first else A["default"], z, i)
        if not M.any():
            vol["expected"].append(sup_fill * sup_area * layer)
            vol["generated"].append(made)
            continue
        wo = W["first_layer"] if first else W["outer_wall"]
        wi = W["first_layer"] if first else W["inner_wall"]
        ws = W["first_layer"] if first else W["solid_infill"]
        wf = W["first_layer"] if first else W["sparse_infill"]
        dist = cv2.distanceTransform(M.astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE) * px  # mm to the edge
        walls = []
        so, si = spacing(wo, layer), spacing(wi, layer)
        # the outer wall's edge on the part's surface, each next wall one spacing in (Orca's perimeters)
        loops = [(wo / 2 + (so + si) / 2 + (j - 1) * si, wi, "inner wall", "inner_wall") for j in range(n_walls - 1, 0, -1)]
        for depth, w, feat, key in loops + [(wo / 2, wo, "outer wall", "outer_wall")]:
            for poly in _contours(dist >= depth):
                speed = S["first_layer"] if first else S[key]
                made += path(poly, F(feat), w, speed, A["first_layer"] if first else A[key], z, i)
                walls.append((poly, w))
        core = dist >= (wo / 2 + so / 2 if n_walls == 1 else wo / 2 + (so + si) / 2 + (n_walls - 1.5) * si)
        covered = np.zeros(M.shape, bool)
        for w in {w for _, w in walls}:
            covered |= _paint(M.shape, [poly for poly, pw in walls if pw == w], w / px)
        gap = M & ~core & ~covered
        gap = ndimage.binary_opening(gap)  # a speck under a line's width is noise, not a gap
        below = [masks.get(i - k) for k in range(1, sh["bottom_shell_layers"] + 1)]
        above = [masks.get(i + k) for k in range(1, sh["top_shell_layers"] + 1)]
        bottom = np.zeros(M.shape, bool) if all(b is not None for b in below) else np.ones(M.shape, bool)
        for b in below:
            if b is not None:
                bottom |= ~b
        top = np.zeros(M.shape, bool)
        for a in above:
            top |= ~a if a is not None else True
        solid = core & (bottom | top)
        sparse = core & ~solid
        deg = 45.0 if i % 2 == 0 else 135.0
        for region, feat in ((gap, "solid infill"), (solid, None)):
            for s in _scan(region, deg, spacing(ws, layer) / px):
                mid = np.rint(s.mean(0)).astype(int)[::-1]
                if feat is None:
                    at = tuple(np.clip(mid, 0, np.array(M.shape) - 1))
                    over, under_it = masks.get(i + 1), masks.get(i - 1)
                    up = over is None or not over[at]
                    name = "top surface" if up else "bottom surface" if under_it is None or not under_it[at] else "solid infill"
                else:
                    name = feat
                key = {"top surface": "top_surface", "bottom surface": "solid_infill"}.get(name, "solid_infill")
                made += path(s, F(name), ws, S["first_layer_infill"] if first else S[key],
                             A["first_layer"] if first else A[key], z, i)
        if dens > 0 and sparse.any():
            gap_px = 2 * spacing(wf, layer) / dens / px  # a grid lays two directions, each at twice the spacing
            for g in (45.0, 135.0):
                for s in _scan(sparse, g, gap_px):
                    made += path(s, F("sparse infill"), wf, S["sparse_infill"], A["sparse_infill"], z, i)
        area = px * px
        vol["expected"].append(layer * area * (float((M & ~core).sum()) + float(solid.sum()) + dens * float(sparse.sum()))
                               + sup_fill * sup_area * layer)
        vol["generated"].append(made)
    a = np.array(rows, float).reshape(-1, 13)
    e0 = np.r_[0.0, np.cumsum(a[:, 6])[:-1]]
    p0 = np.c_[a[:, 0:3], e0]
    p1 = np.c_[a[:, 3:6], e0 + a[:, 6]]
    jerk = float(prof.get("jerk", 8.0))
    tp = gcode.Toolpath(p0, p1, a[:, 7], a[:, 8], a[:, 12].astype(int), a[:, 9].astype(int), a[:, 10], a[:, 11],
                        np.zeros(len(a)), [round((i + 1) * layer, 4) for i in range(grid.n)], [jerk, jerk, 0.4, 5.0],
                        list(prof.get("max_feed", [1e9] * 4)), list(prof.get("max_accel", [1e9] * 4)), "generated")
    tp.volumes = {k: np.asarray(v) for k, v in vol.items()}
    return gcode.plan(tp)
