"""stone strength: will the printed part hold its load, and what helps most if not.

The part is cut into cubes (fea.voxelize), skinned with solid walls over homogenized infill, held where the
person says and loaded on a small patch. Printed plastic is weaker between layers, so two checks run on every
cell: von Mises stress against the layer-plane strength, and tension and shear across layers against the
between-layer strength. Deflection at the load is checked against a sag limit. The safety factor is the
smallest margin.
Numbers come from recipes/lib/refs/materials.json; modeling choices are marked "assumption".
"""

from __future__ import annotations

import math
import re
import shlex
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from . import fea
from . import refs as reftool

G = 9.80665  # m/s^2, standard gravity (CGPM 1901 definition): a kg of load weighs this many N
LINE = 0.45  # mm, one wall line for a 0.4 mm nozzle (assumption: the usual slicer default line width)
NU = 0.35  # Poisson's ratio of printed plastic (assumption: typical of glassy thermoplastics; moves deflection a few %)
FINE = 2.0  # safety factor that counts as fine (assumption: no standard covers printed parts; 2 covers print scatter)
SAG = 0.05  # deflection limit as a share of the lever from the hold to the load, at least 1 mm (assumption: a hook
            # or bracket that moves more than about a twentieth of its reach looks and feels bent)
VOXELS, COARSE = 100_000, 20_000  # cells for the answer, and for the advice re-solves
REFINE, MOST = 300_000, 400_000  # cells when the loaded spot is under 3 cells thick, and the most voxels= takes
PATCH = 3.0  # mm, radius of the load and point-hold patch (assumption: a hand, a strap, a coat loop)
HOLE_D, HOLE_DEEP = 12.0, 2.0  # mm, the widest enclosed opening read as a screw or pin hole, and the shallowest
FACES = {"left": (0, 0), "right": (0, 1), "front": (1, 0), "back": (1, 1), "bottom": (2, 0), "top": (2, 1)}
DIRS = {"down": (2, -1), "up": (2, 1), "left": (0, -1), "right": (0, 1), "front": (1, -1), "back": (1, 1)}
RIGID = ("PLA", "PETG", "ABS", "ASA", "PC", "PA", "PLA-CF", "PETG-CF")
ASSUMPTIONS = [
    "Linear elastic, small deflection: past about a tenth of the lever the numbers run high.",
    f"Wall lines {LINE} mm wide; solid bottom and top layers are OrcaSlicer's K2 profile (refs slicer.k2_shells) at 0.2 mm, "
    "whatever the wall count.",
    "Infill is rho^2 as stiff and as strong as solid plastic (Gibson-Ashby, refs any.infill_exponent).",
    f"Poisson's ratio {NU}; shear across layers follows the between-layer stiffness, and layers slide apart at the "
    "between-layer strength over the square root of 3 (von Mises).",
    "Held places do not move at all; screws hold the whole hole wall.",
    "Peak stress is read on the faces of each cell. It skips cells that touch a held spot or lie within 2 cells of "
    "the load patch, where a hard hold or a pressed patch makes a local spike the part does not see.",
    f"Safety factor {FINE:g} counts as fine; the sag limit is {SAG:.0%} of the lever, at least 1 mm.",
]


@dataclass
class Props:
    name: str
    e_xy: float  # MPa
    e_z: float
    s_xy: float  # MPa, tensile strength in the layer plane
    s_z: float  # between layers
    exponent: float = 2.0
    ids: list[str] = field(default_factory=list)


def material(name: str) -> Props:
    p = reftool.props(name)
    keys = ("e_xy", "e_z", "tensile_xy", "tensile_z")
    ga = reftool.get("any.infill_exponent")
    return Props(name, *(float(p[k]["value"]) for k in keys), float(ga["value"]),
                 [p[k]["id"] for k in keys] + [ga["id"]])


@dataclass
class Case:
    load: float = 0.0  # N
    at: str = "tip"
    dir: tuple = (2, -1)  # (axis, sign)
    fixed: str = "bottom"
    material: str = ""
    infill: float = 15.0  # %
    walls: int = 2
    build: int = 2  # part axis that points up on the bed
    sag: float | None = None  # mm limit, None for SAG x lever
    voxels: int | None = None  # cells for the answer, None for VOXELS
    words: dict = field(default_factory=dict)  # as typed, to echo and rebuild the command
    file: str = ""  # the STL as typed, empty for the job's part

    def command(self, **change) -> str:
        w = {**self.words, **{k: str(v) for k, v in change.items()}}
        return " ".join(["stone strength"] + ([shlex.quote(self.file)] if self.file else [])
                        + [shlex.quote(f"{k}={v}") for k, v in w.items()])


def _number(text: str) -> float:
    return float(re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*", text).group(1))


def parse(items: list[str]) -> tuple[Case, Path | None, list[str]]:
    """Words like load=20N at=tip dir=down fixed=holes material=PETG infill=15 walls=2 orient=x, and an STL."""
    case, file, bad = Case(), None, []
    for it in items:
        if "=" not in it:
            if it.lower().endswith(".stl"):
                file, case.file = Path(it).expanduser().resolve(), it
            else:
                bad.append(f"{it}: use key=value, like load=20N")
            continue
        k, v = (s.strip() for s in it.split("=", 1))
        k = k.lower()
        try:
            if k in ("load", "force", "weight"):
                m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(n|kg|g|lb|lbs|kgf)?", v.lower())
                n = float(m.group(1)) * {"n": 1, None: 1, "kg": G, "kgf": G, "g": G / 1000, "lb": 4.44822, "lbs": 4.44822}[m.group(2)]
                case.load = n
            elif k == "at":
                case.at = v.lower()
                if not (case.at in ("tip", "top", "center") or case.at in FACES or len(v.split(",")) == 3):
                    raise ValueError
                if "," in v:
                    [_number(x) for x in v.split(",")]
            elif k == "dir":
                w = v.lower().replace("+", "")
                if w in DIRS:
                    case.dir = DIRS[w]
                elif w.lstrip("-") in ("x", "y", "z"):
                    case.dir = ("xyz".index(w[-1]), -1 if w.startswith("-") else 1)
                else:
                    raise ValueError
            elif k == "fixed":
                for part in v.lower().split("+"):
                    if not (part in FACES or part == "holes" or len([_number(x) for x in part.split(",")]) in (3, 6)):
                        raise ValueError
                case.fixed = v.lower()
            elif k == "material":
                case.material = reftool.strength_material(v) or ""
                if not case.material:
                    raise ValueError
            elif k == "infill":
                case.infill = _number(v.rstrip("%"))
                if not 0 <= case.infill <= 100:
                    raise ValueError
            elif k == "walls":
                case.walls = int(v)
                if not 1 <= case.walls <= 20:
                    raise ValueError
            elif k == "orient":
                w = v.lower()
                case.build = 2 if w in ("as-printed", "as_printed", "z", "flat") else {"x": 0, "y": 1}[w]
            elif k == "voxels":
                case.voxels = int(float(v))
                if not 5_000 <= case.voxels <= MOST:
                    raise ValueError
            elif k == "sag":
                case.sag = _number(v.lower().removesuffix("mm"))
                if case.sag <= 0:
                    raise ValueError
            else:
                bad.append(f"{k}: not a strength word (load at dir fixed material infill walls orient sag voxels)")
                continue
        except (ValueError, AttributeError, KeyError, TypeError):
            bad.append(f"{k}={v}: {HELP[k] if k in HELP else 'not understood'}")
            continue
        case.words[k] = v
    if case.load <= 0 and not any(b.startswith("load") for b in bad):
        bad.append("load: give the load, like load=20N or load=2kg")
    return case, file, bad


HELP = {"load": "a weight like 20N, 2kg, 500g or 5lb", "at": "tip, top, center, a face (bottom back front left right top) or x,y,z in mm",
        "dir": "down up left right front back, or an axis like -y", "fixed": "a face, holes, x,y,z, or a box x0,y0,z0,x1,y1,z1; join with +",
        "material": "one of " + " ".join(reftool.STRENGTH), "infill": "a percent, 0 to 100", "walls": "a count, 1 to 20",
        "orient": "as-printed, or the part axis that points up on the bed: x, y or z", "sag": "a deflection limit in mm",
        "voxels": "a cell count, 5000 to 400000"}


# geometry: where it is held and where the load goes


@dataclass
class Setup:
    grid: fea.Grid
    model: fea.Model
    wall: np.ndarray
    fixed: np.ndarray  # node ids
    patch: np.ndarray  # loaded node ids
    spot: np.ndarray  # mm
    force: np.ndarray  # (nn, 3) N
    lever: float  # mm from the hold to the load
    held: str  # words for the hold
    problem: str = ""  # why there is nothing to solve


def _surface(model: fea.Model) -> np.ndarray:
    return np.bincount(model.elem.ravel(), minlength=len(model.nodes)) < 8


def _face(model: fea.Model, name: str) -> np.ndarray:
    axis, side = FACES[name]
    x = model.coords[:, axis]
    edge = x.max() if side else x.min()
    return np.nonzero(np.abs(x - edge) < model.grid.pitch * 0.51)[0]


def hole_cells(grid: fea.Grid) -> np.ndarray:
    """Empty cells enclosed in a slice across any axis, no wider than HOLE_D and at least HOLE_DEEP deep: screw and
    pin holes, not engraving."""
    from scipy import ndimage

    out = np.zeros(grid.shape, dtype=bool)
    wide, deep = HOLE_D / grid.pitch + 1, max(1.0, HOLE_DEEP / grid.pitch - 0.5)
    for a in range(3):
        solid = np.moveaxis(grid.solid, a, 0)
        cav = np.array([ndimage.binary_fill_holes(s) for s in solid]) & ~solid
        for i in range(len(cav)):
            lab, _ = ndimage.label(cav[i])
            for k, box in enumerate(ndimage.find_objects(lab), 1):
                if max(s.stop - s.start for s in box) > wide:
                    cav[i][lab == k] = False
        lab, _ = ndimage.label(cav)
        for k, box in enumerate(ndimage.find_objects(lab), 1):
            if box[0].stop - box[0].start >= deep:
                np.moveaxis(out, a, 0)[box] |= lab[box] == k
    return out


def _holes(model: fea.Model) -> tuple[np.ndarray, str]:
    from scipy import ndimage

    g = model.grid
    holes = hole_cells(g)
    walls = ndimage.binary_dilation(holes) & g.solid
    cells = np.argwhere(walls)
    if not len(cells):
        return np.zeros(0, dtype=np.int64), ""
    lab, n = ndimage.label(holes)
    mid = [g.origin + (np.array(c) + 0.5) * g.pitch for c in ndimage.center_of_mass(holes, lab, range(1, n + 1))]
    words = f"the {n} hole{'s' * (n > 1)} at " + ", ".join("({:.0f}, {:.0f}, {:.0f})".format(*c) for c in mid[:6])
    return np.unique(model.full[tuple((cells[:, None, :] + fea.CORNERS[None]).reshape(-1, 3).T)]), words


def _near(model: fea.Model, point, radius: float) -> np.ndarray:
    """Surface nodes within radius of the surface point nearest to `point`."""
    surf = np.nonzero(_surface(model))[0]
    c = model.coords[surf]
    snap = c[np.argmin(np.linalg.norm(c - point, axis=1))]
    return surf[np.linalg.norm(c - snap, axis=1) <= radius]


def _one_side(model: fea.Model, nodes: np.ndarray, point) -> np.ndarray:
    """The nodes joined to the one nearest `point`, so a patch on a thin wall does not reach its far side."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree

    if not len(nodes):
        return nodes
    c = model.coords[nodes]
    i, j = cKDTree(c).query_pairs(1.01 * model.grid.pitch, output_type="ndarray").T
    lab = connected_components(coo_matrix((np.ones(len(i)), (i, j)), (len(c), len(c))), directed=False)[1]
    return nodes[lab == lab[np.argmin(np.linalg.norm(c - point, axis=1))]]


def held_nodes(model: fea.Model, spec: str) -> tuple[np.ndarray, str, list[str]]:
    """The held nodes, words for them, and the words of the spec that hold nothing."""
    found, words, empty = [], [], []
    for part in spec.split("+"):
        if part in FACES:
            found.append(_face(model, part))
            words.append(f"the {part} face")
        elif part == "holes":
            n, w = _holes(model)
            found.append(n)
            words.append(w)
        else:
            v = [float(s) for s in part.split(",")]
            if len(v) == 3:
                found.append(_near(model, v, max(PATCH, 2 * model.grid.pitch)))
            else:
                lo, hi = np.minimum(v[:3], v[3:]), np.maximum(v[:3], v[3:])
                c = model.coords
                found.append(np.nonzero(np.all((c >= lo - 1e-9) & (c <= hi + 1e-9), axis=1))[0])
            words.append(f"({part})")
        if not len(found[-1]):
            empty.append(part)
    return np.unique(np.concatenate(found)).astype(np.int64), " and ".join(words), empty


def load_spot(model: fea.Model, at: str, fixed: np.ndarray) -> np.ndarray:
    from scipy.spatial import cKDTree

    c = model.coords
    surf = np.nonzero(_surface(model))[0]
    if at == "tip":  # the far end, centered across it
        d, _ = cKDTree(c[fixed]).query(c[surf])
        end = surf[d >= d.max() - max(2.0, 2 * model.grid.pitch)]
        return c[end[np.argmin(np.linalg.norm(c[end] - c[end].mean(0), axis=1))]]
    if at == "top":
        top = surf[c[surf, 2] >= c[surf, 2].max() - 1e-6]
        mid = c[top, :2].mean(0)
        return c[top[np.argmin(np.linalg.norm(c[top, :2] - mid, axis=1))]]
    if at == "center":
        target = model.grid.centers().mean(0)
    elif at in FACES:
        face = _face(model, at)
        target = c[face].mean(0)
        return c[face[np.argmin(np.linalg.norm(c[face] - target, axis=1))]]
    else:
        target = np.array([float(s) for s in at.split(",")])
    return c[surf[np.argmin(np.linalg.norm(c[surf] - target, axis=1))]]


def pitch_for(mesh, voxels: int) -> float:
    """The cell that fills the part with about `voxels`, sized to go a whole number of times into its thinnest side."""
    pitch, side = (mesh.volume / voxels) ** (1 / 3), float((mesh.bounds[1] - mesh.bounds[0]).min())
    return side / max(1, round(side / pitch))


def _grown(model: fea.Model, fixed: np.ndarray, point, radius: float, mm: float) -> tuple[fea.Grid, int]:
    """The part `mm` thicker near a point, and the cells of padding; nothing grows onto a held node."""
    from scipy import ndimage

    g = model.grid
    steps = max(1, round(mm / g.pitch))
    pad = steps + 1
    solid = np.pad(g.solid, pad)
    big = fea.Grid(np.ones(solid.shape, bool), g.pitch, g.origin - pad * g.pitch)
    free = (np.linalg.norm(big.centers() - point, axis=1) <= radius).reshape(solid.shape)
    held = model.nodes[fixed] + pad
    for c in fea.CORNERS:
        free[tuple((held - c).T)] = False
    return fea.Grid(ndimage.binary_dilation(solid, iterations=steps, mask=free | solid), g.pitch, big.origin), pad


def setup(mesh, case: Case, props: Props, voxels: int | None = None, grow: tuple | None = None) -> Setup:
    """The voxel model of the part under the case. grow=(point, radius, mm) thickens it near a point; the hold and
    the load stay where they are on the part as it is."""
    from scipy import ndimage

    shells = reftool.get("slicer.k2_shells")["value"]
    caps = (0.2 * shells["bottom_shell_layers"], 0.2 * shells["top_shell_layers"])

    def build(grid: fea.Grid) -> tuple[np.ndarray, fea.Model]:
        wall, weight = fea.shell(grid, case.walls * LINE, case.infill / 100, props.exponent, caps, case.build)
        return wall, fea.Model(grid, weight, fea.stiffness(props.e_xy, props.e_z, NU, case.build))

    wall, model = build(fea.voxelize(mesh, pitch_for(mesh, voxels or VOXELS)))
    grid = model.grid
    fixed, held, empty = held_nodes(model, case.fixed)
    spot = load_spot(model, case.at, fixed) if len(fixed) else model.coords[0]
    patch = _near(model, spot, max(PATCH, 2 * grid.pitch))
    patch = _one_side(model, patch[~np.isin(patch, fixed)], spot)
    problem = ""
    if empty:
        problem = f"found nothing to hold at fixed={'+'.join(empty)}"
    elif not len(patch):
        problem = f"the load at {case.at} sits on the held place, so nothing bends; pick another at= or fixed="
    else:
        lab, _ = ndimage.label(grid.solid)
        body = np.bincount(model.elem[lab[grid.solid] == lab[grid.solid][np.isin(model.elem, patch).any(1)][0]].ravel(),
                           minlength=len(model.nodes)) > 0  # nodes of the piece the load is on
        x = model.coords[fixed[body[fixed]]]
        if len(x) < 3 or np.linalg.matrix_rank(x - x[0], tol=grid.pitch / 2) < 2:
            problem = f"fixed={case.fixed} does not keep the loaded piece from turning; hold a face, the holes or a bigger box"
    if grow:
        grid, pad = _grown(model, fixed, *grow)
        old = model
        wall, model = build(grid)
        ids = model.full[tuple((old.nodes + pad).T)]
        fixed, patch = ids[fixed], ids[patch]
    force = np.zeros((len(model.nodes), 3))
    axis, sign = case.dir
    if len(patch):
        force[patch, axis] = sign * case.load / len(patch)
    lever = float(np.min(np.linalg.norm(model.coords[fixed] - spot, axis=1))) if len(fixed) else 0.0
    return Setup(grid, model, wall, fixed, patch, spot, force, lever, held, problem)


# solve and judge


@dataclass
class Result:
    sf: float
    mode: str  # "layers" (between layers), "along" (in the layer plane) or "sag"
    worst: np.ndarray  # mm, the cell nearest to breaking
    deflection: float  # mm at the load, along the load
    deflection_max: float
    limit: float  # mm sag limit
    ratio: np.ndarray  # per cell: stress over strength, worst of the two checks
    stress: dict
    info: dict
    thin: bool = False  # the loaded spot is under 3 cells across, so its bending stress reads low


def shown(sf: float) -> float:
    """A safety factor as it prints and as it is judged: rounded down, so 1.96 is never 2.0."""
    return math.floor(min(sf, 99.0) * 10 + 1e-6) / 10


def thin_cells(grid: fea.Grid) -> np.ndarray:
    """Solid cells in a wall only 1 or 2 cells thick."""
    from scipy import ndimage

    d = ndimage.distance_transform_edt(np.pad(grid.solid, 1))[1:-1, 1:-1, 1:-1]
    return (ndimage.maximum_filter(d, size=5) < 1.5)[grid.solid]


def judge(st: Setup, props: Props, case: Case, u: np.ndarray, info: dict) -> Result:
    from scipy.spatial import cKDTree

    s = st.model.face_stress(u)
    vm = fea.von_mises(s).max(1)
    slide = np.delete(s[..., 3:], case.build, axis=2)  # the two shears in the layer plane's own direction
    # tension across layers with the shear that slides them; layers press together fine
    across = np.sqrt(np.maximum(s[..., case.build], 0.0) ** 2 + 3 * (slide ** 2).sum(2)).max(1)
    r_along, r_layers = vm / props.s_xy, across / props.s_z
    mark = np.zeros(len(st.model.nodes), dtype=bool)
    mark[st.fixed] = True
    near = cKDTree(st.model.coords[st.patch]).query(st.grid.centers())[0] if len(st.patch) else np.inf
    away = ~mark[st.model.elem].any(1) & (near > 2 * st.grid.pitch)
    if not away.any():
        away[:] = True
    ratio = np.where(away, np.maximum(r_along, r_layers), 0.0)
    axis, sign = case.dir
    defl = float(sign * u[st.patch, axis].mean()) if len(st.patch) else 0.0
    limit = case.sag if case.sag else max(1.0, SAG * st.lever)
    i = int(np.argmax(ratio))
    checks = {"layers": r_layers[i] if away[i] else 0.0, "along": r_along[i] if away[i] else 0.0, "sag": abs(defl) / limit}
    mode = max(checks, key=checks.get)
    sf = 1 / max(checks[mode], 1e-12)
    vm_away = vm[away]
    stress = {"peak_mpa": round(float(vm_away.max()), 2), "p995_mpa": round(float(np.percentile(vm_away, 99.5)), 2),
              "smoothed_max_mpa": round(float(fea.smoothed(st.grid, vm)[away].max()), 2),
              "across_layers_mpa": round(float(across[away].max()), 2)}
    thin = bool((thin_cells(st.grid) & (ratio >= 0.5 * ratio.max())).any())
    return Result(sf, mode, st.grid.centers()[i], defl, float(np.linalg.norm(u, axis=1).max()), limit, ratio, stress, info, thin)


def solve(mesh, case: Case, props: Props, voxels: int | None = None, grow=None) -> tuple[Setup, Result | None]:
    """The part under the case; no result when st.problem says why not."""
    st = setup(mesh, case, props, voxels, grow)
    if st.problem:
        return st, None
    t = time.time()
    u, info = st.model.solve(st.fixed, st.force)
    info.update(voxels=int(st.grid.solid.sum()), pitch_mm=round(st.grid.pitch, 3), seconds=round(time.time() - t, 1))
    if not info["residual"] < 1e-5:  # a loose piece or a hinge; also catches a nan
        st.problem = "the model did not settle (a loose piece, or one joined only along an edge)"
        return st, None
    return st, judge(st, props, case, u, info)


def advise(mesh, case: Case, props: Props, st: Setup, res: Result) -> list[dict]:
    """Single changes ranked by the safety factor they reach. Geometry changes re-solve on a coarse grid and
    scale this answer by the coarse ratio; a material change keeps the stress (force loads) and swaps strengths."""
    out = []
    for name in RIGID:
        if name != props.name:
            p = material(name)
            out.append({"change": f"material={name}", "words": f"print it in {name}", "kind": "material",
                        "sf": min(_strength_sf(res, p), res.limit / max(abs(res.deflection) * props.e_xy / p.e_xy, 1e-12))})
    out = sorted(out, key=lambda a: -a["sf"])[:1]
    coarse = min(COARSE, VOXELS)
    cst, base = solve(mesh, case, props, coarse)
    if base is None:  # the hold is lost on the coarse grid
        return out
    trials = []
    if case.walls + 2 <= 20:
        trials.append((f"walls={case.walls + 2}", f"{case.walls + 2} walls", replace(case, walls=case.walls + 2), None, "walls"))
    for b in range(3):
        if b != case.build:
            trials.append((f"orient={'xyz'[b]}", f"rotate it so its {'xyz'[b]} axis points up on the bed",
                           replace(case, build=b), None, "orient"))
    h = cst.grid.pitch
    trials.append(("", "make it about {:.1f} mm thicker near ({:.0f}, {:.0f}, {:.0f})".format(max(1, round(1 / h)) * h, *res.worst),
                   case, (res.worst, 10.0, 1.0), "thicker"))
    for change, words, c, grow, kind in trials:
        r = solve(mesh, c, props, coarse, grow)[1]
        if r:
            out.append({"change": change, "words": words, "sf": r.sf * res.sf / base.sf, "kind": kind})
    return sorted(out, key=lambda a: -a["sf"])


def _strength_sf(res: Result, p: Props) -> float:
    """Safety factor against breaking in material p, from this stress field."""
    s = res.stress
    return 1 / max(s["peak_mpa"] / p.s_xy, s["across_layers_mpa"] / p.s_z, 1e-12)


# report


def _where(st: Setup, res: Result, case: Case) -> str:
    """Height on the bed of the worst spot and what it is near."""
    lo = st.grid.origin[case.build]
    h = res.worst[case.build] - lo
    from_hold = float(np.min(np.linalg.norm(st.model.coords[st.fixed] - res.worst, axis=1)))
    near = "near where it is held" if from_hold < 0.3 * max(st.lever, 1) else (
        "near the load" if np.linalg.norm(res.worst - st.spot) < 0.3 * max(st.lever, 1) else "between the hold and the load")
    return f"{'xyz'[case.build]} = {h:.0f} mm up from the bed, {near}"


def verdict(st: Setup, res: Result, case: Case, props: Props) -> list[str]:
    sf = shown(res.sf)
    word = "fine" if sf >= FINE else ("holds, with little margin" if sf >= 1 else "fails")
    if res.thin and sf >= 1:
        word = "not sure, the loaded spot is under 3 cells thick in this model and may be weaker"
    how = {"layers": f"breaks between layers at {_where(st, res, case)}",
           "along": f"breaks along the layers at {_where(st, res, case)}",
           "sag": f"bends too far: {abs(res.deflection):.1f} mm, limit {res.limit:.1f} mm"}[res.mode]
    s = res.stress
    return [f"Safety factor {sf:.1f}: {word} ({how})." if sf < FINE else f"Safety factor {sf:.1f}: {word} (weakest: {how}).",
            f"Deflection {abs(res.deflection):.2f} mm at the {case.at} (limit {res.limit:.1f} mm).",
            f"Stress: peak {s['peak_mpa']:.1f} MPa (99.5th percentile {s['p995_mpa']:.1f}, smoothed max {s['smoothed_max_mpa']:.1f}),"
            f" {s['across_layers_mpa']:.1f} MPa pulling or sliding layers apart; {props.name} holds {props.s_xy:g} along, {props.s_z:g} between layers."]


def report(job, items: list[str], out, plan_material: str = "") -> None:
    """stone strength: fill `out` (a cli.Out) with the verdict lines and one NEXT."""
    import trimesh

    from .job import write_json

    case, file, bad = parse(items)
    usage = "stone strength load=20N at=tip dir=down fixed=bottom"
    if bad:
        out.fix("; ".join(bad))
        out.next = usage
        return
    f = file or job.build_dir / "part.stl"
    if not f.is_file():
        out.fix(f"no file at {f}" if file else "no built part yet; build first or name an STL file")
        out.next = "stone build" if not file else usage
        return
    own = job.exists() and f.resolve() == (job.build_dir / "part.stl").resolve()  # the job's part, not another file
    pick = reftool.strength_material(plan_material) if own else ""
    if own and plan_material and not pick and not case.material:
        out.fix(f"no strength data for {plan_material}, the job's filament; name the nearest with material=")
        out.next = case.command(material="PLA")
        return
    case.material = case.material or pick or "PLA"
    props = material(case.material)
    mesh = trimesh.load(f, force="mesh")
    if not mesh.is_watertight or mesh.volume <= 0:
        out.fix(f"{f.name} is not a closed shape, so it has no inside to load; repair it first")
        out.next = "stone build" if own else usage
        return
    st, res = solve(mesh, case, props, case.voxels)
    if res and res.thin and not case.voxels:
        st, res = solve(mesh, case, props, REFINE)
    if res is None:
        out.fix(st.problem)
        out.next = (f"ask the person: what holds the part still ({HELP['fixed']}), and where does the load go? "
                    f"Then: {usage}")
        return
    advice = advise(mesh, case, props, st, res)
    bd = job.build_dir if own else f.parent
    bd.mkdir(parents=True, exist_ok=True)
    axis, sign = case.dir
    write_json(bd / "strength.json", {
        "file": str(f),
        "inputs": {"load_n": round(case.load, 3), "at": case.at, "at_mm": [round(float(v), 2) for v in st.spot],
                   "dir": ("-" if sign < 0 else "+") + "xyz"[axis], "fixed": case.fixed, "material": props.name,
                   "infill_pct": case.infill, "walls": case.walls, "build_axis": "xyz"[case.build], "words": case.words},
        "safety_factor": round(res.sf, 2), "thin": res.thin, "fails_by": res.mode, "worst_mm": [round(float(v), 2) for v in res.worst],
        "deflection_mm": round(abs(res.deflection), 3), "deflection_max_mm": round(res.deflection_max, 3),
        "sag_limit_mm": round(res.limit, 2), "lever_mm": round(st.lever, 1), "stress": res.stress,
        "material": {"e_xy": props.e_xy, "e_z": props.e_z, "s_xy": props.s_xy, "s_z": props.s_z, "refs": props.ids},
        "advice": [{k: (round(v, 2) if k == "sf" else v) for k, v in a.items()} for a in advice],
        "model": res.info, "assumptions": ASSUMPTIONS})
    size = mesh.bounds[1] - mesh.bounds[0]
    up = "as printed" if case.build == 2 else f"{'xyz'[case.build]} axis up on the bed"
    out.add(f"Part: {f.name}, {size[0]:.0f} x {size[1]:.0f} x {size[2]:.0f} mm, {props.name}, {case.walls} walls, "
            f"{case.infill:g}% infill, {up}.",
            f"Load: {case.load:.1f} N ({case.load / G:.2f} kg) at the {case.at} ({', '.join(f'{v:.0f}' for v in st.spot)}) "
            f"toward {'-' if sign < 0 else '+'}{'xyz'[axis]}; held at {st.held}.")
    out.add(*verdict(st, res, case, props))
    better = [a for a in advice if a["sf"] > res.sf * 1.05][:4]
    if better:
        out.add("What helps most: " + "; ".join(f"{a['words']} ({shown(a['sf'])})" for a in better) + ".")
    changed = [w for w, on in ((f"{case.walls} walls", case.walls != Case.walls), (f"{case.infill:g}% infill", case.infill != Case.infill),
                               (props.name, props.name != (pick or "PLA")),
                               (f"its {'xyz'[case.build]} axis up on the bed", case.build != 2)) if on]
    if changed:
        out.add("This holds only for a print with " + ", ".join(changed) + "; tell the person.")
    i = res.info
    out.add(f"Model: {i['voxels']:,} voxels of {i['pitch_mm']} mm, solved in {i['seconds']:.0f} s; linear, untested by a real "
            "break; assumptions in strength.json.")
    sf = shown(res.sf)
    out.result = f"strength: safety factor {sf} at {case.load:.0f} N"
    nxt = (job.status().get("next") or "stone status") if own else "none, the part holds"
    setting = next((a for a in better if a["kind"] != "thicker" and shown(a["sf"]) >= FINE), None)
    if res.thin and sf >= 1:
        out.next = case.command(voxels=MOST) if (case.voxels or 0) < MOST else (
            f"ask the person: the loaded spot is too thin for this model to judge at {case.load:.0f} N; "
            "thicken it, or test a print?")
    elif sf >= FINE and changed:
        out.next = (f"ask the person: it holds {case.load:.0f} N only printed with {', '.join(changed)}; will you slice it that way?"
                    + (f" Then: stone note {shlex.quote('print with ' + ', '.join(changed) + f': holds {case.load:.0f} N')}" if own else ""))
    elif sf >= FINE:
        out.next = nxt
    elif setting:
        out.next = case.command(**dict([setting["change"].split("=", 1)]))
    else:
        top = better[0]["words"] if better else "make it thicker"
        out.next = (f"ask the person: at {case.load:.0f} N it {'fails' if sf < 1 else 'holds with little margin'} "
                    f"(safety factor {sf}, {FINE:g} is fine); {top}, or a lighter load?")
