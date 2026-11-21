"""What a slicer sees: the part cut into layers. Finds pieces that start in the air (islands), measures
how far the part can lean before it tips, and braces a figure's islands with struts to the body."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

VERSION = 1  # in every build stamp: a part built before struts and these checks builds again
PITCH = 0.25  # mm: about one layer, and the same step sideways, so one cell per layer is 45 degrees
MAX_COLUMNS = 360_000  # rays cast upward; a bigger part gets a coarser grid
ISLAND_MIN = 0.5  # mm2: an island this big fails the check (smaller ones are ray noise or a single strand)
TIP_MIN = 10.0  # degrees the part may lean before its center of mass leaves its footprint

STRUT_TOP = 0.45  # mm radius where a strut touches the piece it holds up
STRUT_FOOT = 0.9  # mm radius where it stands
STRUT_SINK = 0.4  # mm a strut reaches up into the piece it holds
STRUT_ROOT = 1.6  # mm it reaches down into what it stands on, so its slanted end stays inside
STRUT_SLOPE = 0.8  # sideways mm per mm down: steeper than 45 degrees, so the strut prints without help
STRUT_COVER = 1.5  # mm: every cell of an island is this close to a strut top
STRUT_REACH = 18.0  # mm: longest strut
TRIM_AREA = 1.5  # mm2: a hanging tip no thicker than this in any layer is a hair strand or a nub, not a hand
TRIM_RISE = 4.0  # mm: the most a tip is cut back, up to the piece it hangs from
TRIM_DUST = 1.0  # mm3: a loose bit this small left by a cut is dropped
TRIM_FACE = 8.0  # mm2: a tip with only the face to stand on is cut back up to this thick
NECK_VALLEY = 1.25  # the neck layer is at least this much smaller than the torso and the head (parts.py)
FACE_SIDES = 0.75  # share of the head's half width that is face; the ears and hair beyond may hold a strut


@dataclass
class Island:
    z: float  # mm above the bed where the piece starts
    area: float  # mm2 of its first layer
    x: float
    y: float
    cells: np.ndarray  # (n, 2) grid cells of its first layer
    k: int  # layer index


@dataclass
class Grid:
    occ: np.ndarray  # (nx, ny, nz) bool: material at each cell center
    lo: np.ndarray  # mesh lower corner
    pitch: float

    def xy(self, cells) -> np.ndarray:
        return self.lo[:2] + (np.asarray(cells, float) + 0.5) * self.pitch

    def z(self, k) -> np.ndarray:
        return self.lo[2] + (np.asarray(k, float) + 0.5) * self.pitch


def occupancy(mesh, pitch: float = PITCH) -> Grid | None:
    """Cast one ray straight up through each grid column and fill between entry and exit hits.
    None when no ray engine is installed."""
    lo, hi = mesh.bounds
    ext = hi - lo
    pitch = max(pitch, math.sqrt(ext[0] * ext[1] / MAX_COLUMNS))
    xs = np.arange(lo[0] + pitch / 2, hi[0], pitch)
    ys = np.arange(lo[1] + pitch / 2, hi[1], pitch)
    nz = max(1, int(math.ceil(ext[2] / pitch)))
    occ = np.zeros((len(xs), len(ys), nz), bool)
    if len(xs) == 0 or len(ys) == 0:
        return Grid(occ, np.array(lo, float), pitch)
    X, Y = np.meshgrid(xs, ys, indexing="ij")
    org = np.c_[X.ravel(), Y.ravel(), np.full(X.size, lo[2] - 1.0)]
    up = np.tile([0.0, 0.0, 1.0], (len(org), 1))
    try:
        loc, ri, _ = mesh.ray.intersects_location(org, up, multiple_hits=True)
    except ImportError:
        return None
    if len(ri) == 0:
        return Grid(occ, np.array(lo, float), pitch)
    order = np.lexsort((loc[:, 2], ri))
    loc, ri = loc[order], ri[order]
    zc = lo[2] + (np.arange(nz) + 0.5) * pitch
    starts = np.r_[0, np.flatnonzero(np.diff(ri)) + 1, len(ri)]
    for a, b in zip(starts[:-1], starts[1:]):
        z = loc[a:b, 2]
        z = z[np.r_[True, np.diff(z) > 1e-6]]  # one hit where a ray crosses an edge shared by two faces
        if len(z) % 2:
            z = z[:-1]
        i, j = divmod(int(ri[a]), len(ys))
        for z0, z1 in zip(z[0::2], z[1::2]):
            k0, k1 = np.searchsorted(zc, [z0, z1])
            occ[i, j, k0:k1] = True
    return Grid(occ, np.array(lo, float), pitch)


def islands(grid: Grid) -> list[Island]:
    """Pieces of a layer with no material under them, within 45 degrees, in the layer below."""
    from scipy import ndimage

    occ, p = grid.occ, grid.pitch
    reach = ndimage.generate_binary_structure(2, 2)
    found = []
    for k in range(1, occ.shape[2]):
        layer = occ[:, :, k]
        if not layer.any():
            continue
        lab, n = ndimage.label(layer, structure=reach)
        below = ndimage.binary_dilation(occ[:, :, k - 1], structure=reach)
        held = np.unique(lab[below & layer])
        for c in range(1, n + 1):
            if c in held:
                continue
            cells = np.argwhere(lab == c)
            x, y = grid.xy(cells).mean(axis=0)
            found.append(Island(float(grid.z(k) - p / 2), len(cells) * p * p, float(x), float(y), cells, k))
    return found


def tip_angle(mesh, grid: Grid) -> float | None:
    """Degrees the part can lean before its center of mass passes the edge of what touches the bed.
    0 when the center of mass is already outside. None when nothing touches the bed."""
    from scipy.spatial import ConvexHull, QhullError

    base = grid.occ[:, :, 0]
    if not base.any():
        return None
    pts = grid.xy(np.argwhere(base))
    # the corners of each cell, so a part one cell wide still has a footprint
    h = grid.pitch / 2
    pts = np.concatenate([pts + [dx, dy] for dx in (-h, h) for dy in (-h, h)])
    com = mesh.center_mass if mesh.is_watertight and mesh.volume > 0 else mesh.centroid
    try:
        hull = ConvexHull(pts)
    except (QhullError, ValueError):
        return 0.0
    margin = float(-(hull.equations[:, :2] @ com[:2] + hull.equations[:, 2]).max())
    if margin <= 0:
        return 0.0
    rise = float(com[2] - mesh.bounds[0][2])
    return math.degrees(math.atan2(margin, max(rise, 1e-6)))


def where(island: Island, mesh) -> str:
    """Plain words for where an island sits on the part."""
    lo, hi = mesh.bounds
    w = []
    fx = (island.x - lo[0]) / max(hi[0] - lo[0], 1e-6)
    fy = (island.y - lo[1]) / max(hi[1] - lo[1], 1e-6)
    if fy < 0.35:
        w.append("front")
    elif fy > 0.65:
        w.append("back")
    if fx < 0.35:
        w.append("left")
    elif fx > 0.65:
        w.append("right")
    side = " ".join(w) or "middle"
    return f"{island.z:.1f} mm up, {side}"


@dataclass
class Strut:
    top: np.ndarray
    foot: np.ndarray


def _anchors(island: Island, grid: Grid) -> np.ndarray:
    """Strut tops spread over an island so every cell is within STRUT_COVER of one."""
    pts = grid.xy(island.cells)
    chosen = [pts[np.argmin(np.linalg.norm(pts - pts.mean(axis=0), axis=1))]]
    for _ in range(11):
        d = np.min(np.linalg.norm(pts[:, None] - np.array(chosen)[None], axis=2), axis=1)
        if d.max() <= STRUT_COVER:
            break
        chosen.append(pts[int(np.argmax(d))])
    return np.array(chosen)


def _inside(grid: Grid, pt) -> bool:
    i = np.floor((np.asarray(pt, float) - grid.lo) / grid.pitch).astype(int)
    return bool(np.all(i >= 0) and np.all(i < grid.occ.shape) and grid.occ[tuple(i)])


def _clear(grid: Grid, top, foot) -> bool:
    """Nothing solid on the way from top to foot, but for a cell at each end."""
    top, foot = np.asarray(top, float), np.asarray(foot, float)
    d = float(np.linalg.norm(top - foot))
    t = np.arange(2 * grid.pitch, d - 2 * grid.pitch, grid.pitch / 2) / max(d, 1e-9)
    if len(t) == 0:
        return True
    i = np.floor((top + (foot - top) * t[:, None] - grid.lo) / grid.pitch).astype(int)
    ok = np.all((i >= 0) & (i < grid.occ.shape), axis=1)
    return not grid.occ[tuple(i[ok].T)].any()


def head(grid: Grid) -> dict | None:
    """{"neck", "top": z, "cx", "cy": the head's middle, "hw", "hd": its half width and depth}, or
    None when no neck is found. The neck is the narrowest layer between the shoulders and the top of
    the head, at least NECK_VALLEY smaller than both, as parts.anatomy finds it on the mesh."""
    occ = grid.occ
    A = occ.sum(axis=(0, 1)).astype(float)
    ks = np.arange(int(len(A) * 0.45), len(A) - int(round(1.0 / grid.pitch)))
    if len(ks) < 5:
        return None
    a = A[ks]
    score = np.minimum(np.maximum.accumulate(a), np.maximum.accumulate(a[::-1])[::-1]) / np.maximum(a, 1e-9)
    score[a <= 0] = 0
    i = int(score.argmax())
    if score[i] < NECK_VALLEY:
        return None
    kn = int(ks[i])
    xy = grid.xy(np.argwhere(occ[:, :, kn:].any(axis=2)))
    (x0, y0), (x1, y1) = xy.min(axis=0), xy.max(axis=0)
    top = int(np.flatnonzero(A)[-1])
    return {"neck": float(grid.z(kn)), "top": float(grid.z(top)), "cx": float(x0 + x1) / 2,
            "cy": float(y0 + y1) / 2, "hw": float(x1 - x0) / 2, "hd": float(y1 - y0) / 2}


def face_zone(grid: Grid):
    """A test for points on a figure's face, or None when no neck is found: above the neck, in the
    front half of the head (-y), and inside FACE_SIDES of its half width. A strut that stands there
    leaves a scar on the face when it snaps off, and reads as a bar across it."""
    h = head(grid)
    if h is None:
        return None

    def on_face(q) -> bool:
        return bool(q[2] > h["neck"] and q[1] < h["cy"] and abs(q[0] - h["cx"]) < FACE_SIDES * h["hw"])
    return on_face


def plan_struts(grid: Grid, found: list[Island], floor=None, keep_off=None) -> tuple[list[Strut], list[Island]]:
    """A strut under each island, from the closest material below it within the steep cone.
    floor(x, y) -> z or None gives a surface under the part (a plinth top) a strut may stand on;
    keep_off(point) -> True marks a surface no strut may stand on (the face).
    Returns the struts and the islands no strut could reach."""
    from scipy import ndimage
    from scipy.spatial import cKDTree

    occ, p = grid.occ, grid.pitch
    inner = ndimage.binary_erosion(occ, structure=ndimage.generate_binary_structure(3, 1))
    surf = np.argwhere(occ & ~inner)
    pts = np.c_[grid.xy(surf[:, :2]), grid.z(surf[:, 2])]
    tree = cKDTree(pts)
    struts, missed = [], []
    for isl in found:
        made = 0
        for a in _anchors(isl, grid):
            top = np.array([a[0], a[1], isl.z])
            best = None
            near = []
            for i in tree.query_ball_point(top, STRUT_REACH):
                q = pts[i]
                dz = top[2] - q[2]
                if dz >= 2 * p and math.hypot(q[0] - top[0], q[1] - top[1]) <= STRUT_SLOPE * dz:
                    near.append((float(np.linalg.norm(q - top)), i))
            for d, i in sorted(near):
                q = pts[i]
                if not _inside(grid, q - (top - q) / d * STRUT_ROOT):
                    continue  # its root would poke out under a thin strand and hang in the air itself
                if keep_off is not None and keep_off(q):
                    continue
                if not _clear(grid, top, q):
                    continue  # it would run through the figure on the way down, as through a cheek
                best = (d, q)
                break
            if floor is not None:
                fz = floor(top[0], top[1])
                if (fz is not None and 2 * p <= top[2] - fz <= STRUT_REACH
                        and (best is None or top[2] - fz < best[0]) and _clear(grid, top, [top[0], top[1], fz])):
                    best = (top[2] - fz, np.array([top[0], top[1], fz]))
            if best is None:
                continue
            struts.append(Strut(top, best[1]))
            made += 1
        if not made:
            missed.append(isl)
    return struts, missed


def tips(grid: Grid, found: list[Island], widest: float = TRIM_AREA) -> list[list[tuple[int, np.ndarray]]]:
    """For each island that is the end of a thin strand hanging from a piece that stands without
    it: the strand's cells, layer by layer, up to where it joins. Cut away, the strand ends at the
    join and needs no strut. A strut there runs down across the face (random five, round 3), and a
    0.4 mm nozzle cannot lay a strand that thin in the air anyway."""
    from scipy import ndimage

    occ, p = grid.occ, grid.pitch
    reach = ndimage.generate_binary_structure(2, 2)
    out = []
    for isl in found:
        cur = np.zeros(occ.shape[:2], bool)
        cur[tuple(isl.cells.T)] = True
        if cur.sum() * p * p > widest:
            continue
        layers = [(isl.k, cur)]
        for k in range(isl.k + 1, min(occ.shape[2], isl.k + int(round(TRIM_RISE / p)) + 1)):
            lab, _ = ndimage.label(occ[:, :, k], structure=reach)
            ids = np.unique(lab[ndimage.binary_dilation(cur, structure=reach) & (lab > 0)])
            if len(ids) == 0:
                break  # it ends going up too, or slants too far to follow
            nxt = np.isin(lab, ids)
            if (ndimage.binary_dilation(occ[:, :, k - 1] & ~cur, structure=reach) & nxt).any():
                out.append(layers)  # it joins a piece that stands without it
                break
            if nxt.sum() * p * p > widest:
                break  # it thickens before it joins: a hand or a limb, which gets a strut
            cur = nxt
            layers.append((k, cur))
    return out


def _cut_solid(grid: Grid, strands: list[list[tuple[int, np.ndarray]]]):
    """One column of boxes per grid column of each strand, a cell wider all round so the strand's
    surface between cell centers goes too, from the layer under its tip to the join."""
    import manifold3d as m3d
    from scipy import ndimage

    p = grid.pitch
    reach = ndimage.generate_binary_structure(2, 2)
    boxes = []
    for layers in strands:
        span: dict[tuple[int, int], list[int]] = {}
        for k, mask in layers:
            for i, j in np.argwhere(ndimage.binary_dilation(mask, structure=reach)):
                lo_hi = span.setdefault((int(i), int(j)), [k, k])
                lo_hi[0], lo_hi[1] = min(lo_hi[0], k), max(lo_hi[1], k)
        for (i, j), (k0, k1) in span.items():
            x, y = grid.xy([i, j])
            z0, z1 = float(grid.z(k0)) - p, float(grid.z(k1)) + p / 2
            boxes.append(m3d.Manifold.cube([p, p, z1 - z0]).translate([x - p / 2, y - p / 2, z0]))
    return m3d.Manifold.batch_boolean(boxes, m3d.OpType.Add) if boxes else None


def _strut_solid(s: Strut):
    import manifold3d as m3d

    v = s.top - s.foot
    length = float(np.linalg.norm(v))
    u = v / length
    total = length + STRUT_SINK + STRUT_ROOT
    c = m3d.Manifold.cylinder(total, STRUT_FOOT, STRUT_TOP, 16).translate([0, 0, -STRUT_ROOT])
    # turn +z onto u
    zx = math.degrees(math.atan2(math.hypot(u[0], u[1]), u[2]))
    zz = math.degrees(math.atan2(u[1], u[0]))
    return c.rotate([0, zx, 0]).rotate([0, 0, zz]).translate(s.foot.tolist())


def to_manifold(mesh):
    import manifold3d as m3d

    m = m3d.Manifold(m3d.Mesh(vert_properties=np.asarray(mesh.vertices, np.float32),
                              tri_verts=np.asarray(mesh.faces, np.uint32)))
    return m if m.status() == m3d.Error.NoError else None


def from_manifold(m):
    import trimesh

    out = m.to_mesh()
    return trimesh.Trimesh(np.asarray(out.vert_properties)[:, :3], np.asarray(out.tri_verts), process=True)


def brace(mesh, floor=None, rounds: int = 3, figure: bool = False):
    """Cut back thin hanging tips, then add struts under every island left. On a figure no strut
    stands on the face; a tip with only the face under it is cut back instead, up to TRIM_FACE
    thick. Returns (mesh, struts, islands left, tips cut). The mesh is unchanged when it is not a
    closed solid manifold3d accepts."""
    import manifold3d as m3d

    body = to_manifold(mesh)
    ground = float(mesh.bounds[0][2])

    def hanging(grid):
        # a strut root sinks below the feet into the plinth: what is at the feet or under the
        # plinth top still stands
        out = []
        for i in islands(grid):
            fz = floor(i.x, i.y) if floor is not None else None
            if i.area >= 2 * grid.pitch ** 2 and i.z > max(ground, fz if fz is not None else ground) + grid.pitch:
                out.append(i)
        return out

    grid = occupancy(mesh)
    if grid is None:
        return mesh, [], [], 0
    left = hanging(grid)
    if body is None:
        return mesh, [], left, 0
    every, cut = [], 0
    face = face_zone(grid) if figure else None  # found once, before any cut or strut changes the head

    def trim(strands):
        nonlocal body, mesh, grid, left, cut
        body = body - _cut_solid(grid, strands)
        # a cut can leave a wisp beside the strand on its own; dust that small never prints
        body = m3d.Manifold.compose([c for c in body.decompose() if c.volume() >= TRIM_DUST])
        cut += len(strands)
        mesh = from_manifold(body)
        grid = occupancy(mesh)
        left = hanging(grid)

    for _ in range(rounds):
        if not left:
            break
        for _ in range(3):  # a cut can bare the tip of the strand it joined
            strands = tips(grid, left)
            if not strands:
                break
            trim(strands)
        if not left:
            break
        if face is not None:
            _, missed = plan_struts(grid, left, floor, face)
            strands = tips(grid, missed, TRIM_FACE)
            if strands:
                trim(strands)
                if not left:
                    break
        struts, missed = plan_struts(grid, left, floor, face)
        if not struts:
            break
        for s in struts:
            body = body + _strut_solid(s)
        every += struts
        mesh = from_manifold(body)
        grid = occupancy(mesh)
        left = hanging(grid)
    return mesh, every, left, cut


def plinth(params: dict) -> tuple[float, float, float | None]:
    """(figure scale in mm, plinth top in the figure's own mm, plinth radius a strut may stand
    within or None for no plinth), the numbers recipes/figure/recipe.scad works out."""
    base = str(params.get("base") or "round")
    height = float(params.get("height") or 90)
    base_h = float(params.get("base_h") or 0)
    name = str(params.get("name") or "")
    bh = 0.0 if base == "none" else base_h if base_h > 0 else 8.0 if name == "" else 12.0
    fh = height - bh
    sink = 0.0 if base == "none" else min(1.2, bh / 3)
    if base == "none":
        return fh + sink, 0.0, None
    base_d = float(params.get("base_d") or 0)
    bd = base_d if base_d > 0 else max(30.0, fh * 0.68 + 8, len(name) * fh * 0.075 + 14)
    dr = bd / 2 - min(1.2, bh / 8)
    if base == "hex":
        dr *= math.cos(math.radians(30))
    return fh + sink, sink, dr - STRUT_FOOT - 0.5


STRUT_RGB = (110.0, 165.0, 225.0)  # struts in views.png: blue, so a snap-off strut does not read as a drip


def part_struts(struts: list[Strut], params: dict) -> list[dict]:
    """The struts in the built part's mm, where recipes/figure/recipe.scad puts the figure: turned by
    spin, then raised onto the plinth."""
    scale, _, _ = plinth(params)
    lift = float(params.get("height") or 90) - scale
    a = math.radians(float(params.get("spin") or 0))
    rz = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
    return [{"foot": (rz @ s.foot + [0, 0, lift]).round(3).tolist(),
             "top": (rz @ s.top + [0, 0, lift]).round(3).tolist()} for s in struts]


def strut_faces(points, struts: list[dict], margin: float = 0.2) -> np.ndarray:
    """Which points (face centers of the built part) lie on a strut's tapered rod."""
    pts = np.asarray(points, float)
    on = np.zeros(len(pts), bool)
    for s in struts:
        a, b = np.asarray(s["foot"], float), np.asarray(s["top"], float)
        ab = b - a
        t = np.clip((pts - a) @ ab / max(float(ab @ ab), 1e-9), 0.0, 1.0)
        d = np.linalg.norm(pts - (a + t[:, None] * ab), axis=1)
        on |= d <= STRUT_FOOT + (STRUT_TOP - STRUT_FOOT) * t + margin
    return on


def brace_figure(src, out, params: dict) -> tuple[list[Strut], list[str], list[str], int]:
    """Write the unit-height figure at src to out with thin hanging tips cut back and struts under
    its other islands, sized for the print the params make. Returns the struts, where they hold
    (part heights), the spots still in the air, in words, and how many tips were cut."""
    import trimesh

    scale, top, radius = plinth(params)
    lift = float(params.get("height") or 90) - scale  # the figure's z = 0 sits this high in the part
    mesh = trimesh.load(str(src), force="mesh")
    mesh.apply_scale(scale)

    def floor(x, y):  # the plinth top; with no plinth a strut on the bed would be a lone pin
        return top if math.hypot(x, y) <= radius else None

    braced, struts, left, cut = brace(mesh, floor if radius is not None else None, figure=True)
    held = [f"{s.top[2] + lift:.0f} mm" for s in struts]
    spots = [where(i, braced).replace(f"{i.z:.1f} mm up", f"{i.z + lift:.1f} mm up") for i in left]
    braced.apply_scale(1.0 / scale)
    braced.export(str(out))
    return struts, held, spots, cut
