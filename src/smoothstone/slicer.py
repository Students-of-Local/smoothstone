"""A slicer's view of an STL, with no slicer installed.

The part is cut into layers the way an FDM slicer cuts it (one cross-section at the middle of
each layer) and each cross-section is drawn on a fine pixel grid. Then it looks for what a slicer
prints wrong or refuses:

- a cross-section that does not close (the mesh has a hole), so the slicer guesses the inside;
- detail thinner than the slicer's smallest line, which it drops;
- an island that starts in mid air, with nothing under it in the layer below;
- a ledge that reaches farther past the layer below than an unsupported line can hang;
- a first layer too small to hold the part on the bed;
- a part bigger than the bed.

Defaults match a 0.4 mm nozzle at 0.2 mm layers (Creality K2, Prusa, Bambu and Orca's standard
profiles). Arachne, the wall generator in PrusaSlicer, OrcaSlicer, Bambu Studio, Creality Print
and Cura, drops a feature narrower than its minimum feature size, 25% of the nozzle.
"""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from . import config

LAYER = 0.2  # mm
NOZZLE = 0.4  # mm
PIXEL = 0.05  # mm
MIN_FEATURE = 0.25  # of the nozzle; Arachne's min_feature_size default
# A piece that starts in mid air and joins the part on the very next layer is an overhang: the next
# layer's lines bond it before it moves. One this big, or one that grows this big while it hangs for
# two layers or more, prints onto nothing and the nozzle drags it. The same bar as stone's own
# islands check (printable.ISLAND_MIN).
ISLAND = 0.5  # mm2
# How far one layer may reach past the one below and still print without support: a line can
# hang about half its width past the line under it, and a 60 degree slope at 0.2 mm layers moves
# 0.35 mm a layer. Past this the plastic droops.
REACH = 0.6  # mm
# A ledge only sags when it is wide: a patch this many square mm reaching past REACH, with
# nothing under it, droops visibly. Bridges between two walls also land here, and figures have
# none worth trusting.
LEDGE_AREA = 4.0  # mm2
FIRST_LAYER_MIN = 20.0  # mm2 on the bed
# What a slicer refuses or prints wrong. A ledge prints, as an overhang that may sag; a feature too
# thin is dropped and counted in Report.dropped.
FAILS = ("open", "floating", "bed", "size")


@dataclass
class Problem:
    kind: str  # open, thin, floating, ledge, bed, size
    z: float  # mm, middle of the layer
    area: float  # mm2
    where: tuple[float, float] = (0.0, 0.0)  # x, y in mm
    note: str = ""


@dataclass
class Report:
    file: str
    layers: int
    layer: float
    nozzle: float
    size: list[float]
    first_layer: float  # mm2
    dropped: float  # mm2 of cross-section summed over layers that the slicer drops as too thin
    problems: list[Problem] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(p.kind in FAILS for p in self.problems)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ok"] = self.ok
        d["fails"] = list(FAILS)
        return d


def _segments(tris: np.ndarray, z: float, faces: np.ndarray | None = None, big: int | None = None):
    """The (n, 2, 2) XY segments where the plane at height z cuts the triangles, and for each end
    the mesh edge it lies on (a key per vertex pair), when the faces' vertex indices are given."""
    above = tris[:, :, 2] > z
    n = above.sum(1)
    cut = (n == 1) | (n == 2)
    t, a = tris[cut], above[cut]
    lone = np.where(a.sum(1) == 1, np.argmax(a, 1), np.argmin(a, 1))
    rows = np.arange(len(t))
    i0, i1, i2 = lone, (lone + 1) % 3, (lone + 2) % 3
    p0, p1, p2 = t[rows, i0], t[rows, i1], t[rows, i2]

    def at(p, q):
        s = (z - p[:, 2]) / (q[:, 2] - p[:, 2])
        return p[:, :2] + s[:, None] * (q[:, :2] - p[:, :2])

    seg = np.stack([at(p0, p1), at(p0, p2)], 1)
    if faces is None:
        return seg
    f = faces[cut]
    v0, v1, v2 = f[rows, i0].astype(np.int64), f[rows, i1].astype(np.int64), f[rows, i2].astype(np.int64)
    if big is None:
        big = int(faces.max()) + 1 if len(faces) else 1

    def key(u, v):
        return np.minimum(u, v) * big + np.maximum(u, v)

    return seg, np.stack([key(v0, v1), key(v0, v2)], 1)


def _open_ends(keys: np.ndarray) -> int:
    """Segment ends on a mesh edge no other segment shares: a closed cross-section has none."""
    if not len(keys):
        return 0
    k = np.sort(keys.ravel())  # every edge shows up an even number of times exactly when sorted pairs match
    return int((k[0::2] != k[1::2]).sum())


def _raster(seg: np.ndarray, x0: float, y0: float, w: int, h: int) -> np.ndarray:
    """Fill a cross-section by the even-odd rule on a w by h grid of PIXEL squares."""
    grid = np.zeros((h, w + 1), np.int8)  # counts wrap at 128, but only their parity matters
    if len(seg):
        a, b = seg[:, 0], seg[:, 1]
        lo, hi = np.minimum(a[:, 1], b[:, 1]), np.maximum(a[:, 1], b[:, 1])
        r0 = np.ceil((lo - y0) / PIXEL - 0.5).astype(np.int64)
        r1 = np.ceil((hi - y0) / PIXEL - 0.5).astype(np.int64)  # rows r0..r1-1 cross
        count = np.clip(r1 - r0, 0, None)
        keep = count > 0
        if keep.any():
            idx = np.repeat(np.nonzero(keep)[0], count[keep])
            start = np.repeat(r0[keep], count[keep])
            offs = np.arange(len(idx)) - np.repeat(np.cumsum(count[keep]) - count[keep], count[keep])
            row = start + offs
            yc = y0 + (row + 0.5) * PIXEL
            ax, ay, bx, by = a[idx, 0], a[idx, 1], b[idx, 0], b[idx, 1]
            x = ax + (yc - ay) / (by - ay) * (bx - ax)
            col = np.clip(np.ceil((x - x0) / PIXEL - 0.5).astype(np.int64), 0, w)
            ok = (row >= 0) & (row < h)
            np.add.at(grid, (row[ok], col[ok]), 1)
    return (np.cumsum(grid, 1, dtype=np.int8)[:, :w] & 1).view(bool)


def _far(kept: np.ndarray, prev: np.ndarray, reach: float) -> np.ndarray:
    """Pixels of kept more than reach pixels from any pixel of prev. The distance runs on a grid
    twice as coarse (a ledge is a warning; 0.1 mm does not change it), which takes a quarter of
    the time on a wide cross-section."""
    from scipy import ndimage

    h, w = prev.shape
    ph, pw = -h % 2, -w % 2
    cp = np.pad(prev, ((0, ph), (0, pw))).reshape((h + ph) // 2, 2, (w + pw) // 2, 2).any((1, 3))
    d = ndimage.distance_transform_edt(~cp) * 2
    d = np.repeat(np.repeat(d, 2, 0), 2, 1)[:h, :w]
    return kept & (d > reach + 1)  # a coarse cell sits up to a pixel nearer than its finest pixel


def _disk(r: float) -> np.ndarray:
    k = int(math.ceil(r))
    y, x = np.mgrid[-k:k + 1, -k:k + 1]
    return x * x + y * y <= r * r + 1e-9


def slice_mesh(mesh, name: str = "", layer: float = LAYER, nozzle: float = NOZZLE,
               bed=None) -> Report:
    from scipy import ndimage

    bed = bed or config.DEFAULT_BED
    lo, hi = mesh.bounds
    size = [round(float(v), 2) for v in hi - lo]
    tris = np.asarray(mesh.triangles, float) - [lo[0], lo[1], lo[2]]
    faces = np.asarray(mesh.faces)
    margin = 4 * PIXEL
    x0 = y0 = -margin
    w = int(math.ceil((hi[0] - lo[0] + 2 * margin) / PIXEL))
    h = int(math.ceil((hi[1] - lo[1] + 2 * margin) / PIXEL))
    n = max(1, int(math.floor((hi[2] - lo[2]) / layer + 0.5)))
    px2 = PIXEL * PIXEL
    feature = _disk(max(1.0, MIN_FEATURE * nozzle / 2 / PIXEL))
    reach = REACH / PIXEL
    rest = _disk(nozzle / 2 / PIXEL)  # a line rests on the one below when it overlaps half its width
    eps = 1e-6 * max(1.0, float(hi[2] - lo[2]))
    big = int(faces.max()) + 1 if len(faces) else 1
    # which layers each triangle can cross, found once: a layer then cuts only its own few
    tz = tris[:, :, 2]
    first_i = np.clip(np.floor((tz.min(1) - eps) / layer - 0.5).astype(np.int64), 0, n - 1)
    last_i = np.clip(np.ceil((tz.max(1) - eps) / layer - 0.5).astype(np.int64), 0, n - 1)
    span = last_i - first_i + 1
    tri_of = np.repeat(np.arange(len(tris)), span)
    layer_of = np.repeat(first_i, span) + np.arange(len(tri_of)) - np.repeat(np.cumsum(span) - span, span)
    order = np.argsort(layer_of, kind="stable")
    tri_of = tri_of[order]
    bounds = np.r_[0, np.cumsum(np.bincount(layer_of, minlength=n))]

    problems: list[Problem] = []
    if any(size[i] > bed[i] + 1e-6 for i in range(3)):
        problems.append(Problem("size", 0.0, 0.0, note=f"{size} mm does not fit the {list(bed)} mm bed"))

    def spot(mask, rows_cols=None):
        ys, xs = np.nonzero(mask) if rows_cols is None else rows_cols
        return (round(float(lo[0] + x0 + (xs.mean() + 0.5) * PIXEL), 1),
                round(float(lo[1] + y0 + (ys.mean() + 0.5) * PIXEL), 1))

    prev = np.zeros((h, w), bool)
    sup_prev = prev
    free_prev = np.zeros((h, w), np.int32)  # piece id of each floating pixel in the layer below, 0 elsewhere
    pieces: list[dict] = []  # each piece that started in mid air, followed up to where it joins
    first = 0.0
    dropped = 0.0
    eight = np.ones((3, 3), bool)
    pad = int(math.ceil(reach)) + rest.shape[0] + 2
    fp = feature.shape[0]

    def cut(i):
        """One layer on its own: where the plane cuts, whether it closes, and what a line can
        print of it (cropped to the layer's own box). Layers do not depend on each other here."""
        z = (i + 0.5) * layer + eps
        mine_t = tri_of[bounds[i]:bounds[i + 1]]
        seg, keys = _segments(tris[mine_t], z, faces[mine_t], big)
        is_open = bool(_open_ends(keys))
        if not len(seg):
            return z, is_open, None, None, 0.0
        r_lo = max(0, int(math.floor((seg[:, :, 1].min() - y0) / PIXEL)) - fp)
        r_hi = min(h, int(math.ceil((seg[:, :, 1].max() - y0) / PIXEL)) + fp + 1)
        c_lo = max(0, int(math.floor((seg[:, :, 0].min() - x0) / PIXEL)) - fp)
        c_hi = min(w, int(math.ceil((seg[:, :, 0].max() - x0) / PIXEL)) + fp + 1)
        box = (slice(r_lo, r_hi), slice(c_lo, c_hi))
        raw = _raster(seg, x0 + c_lo * PIXEL, y0 + r_lo * PIXEL, c_hi - c_lo, r_hi - r_lo)
        kept = ndimage.binary_opening(raw, feature)
        return z, is_open, box, kept, float((raw & ~kept).sum()) * px2

    from concurrent.futures import ThreadPoolExecutor

    def layers():
        # numpy and scipy let go of the GIL for the heavy work, so threads cut layers side by side;
        # a few at a time keeps memory to a handful of layers
        with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 1)) as pool:
            chunk = 16
            for a in range(0, n, chunk):
                yield from pool.map(cut, range(a, min(n, a + chunk)))

    for i, (z, is_open, box, kc, lost) in enumerate(layers()):
        zmm = round(float(lo[2] + z), 2)
        if is_open:
            problems.append(Problem("open", zmm, 0.0, note="the cross-section does not close; the mesh has a hole here"))
        dropped += lost
        kept = np.zeros((h, w), bool)
        if box is not None:
            kept[box] = kc
        # work only where this layer or the one below has material: most layers of a figure are a
        # small part of the plinth's frame
        occ = kept | prev
        rows = np.flatnonzero(occ.any(1))
        cols = np.flatnonzero(occ.any(0)) if len(rows) else rows
        sup = np.zeros((h, w), bool)
        free = np.zeros((h, w), np.int32)
        if len(rows):
            win = (slice(max(0, rows[0] - pad), min(h, rows[-1] + pad + 1)),
                   slice(max(0, cols[0] - pad), min(w, cols[-1] + pad + 1)))
            r0, c0 = win[0].start, win[1].start
            lprev = prev[win]
            lkept = kept[win]
            if i == 0:
                sup[win] = lkept
            else:
                labels, k = ndimage.label(lkept, eight)
                sizes = np.bincount(labels.ravel(), minlength=k + 1)
                lsup = sup_prev[win]
                held = np.bincount(labels[lsup & lkept], minlength=k + 1) > 0  # most pieces sit right on what stands
                held[0] = False
                rest_of = np.nonzero(~held[1:])[0] + 1
                if len(rest_of) and lsup.any():  # the others may still rest within half a line of it
                    loose = np.isin(labels, rest_of)
                    ys, xs = np.nonzero(loose)
                    m = rest.shape[0]
                    box = (slice(max(0, ys.min() - m), ys.max() + m + 1), slice(max(0, xs.min() - m), xs.max() + m + 1))
                    grown = ndimage.binary_dilation(lsup[box], rest)
                    held |= np.bincount(labels[box][grown & loose[box]], minlength=k + 1) > 0
                    held[0] = False
                sup[win] = held[labels]
                lfree = free_prev[win]
                near = ndimage.grey_dilation(lfree, footprint=rest) if lfree.any() else lfree
                both = (labels > 0) & (near > 0)
                links: dict[int, set] = {}
                for c, pid in np.unique(np.c_[labels[both], near[both]], axis=0) if both.any() else []:
                    links.setdefault(int(c), set()).add(int(pid))
                lnew = np.zeros(lkept.shape, np.int32)
                for c in np.nonzero(~held[1:])[0] + 1:
                    ids = links.get(int(c), set())
                    area = float(sizes[c]) * px2
                    mine = labels == c
                    ys, xs = np.nonzero(mine)
                    xy = np.c_[lo[0] + x0 + (xs + c0 + 0.5) * PIXEL, lo[1] + y0 + (ys + r0 + 0.5) * PIXEL]
                    bottom = float(lo[2] + i * layer)
                    if ids:
                        pid = min(ids)
                        for other in ids - {pid}:
                            pieces[other - 1].setdefault("joined", zmm)
                        pc = pieces[pid - 1]
                        pc["peak"] = max(pc["peak"], area)
                        pc["layers"].append((bottom, xy))
                    else:
                        pieces.append({"z": zmm, "bottom": bottom, "area": area, "peak": area,
                                       "where": (round(float(xy[:, 0].mean()), 1), round(float(xy[:, 1].mean()), 1)),
                                       "xy": xy, "layers": [(bottom, xy)]})
                        pid = len(pieces)
                    lnew[mine] = pid
                for c in np.nonzero(held[1:])[0] + 1:
                    for pid in links.get(int(c), ()):  # a floating piece joins what stands
                        pieces[pid - 1].setdefault("joined", zmm)
                free[win] = lnew
                if lprev.any() and float((lkept & ~lprev).sum()) * px2 >= LEDGE_AREA:
                    far = _far(lkept, lprev, reach)
                    if far.any():
                        fl, fk = ndimage.label(far, eight)
                        fs = np.bincount(fl.ravel(), minlength=fk + 1)
                        for j in np.nonzero(fs[1:] * px2 >= LEDGE_AREA)[0] + 1:
                            ys, xs = np.nonzero(fl == j)
                            problems.append(Problem(
                                "ledge", zmm, round(float(fs[j]) * px2, 1),
                                (round(float(lo[0] + x0 + (xs.mean() + c0 + 0.5) * PIXEL), 1),
                                 round(float(lo[1] + y0 + (ys.mean() + r0 + 0.5) * PIXEL), 1)),
                                f"reaches more than {REACH} mm past the layer below with nothing under it"))
        if i == 0:
            first = float(kept.sum()) * px2
            if first < FIRST_LAYER_MIN:
                problems.append(Problem("bed", zmm, round(first, 1), spot(kept) if kept.any() else (0.0, 0.0),
                                        f"only {first:.1f} mm2 touches the bed (need {FIRST_LAYER_MIN:.0f})"))
        prev, sup_prev, free_prev = kept, sup, free
    floating = []
    for pc in pieces:
        pc["rise"] = round(pc.get("joined", zmm) - pc["z"], 2)
        if pc["area"] >= ISLAND or (pc["peak"] >= ISLAND and pc["rise"] >= 2 * layer - 1e-6):
            floating.append(pc)
            problems.append(Problem("floating", round(pc["bottom"], 2), round(pc["peak"], 2), pc["where"],
                                    f"starts in mid air ({pc['area']:.2f} mm2) and hangs {pc['rise']:.1f} mm "
                                    "before it joins the part; the nozzle drags it"))
    rep = Report(name, n, layer, nozzle, size, round(first, 1), round(dropped, 1), problems)
    rep.floating = floating  # with each piece's points: first layer ("xy", mm) and every layer it hangs ("layers"), for brace
    return rep



def slice_stl(path, layer: float = LAYER, nozzle: float = NOZZLE, bed=None) -> Report:
    import trimesh

    mesh = trimesh.load(str(path), force="mesh")
    if not isinstance(mesh, trimesh.Trimesh) or not len(mesh.faces):
        raise ValueError("no mesh in file")
    return slice_mesh(mesh, str(path), layer, nozzle, bed)


def summary(rep: Report, limit: int = 8) -> list[str]:
    """Plain lines for the terminal: one per kind of problem, worst first."""
    lines = [f"{rep.layers} layers of {rep.layer} mm, {rep.nozzle} mm nozzle; "
             f"first layer {rep.first_layer} mm2; {rep.dropped} mm2 too thin to print"]
    kinds: dict[str, list[Problem]] = {}
    for p in rep.problems:
        kinds.setdefault(p.kind, []).append(p)
    lines.append("PASS slices cleanly" if rep.ok else "FAIL a slicer prints this wrong")
    for kind, ps in sorted(kinds.items(), key=lambda kv: kv[0] not in FAILS):
        ps = sorted(ps, key=lambda p: -p.area)
        top = ps[0]
        at = f" at z {top.z} mm, x {top.where[0]} y {top.where[1]}" if kind != "size" else ""
        tag = "FAIL" if kind in FAILS else "WARN"
        lines.append(f"{tag} {kind}: {len(ps)} found; worst {top.area} mm2{at}: {top.note}")
        for p in ps[1:limit]:
            lines.append(f"     {kind} z {p.z} mm, {p.area} mm2 at x {p.where[0]} y {p.where[1]}")
    return lines
