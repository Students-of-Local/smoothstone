"""stone fit: the round holes and pegs in a part, found in its mesh.

A round hole is a polygon whose flats sit inside the modeled circle (exact geometry, from the
side count OpenSCAD's $fn, $fa and $fs give).

The round features come from the mesh: it is cut across each axis with slicer.py's own
cross-section, each closed loop is followed by the mesh edges it crosses, straight runs merge into
the polygon's sides, and a loop that is a regular polygon is a hole or a peg.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import refs as reftool
from . import slicer

AXES = {"z": (0, 1, 2), "x": (1, 2, 0), "y": (2, 0, 1)}  # the axis's coordinate goes last
MAX_LEVELS = 160  # cuts per axis; a prism-built part needs only one between each pair of vertex heights
MIN_D = 1.0  # mm: smaller round loops are text and texture, not features
MIN_DEPTH = 0.6  # mm: shorter runs are chamfers and flares at the ends of a feature
MAX_LOOP = 1200  # segments: a longer loop is an outline, never a round feature
SAME_D = 0.02  # mm: sections this close in diameter are one feature
SAME_AXIS = 0.05  # mm: centers this close are one axis line
STEP = 0.05  # mm: suggested sizes round to this
CALIBRATED_BAND = 0.05  # mm, plus or minus on a size, after a coupon: assumption (caliper reading, print repeatability)

SHRINK = {"PLA": "pla", "PLA+": "pla", "PETG": "petg", "ABS": "abs", "ASA": "asa", "PC": "pc", "PA": "pa"}


def lib() -> dict:
    return reftool.load()


def val(ref_id: str):
    return lib()[ref_id]["value"]


def cite(ref_id: str) -> str:
    return lib()[ref_id]["cite"]


def num(v: float, nd: int = 2) -> str:
    return f"{v:.{nd}f}"


# geometry

def fragments(r: float, fn: float = 0, fa: float = 12, fs: float = 2) -> int:
    """How many sides OpenSCAD gives a circle of radius r (refs fit.fragments)."""
    if fn > 0:
        return max(int(fn), 3)
    return int(math.ceil(max(min(360.0 / fa, r * 2 * math.pi / fs), 5)))


def inscribed(d: float, n: int) -> float:
    """The flats of an n-sided polygon whose corners sit on a circle of diameter d: what a pin in
    the hole touches."""
    return d * math.cos(math.pi / n)


@dataclass
class Feature:
    kind: str  # hole | peg
    axis: str  # z (upright on the bed), x or y (on its side)
    center: tuple[float, float]  # in the plane across the axis
    d: float  # corner circle, mm: the modeled diameter
    n: int  # sides
    lo: float  # along the axis, mm
    hi: float
    at_bed: bool = False  # an upright feature that opens on the bed
    flare: bool = False  # it widens at the bed (stone's bed chamfer takes the elephant foot)
    count: int = 1
    shape: str = "round"  # round | teardrop (a point on top, so it prints on its side)

    @property
    def depth(self) -> float:
        return self.hi - self.lo

    @property
    def size(self) -> float:
        """What a mating part meets: a hole's flats, a peg's corners."""
        return inscribed(self.d, self.n) if self.kind == "hole" else self.d


def _components(keys: np.ndarray) -> np.ndarray:
    """Label each segment with its closed loop: two segments that end on the same mesh edge touch."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    m = len(keys)
    flat = keys.ravel()
    order = np.argsort(flat, kind="stable")
    sk = flat[order]
    same = np.nonzero(sk[1:] == sk[:-1])[0]
    a, b = order[same] // 2, order[same + 1] // 2
    g = coo_matrix((np.ones(len(a)), (a, b)), shape=(m, m))
    return connected_components(g, directed=False)[1]


def _loop(seg: np.ndarray, keys: np.ndarray, idx: np.ndarray) -> np.ndarray | None:
    """The loop's points in order, or None when it does not close."""
    ends: dict[int, list[tuple[int, int]]] = {}
    for s in idx:
        for e in (0, 1):
            ends.setdefault(int(keys[s, e]), []).append((int(s), e))
    start = int(idx[0])
    pts = [seg[start, 0]]
    s, e = start, 1
    for _ in range(len(idx) + 1):
        pts.append(seg[s, e])
        nxt = [p for p in ends[int(keys[s, e])] if p[0] != s]
        if len(nxt) != 1:
            return None
        s, e0 = nxt[0]
        if s == start:
            return np.array(pts[:-1])
        e = 1 - e0
    return None


def _corners(pts: np.ndarray) -> np.ndarray:
    """Where a closed polyline turns: cut points on a side's diagonal lie on a straight run."""
    d = np.roll(pts, -1, 0) - pts
    keep = np.hypot(d[:, 0], d[:, 1]) > 1e-9
    pts, d = pts[keep], d[keep]
    if len(pts) < 3:
        return pts
    u = d / np.hypot(d[:, 0], d[:, 1])[:, None]
    prev = np.roll(u, 1, 0)
    turn = np.abs(prev[:, 0] * u[:, 1] - prev[:, 1] * u[:, 0])
    return pts[turn > 1e-6]


def _fit(pts: np.ndarray) -> tuple[float, float, float, float]:
    """Least squares circle through points: center, radius, worst miss."""
    a = np.c_[2 * pts, np.ones(len(pts))]
    b = (pts ** 2).sum(1)
    (cx, cy, c), *_ = np.linalg.lstsq(a, b, rcond=None)
    r = math.sqrt(max(c + cx * cx + cy * cy, 0.0))
    return float(cx), float(cy), r, float(np.abs(np.hypot(pts[:, 0] - cx, pts[:, 1] - cy) - r).max())


def _circle(corners: np.ndarray) -> tuple[float, float, float, int, str] | None:
    """Center, corner radius, sides and shape of a round loop: a regular polygon ("round"), or one
    with a single corner drawn out to a point ("teardrop", a hole made to print on its side).
    None when the loop is neither."""
    k = len(corners)
    if k < 5:
        return None
    cx, cy, r, miss = _fit(corners)
    side = np.hypot(*(np.roll(corners, -1, 0) - corners).T)
    if r > 0 and miss <= 1e-3 * r + 1e-4:
        if side.max() > 1.05 * side.min():  # uneven sides: a rounded slot or a cut circle, not a round feature
            return None
        return cx, cy, r, k, "round"
    if k < 7:
        return None
    far = int(np.argmax(np.hypot(*(corners - corners.mean(0)).T)))
    rest = np.delete(corners, far, 0)
    cx, cy, r, miss = _fit(rest)
    if r <= 0 or miss > 1e-3 * r + 1e-4 or math.hypot(*(corners[far] - (cx, cy))) < 1.2 * r:
        return None
    arc = np.delete(side, [(far - 1) % k, far])  # the arc's own sides, not the two to the tip
    if arc.max() > 1.05 * arc.min():
        return None
    step = 2 * math.asin(min(1.0, float(np.median(arc)) / (2 * r)))
    return cx, cy, r, int(round(2 * math.pi / step)), "teardrop"


def _inside(p: np.ndarray, seg: np.ndarray) -> bool:
    """Is the point in the cross-section's material (even-odd)."""
    a, b = seg[:, 0], seg[:, 1]
    cross = (a[:, 1] > p[1]) != (b[:, 1] > p[1])
    if not cross.any():
        return False
    a, b = a[cross], b[cross]
    x = a[:, 0] + (p[1] - a[:, 1]) / (b[:, 1] - a[:, 1]) * (b[:, 0] - a[:, 0])
    return bool((x > p[0]).sum() % 2)


def _levels(coord: np.ndarray, lo: float, hi: float) -> list[tuple[float, float, float]]:
    """Cut heights with the slab each one stands for: midway between vertex heights, so each cut
    crosses whole sides of a prism, or evenly spaced when there are too many."""
    zs = np.unique(np.round(coord, 4))
    zs = zs[(zs >= lo - 1e-6) & (zs <= hi + 1e-6)]
    if len(zs) < 2:
        return []
    if len(zs) - 1 > MAX_LEVELS:
        zs = np.linspace(lo, hi, MAX_LEVELS + 1)
    return [((a + b) / 2, a, b) for a, b in zip(zs[:-1], zs[1:]) if b - a > 1e-4]


def find_features(mesh, axes=("z", "x", "y")) -> list[Feature]:
    """Round holes and pegs in the mesh, along each axis, with their sides, depth and where they open."""
    lo3, hi3 = mesh.bounds
    out: list[Feature] = []
    faces = np.asarray(mesh.faces)
    big = int(faces.max()) + 1 if len(faces) else 1
    for axis in axes:
        perm = AXES[axis]
        tris = np.asarray(mesh.triangles, float)[:, :, perm]
        verts = np.asarray(mesh.vertices, float)[:, perm]
        lo, hi = float(lo3[perm[2]]), float(hi3[perm[2]])
        span = min(float(hi3[perm[0]] - lo3[perm[0]]), float(hi3[perm[1]] - lo3[perm[1]]))
        tz = tris[:, :, 2]
        zmin, zmax = tz.min(1), tz.max(1)
        lines: list[dict] = []  # one per axis line and diameter: its sections
        for z, za, zb in _levels(verts[:, 2], lo, hi):
            mask = (zmin < z) & (zmax > z)
            if not mask.any():
                continue
            seg, keys = slicer._segments(tris[mask], z, faces[mask], big)
            if not len(seg):
                continue
            lab = _components(keys)
            sizes = np.bincount(lab)
            for comp in np.nonzero((sizes >= 5) & (sizes <= MAX_LOOP))[0]:
                idx = np.nonzero(lab == comp)[0]
                pts = _loop(seg, keys, idx)
                if pts is None:
                    continue
                corners = _corners(pts)
                got = _circle(corners)
                if got is None:
                    continue
                cx, cy, r, n, shape = got
                if 2 * r < MIN_D:
                    continue
                # a point just inside the flats: material there means a peg, none a hole
                dist = np.hypot(corners[:, 0] - cx, corners[:, 1] - cy)
                i = int(np.argmin(np.abs(dist - r)))  # two neighbors on the circle, away from a tip
                j = (i + 1) % len(corners) if abs(dist[(i + 1) % len(corners)] - r) < 1e-3 * r + 1e-4 else i - 1
                mid = (corners[i] + corners[j]) / 2 - (cx, cy)
                mid = mid / np.hypot(*mid)
                rin = r * math.cos(math.pi / n)
                p = np.array([cx, cy]) + mid * (rin - min(0.05, 0.2 * rin))
                kind = "peg" if _inside(p, seg) else "hole"
                if shape == "teardrop" and kind == "peg":
                    continue
                if kind == "peg" and 2 * r >= 0.8 * span:
                    continue  # the part's own round outline
                for ln in lines:
                    if (ln["kind"] == kind and abs(ln["d"] - 2 * r) <= SAME_D
                            and math.hypot(ln["cx"] - cx, ln["cy"] - cy) <= SAME_AXIS):
                        ln["lo"], ln["hi"] = min(ln["lo"], za), max(ln["hi"], zb)
                        ln["w"] += zb - za
                        break
                else:
                    lines.append({"kind": kind, "cx": cx, "cy": cy, "d": 2 * r, "n": n, "lo": za, "hi": zb, "w": zb - za,
                                  "shape": shape})
        for ln in lines:
            if ln["w"] < MIN_DEPTH:
                continue
            f = Feature(ln["kind"], axis, (round(ln["cx"], 3), round(ln["cy"], 3)), ln["d"], ln["n"], ln["lo"], ln["hi"],
                        shape=ln["shape"])
            if axis == "z" and f.lo <= lo + 0.5:
                f.at_bed = True
                f.flare = any(o is not ln and o["kind"] == f.kind and o["lo"] <= lo + 1e-6 and o["d"] > f.d + SAME_D
                              and math.hypot(o["cx"] - ln["cx"], o["cy"] - ln["cy"]) <= SAME_AXIS for o in lines)
            out.append(f)
    return _merge(out)


def _merge(feats: list[Feature]) -> list[Feature]:
    """Alike features (kind, axis, size, sides, depth) become one line with a count."""
    out: list[Feature] = []
    for f in sorted(feats, key=lambda f: (f.axis != "z", f.kind, -f.d)):
        for g in out:
            if (g.kind == f.kind and g.axis == f.axis and g.n == f.n and g.shape == f.shape and abs(g.d - f.d) <= SAME_D
                    and abs(g.depth - f.depth) <= 0.05 and g.at_bed == f.at_bed):
                g.count += 1
                break
        else:
            out.append(f)
    return out


def load_mesh(path: Path):
    from .check import _load

    return _load(path)

