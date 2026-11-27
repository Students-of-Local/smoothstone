"""Print checks on an STL: watertight, one body, on the bed, walls, overhangs, dims."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from . import config, refs

MIN_WALL = 0.8  # mm
WALL_SAMPLES = 3000
WALL_PERCENTILE = 3
OVERHANG_COS = math.cos(math.radians(45))
REST_TOL = 0.05  # mm
CONTACT_TOL = 0.1  # mm
BED_SKIP = 0.2  # mm
# The bed chamfer (lib/stone.scad BED_CHAMFER) steps 0.4 mm in over the first 0.4 mm: a 45 degree
# slope built from ledges. A downward face lying wholly below this height is that slope, not an
# overhang.
CHAMFER_ZONE = 0.45  # mm
# bed_edge: the first layer squashes out (elephant foot). PrusaSlicer's default elephant-foot
# compensation is 0.2 mm, so a part needs at least that much inset at the bed edge.
BED_EDGE_Z = 0.8  # mm, the slice the bed contact is compared with
MIN_BED_EDGE = 0.2  # mm
# text: a 0.4 mm nozzle lays a letter stroke as at least two lines, so it needs 0.8 mm.
MIN_STROKE = 0.8  # mm
# Thin strokes of each bold font as a share of the letter height (text size): the 10th percentile
# of the stroke widths along the letters' center lines, measured from OpenSCAD's own text().
TEXT_STROKE = {"sans": 0.15, "serif": 0.07, "mono": 0.14}
# A recipe tells the check what text it made with
#   echo(stone_text = [letter height, font, setting that grows it, that setting's value now]);
# the setting is then raised in proportion. "font" as the setting means no size can pass.
# finger_gap: a guard's largest opening must stop the IEC 61032 test finger (IP2X), whose
# diameter and source live in the reference library (recipes/lib/refs, ip2x.finger).
MAX_FINGER_GAP = float(refs.get("ip2x.finger")["value"]["diameter"])  # mm, 12
GAP_PX = 0.1  # mm, raster step for the gap
# A guard tells the check where its opening is and what closes it up:
#   echo(stone_grille = [center x, center y, radius, z of the middle, setting, its value, "up" | "down"]);
GRILLE_ECHO = re.compile(
    r'ECHO: stone_grille = \[([-\d.e+]+), ([-\d.e+]+), ([-\d.e+]+), ([-\d.e+]+), "(\w+)", ([-\d.e+]+), "(up|down)"\]')
TEXT_ECHO = re.compile(r'ECHO: stone_text = \[([-\d.e+]+), "(\w+)", "(\w+)", ([-\d.e+]+)\]')


@dataclass
class Result:
    name: str
    ok: bool
    value: object = None
    detail: str = ""
    # default advice when no recipe parameter is known
    advice: str = ""
    # "up" or "down" when growing or shrinking a parameter helps
    direction: str = ""
    need: float | None = None
    measured: float | None = None
    # the setting the part itself names as the fix, and its value now (see TEXT_ECHO)
    param: str = ""
    at: float | None = None
    # flat ledges excluded from the wall reading (window sill, port rim, post face), mm
    steps: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _fmt(v: float, nd: int = 1) -> str:
    return f"{v:.{nd}f}"


def load_off(path) -> "trimesh.Trimesh":
    """Read an OFF file as written by OpenSCAD, keeping its shared vertices. Polygons with more
    than three corners (OpenSCAD passes polyhedron faces through untouched) become triangle fans."""
    import trimesh

    lines = [ln for ln in Path(path).read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    if not lines or not lines[0].startswith("OFF"):
        raise ValueError("not an OFF file")
    # counts live on the OFF header line when OpenSCAD writes it that way ("OFF 1244 2488 0"),
    # otherwise on the next line ("OFF" alone).
    counts = (lines[0].split() + lines[1].split())[1:3]
    nv, nf = (int(w) for w in counts)
    body = lines[1:] if lines[0].split()[1:3] else lines[2:]
    verts = np.array([ln.split()[:3] for ln in body[:nv]], dtype=float).reshape(nv, 3)
    tris = []
    for ln in body[nv:nv + nf]:
        w = ln.split()  # count, indices, then optional face color
        k = int(w[0])
        idx = [int(x) for x in w[1:1 + k]]
        tris.extend([idx[0], idx[j], idx[j + 1]] for j in range(1, k - 1))
    return trimesh.Trimesh(verts, np.array(tris, dtype=np.int64).reshape(-1, 3), process=False)


def _load(path: Path):
    import trimesh

    if Path(path).suffix.lower() == ".off":
        return load_off(path)

    # An OFF from OpenSCAD carries the exact shared vertices; merging by position would only add
    # errors. STL has no shared vertices, so it is merged.
    mesh = trimesh.load(str(path), force="mesh", process=Path(path).suffix.lower() != ".off")
    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError("no mesh in file")
    return mesh


def _first_hits(mesh, origins, dirs, multiple_hits=False):
    """First hit locations per ray. Returns (index_ray, locations, face_ids) or None."""
    try:
        loc, idx_ray, face_ids = mesh.ray.intersects_location(origins, dirs, multiple_hits=multiple_hits)
        return idx_ray, loc, face_ids
    except ImportError:
        return None


def thinnest_wall(mesh, samples: int = WALL_SAMPLES, seed: int = 0):
    """(thinnest wall mm, list of step mm).

    A wall run leaves the part on a face whose outward normal points along the ray. A step run
    crossed a cut's own ledge (window sill, port rim) and came back out of the face it started on,
    so its hit face's normal points back at the ray. That is topology, not a distance: a 0.4 mm
    plate's run is 0.4 mm and still a wall; a post boss's 1.7 mm face is a distinct surface and
    still reported as a wall. Steps are returned separately so nothing is silently hidden.
    """
    import trimesh

    try:
        pts, fi = trimesh.sample.sample_surface(mesh, samples, seed=seed)
    except TypeError:
        pts, fi = trimesh.sample.sample_surface(mesh, samples)
    normals = mesh.face_normals[fi]
    origins = pts - normals * 1e-4
    got = _first_hits(mesh, origins, -normals)
    if got is None:
        return None, []
    idx_ray, loc, hit_ids = got
    if len(idx_ray) == 0:
        return None, []
    dist = np.linalg.norm(loc - origins[idx_ray], axis=1)
    keep = dist > 5e-3  # drop self hits from float error
    dist, hit_ids = dist[keep], hit_ids[keep]
    # a wall run exits the part, so its hit face's outward normal opposes the start normal; a step
    # run crossed a cut's own ledge and came back out of the face it started on, so the hit face
    # looks the same way (dot > 0)
    is_step = np.einsum("ij,ij->i", normals[idx_ray][keep], mesh.face_normals[hit_ids]) > 0
    steps = sorted({round(float(d), 2) for d in dist[is_step]})
    walls = dist[~is_step]
    if len(walls) == 0:
        return None, steps
    return float(np.percentile(walls, WALL_PERCENTILE)), steps


def slice_area(mesh, z: float) -> tuple[float, float]:
    """(area, perimeter) of the mesh's cross section at height z. Each segment is turned so the
    face it came from lies on its right, which makes outlines run counterclockwise and holes
    clockwise, so the shoelace sum is the net area."""
    import trimesh

    seg, fi = trimesh.intersections.mesh_plane(mesh, [0, 0, 1], [0, 0, z], return_faces=True)
    if len(seg) == 0:
        return 0.0, 0.0
    a, b = seg[:, 0, :2], seg[:, 1, :2]
    d = b - a
    n = mesh.face_normals[fi][:, :2]
    flip = (d[:, 1] * n[:, 0] - d[:, 0] * n[:, 1]) < 0
    a, b = np.where(flip[:, None], b, a), np.where(flip[:, None], a, b)
    area = 0.5 * float(np.sum(a[:, 0] * b[:, 1] - b[:, 0] * a[:, 1]))
    return area, float(np.linalg.norm(d, axis=1).sum())


def bed_edge_inset(mesh, contact: float) -> float | None:
    """Mean inset of the bed edge, mm: (area of the slice at BED_EDGE_Z minus the bed contact
    area) over the slice perimeter. 0 for a straight wall, about 0.4 for a 0.4 mm chamfer."""
    zmin = float(mesh.bounds[0][2])
    area, per = slice_area(mesh, zmin + BED_EDGE_Z)
    if per <= 0:
        return None
    return (area - contact) / per


def slice_mask(mesh, z: float, x0: float, y0: float, n: int, px: float) -> np.ndarray:
    """n x n raster (rows along y) of the cross section at height z, cells of px from (x0, y0):
    True where the cell center is inside the part, by the crossings of each row (even-odd)."""
    import trimesh

    seg = trimesh.intersections.mesh_plane(mesh, [0, 0, 1], [0, 0, z])
    xs = x0 + (np.arange(n) + 0.5) * px
    ys = y0 + (np.arange(n) + 0.5) * px
    out = np.zeros((n, n), bool)
    if len(seg) == 0:
        return out
    ax, ay, bx, by = seg[:, 0, 0], seg[:, 0, 1], seg[:, 1, 0], seg[:, 1, 1]
    lo, hi = np.minimum(ay, by), np.maximum(ay, by)
    for i, y in enumerate(ys):
        m = (lo <= y) & (hi > y)
        if not m.any():
            continue
        x = np.sort(ax[m] + (y - ay[m]) / (by[m] - ay[m]) * (bx[m] - ax[m]))
        out[i] = np.searchsorted(x, xs) % 2 == 1
    return out


def largest_gap(mesh, cx: float, cy: float, r: float, z: float, px: float = GAP_PX) -> float:
    """Diameter of the biggest ball that passes the grille: twice the largest distance from an
    empty point of the slice at z, inside the opening circle, to the part or the circle."""
    from scipy import ndimage

    n = int(math.ceil(2 * r / px)) + 2
    x0, y0 = cx - n * px / 2, cy - n * px / 2
    solid = slice_mask(mesh, z, x0, y0, n, px)
    c = (np.arange(n) + 0.5) * px - n * px / 2
    inside = c[None, :] ** 2 + c[:, None] ** 2 < r * r
    empty = inside & ~solid
    if not empty.any():
        return 0.0
    return 2 * float(ndimage.distance_transform_edt(empty).max()) * px


def grille_results(mesh, log: str | None) -> list[Result]:
    out = []
    for m in GRILLE_ECHO.finditer(log or ""):
        cx, cy, r, z = (float(m[i]) for i in range(1, 5))
        gap = largest_gap(mesh, cx, cy, r, float(mesh.bounds[0][2]) + z)
        out.append(Result("finger_gap", gap <= MAX_FINGER_GAP, round(gap, 1),
                          f"largest opening {gap:.1f} mm (max {MAX_FINGER_GAP:.0f} mm, the test finger)",
                          advice="a finger fits through the grille; make the openings smaller",
                          direction=m[7], need=MAX_FINGER_GAP, measured=gap, param=m[5], at=float(m[6])))
    return out


def text_echoes(log: str | None) -> list[tuple[float, str, str, float]]:
    """(letter height, font, setting, its value) for each stone_text echo in an OpenSCAD log."""
    return [(float(m[1]), m[2], m[3], float(m[4])) for m in TEXT_ECHO.finditer(log or "")]


def text_results(log: str | None) -> list[Result]:
    """One text check for the thinnest lettering the part has, or none when it has no text."""
    worst = None
    for size, font, param, at in text_echoes(log):
        k = TEXT_STROKE.get(font, TEXT_STROKE["sans"])
        if worst is None or size * k < worst[0]:
            worst = (size * k, size, font, param, at, MIN_STROKE / k)
    if worst is None:
        return []
    stroke, size, font, param, at, need = worst
    return [Result("text", stroke >= MIN_STROKE - 1e-6, round(stroke, 2),
                   f"letter strokes {stroke:.2f} mm at {size:.1f} mm {font} (need {MIN_STROKE} mm, "
                   f"{need:.1f} mm letters)",
                   advice="the letters are too thin for a 0.4 mm nozzle; make them bigger",
                   direction="up", need=need, measured=size, param=param, at=at)]


def _hull_area(xy: np.ndarray) -> float:
    from scipy.spatial import ConvexHull, QhullError

    if len(xy) < 3:
        return 0.0
    try:
        return float(ConvexHull(xy).volume)
    except (QhullError, ValueError):
        return 0.0


def check_mesh(mesh, recipe=None, params=None, bed=None, log=None) -> list[Result]:
    """log: the OpenSCAD output of the build, which carries the stone_text echoes."""
    out: list[Result] = []
    bed = bed or config.DEFAULT_BED
    max_bodies = recipe.max_bodies if recipe else 1
    max_overhang = recipe.max_overhang if recipe else 0.05

    out.append(Result("loads", len(mesh.faces) > 0, len(mesh.faces), f"{len(mesh.faces)} faces",
                      advice="the STL has no faces; rebuild the part"))
    if len(mesh.faces) == 0:
        return out

    # the slicer pass needs nothing the other checks find, so it runs beside them; trimesh's
    # caches it reads are filled here first, so the thread only reads them
    from concurrent.futures import ThreadPoolExecutor

    from . import slicer

    mesh.bounds, mesh.triangles, mesh.faces
    with ThreadPoolExecutor(1) as pool:
        sliced = pool.submit(slicer.slice_mesh, mesh, bed=bed)
        return _check_rest(mesh, out, sliced, recipe, params, bed, log, max_bodies, max_overhang)


def _check_rest(mesh, out, sliced, recipe, params, bed, log, max_bodies, max_overhang) -> list[Result]:
    wt = bool(mesh.is_watertight)
    out.append(Result("watertight", wt, wt, "closed surface" if wt else "surface has holes",
                      advice="the surface has holes; go back to the default parameters"))

    # a hole through the part (a case window, a port) is a legitimate print feature: it changes the
    # surface's shape but does not mean the mesh is broken, so the window/port cuts must not FIX
    holes = (2 - mesh.euler_number) // 2 if wt else 0
    if holes > 0:
        out.append(Result("through_holes", True, holes, f"{holes} through holes (window/port cuts)"))

    from .clean import problems, slicer_view

    bad = problems(slicer_view(mesh.vertices, mesh.faces))
    out.append(Result("slicer", not bad, bad or "ok", "; ".join(bad) or "no non-manifold edges or zero-area faces",
                      advice="a slicer will report this mesh as broken; rebuild the part with stone build"))

    bodies = len(mesh.split(only_watertight=False))
    out.append(Result("bodies", bodies <= max_bodies, bodies,
                      f"{bodies} bodies (max {max_bodies})",
                      advice="the part is in separate pieces; make them touch or overlap"))

    vol = float(mesh.volume) if wt else float(abs(mesh.volume))
    out.append(Result("volume", vol > 0, round(vol, 1), f"{_fmt(vol)} mm3",
                      advice="the part has no volume; go back to the default parameters"))

    lo, hi = mesh.bounds
    ext = hi - lo
    fits = bool(all(ext[i] <= bed[i] + 1e-6 for i in range(3)))
    worst = max(ext[i] / bed[i] for i in range(3))
    out.append(Result("bed", fits, [round(float(e), 2) for e in ext],
                      f"{_fmt(ext[0])} x {_fmt(ext[1])} x {_fmt(ext[2])} mm on a "
                      f"{_fmt(bed[0], 0)} x {_fmt(bed[1], 0)} x {_fmt(bed[2], 0)} mm bed",
                      advice="the part is bigger than the bed; make it smaller",
                      direction="down", need=1.0, measured=float(worst)))

    zmin = float(lo[2])
    rest = abs(zmin) <= REST_TOL
    out.append(Result("resting", rest, round(zmin, 3), f"lowest point z = {zmin:.2f} mm",
                      advice=f"move the part so its lowest point is at z = 0 (now {zmin:.2f} mm)"))

    nz = mesh.face_normals[:, 2]
    tri_z = mesh.triangles[:, :, 2]
    areas = mesh.area_faces
    down = (nz < -0.99) & (tri_z.max(axis=1) <= zmin + CONTACT_TOL)
    contact = float(areas[down].sum())
    bbox_area = float(ext[0] * ext[1])
    need = min(200.0, 0.15 * bbox_area)
    ok = contact >= need
    hull = 0.0
    if not ok and 0.15 * bbox_area < 200.0:
        # small part: 30 percent of the footprint hull is enough
        hull = _hull_area(mesh.vertices[:, :2])
        ok = contact >= 0.3 * hull
    out.append(Result("first_layer", ok, round(contact, 1),
                      f"{_fmt(contact)} mm2 on the bed (need {_fmt(need)} mm2)",
                      advice="too little of the part touches the bed; give it a flat base",
                      direction="up", need=need, measured=contact))

    # recipe parts only: an STL from elsewhere gets its elephant-foot compensation in the slicer
    skip = recipe.skip.get("bed_edge") if recipe else "not a recipe part"
    inset = None if skip else bed_edge_inset(mesh, contact)
    if inset is None:
        out.append(Result("bed_edge", True, None, f"skipped ({skip or 'no slice above the bed'})"))
    else:
        out.append(Result("bed_edge", inset >= MIN_BED_EDGE, round(inset, 2),
                          f"bed edge inset {inset:.2f} mm (need {MIN_BED_EDGE} mm)",
                          advice="the first layer will flare past the wall (elephant foot); chamfer "
                                 "the bottom edge 0.4 mm, as soft_extrude and bed_chamfer do",
                          direction="up", need=MIN_BED_EDGE, measured=inset))

    out.extend(grille_results(mesh, log))
    # before min_wall: thin letters are thin walls too, and the text fix sizes both at once
    out.extend(text_results(log))

    wall, steps = thinnest_wall(mesh)
    need_wall = recipe.min_wall if recipe else MIN_WALL
    if wall is None:
        out.append(Result("min_wall", True, None, "skipped (no ray engine or no hits)"))
    else:
        step_txt = f"; steps {steps} mm" if steps else ""
        out.append(Result("min_wall", wall >= need_wall, round(wall, 2),
                          f"thinnest wall {wall:.2f} mm (need {need_wall} mm){step_txt}",
                          advice="a wall is too thin; make it thicker",
                          direction="up", need=need_wall, measured=wall, steps=steps))

    face_zmin = tri_z.min(axis=1)
    face_zmax = tri_z.max(axis=1)
    over = (nz < -OVERHANG_COS - 1e-3) & (face_zmin > zmin + BED_SKIP) & (face_zmax > zmin + CHAMFER_ZONE)
    total = float(areas.sum())
    frac = float(areas[over].sum()) / total if total > 0 else 0.0
    out.append(Result("overhang", frac <= max_overhang, round(frac, 4),
                      f"{frac * 100:.1f}% of the surface hangs past 45 deg "
                      f"(max {max_overhang * 100:.0f}%)",
                      advice="too much of the part hangs in the air; add a chamfer or flip it"))

    out.extend(layer_checks(mesh, recipe, bed, sliced.result()))

    if recipe is not None and recipe.dims:
        try:
            want = recipe.expected_dims(recipe.merged(params or {}))
        except (ValueError, TypeError, ZeroDivisionError, KeyError) as e:
            out.append(Result("dims", True, None, f"skipped ({e})"))
        else:
            tol = recipe.dims_tol
            axes = {"x": 0, "y": 1, "z": 2}
            bad = []
            for axis, w in want.items():
                got = float(ext[axes[axis]])
                if abs(got - w) > tol:
                    bad.append(f"{axis} {got:.1f} mm, expected {w:.1f} mm")
            detail = "; ".join(bad) if bad else "size matches the recipe"
            out.append(Result("dims", not bad, bad or "ok", detail,
                              advice="size does not match the recipe; go back to the defaults"))
    return out


def layer_checks(mesh, recipe=None, bed=None, rep=None) -> list[Result]:
    """What a slicer sees layer by layer (slicer.py, at a slicer's own resolution): pieces that
    start in the air, cross-sections that do not close, and how far the part can lean before it
    tips over."""
    from . import printable, slicer

    out = []
    rep = rep or slicer.slice_mesh(mesh, bed=bed)
    big = sorted((p for p in rep.problems if p.kind == "floating"), key=lambda p: -p.area)
    spots = "; ".join(f"{p.area:.1f} mm2 at {p.z:.1f} mm up (x {p.where[0]}, y {p.where[1]})" for p in big[:4])
    if not big:
        out.append(Result("islands", True, 0, "every layer stands on the one below"))
    elif recipe is not None and recipe.supports:
        out.append(Result("islands", True, len(big),
                          f"{len(big)} spots start in the air ({spots}): in the slicer, supports on, everywhere"))
    else:
        out.append(Result("islands", False, len(big), f"{len(big)} pieces start in the air: {spots}",
                          advice="a piece starts in mid-air and would print onto nothing; give it a "
                                 "45 degree chamfer from below or turn the part so it grows from the bed"))
    bad = [p for p in rep.problems if p.kind == "open"]
    ledges = [p for p in rep.problems if p.kind == "ledge"]
    note = f"{rep.layers} layers of {rep.layer} mm; {rep.dropped} mm2 too thin for a {rep.nozzle} mm nozzle"
    if ledges:
        note += f"; {len(ledges)} ledges may sag (worst {max(p.area for p in ledges):.1f} mm2 at {ledges[0].z:.1f} mm up)"
    out.append(Result("sliced", not bad, len(bad),
                      f"{len(bad)} layers do not close, first at {bad[0].z:.1f} mm up" if bad else note,
                      advice="a cross-section does not close, so the slicer guesses the inside; rebuild the part"))
    grid = printable.occupancy(mesh)
    if grid is None:
        out.append(Result("tipping", True, None, "skipped (no ray engine)"))
        return out
    angle = printable.tip_angle(mesh, grid)
    if angle is None:
        out.append(Result("tipping", True, None, "skipped (nothing on the bed)"))
    else:
        out.append(Result("tipping", angle >= printable.TIP_MIN, round(angle, 1),
                          f"leans {angle:.0f} deg before it tips (need {printable.TIP_MIN:.0f})",
                          advice="the part is top-heavy for what it stands on; widen its base",
                          direction="up", need=printable.TIP_MIN, measured=angle))
    return out


def check_stl(path, recipe=None, params=None, bed=None, log=None) -> list[Result]:
    path = Path(path)
    try:
        mesh = _load(path)
    except Exception as e:  # trimesh raises many types on bad files
        return [Result("loads", False, None, f"cannot read {path.name}: {type(e).__name__}",
                       advice="the STL is missing or broken; rebuild the part")]
    return check_mesh(mesh, recipe=recipe, params=params, bed=bed, log=log)


def passed(results: list[Result]) -> bool:
    return all(r.ok for r in results)


def measured_size(results: list[Result]) -> list[float] | None:
    for r in results:
        if r.name == "bed" and isinstance(r.value, list):
            return r.value
    return None


def format_results(results: list[Result], fix_line=None) -> list[str]:
    """One line per check: PASS, or FIX with the measured problem and one change.

    fix_line(result) may return the change text (for example "set h=1.2").
    """
    lines = []
    for r in results:
        if r.ok:
            lines.append(f"PASS {r.name}: {r.detail}")
        else:
            custom = fix_line(r) if fix_line else None
            lines.append(f"FIX: {r.name} {r.detail}; {custom or r.advice}")
    return lines
