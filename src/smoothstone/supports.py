"""stone supports: before a print, whether the part needs supports, where, and why.

The part is cut into layers on a pixel grid with slicer.py's cut, and each layer is compared with the
one below, the way a slicer's support generator does:

- a piece with nothing under it starts in mid air (island);
- a part of a layer reaching farther past the layer below than one layer's reach hangs (ledge); the
  reach is layer height x tan(90 - threshold), with OrcaSlicer's 30 deg threshold from the bed. On a
  0.1 mm grid one 0.2 mm layer's step is only 3 or 4 pixels either side of the 3.5 pixel reach, so
  pixels alone cannot tell 58 deg from 63; a piece within a pixel of the reach (about 50 to 72 deg
  from vertical) hangs only when a face past the threshold bounds it;
- a hanging piece held on two opposite sides is a bridge, and prints with no support up to the
  slicer's max bridge length (10 mm in OrcaSlicer and its K2 profile).

Then the faces (overhang area by angle, from each face's normal), tipping (statics: the center of
mass of the part printed so far over its first layer; and OrcaSlicer's auto brim formula for a part
tall for its base), and the six resting orientations compared on support volume, as advice only.
"""

from __future__ import annotations

import json
import math
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import config, refs, slicer

LAYER = slicer.LAYER  # mm
PX = 0.1  # mm: the grid a layer is drawn on; a bigger part gets a coarser one
MAX_PIXELS = 2_500_000  # per layer
MAX_SIZE = 1000.0  # mm: a part longer than this on any side is in the wrong units (no bed is that big)
MAX_LAYERS = 10_000  # 2 m at 0.2 mm layers
COVER = 0.9  # share of a hanging piece the lines of one direction must cross, held at both ends, to call it a bridge (stone's rule)
LINK = 1.0  # mm: hanging pieces this close in consecutive layers are one region
FACE_NEAR = 1.0  # mm: a face this close to a region's points belongs to it
BANDS = ((45, 60), (60, 75), (75, 90))  # deg from vertical
ORCA_MAX_BRIM = 18.0  # mm, the cap in OrcaSlicer's auto brim formula (Brim.cpp)
ORCA_BRIM_DIV = 1920.0  # the formula's divisor (Brim.cpp)
BRIM_RISK = 5.0  # mm: Orca omits a smaller auto brim (Brim.cpp, "small brims are omitted")
ADHESION = {"PLA": 1.0, "PLA+": 1.0, "PETG": 2.0, "ASA": 1.0, "ABS": 1.0, "TPU": 0.5, "PA": 1.0, "PC": 1.0}  # OrcaSlicer MaterialType.cpp
SOURCES = ("slicer.support_threshold_angle", "slicer.max_bridge_length", "slicer.support_spacing",
           "slicer.auto_brim", "physics.support_polygon", "slicer.k2_speeds")
RED, YELLOW, CLAY = (215.0, 50.0, 45.0), (235.0, 190.0, 50.0), (205.0, 200.0, 190.0)


def threshold() -> float:
    return float(refs.get("slicer.support_threshold_angle")["value"])  # deg from the bed


def max_bridge() -> float:
    return float(refs.get("slicer.max_bridge_length")["value"])


def reach(layer: float = LAYER) -> float:
    """How far (mm) one layer may reach past the one below with no support."""
    return layer * math.tan(math.radians(90 - threshold()))


@dataclass
class Grid:
    lo: np.ndarray  # the mesh's lower corner, mm
    px: float
    layer: float
    n: int  # layers
    w: int
    h: int
    margin: float

    def x(self, cols):
        return self.lo[0] - self.margin + (np.asarray(cols) + 0.5) * self.px

    def y(self, rows):
        return self.lo[1] - self.margin + (np.asarray(rows) + 0.5) * self.px

    def z(self, i: int) -> float:
        """The bottom of layer i, mm."""
        return float(self.lo[2] + i * self.layer)


def cut(mesh, layer: float = LAYER, px: float | None = None):
    """The grid, and an iterator over every layer's filled cross-section (h, w) cut at mid layer.
    Raises ValueError for a part no printer could hold: its layers would take hours or not fit in
    memory."""
    lo, hi = (np.asarray(b, float) for b in mesh.bounds)
    ext = hi - lo
    if not layer > 0:
        raise ValueError(f"layer height {layer} mm is not a layer height")
    if float(ext.max()) > MAX_SIZE:
        raise ValueError(f"the part is {' x '.join(f'{v:.0f}' for v in ext)} mm, too big for any bed: "
                         "is it in the wrong units (inches, microns)?")
    if ext[2] / layer > MAX_LAYERS:
        raise ValueError(f"{ext[2]:.0f} mm at {layer} mm layers is {ext[2] / layer:.0f} layers, over {MAX_LAYERS}")
    px = px or max(PX, math.sqrt((ext[0] + 1) * (ext[1] + 1) / MAX_PIXELS))
    margin = 3 * px
    w = int(math.ceil((ext[0] + 2 * margin) / px))
    h = int(math.ceil((ext[1] + 2 * margin) / px))
    n = max(1, int(math.floor(ext[2] / layer + 0.5)))
    tris = np.asarray(mesh.triangles, float) - lo
    eps = 1e-6 * max(1.0, float(ext[2]))
    tz = tris[:, :, 2]
    first = np.clip(np.floor((tz.min(1) - eps) / layer - 0.5).astype(np.int64), 0, n - 1)
    last = np.clip(np.ceil((tz.max(1) - eps) / layer - 0.5).astype(np.int64), 0, n - 1)
    span = last - first + 1
    tri_of = np.repeat(np.arange(len(tris)), span)
    layer_of = np.repeat(first, span) + np.arange(len(tri_of)) - np.repeat(np.cumsum(span) - span, span)
    tri_of = tri_of[np.argsort(layer_of, kind="stable")]
    bounds = np.r_[0, np.cumsum(np.bincount(layer_of, minlength=n))]
    grid = Grid(lo, px, layer, n, w, h, margin)

    def one(i):
        seg = slicer._segments(tris[tri_of[bounds[i]:bounds[i + 1]]], (i + 0.5) * layer + eps)
        return slicer._raster(seg, -margin, -margin, w, h, px) if len(seg) else np.zeros((h, w), bool)

    def layers():
        with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 1)) as pool:
            for a in range(0, n, 16):
                yield from pool.map(one, range(a, min(n, a + 16)))

    return grid, layers()


def _lines(a: np.ndarray, deg: int) -> np.ndarray:
    """The array turned so lines in direction deg (0, 45, 90, 135) run along its rows."""
    if deg == 0:
        return a
    if deg == 90:
        return a.T
    h, w = a.shape
    r, c = np.indices(a.shape)
    k = c - r + h - 1 if deg == 45 else c + r
    out = np.zeros((w + h - 1, h), bool)
    out[k.ravel(), r.ravel()] = a.ravel()
    return out


def bridge_span(piece: np.ndarray, held: np.ndarray, px: float) -> tuple[float, int] | None:
    """A hanging piece and what holds it (same crop): the span of the bridge it makes, (mm, deg), in
    the direction whose lines cross it held at both ends with the shortest longest line; None when no
    direction holds it on two opposite sides."""
    best = None
    for deg in (0, 90, 45, 135):
        step = px * (math.sqrt(2) if deg in (45, 135) else 1.0)
        u = np.pad(_lines(piece, deg), ((0, 0), (1, 1)))
        an = np.pad(_lines(held, deg), ((0, 0), (1, 1)))
        d = np.diff(u.astype(np.int8), axis=1)
        st, en = np.argwhere(d == 1), np.argwhere(d == -1)
        if not len(st):
            continue
        rows, s, e = st[:, 0], st[:, 1] + 1, en[:, 1]
        length = e - s + 1
        both = an[rows, s - 1] & an[rows, e + 1]
        if length[both].sum() >= COVER * length.sum():
            span = float(length[both].max()) * step
            if best is None or span < best[0]:
                best = (span, deg)
    return best


class _Union:
    def __init__(self):
        self.up: list[int] = []

    def add(self) -> int:
        self.up.append(len(self.up))
        return len(self.up) - 1

    def root(self, a: int) -> int:
        while self.up[a] != a:
            self.up[a] = self.up[self.up[a]]
            a = self.up[a]
        return a

    def join(self, a: int, b: int) -> None:
        self.up[self.root(a)] = self.root(b)


class _Steep:
    """The faces past the threshold, to ask whether one bounds a piece the pixels cannot decide."""

    def __init__(self, mesh, layer: float, tol: float):
        ang, bed = face_angles(mesh)
        t = np.asarray(mesh.triangles, float)[(ang > 90 - threshold()) & ~bed]
        self.t, self.lo, self.hi = t, t.min(1), t.max(1)
        self.half, self.tol = layer / 2, tol

    def near(self, x: np.ndarray, y: np.ndarray, z: float, most: int = 400) -> bool:
        """Whether a steep face lies within tol of any point (x, y, z); z is the middle of the slab
        between this layer's cut and the one below, where the face that makes the step crosses."""
        if not len(self.t):
            return False
        from trimesh.triangles import closest_point

        tol = self.tol
        sel = ((self.lo[:, 2] <= z + self.half + tol) & (self.hi[:, 2] >= z - self.half - tol)
               & (self.lo[:, 0] <= x.max() + tol) & (self.hi[:, 0] >= x.min() - tol)
               & (self.lo[:, 1] <= y.max() + tol) & (self.hi[:, 1] >= y.min() - tol))
        if not sel.any():
            return False
        k = max(1, int(math.ceil(len(x) / most)))
        p = np.c_[x[::k], y[::k], np.full(len(x[::k]), z)]
        for t in np.array_split(self.t[sel], max(1, int(sel.sum()) * len(p) // 200_000)):
            tt, pp = np.repeat(t, len(p), 0), np.tile(p, (len(t), 1))
            if (np.linalg.norm(closest_point(tt, pp) - pp, axis=1) <= tol).any():
                return True
        return False


def analyze(mesh, layer: float = LAYER, material: str = "PLA", px: float | None = None, columns: bool = False) -> dict:
    """Everything stone supports reports, as a dict ready for supports.json. With columns=True it also
    keeps, under "_columns", each needed region's pixels per layer for the toolpath generator."""
    from scipy import ndimage

    if abs(mesh.bounds[0][2]) > 1e-9:  # a slicer drops the part onto the bed: z is height above it
        mesh = mesh.copy()
        mesh.apply_translation((0.0, 0.0, -float(mesh.bounds[0][2])))
    grid, layers = cut(mesh, layer, px)
    px, px2 = grid.px, grid.px * grid.px
    rpx = reach(layer) / px
    # Each edge snaps to the grid, so a step of a pixels shows as floor(a) or ceil(a), and a square
    # corner as up to sqrt(2) x (a + 1). A face past the threshold (a > rpx) therefore always shows
    # a pixel farther than rpx - 1, and a face under it never one farther than sqrt(2) x (rpx + 1).
    # Pixels past the first are candidates; one past the second hangs on the pixels' word; between
    # the two (about 50 to 72 deg at 0.1 mm), the faces decide.
    lo_px, hi_px = rpx - 1, math.sqrt(2) * (rpx + 1)
    steep = _Steep(mesh, layer, max(px, layer))
    limit = max_bridge()
    eight = np.ones((3, 3), bool)
    link = int(math.ceil(LINK / px))
    pad = int(math.ceil(rpx)) + link + 3
    top = np.zeros((grid.h, grid.w), np.float32)  # mm above the bed of the material in each column so far
    hang = np.zeros((grid.h, grid.w), np.int32)  # piece id + 1 of each hanging pixel of the layer below
    prev = np.zeros((grid.h, grid.w), bool)
    pieces: list[dict] = []
    uf = _Union()
    first = None
    mass = []  # per layer: area mm2, x, y, top z
    cols: list[tuple] = []
    for i, mask in enumerate(layers):
        zb, zt = i * layer, (i + 1) * layer
        if mask.any():
            ys, xs = np.nonzero(mask)
            mass.append((len(ys) * px2, float(grid.x(xs).mean()), float(grid.y(ys).mean()), zt))
        if i == 0:
            first = mask
        elif mask.any():
            rows, cs = np.flatnonzero((mask | prev).any(1)), np.flatnonzero((mask | prev).any(0))
            win = (slice(max(0, rows[0] - pad), rows[-1] + pad + 1), slice(max(0, cs[0] - pad), cs[-1] + pad + 1))
            lm, lp = mask[win], prev[win]
            d = ndimage.distance_transform_edt(~lp) if lp.any() else np.full(lm.shape, np.inf)
            far = lm & (d > lo_px)
            nxt = np.zeros(lm.shape, np.int32)
            found = []
            if far.any():
                lab, _ = ndimage.label(far, eight)
                for c, box in enumerate(ndimage.find_objects(lab), 1):
                    yy, xx = np.nonzero(lab[box] == c)
                    yy, xx = yy + box[0].start, xx + box[1].start
                    if d[yy, xx].max() > hi_px or steep.near(grid.x(xx + win[1].start), grid.y(yy + win[0].start), grid.z(i)):
                        found.append((yy, xx))
            if found:
                ulab, _ = ndimage.label(lm & ~lp, eight)
                mlab, mk = ndimage.label(lm, eight)
                held = np.zeros(mk + 1, bool)
                held[np.unique(mlab[lm & ndimage.binary_dilation(lp, eight)])] = True
                held[0] = False
                below = ndimage.grey_dilation(hang[win], footprint=slicer._disk(link)) if hang[win].any() else hang[win]
                uboxes = ndimage.find_objects(ulab)
                for yy, xx in found:
                    at = (yy[0], xx[0])
                    kind, span = "ledge", None
                    if not held[mlab[at]]:
                        kind = "island"
                    else:
                        ub = tuple(slice(max(0, b.start - 1), b.stop + 1) for b in uboxes[ulab[at] - 1])
                        got = bridge_span(ulab[ub] == ulab[at], (lm & lp)[ub], px)
                        if got:
                            span = round(got[0], 2)
                            kind = "bridge" if got[0] <= limit else "long bridge"
                    gr, gc = yy + win[0].start, xx + win[1].start
                    need = kind != "bridge"
                    vol = float(np.clip(zb - top[gr, gc], 0, None).sum()) * px2 if need else 0.0
                    lean = math.degrees(math.atan2(float(d[yy, xx].max()) * px, layer)) if kind == "ledge" else 90.0
                    step = max(1, int(round(0.5 / px)))
                    keep = (gr % step == 0) & (gc % step == 0)
                    if not keep.any():
                        keep[0] = True
                    pid = uf.add()
                    pieces.append({"i": i, "z": (grid.z(i), grid.z(i + 1)), "area": len(yy) * px2, "kind": kind,
                                   "span": span, "need": need, "mm3": vol, "lean": lean,
                                   "x": float(grid.x(gc).mean()), "y": float(grid.y(gr).mean()),
                                   "pts": np.c_[grid.x(gc[keep]), grid.y(gr[keep]), np.full(keep.sum(), grid.z(i))]})
                    for other in np.unique(below[yy, xx]):
                        if other and pieces[other - 1]["need"] == need:
                            uf.join(pid, int(other) - 1)
                    nxt[yy, xx] = pid + 1
                    if columns and need:
                        cols.append((pid, i, gr, gc, np.round(top[gr, gc] / layer).astype(np.int32)))
            hang[:] = 0
            hang[win] = nxt
        else:
            hang[:] = 0
        top[mask] = zt
        prev = mask
    rep = _report(mesh, grid, pieces, uf, first, mass, material)
    if columns:
        rep["_columns"] = [(uf.root(pid), i, r, c, base) for pid, i, r, c, base in cols]
        rep["_grid"] = grid
    return rep


def _regions(pieces: list[dict], uf: _Union) -> list[dict]:
    groups: dict[int, list[dict]] = {}
    for pid, p in enumerate(pieces):
        groups.setdefault(uf.root(pid), []).append(p)
    out = []
    for root, ps in groups.items():
        area = sum(p["area"] for p in ps)
        kinds = sorted({p["kind"] for p in ps}, key=["island", "long bridge", "ledge", "bridge"].index)
        need = ps[0]["need"]
        small = slicer.ISLAND if "island" in kinds else slicer.LEDGE_AREA
        if need and area < small:
            continue
        spans = [p["span"] for p in ps if p["span"] is not None]
        out.append({"root": root, "need": need, "z": [round(min(p["z"][0] for p in ps), 2), round(max(p["z"][1] for p in ps), 2)],
                    "area_mm2": round(area, 1), "why": kinds, "span_mm": max(spans) if spans else None,
                    "where": [round(sum(p["x"] * p["area"] for p in ps) / area, 1), round(sum(p["y"] * p["area"] for p in ps) / area, 1)],
                    "support_mm3": round(sum(p["mm3"] for p in ps), 1), "worst_deg": round(max(p["lean"] for p in ps), 1),
                    "pts": np.concatenate([p["pts"] for p in ps])})
    return sorted(out, key=lambda r: (not r["need"], -r["support_mm3"], -r["area_mm2"]))


def face_angles(mesh) -> tuple[np.ndarray, np.ndarray]:
    """Each face's overhang angle from vertical (0 a wall, 90 a flat ceiling; 0 for faces that look
    up) and whether it lies on the bed."""
    n = np.asarray(mesh.face_normals)
    ang = np.degrees(np.arcsin(np.clip(-n[:, 2], 0.0, 1.0)))
    bed = (np.asarray(mesh.triangles_center)[:, 2] - mesh.bounds[0][2] < LAYER / 2) & (n[:, 2] < -0.99)
    return ang, bed


def _tipping(mesh, grid: Grid, first, mass, material: str) -> dict:
    from scipy.spatial import ConvexHull, QhullError

    if first is None or not first.any():
        return {"risk": True, "why": "nothing touches the bed"}
    from scipy import ndimage

    ys, xs = np.nonzero(first)
    x, y = grid.x(xs), grid.y(ys)
    by_, bx_ = np.nonzero(first & ~ndimage.binary_erosion(first))  # the hull needs only the edge
    h = grid.px / 2
    pts = np.concatenate([np.c_[grid.x(bx_) + dx, grid.y(by_) + dy] for dx in (-h, h) for dy in (-h, h)])
    try:
        hull = ConvexHull(pts)
    except (QhullError, ValueError):
        return {"risk": True, "why": "the first layer has no area"}
    hp = pts[hull.vertices]
    widths = [float(np.abs((hp - hp[k]) @ (np.array([-e[1], e[0]]) / max(1e-9, np.hypot(*e)))).max())
              for k, e in enumerate(np.roll(hp, -1, 0) - hp)]
    base = min(widths)
    m = np.array(mass)
    cum = np.cumsum(m[:, 0])
    cx, cy = np.cumsum(m[:, 0] * m[:, 1]) / cum, np.cumsum(m[:, 0] * m[:, 2]) / cum
    margin = (-(hull.equations[:, :2] @ np.c_[cx, cy].T + hull.equations[:, 2:3])).min(0)  # mm inside the footprint
    worst = int(np.argmin(margin))
    height = float(mesh.extents[2])
    area = len(xs) * grid.px ** 2
    ixx = float(((y - y.mean()) ** 2).sum()) * grid.px ** 2 + area * grid.px ** 2 / 12
    iyy = float(((x - x.mean()) ** 2).sum()) * grid.px ** 2 + area * grid.px ** 2 / 12
    bx, by = float(np.ptp(x)) + grid.px, float(np.ptp(y)) + grid.px
    fast = max(refs.get("slicer.k2_speeds")["value"][k] for k in ("outer_wall", "inner_wall", "sparse_infill", "solid_infill", "top_surface", "support"))
    hta = max(height / ixx * by, height / iyy * bx) * height / ORCA_BRIM_DIV
    brim = ADHESION.get(material, 1.0) * min(hta * fast, ORCA_MAX_BRIM, 1.5 * math.hypot(bx, by))
    leaves = bool(margin[worst] < 0)
    risk = leaves or brim >= BRIM_RISK
    why = (f"the center of mass leaves the first layer at z {m[worst, 3]:.1f} mm" if leaves else
           f"tall for its base: OrcaSlicer's auto brim would add {brim:.1f} mm" if risk else "stands on its own")
    return {"risk": risk, "why": why, "height_mm": round(height, 1), "base_mm": round(base, 1),
            "ratio": round(height / max(base, 1e-6), 2), "com_margin_mm": round(float(margin[worst]), 2),
            "com_worst_z_mm": round(float(m[worst, 3]), 2), "orca_brim_mm": round(brim, 1), "first_layer_mm2": round(area, 1)}


ORIENTS = (("as built", None, None), ("upside down", 180, (1, 0, 0)), ("front face down", 90, (1, 0, 0)),
           ("back face down", -90, (1, 0, 0)), ("left side down", -90, (0, 1, 0)), ("right side down", 90, (0, 1, 0)))


def orientations(mesh) -> list[dict]:
    """Each of the six axis-aligned rests, from the faces: the support space under faces past the
    threshold (each face's area seen from below times its drop to the part or the bed) and the flat
    area on the bed. The same estimate for all six, so they compare fairly."""
    import trimesh

    out = []
    for name, deg, axis in ORIENTS:
        m = mesh.copy()
        if deg is not None:
            m.apply_transform(trimesh.transformations.rotation_matrix(math.radians(deg), axis))
        ang, bed = face_angles(m)
        n, c, a = np.asarray(m.face_normals), np.asarray(m.triangles_center), np.asarray(m.area_faces)
        lo = float(m.bounds[0][2])
        need = (ang > 90 - threshold()) & ~bed
        vol = 0.0
        if need.any():
            org = c[need] - [0.0, 0.0, 1e-3]
            drop = org[:, 2] - lo
            try:
                loc, ri, _ = m.ray.intersects_location(org, np.tile([0.0, 0.0, -1.0], (len(org), 1)), multiple_hits=False)
                drop[ri] = org[ri, 2] - loc[:, 2]
            except ImportError:
                pass
            vol = float((a[need] * -n[need, 2] * np.clip(drop, 0, None)).sum())
        out.append({"name": name, "rotate_deg": deg, "axis": axis, "support_mm3": round(vol, 1),
                    "first_layer_mm2": round(float(a[bed].sum()), 1), "height_mm": round(float(m.extents[2]), 1)})
    return out


def advice(orients: list[dict], needed: bool = True) -> dict:
    """The rest to suggest. A part the layers say needs no support stays as built: the face estimate
    counts bridge ceilings, which print without support."""
    now = orients[0]
    if not needed:
        return {"best": now["name"], "keep": True, "line": "Orientation: as built, it needs no support"}
    ok = [o for o in orients if o["first_layer_mm2"] >= slicer.FIRST_LAYER_MIN] or orients[:1]
    best = min(ok, key=lambda o: (o["support_mm3"], -o["first_layer_mm2"]))
    keep = best is now or now["support_mm3"] - best["support_mm3"] <= max(0.1 * now["support_mm3"], 50.0)
    return {"best": now["name"] if keep else best["name"], "keep": keep,
            "line": (f"Orientation: as built is best ({now['support_mm3'] / 1000:.1f} cm3 of support space)" if keep else
                     f"Orientation: {best['name']} needs {best['support_mm3'] / 1000:.1f} cm3 of support space instead of "
                     f"{now['support_mm3'] / 1000:.1f} cm3, first layer {best['first_layer_mm2']:.0f} mm2 "
                     "(advice only: turn it in the slicer)")}


def _report(mesh, grid, pieces, uf, first, mass, material) -> dict:
    regions = _regions(pieces, uf)
    need = [r for r in regions if r["need"]]
    ang, bed = face_angles(mesh)
    area = np.asarray(mesh.area_faces)
    bands = {f"{a}-{b}": round(float(area[(ang > a) & (ang <= b + 1e-9) & ~bed].sum()), 1) for a, b in BANDS}
    rgb = np.tile(CLAY, (len(area), 1))
    hit = (ang > 30) & ~bed
    if regions and hit.any():
        from scipy.spatial import cKDTree

        owner = np.concatenate([np.full(len(r["pts"]), k) for k, r in enumerate(regions)])
        dist, idx = cKDTree(np.concatenate([r["pts"] for r in regions])).query(np.asarray(mesh.triangles_center)[hit])
        faces = np.flatnonzero(hit)
        near = dist <= max(FACE_NEAR, 3 * grid.px)
        for k, r in enumerate(regions):
            mine = faces[near & (owner[idx] == k)]
            if len(mine):
                r["worst_deg"] = round(float(ang[mine].max()), 1)
                rgb[mine] = RED if r["need"] else YELLOW
    orients = orientations(mesh)
    vol = sum(r["support_mm3"] for r in need)
    sp = refs.get("slicer.support_spacing")["value"]
    fill = sp["line_width"] / sp["base_pattern_spacing"]
    for k, r in enumerate(regions):
        r["n"] = k + 1
        r.pop("pts")
    return {"needed": bool(need), "material": material, "layer_mm": grid.layer, "pixel_mm": round(grid.px, 3),
            "threshold_deg": threshold(), "reach_mm": round(reach(grid.layer), 3), "max_bridge_mm": max_bridge(),
            "regions": need, "bridges": [r for r in regions if not r["need"]], "bands_mm2": bands,
            "support": {"space_mm3": round(vol, 1), "plastic_mm3": round(vol * fill, 1), "fill": round(fill, 3)},
            "tipping": _tipping(mesh, grid, first, mass, material), "orientations": orients, "advice": advice(orients, bool(need)),
            "sources": list(SOURCES), "_rgb": rgb}


def why_text(r: dict, limit: float) -> str:
    out = []
    for k in r["why"]:
        if k == "island":
            out.append("starts in mid air")
        elif k == "long bridge":
            out.append(f"bridge {r['span_mm']:.1f} mm long, over {limit:.0f} mm")
        elif k == "ledge":
            out.append("hangs past the layer below")
    return "; ".join(out)


def lines(rep: dict, limit: int = 6) -> list[str]:
    """The short report a small model reads."""
    out = [f"Supports needed: {'yes' if rep['needed'] else 'no'}"
           + (f" ({len(rep['regions'])} regions)" if len(rep["regions"]) > 1 else "")]
    for r in rep["regions"][:limit]:
        z = f"z {r['z'][0]:.1f} mm" if r["z"][1] - r["z"][0] <= rep["layer_mm"] + 1e-6 else f"z {r['z'][0]:.1f} to {r['z'][1]:.1f} mm"
        out.append(f"{r['n']}. {z} at x {r['where'][0]} y {r['where'][1]}, {r['area_mm2']:.0f} mm2, "
                   f"worst {r['worst_deg']:.0f} deg: {why_text(r, rep['max_bridge_mm'])}")
    if len(rep["regions"]) > limit:
        out.append(f"({len(rep['regions']) - limit} more regions in supports.json)")
    if rep["bridges"]:
        spans = ", ".join(f"{b['span_mm']:.1f}" for b in rep["bridges"][:4] if b["span_mm"] is not None)
        out.append(f"Bridges that print without support (up to {rep['max_bridge_mm']:.0f} mm): {len(rep['bridges'])}, spans {spans} mm")
    out.append("Overhang area by angle from vertical: " + ", ".join(f"{k} deg {v:.0f} mm2" for k, v in rep["bands_mm2"].items()))
    if rep["needed"]:
        s = rep["support"]
        out.append(f"Support: about {s['space_mm3'] / 1000:.1f} cm3 of space under the regions, about "
                   f"{s['plastic_mm3'] / 1000:.1f} cm3 of plastic at {s['fill'] * 100:.0f}% fill")
    t = rep["tipping"]
    if "ratio" in t:
        out.append(f"Tipping: {'RISK' if t['risk'] else 'low'}, {t['why']} (height {t['height_mm']} mm, "
                   f"base {t['base_mm']} mm wide{', use a brim' if t['risk'] else ''})")
    else:
        out.append(f"Tipping: RISK, {t['why']}")
    out.append(rep["advice"]["line"])
    return out


def write(rep: dict, mesh, dest: Path) -> tuple[Path, Path | None]:
    """supports.json, and supports.png: the part from three sides with the faces that need support
    in red and bridges in yellow."""
    from . import colors

    dest.mkdir(parents=True, exist_ok=True)
    js = dest / "supports.json"
    js.write_text(json.dumps({k: v for k, v in rep.items() if not k.startswith("_")}, indent=1))
    png = dest / "supports.png"
    try:
        views = [("front", 0.0, math.radians(20)), ("side", math.radians(90), math.radians(20)),
                 ("from below", math.radians(35), math.radians(-40))]
        colors.render(mesh, rep["_rgb"], png, views=views, px=420, cols=3)
    except Exception:  # a picture is never worth failing the report
        return js, None
    return js, png


def load(path: Path):
    import trimesh

    mesh = trimesh.load(str(path), force="mesh")
    if not isinstance(mesh, trimesh.Trimesh) or not len(mesh.faces):
        raise ValueError("no mesh in file")
    return mesh


def cmd(args, job, out):
    """stone supports [file.stl]: the report, supports.json and supports.png. NEXT goes back to
    where the job was."""
    f = Path(args.file).expanduser().resolve() if args.file else job.build_dir / "part.stl"
    if not f.is_file():
        out.fix(f"no file at {f}" if args.file else "no built part yet; build first or name an STL file")
        out.next = "stone supports <file.stl>" if args.file else "stone build"
        return out
    material = args.material
    if not material and job.exists():
        material = refs.material_for(job.request()).material
    material = (material or "PLA").upper()
    mesh = load(f)
    bed = config.bed(job.root)
    size = [round(float(v), 1) for v in mesh.extents]
    if any(size[k] > bed[k] + 1e-6 for k in range(3)):  # as stone slice: nothing else matters until it fits
        out.fix(f"{f.name} is {size[0]:g} x {size[1]:g} x {size[2]:g} mm and does not fit the "
                f"{bed[0]:g} x {bed[1]:g} x {bed[2]:g} mm bed; if it is in the wrong units (inches, "
                "microns), export it again in mm")
        out.next = "stone supports <file.stl>" if args.file else "stone build"
        return out
    try:
        rep = analyze(mesh, layer=args.layer, material=material)
    except ValueError as e:
        out.fix(str(e))
        out.next = "stone supports <file.stl>" if args.file else "stone build"
        return out
    js, png = write(rep, mesh, job.build_dir if job.exists() and not args.file else f.parent)
    out.add(f"File: {f} ({material}, {args.layer} mm layers)")
    out.add(*lines(rep))
    out.add(f"Picture: {png} (red needs support, yellow bridges)" if png else "Picture: not drawn")
    out.add(f"Data: {js}")
    out.result = "supports needed" if rep["needed"] else "no supports needed"
    nxt = job.status().get("next") if job.exists() else None
    out.next = nxt if nxt and nxt != "stone status" else "none, the supports check is done"
    return out
