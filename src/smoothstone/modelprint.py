"""Make a found model print well on the person's printer: scale it to the size asked for, name its
features too thin for the nozzle, split it into bed-sized parts with alignment pins, check every part
the way stone checks a recipe part, and say how much filament and time each takes.

Every change to the mesh is a line the person can read. Each part prints on its largest flat face:
the lowest part's base or a cut face, or a flat side when that is clearly larger, and only in an
orientation that still fits the bed. A part with no flat face is laid on its flattest side.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

NOZZLE = 0.4  # mm
TWO_LINES = 2 * NOZZLE  # a wall a 0.4 mm nozzle draws as two lines
DROPPED = 0.1  # mm: Arachne leaves out a feature narrower than 25% of the nozzle
FILL = 0.98  # share of the bed a "fits my bed" model fills, so it never touches the bed's edge
BED_ROOM = 1.0  # mm kept free on each axis of a part
# alignment pins: a square pin cannot turn in its hole, so one pin aligns a joint. The hole is the
# pin plus 0.15 mm a side, turned 45 degrees so a sideways hole has a 45 degree roof and prints
# without support.
PIN = 4.0  # mm square
PIN_HOLE = PIN + 0.3
PIN_DEPTH = 6.0  # mm into each part
PIN_SHORT = 0.5  # mm the pin is shorter than both holes, so the faces close
PIN_CHAMFER = 0.5
WALL = 1.2  # mm of the part kept round a hole
# 1.75 mm filament as a peg, for a joint too small for a printed pin
PEG_HOLE = 2.0
PEG_DEPTH = 6.0
CRUMB = 2.0  # mm3: a piece a cut leaves smaller than this cannot print and is left out
SMALL_SECTION = 30.0  # mm2: a cut through this little is a spire or rod, not a place to cut
PLA = 1.24  # g/cm3
INFILL = 0.15
WALLS_MM = 2 * NOZZLE  # shell thickness: two walls, and as thick top and bottom
FLOW = 4.0  # mm3/s: a detailed model's average with slow outer walls and short moves
PALETTE = [(230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200), (245, 130, 48), (145, 30, 180),
           (70, 240, 240), (240, 50, 230), (210, 245, 60), (250, 190, 212), (0, 128, 128), (170, 110, 40)]
CLAY = (217.0, 160.0, 102.0)
RENDER_SIZE = 100.0  # mm the views are drawn at, whatever the model's size


def to_manifold(mesh):
    import manifold3d as m3

    g = m3.Mesh(vert_properties=np.asarray(mesh.vertices, np.float32), tri_verts=np.asarray(mesh.faces, np.uint32))
    g.merge()
    man = m3.Manifold(g)
    if man.status() != m3.Error.NoError:
        raise ValueError(f"the model is not a closed solid ({man.status().name})")
    return man


def to_trimesh(man):
    import trimesh

    o = man.to_mesh()
    return trimesh.Trimesh(np.asarray(o.vert_properties[:, :3], float), np.asarray(o.tri_verts, np.int64),
                           process=False)


# the frame of a cut: local (u, v, w) with w along the cut's axis; a cyclic order of x, y, z, so it
# is a rotation


def frame(axis: int) -> np.ndarray:
    a1, a2 = (axis + 1) % 3, (axis + 2) % 3
    M = np.zeros((3, 3))
    M[0, a1] = M[1, a2] = M[2, axis] = 1.0
    return M


def affine(M: np.ndarray, t=(0.0, 0.0, 0.0)) -> list:
    return np.c_[M, np.asarray(t, float)].tolist()


def section(man, axis: int, pos: float):
    """The cross-section at pos along axis, in that cut's (u, v) frame."""
    return man.transform(affine(frame(axis))).slice(pos)


def section_score(cs) -> float:
    """How good a place to cut: the area of the big pieces, less a lot for each small one (a cut
    through a spire makes a tip too small to print or pin on its own)."""
    score = 0.0
    for c in cs.decompose():
        a = c.area()
        score += a if a >= SMALL_SECTION else -300.0
    return score


# size


def footprint_turn(mesh, log: list[str]):
    """Turn the model about the vertical so its footprint's box is smallest, long side along x."""
    import trimesh

    xy = mesh.vertices[:, :2]
    try:
        T, ext = trimesh.bounds.oriented_bounds_2D(xy)
    except Exception:
        return mesh
    ang = math.degrees(math.atan2(T[1, 0], T[0, 0]))
    if ext[1] > ext[0]:
        ang += 90.0
    ang = ((ang + 90.0) % 180.0) - 90.0
    e0 = mesh.extents
    R = trimesh.transformations.rotation_matrix(math.radians(ang), [0, 0, 1])
    m = mesh.copy()
    m.apply_transform(R)
    e1 = m.extents
    if abs(ang) < 2.0 or e1[0] * e1[1] > e0[0] * e0[1] * 0.97:
        m = mesh.copy()  # already square to its box: the file's turn stays
        if m.extents[1] > m.extents[0]:
            m.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [0, 0, 1]))
            log.append("Turned it a quarter turn so its long side runs along x.")
    else:
        log.append(f"Turned it {abs(ang):.0f} deg about the vertical so its footprint lines up with the bed.")
    m.apply_translation(-m.bounds[0])
    return m


def scale_to(mesh, t: dict, log: list[str]):
    """Scale to the request's size; for a model with no size, the largest that fits the bed."""
    e = mesh.extents
    bed = t["bed"]
    if t["mode"] == "fit":
        s = FILL * min(bed[0] / e[0], bed[1] / e[1], bed[2] / e[2])
        why = f"the largest that fits the {bed[0]:.0f} x {bed[1]:.0f} x {bed[2]:.0f} mm bed"
    elif t["mode"] == "z":
        s = t["mm"] / e[2]
        why = f"{t['mm']:g} mm tall"
    elif t["mode"] == "long":
        s = t["mm"] / max(e[0], e[1])
        why = f"{t['mm']:g} mm long"
    else:
        s = t["mm"] / max(e)
        why = f"{t['mm']:g} mm on its longest side"
    m = mesh.copy()
    m.apply_scale(s)
    m.apply_translation(-m.bounds[0])
    f = m.extents
    log.append(f"Scaled it {s:.3g} times to {why}: {f[0]:.1f} x {f[1]:.1f} x {f[2]:.1f} mm.")
    return m, s


# thin features


NEEDLE = 2.0  # mm: a spire whose last this much is under two lines is a needle; shorter, only its point


@dataclass
class Thin:
    kind: str  # "tip": spire or pinnacle; "rod": rod or lattice bar; "edge": railing, fin or thin edge
    z0: float
    z1: float
    count: int = 0
    needles: int = 0  # tips thin for NEEDLE mm or more
    longest: float = 0.0  # mm of the longest thin run
    vanish: int = 0  # of them, how many lose 1 mm or more to the slicer (under 0.1 mm)
    layers: int = 0


def _inside(cs, x: float, y: float, r: float = 0.05) -> bool:
    import manifold3d as m3

    sq = m3.CrossSection.square([2 * r, 2 * r], True).translate([x, y])
    return (cs ^ sq).area() > 1e-9


def thin_features(man, height: float, step: float | None = None) -> list[Thin]:
    """Features narrower than two nozzle lines, found in cross-sections up the model and named: the
    tips of spires and pinnacles (a thin piece that ends going up), rods and lattice bars (a thin
    piece with more model above it), and railings, fins and thin edges (a thin strip on a wider
    piece). A piece is followed up the layers on a 3 mm grid, so the counts are close, not exact."""
    step = step or max(0.5, height / 300)
    zs = np.arange(step / 2, height, step)
    cells: dict[tuple[int, int], dict] = {}
    edge_layers, edge_z = 0, []
    for z in zs:
        cs = man.slice(float(z))
        fringe = 0.0
        for c in cs.decompose():
            if c.area() <= 0:
                continue
            core = c.offset(-TWO_LINES / 2)
            if core.is_empty():
                x0, y0, x1, y1 = c.bounds()
                key = (int((x0 + x1) / 2 // 3), int((y0 + y1) / 2 // 3))
                d = cells.setdefault(key, {"z0": float(z), "z1": float(z), "n": 0, "gone": 0})
                d.update(z1=float(z), x=(x0 + x1) / 2, y=(y0 + y1) / 2)
                d["n"] += 1
                d["gone"] += int(c.offset(-DROPPED / 2).is_empty())
            else:
                fringe += c.area() - core.offset(TWO_LINES / 2).area()
        if fringe > 1.0:
            edge_layers += 1
            edge_z.append(float(z))
    got: dict[str, Thin] = {}
    for d in cells.values():
        top = d["z1"] + step
        kind = "rod" if top < height and _inside(man.slice(float(top)), d["x"], d["y"], 0.3) else "tip"
        t = got.setdefault(kind, Thin(kind, d["z0"], d["z1"]))
        run = d["n"] * step
        t.count += 1
        t.needles += int(run >= NEEDLE)
        t.longest = max(t.longest, run)
        t.vanish += int(d["gone"] * step >= 1.0)
        t.layers += d["n"]
        t.z0, t.z1 = min(t.z0, d["z0"]), max(t.z1, d["z1"])
    out = [got[k] for k in ("tip", "rod") if k in got]
    if edge_layers:
        out.append(Thin("edge", min(edge_z), max(edge_z), layers=edge_layers))
    return out


def thin_lines(found: list[Thin], height: float, step: float) -> list[str]:
    if not found:
        return [f"Thin features: none under {TWO_LINES:g} mm (two lines of a {NOZZLE:g} mm nozzle) at this size."]
    out = []
    for t in found:
        span = f"from {t.z0:.0f} to {t.z1:.0f} mm up"
        gone = f"; the slicer leaves out 1 mm or more of {t.vanish} (under {DROPPED:g} mm)" if t.vanish else ""
        if t.kind == "tip":
            if t.needles:
                out.append(f"Thin: about {t.needles} spires and pinnacles end in needles under {TWO_LINES:g} mm, "
                           f"{NEEDLE:g} mm long or more (the longest {t.longest:.0f} mm), {span}: they print as "
                           f"one line and snap off easily{gone}.")
            rest = t.count - t.needles
            if rest:
                out.append(f"Thin: the points of about {rest} {'other ' if t.needles else ''}spires and pinnacles are "
                           f"finer than the nozzle; they print a little blunt.")
        elif t.kind == "rod":
            out.append(f"Thin: about {t.count} rods and lattice bars under {TWO_LINES:g} mm (the longest "
                       f"{t.longest:.0f} mm), {span}: one line each, fragile{gone}.")
        else:
            out.append(f"Thin: railings, fins or thin edges under {TWO_LINES:g} mm on {t.layers} of "
                       f"{int(height / step)} layers checked, {span}: they print as one line.")
    return out


# the split


def _band_parts(lo_b, hi_b, bed) -> int:
    """How many parts a band with this footprint box takes: one when it fits the bed."""
    ex, ey = hi_b[0] - lo_b[0], hi_b[1] - lo_b[1]
    return int(math.ceil(ex / (bed[0] - BED_ROOM) - 1e-9)) * int(math.ceil(ey / (bed[1] - BED_ROOM) - 1e-9))


def _cut_score(cs) -> float:
    """A place for a cut across the footprint: the smaller the cross-section the better, and never
    through a spire or rod (a piece under SMALL_SECTION)."""
    score = 0.0
    for c in cs.decompose():
        a = c.area()
        score -= a if a >= SMALL_SECTION else 5000.0
    return score


def _cuts_along(man, ax: int, lo: float, L: float, U: float, score, mid_weight: float = 0.5) -> list[float]:
    n = int(math.ceil(L / U - 1e-9))
    got, prev = [], 0.0
    for k in range(1, n):
        a = max(prev + 1.0, L - (n - k) * U)
        b = min(prev + U, L - 1.0)
        mid = prev + (L - prev) / (n - k + 1)
        best, best_s = mid if a <= mid <= b else (a + b) / 2, -math.inf
        for q in np.linspace(a, b, 41):
            sc = score(section(man, ax, lo + float(q))) - mid_weight * abs(q - mid)
            if sc > best_s:
                best, best_s = float(q), sc
        got.append(round(lo + best, 2))
        prev = best
    return got


def plan_split(man, ext, bed) -> dict:
    """Where to cut so every part fits the bed: {"z": [heights], "bands": [{0: [x], 1: [y]} per band
    from the bottom]}. Cuts go across z first, as few as fit, each placed so the bands above and below
    take the fewest parts (a tower above a wide base stays whole) and then where the section is broad
    enough for pins. x and y cuts go only into a band whose own footprint is wider than the bed, where
    its cross-section is smallest and through no spire."""
    x0, y0, z0, x1, y1, z1 = man.bounding_box()
    H = z1 - z0
    Uz = float(bed[2]) - BED_ROOM
    zs = np.arange(z0 + 0.5, z1, 1.0)
    boxes = []
    for z in zs:
        b = man.slice(float(z)).bounds()
        boxes.append(b if b[2] >= b[0] else (np.inf, np.inf, -np.inf, -np.inf))
    boxes = np.asarray(boxes, float)

    def band_box(a, b):
        sel = boxes[(zs >= a) & (zs <= b)]
        if not len(sel) or not np.isfinite(sel).any():
            return (0.0, 0.0), (0.0, 0.0)
        return (sel[:, 0].min(), sel[:, 1].min()), (sel[:, 2].max(), sel[:, 3].max())

    n = int(math.ceil(H / Uz - 1e-9))
    zc, prev = [], 0.0
    for k in range(1, n):
        a = max(prev + 1.0, H - (n - k) * Uz)
        b = min(prev + Uz, H - 1.0)
        best, best_key = (a + b) / 2, None
        for q in np.linspace(a, b, 41):
            q = float(q)
            parts = _band_parts(*band_box(z0 + prev, z0 + q), bed)
            if k == n - 1:
                parts += _band_parts(*band_box(z0 + q, z1), bed)
            key = (-parts, section_score(section(man, 2, z0 + q)))
            if best_key is None or key > best_key:
                best, best_key = q, key
        zc.append(round(z0 + best, 2))
        prev = best
    edges = [z0, *zc, z1]
    bands = []
    for a, b in zip(edges[:-1], edges[1:]):
        (bx0, by0), (bx1, by1) = band_box(a, b)
        band = {}
        for ax, lo_, hi_ in ((0, bx0, bx1), (1, by0, by1)):
            U = float(bed[ax]) - BED_ROOM
            if hi_ - lo_ > U:
                band[ax] = _cuts_along(man, ax, lo_, hi_ - lo_, U, _cut_score)
        bands.append(band)
    return {"z": zc, "bands": bands}


def plan_cuts_of(plan: dict) -> dict[int, list[float]]:
    """Every cut plane of a plan by axis, for the joints."""
    out: dict[int, list[float]] = {}
    if plan["z"]:
        out[2] = list(plan["z"])
    for band in plan["bands"]:
        for ax, ps in band.items():
            out.setdefault(ax, [])
            out[ax] += [p for p in ps if p not in out[ax]]
    return out


def plan_parts(plan: dict) -> int:
    return sum((len(b.get(0, [])) + 1) * (len(b.get(1, [])) + 1) for b in plan["bands"])


@dataclass
class Part:
    man: object
    cell: tuple
    number: int = 0
    to_print: np.ndarray = field(default_factory=lambda: np.eye(4))
    file: str = ""
    holes: int = 0
    bodies: int = 1  # pieces in the part, each standing on the bed


def _cut(pieces, ax: int, ps: list[float], slot: int):
    """Cut every piece at each plane along ax; the piece above a cut gets the next index in its cell."""
    for k, p in enumerate(ps):
        nxt = []
        for m, cell in pieces:
            if cell[slot] != k:
                nxt.append((m, cell))
                continue
            n = [0.0, 0.0, 0.0]
            n[ax] = 1.0
            top, bottom = m.split_by_plane(n, p)
            if not bottom.is_empty():
                nxt.append((bottom, cell))
            if not top.is_empty():
                c = list(cell)
                c[slot] = k + 1
                nxt.append((top, tuple(c)))
        pieces = nxt
    return pieces


def split(man, plan: dict, log: list[str]) -> list[Part]:
    """The parts of a plan (plan_split), numbered from the bottom band up, then y, then x."""
    pieces = _cut([(man, (0, 0, 0))], 2, plan["z"], 0)
    cells = []
    for band_i, band in enumerate(plan["bands"]):
        mine = [(m, c) for m, c in pieces if c[0] == band_i]
        mine = _cut(mine, 1, band.get(1, []), 1)
        mine = _cut(mine, 0, band.get(0, []), 2)
        cells += mine
    parts, crumbs = [], 0
    for m, cell in cells:
        # one part per cell: a cut through several towers leaves them as pieces of one part, each
        # standing on its own cut face (the islands check finds any that does not)
        keep = []
        for c in m.decompose():
            if c.volume() < CRUMB:
                crumbs += 1
            else:
                keep.append(c)
        if keep:
            import manifold3d as m3

            parts.append(Part(m3.Manifold.compose(keep) if len(keep) > 1 else keep[0], cell, bodies=len(keep)))
    if crumbs:
        log.append(f"Left out {crumbs} crumbs under {CRUMB:g} mm3 that the cuts left.")
    parts.sort(key=lambda p: p.cell)
    for i, p in enumerate(parts, 1):
        p.number = i
    return parts


def _hole_solid(axis: int, pos: float, u: float, v: float, kind: str, depth: float):
    """The hole through both faces of a joint, depth into each part, in world coordinates."""
    import manifold3d as m3

    if kind == "pin":
        cs = m3.CrossSection.square([PIN_HOLE, PIN_HOLE], True).rotate(45.0)
    else:
        cs = m3.CrossSection.circle(PEG_HOLE / 2, 24)
    solid = cs.translate([u, v]).extrude(2 * depth).translate([0, 0, pos - depth])
    return solid.transform(affine(frame(axis).T))


def _region_points(cs, n: int) -> list[tuple[float, float]]:
    """Up to n points in a region, far apart: its pieces' middles first, then the corners farthest apart."""
    pts = []
    comps = sorted(cs.decompose(), key=lambda c: -c.area())
    for c in comps:
        x0, y0, x1, y1 = c.bounds()
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        if _inside(c, mx, my):
            pts.append((mx, my))
        for poly in c.to_polygons():
            for x, y in np.asarray(poly)[:: max(1, len(poly) // 16)]:
                pts.append((float(x), float(y)))
    if not pts:
        return []
    chosen = [pts[0]]
    while len(chosen) < n:
        far = max(pts, key=lambda p: min(math.dist(p, q) for q in chosen))
        if min(math.dist(far, q) for q in chosen) < 3 * PIN_HOLE:
            break
        chosen.append(far)
    rest = [p for p in pts if p not in chosen]
    return chosen + rest


@dataclass
class Joint:
    a: int
    b: int
    axis: int
    pos: float
    kind: str  # "pin", "peg" or "glue"
    pins: list = field(default_factory=list)  # (u, v, depth)
    area: float = 0.0


def joints(parts: list[Part], cuts: dict[int, list[float]], log: list[str]) -> list[Joint]:
    """Pin holes at every joint: square printed pins where there is room, 1.75 mm filament pegs where
    there is less, glue alone where there is none. Each hole is checked to lie wholly in its part."""
    import manifold3d as m3

    out = []
    for ax, ps in cuts.items():
        for p in ps:
            lower = [q for q in parts if abs(q.man.bounding_box()[3 + ax] - p) < 1e-3]
            upper = [q for q in parts if abs(q.man.bounding_box()[ax] - p) < 1e-3]
            for A in lower:
                sa = section(A.man, ax, p - 0.02)
                for B in upper:
                    sb = section(B.man, ax, p + 0.02)
                    ov = sa ^ sb
                    area = ov.area()
                    if area < 1.0:
                        continue
                    j = Joint(A.number, B.number, ax, p, "glue", area=area)
                    for kind, inset, depth in (("pin", PIN_HOLE / math.sqrt(2) + WALL, PIN_DEPTH),
                                               ("peg", PEG_HOLE / 2 + WALL * 0.8, PEG_DEPTH)):
                        room = ov.offset(-inset, m3.JoinType.Round)
                        if room.is_empty():
                            continue
                        want = 2 if area >= 300 else 1
                        placed = []
                        for u, v in _region_points(room, want)[:24]:
                            if len(placed) >= want:
                                break
                            if any(math.dist((u, v), q[:2]) < 3 * PIN_HOLE for q in placed):
                                continue
                            for d in (depth, depth * 2 / 3):
                                hole = _hole_solid(ax, p, u, v, kind, d)
                                half = hole.volume() / 2
                                cut_a = A.man.volume() - (A.man - hole).volume()
                                cut_b = B.man.volume() - (B.man - hole).volume()
                                if cut_a >= 0.97 * half and cut_b >= 0.97 * half:
                                    placed.append((u, v, d))
                                    break
                        if placed:
                            j.kind, j.pins = kind, placed
                            break
                    for u, v, d in j.pins:
                        hole = _hole_solid(ax, p, u, v, j.kind, d)
                        A.man, B.man = A.man - hole, B.man - hole
                        A.holes += 1
                        B.holes += 1
                    out.append(j)
    return out


def joint_line(j: Joint) -> str:
    where = f"cut at {'xyz'[j.axis]} {j.pos:.1f} mm"
    if j.kind == "pin":
        deep = "/".join(sorted({f"{d:.0f}" for _, _, d in j.pins}))
        return (f"Parts {j.a} and {j.b} ({where}): {len(j.pins)} square pin{'s' if len(j.pins) > 1 else ''}, "
                f"{PIN_HOLE:.1f} mm holes {deep} mm deep each side.")
    if j.kind == "peg":
        return (f"Parts {j.a} and {j.b} ({where}): {len(j.pins)} hole{'s' if len(j.pins) > 1 else ''} for a 1.75 mm "
                f"filament peg ({PEG_HOLE:g} mm, {j.pins[0][2]:.0f} mm deep each side): too small for a printed pin.")
    return f"Parts {j.a} and {j.b} ({where}): {j.area:.0f} mm2 to glue, too small for a pin; line them up by eye."


def pins_mesh(lengths: list[float], bed):
    """Every printed pin, lying on a side, in rows along y that wrap to fit the bed minus BED_ROOM:
    square pins with chamfered ends."""
    import manifold3d as m3

    gap = 4.0
    room_y = float(bed[1]) - BED_ROOM
    per_row = max(1, int((room_y - PIN) // (PIN + gap)) + 1)
    out, x = [], 0.0
    for r in range(0, len(lengths), per_row):
        row = lengths[r:r + per_row]
        for i, L in enumerate(row):
            core = m3.Manifold.cube([L - 2 * PIN_CHAMFER, PIN, PIN], True)
            ends = m3.Manifold.cube([L, PIN - 2 * PIN_CHAMFER, PIN - 2 * PIN_CHAMFER], True)
            pin = m3.Manifold.batch_hull([core, ends])
            out.append(pin.translate([x + L / 2, PIN / 2 + i * (PIN + gap), PIN / 2]))
        x += max(row) + gap
    return m3.Manifold.compose(out) if out else None


# orientation, export


def flat_bottom(mesh) -> float:
    """mm2 of faces lying flat on the bed."""
    z0 = mesh.bounds[0][2]
    tz = mesh.triangles[:, :, 2]
    down = (mesh.face_normals[:, 2] < -0.99) & (tz.max(axis=1) <= z0 + 0.1)
    return float(mesh.area_faces[down].sum())


def lay_flat(mesh, bed) -> tuple[object, np.ndarray, str | None]:
    """Lay the part on its largest flat face (the model's own base or a cut face, most often): the
    side of the six with the most area flat on the bed, keeping the model's up on a near tie. A side
    is taken only when the part laid on it still fits the bed minus BED_ROOM: the split fits each part
    the model's way up, and a tall band laid down can run past a short axis."""
    import trimesh

    room = np.asarray(bed, float)[:3] - BED_ROOM
    best, bestT, best_a, why = mesh, np.eye(4), flat_bottom(mesh), None
    keep = best_a
    for d, name in (([1, 0, 0], "+x"), ([-1, 0, 0], "-x"), ([0, 1, 0], "+y"), ([0, -1, 0], "-y"), ([0, 0, 1], "+z")):
        T = trimesh.geometry.align_vectors(d, [0, 0, -1])
        m = mesh.copy()
        m.apply_transform(T)
        if np.any(m.extents > room + 1e-6):
            continue
        a = flat_bottom(m)
        if a > best_a and a > keep * 1.1:
            best, bestT, best_a, why = m, T, a, name
    if why is not None:
        return best, bestT, f"its {why} side, its largest flat face ({best_a:.0f} mm2)"
    return mesh, np.eye(4), None


def estimate(mesh) -> tuple[float, float]:
    """(grams of PLA, hours) at 15% infill, two walls, 0.2 mm layers: a rough figure, not a slicer's."""
    vol = float(abs(mesh.volume))
    shell = min(vol, float(mesh.area) * WALLS_MM / 2)
    used = shell + INFILL * (vol - shell)
    return used / 1000 * PLA, used / FLOW / 3600


# a found model's own checks: thin walls measured and reported, overhangs printed on supports

ONE_LINE = NOZZLE  # mm: a feature narrower than this prints as one thin line at best
# The share of a found part's volume in features under one line past which it no longer prints as the
# model. Measured (LOG.md, models 1, round 2) at the spec sizes: the parts that printed in round 1
# (Cologne 0.03%, Taj Mahal by Bazzar701 0.005%), the MiniWorld3D models with dozens of makes each
# (Taj 0.03%, St. Basil's 0.10%, Notre-Dame by gogole 0.09%), and the most made model of all, "Eiffel
# Tower FDM printable" (180 makes at 220 mm), 0.89% at 200 mm. 1.5% clears the model makers print
# with room for its size; a model past it is mostly lattice a nozzle cannot draw.
DROP_LIMIT = 0.015
SUPPORT_PX = 0.5  # mm: the support estimate's grid and layer
SUPPORT_FILL = 0.15  # share of the support region a slicer's supports fill (tree or grid, with interface)
SUPPORT_MIN = 0.5  # g: less than this is a few touch points, not a part that needs supports


def _opened(cs, r: float) -> float:
    """Area of the cross-section left after an opening of radius r: what lines r * 2 wide can draw."""
    import manifold3d as m3

    core = cs.offset(-r, m3.JoinType.Round, circular_segments=12)
    return 0.0 if core.is_empty() else core.offset(r, m3.JoinType.Round, circular_segments=12).area()


def thin_shares(man, step: float = 0.5) -> dict:
    """The share of the part's volume in features narrower than what the slicer draws (DROPPED,
    which Arachne leaves out), one line and two lines, from cross-sections every `step` mm in the
    part's print orientation (the slicer's own view: a feature is thin across the layer)."""
    x0, y0, z0, x1, y1, z1 = man.bounding_box()
    tot = d0 = d1 = d2 = 0.0
    for z in np.arange(z0 + step / 2, z1, step):
        cs = man.slice(float(z))
        a = cs.area()
        if a <= 0:
            continue
        tot += a
        d0 += a - _opened(cs, DROPPED / 2)
        d1 += a - _opened(cs, ONE_LINE / 2)
        d2 += a - _opened(cs, TWO_LINES / 2)
    if tot <= 0:
        return {"dropped": 0.0, "one_line": 0.0, "two_lines": 0.0}
    return {"dropped": round(d0 / tot, 5), "one_line": round(d1 / tot, 5), "two_lines": round(d2 / tot, 5)}


def surface_thickness(mesh, samples: int = 3000) -> dict:
    """The share of the surface on walls thinner than one line and two lines (a ray in from each
    sample point), and the thinnest wall at stone's percentile (check.WALL_PERCENTILE)."""
    from . import check

    import trimesh

    pts, fi = trimesh.sample.sample_surface(mesh, samples, seed=0)
    n = mesh.face_normals[fi]
    o = pts - n * 1e-4
    got = check._ray_hits(mesh, o, -n)
    if got is None or not len(got[0]):
        return {"one_line": None, "two_lines": None, "wall": None}
    idx, loc = got
    d = np.linalg.norm(loc - o[idx], axis=1)
    d = d[d > 5e-3]
    if not len(d):
        return {"one_line": None, "two_lines": None, "wall": None}
    return {"one_line": round(float((d < ONE_LINE).mean()), 4), "two_lines": round(float((d < TWO_LINES).mean()), 4),
            "wall": round(float(np.percentile(d, check.WALL_PERCENTILE)), 3)}


def cut_loose(mesh, rep) -> list[dict]:
    """Pieces the slicer finds in the air that the model itself holds up: material is right under
    them, but too thin to print, so dropping it cuts the piece loose. A piece with nothing under it
    is an overhang, which supports hold."""
    man = to_manifold(mesh)
    out = []
    for pc in getattr(rep, "floating", []):
        below = man.slice(float(pc["bottom"]) - rep.layer / 2)
        if below.is_empty() or "joined" in pc:  # a piece that joins the part above hangs on it: supports hold it
            continue
        pts = np.asarray(pc["xy"], float)
        pts = pts[:: max(1, len(pts) // 40)]
        if any(_inside(below, float(x), float(y), ONE_LINE / 2) for x, y in pts):
            out.append({"z": round(float(pc["bottom"]), 1), "where": pc["where"], "area": round(float(pc["peak"]), 1)})
    return out


def _raster(cs, x0: float, y0: float, w: int, h: int, px: float) -> np.ndarray:
    from skimage.draw import polygon

    m = np.zeros((h, w), bool)
    for poly in cs.to_polygons():
        q = np.asarray(poly, float)
        if len(q) < 3:
            continue
        rr, cc = polygon((q[:, 1] - y0) / px, (q[:, 0] - x0) / px, (h, w))
        t = np.zeros((h, w), bool)
        t[rr, cc] = True
        m ^= t  # even-odd: a hole's polygon cancels its outline's
    return m


def support_volume(man, px: float = SUPPORT_PX) -> float:
    """mm3 of space a slicer fills with supports: under every spot that hangs past 45 degrees, down
    to the bed or to the part below, on a px mm grid and px mm layers."""
    from scipy import ndimage

    x0, y0, z0, x1, y1, z1 = man.bounding_box()
    w, h = int(math.ceil((x1 - x0) / px)) + 2, int(math.ceil((y1 - y0) / px)) + 2
    zs = np.arange(z0 + px / 2, z1, px)
    if len(zs) < 2 or w * h > 4_000_000:
        return 0.0
    solid = [_raster(man.slice(float(z)), x0 - px, y0 - px, w, h, px) for z in zs]
    reach = np.ones((3, 3), bool)  # one cell a layer as tall as it is wide: 45 degrees
    need = np.zeros((h, w), bool)
    vol = 0.0
    for k in range(len(zs) - 1, 0, -1):
        over = solid[k] & ~ndimage.binary_dilation(solid[k - 1], reach)
        need = (need | over) & ~solid[k - 1]
        vol += float(need.sum()) * px * px * px
    return vol


def found_checks(path: str, bed, bodies: int = 1) -> dict:
    """stone's checks on a found model's part, with the slicer's view of it (run in its own process).

    The walls of a model made for display are thinner than two lines almost everywhere they are fine
    (spires, railings, lattices), so min_wall here is measured, not a bar: the part fails it only when
    more of its volume than DROP_LIMIT is under one line, or when what the slicer drops cuts a piece
    loose. Overhangs and pieces in the air print on supports, which the build reports; recipes and
    engineering parts keep the 0.8 mm bar and the overhang limit unchanged (check.py)."""
    from concurrent.futures import Future
    from types import SimpleNamespace

    from . import check, slicer

    mesh = check._load(Path(path))
    out = [check.Result("loads", len(mesh.faces) > 0, len(mesh.faces), f"{len(mesh.faces)} faces")]
    rep = slicer.slice_mesh(mesh, bed=tuple(bed))
    done: Future = Future()
    done.set_result(rep)
    recipe = SimpleNamespace(max_bodies=bodies, max_overhang=1.0, skip={"bed_edge": "a found model's part"},
                             min_wall=0.0, supports=True, dims=None)
    res = check._check_rest(mesh, out, done, recipe, None, tuple(bed), None, bodies, 1.0)
    man = to_manifold(mesh)
    shares = thin_shares(man)
    surf = surface_thickness(mesh)
    loose = cut_loose(mesh, rep)
    sup = support_volume(man) * SUPPORT_FILL
    g, h = sup / 1000 * PLA, sup / FLOW / 3600
    floating = len(getattr(rep, "floating", []))
    final = []
    for r in res:
        if r.name == "min_wall":
            over = DROP_LIMIT is not None and shares["one_line"] > DROP_LIMIT
            ok = not over and not loose
            bits = [f"{shares['one_line'] * 100:.1f}% of the volume under one line ({ONE_LINE:g} mm), "
                    f"{shares['two_lines'] * 100:.1f}% under two, {shares['dropped'] * 100:.2f}% dropped by the slicer"]
            if over:
                bits.append(f"over the {DROP_LIMIT * 100:.0f}% that still prints as the model")
            if loose:
                bits.append(f"{len(loose)} piece{'s' if len(loose) > 1 else ''} cut loose where a thin neck is "
                            f"dropped (first at {loose[0]['z']:.0f} mm up)")
            r = check.Result("min_wall", ok, shares["one_line"], "; ".join(bits),
                             advice="print it bigger, or with a 0.2 mm nozzle or resin")
        elif r.name == "overhang":
            r = check.Result("overhang", True, r.value, r.detail.split(" (max")[0] + ": printed on supports")
        final.append(r)
    final.append(check.Result("supports", True, round(g, 1),
                              f"about {g:.0f} g and {h:.1f} h of supports" if g >= SUPPORT_MIN else "none needed"))
    return {"checks": [r.to_dict() for r in final], "shares": shares, "surface": surf, "cut_loose": loose,
            "support_g": round(g, 1), "support_h": round(h, 2), "floating": floating}


def check_part(path: str, bed, bodies: int = 1) -> list[dict]:
    """The checks of found_checks alone (the grader runs them again on the files)."""
    return found_checks(path, bed, bodies)["checks"]


def export(mesh, path: Path) -> tuple[object, np.ndarray, bool]:
    """Write the part as a slicer will read it (float32, closed, no zero-area faces), its lowest
    corner at the origin. Returns the mesh written and the shift that put it there."""
    from . import clean

    broken = False
    try:
        m = clean.for_slicer(mesh)
    except ValueError:  # solids that only touch keep edges a slicer calls broken (LOG.md, models 1)
        m, broken = mesh.copy(), True
    shift = -np.asarray(m.bounds[0], float)
    m.apply_translation(shift)
    m.export(str(path))
    return m, shift, broken


def render(meshes: list, rgb: list, out: Path) -> Path | None:
    import trimesh

    from . import colors

    try:
        m = trimesh.util.concatenate(meshes)
        cols = np.concatenate([np.tile(np.asarray(c, float), (len(x.faces), 1)) for x, c in zip(meshes, rgb)])
        # drawn at RENDER_SIZE: the views split faces to 1 mm before drawing, which a 300 mm model's
        # wide cut faces turned into millions (a 13 minute picture); the picture is the same shape
        m.apply_scale(RENDER_SIZE / max(float(max(m.extents)), 1e-6))
        colors.render_views(m, cols, out)
        return out
    except Exception:
        return None


def layout(parts: list, gap: float = 10.0) -> list:
    """The parts as they print, side by side in rows, for one picture of them all."""
    row_w = max(300.0, math.sqrt(sum(p.extents[0] * p.extents[1] for p in parts)) * 1.6)
    x = y = row_h = 0.0
    out = []
    for p in parts:
        e = p.extents
        if x > 0 and x + e[0] > row_w:
            x, y, row_h = 0.0, y + row_h + gap, 0.0
        q = p.copy()
        q.apply_translation([x - q.bounds[0][0], y - q.bounds[0][1], -q.bounds[0][2]])
        out.append(q)
        x += e[0] + gap
        row_h = max(row_h, e[1])
    return out


def label_layout(png: Path, labels: list[tuple[str, tuple]]) -> None:
    """A legend on the layout picture: each part's number in its color."""
    from PIL import Image, ImageDraw, ImageFont

    try:
        im = Image.open(png).convert("RGB")
    except OSError:
        return
    font = ImageFont.load_default(size=16)
    h = 26
    top = Image.new("RGB", (im.width, im.height + h * ((len(labels) + 9) // 10)), (40, 40, 40))
    top.paste(im, (0, top.height - im.height))
    d = ImageDraw.Draw(top)
    for i, (t, c) in enumerate(labels):
        d.text((10 + (i % 10) * (im.width // 10), 4 + (i // 10) * h), t, fill=tuple(int(x) for x in c), font=font)
    top.save(png)


# the whole step


def make(root: Path, request: str, bed_default, progress=None) -> dict:
    """Fit the job's found model to the printer. Returns {"ok", "lines", "fix", "parts", "files", ...}
    and writes the parts, the pins, build/model/parts.json, build/views.png and build/layout.png."""
    import json
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor

    import trimesh

    from . import models

    say = progress or (lambda text: None)
    info = models.taken(root)
    generated = info.get("source") == "landmark" and isinstance(info.get("target"), dict)
    t = info["target"] if generated else models.target(request, bed_default)
    bed = [float(x) for x in t["bed"]]
    lines = [models.asked_size_line(t)]
    mesh = trimesh.load(info["stl"], force="mesh", process=False)
    log: list[str] = []
    mesh = footprint_turn(mesh, log)
    if generated:
        s = 1.0
        log.append("Kept the landmark's generated scale, 2 mm plinth and printable tip dimensions.")
    else:
        mesh, s = scale_to(mesh, t, log)
    man = to_manifold(mesh)
    H = float(mesh.extents[2])
    step = max(0.5, H / 300)
    say("measuring thin features")
    thin = thin_features(man, H, step)
    say("planning the cuts")
    plan = plan_split(man, mesh.extents, bed)
    cuts = plan_cuts_of(plan)
    if cuts:
        parts = split(man, plan, log)
        where = ", ".join(f"{'xyz'[a]} " + " and ".join(f"{p:.1f}" for p in ps) for a, ps in sorted(cuts.items()))
        log.append(f"Split it into {len(parts)} parts so each fits the {models.fmt3(bed)} bed: cuts at {where} mm.")
        say("placing alignment pins")
        js = joints(parts, cuts, log)
    else:
        # no cut: the model's own separate pieces (towers on one base plate) each stand on the bed,
        # and the islands check still fails any that starts in the air
        parts, js = [Part(man, (0, 0, 0), 1, bodies=len(man.decompose()))], []
    bd = root / "build" / "model"
    bd.mkdir(parents=True, exist_ok=True)
    name = models.slug(info.get("subject") or info.get("name") or "model")
    for old in [*root.glob(f"{name}*.stl"), *root.glob("*_part*.stl"), *root.glob("*_pins.stl")]:
        old.unlink(missing_ok=True)
    files, assembled, records = [], [], []
    for p in parts:
        tm = to_trimesh(p.man)
        assembled.append(tm.copy())
        flat, T, why = lay_flat(tm, bed)
        f = root / (f"{name}.stl" if len(parts) == 1 else f"{name}_part{p.number}.stl")
        written, shift, broken = export(flat, f)
        M = np.eye(4)
        M[:3, 3] = shift
        p.to_print = M @ T
        p.file = str(f)
        if why:
            log.append(f"Part {p.number} lies on {why}.")
        if p.bodies > 1:
            log.append(f"Part {p.number} prints as {p.bodies} pieces, each standing on its cut face.")
        files.append(f)
        g, h = estimate(written)
        records.append({"number": p.number, "file": str(f), "cell": list(p.cell), "to_print": p.to_print.tolist(),
                        "size_mm": [round(float(x), 2) for x in written.extents], "grams": round(g, 1),
                        "hours": round(h, 2), "holes": p.holes, "bodies": p.bodies, "saves_broken": broken})
    pin_lengths = [2 * d - PIN_SHORT for j in js if j.kind == "pin" for _, _, d in j.pins]
    pins_file = None
    if pin_lengths:
        pins_file = root / f"{name}_pins.stl"
        pm = to_trimesh(pins_mesh(pin_lengths, bed))
        pm.export(str(pins_file))
    say(f"checking {len(files)} part{'s' if len(files) > 1 else ''}")
    jobs = [(str(f), bed, p.bodies) for f, p in zip(files, parts)] + ([(str(pins_file), bed, len(pin_lengths))] if pins_file else [])
    with ProcessPoolExecutor(max_workers=max(1, min(len(jobs), 3 if generated else 8)), mp_context=mp.get_context("spawn")) as pool:
        full = list(pool.map(found_checks, *zip(*jobs)))
    res = [f_["checks"] for f_ in full]
    ok = True
    part_lines, fixes = [], []
    for rec, f_ in zip(records, full):
        r = f_["checks"]
        rec.update({"checks": r, "thin_shares": f_["shares"], "surface": f_["surface"], "cut_loose": f_["cut_loose"],
                    "support_g": f_["support_g"], "support_h": f_["support_h"]})
        bad = [x for x in r if not x["ok"]]
        e = rec["size_mm"]
        sup = f", supports {rec['support_g']:.0f} g" if rec["support_g"] >= SUPPORT_MIN else ""
        head = (f"Part {rec['number']}" if len(parts) > 1 else "Part") + \
            f": {e[0]:.1f} x {e[1]:.1f} x {e[2]:.1f} mm, {rec['grams']:.0f} g, {rec['hours']:.1f} h{sup}"
        if bad:
            ok = False
            part_lines.append(head + ", FIX " + "; ".join(f"{x['name']} {x['detail']}" for x in bad)[:200])
            fixes += [f"{x['name']}: {x['advice']}" for x in bad]
        else:
            part_lines.append(head + f", all {len(r)} checks pass")
    pins_rec = None
    if pins_file:
        r = res[-1]
        bad = [x for x in r if not x["ok"]]
        pins_rec = {"file": str(pins_file), "count": len(pin_lengths), "checks": r}
        if bad:
            ok = False
            part_lines.append(f"Pins: FIX " + "; ".join(f"{x['name']} {x['detail']}" for x in bad)[:200])
        else:
            part_lines.append(f"Pins: {len(pin_lengths)} square pins {PIN:g} mm, print {pins_file.name}; "
                              f"all {len(r)} checks pass")
    pegs = sum(len(j.pins) for j in js if j.kind == "peg")
    sup_g = sum(r["support_g"] for r in records)
    sup_h = sum(r["support_h"] for r in records)
    grams = sum(r["grams"] for r in records) + sup_g
    hours = sum(r["hours"] for r in records) + sup_h
    need = [r["number"] for r in records if r["support_g"] >= SUPPORT_MIN]
    if need:
        who = "It needs" if len(records) == 1 else \
            f"Part{'s' if len(need) > 1 else ''} {', '.join(map(str, need))} need{'' if len(need) > 1 else 's'}"
        part_lines.append(f"Supports: {who} supports under overhangs and pieces that start in the air, about "
                          f"{sup_g:.0f} g and {sup_h:.1f} h; tree supports suit towers and spires and come off cleaner.")
    walls = [r["surface"]["wall"] for r in records if r["surface"].get("wall")]
    one = max((r["thin_shares"]["one_line"] for r in records), default=0.0)
    if walls and min(walls) < TWO_LINES:
        k = TWO_LINES / min(walls)
        size_now = np.ptp(np.concatenate([m.bounds for m in assembled]), axis=0)
        within = "within" if one <= DROP_LIMIT else "over"
        part_lines.append(f"Thin walls: the thinnest are {min(walls):.2f} mm and {one * 100:.1f}% of the volume is under "
                          f"one line ({ONE_LINE:g} mm), {within} the {DROP_LIMIT * 100:.1f}% that prints as the model. "
                          f"To print them whole: make it {k:.1f} times bigger ({max(size_now) * k:.0f} mm on its "
                          f"longest side), or use a 0.2 mm nozzle or a resin printer.")
    if pins_file:
        g, h = estimate(trimesh.load(str(pins_file), force="mesh"))
        grams, hours = grams + g, hours + h
    say("drawing the views")
    views = render(assembled, [CLAY] * len(assembled), root / "build" / "views.png")
    laid = layout([trimesh.load(str(f), force="mesh", process=False) for f in files])
    cols = [PALETTE[i % len(PALETTE)] for i in range(len(laid))]
    lay_png = render(laid, cols, root / "build" / "layout.png") if len(laid) > 1 or generated else None
    if lay_png:
        label_layout(lay_png, [(f"part {r['number']}", c) for r, c in zip(records, cols)])
    size = np.ptp(np.concatenate([m.bounds for m in assembled]), axis=0)
    data = {"model": {k: info.get(k) for k in ("name", "author", "license", "url", "source", "id")},
            "target": t, "bed": bed, "scale": s, "size_mm": [round(float(x), 2) for x in size],
            "parts": records, "pins": pins_rec, "pegs": pegs,
            "joints": [{"a": j.a, "b": j.b, "axis": "xyz"[j.axis], "at": j.pos, "kind": j.kind,
                        "pins": [list(map(float, q)) for q in j.pins], "area": round(j.area, 1)} for j in js],
            "thin": [t_.__dict__ for t_ in thin], "grams": round(grams, 1), "hours": round(hours, 2), "passed": ok,
            "views": str(views) if views else None, "layout": str(lay_png) if lay_png else None}
    (bd / "parts.json").write_text(json.dumps(data, indent=1))
    lines += log + thin_lines(thin, H, step)
    if js:
        kinds = {k: [j for j in js if j.kind == k] for k in ("pin", "peg", "glue")}
        bits = []
        if kinds["pin"]:
            bits.append(f"{len(kinds['pin'])} with square pins")
        if kinds["peg"]:
            bits.append(f"{len(kinds['peg'])} with 1.75 mm filament pegs ({pegs} pegs, cut {2 * PEG_DEPTH - 0.5:g} mm long)")
        if kinds["glue"]:
            bits.append(f"{len(kinds['glue'])} to glue only")
        lines.append(f"Joints: {len(js)}, " + ", ".join(bits) + f"; each listed in {bd / 'parts.json'}")
        for j in js[:3]:
            lines.append(joint_line(j))
    lines += part_lines
    n = len(records)
    lines.append(f"Total: {n} part{'s' if n > 1 else ''}{' and the pins' if pins_file else ''}, about {grams:.0f} g "
                 f"of PLA and {hours:.1f} h (15% infill, two walls, 0.2 mm layers; your slicer's figure is exact)")
    return {"ok": ok, "lines": lines, "fixes": fixes, "files": [str(f) for f in files],
            "broken": [r["number"] for r in records if r["saves_broken"]],
            "pins": str(pins_file) if pins_file else None, "views": views, "layout": lay_png, "data": data}
