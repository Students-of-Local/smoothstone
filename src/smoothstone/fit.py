"""stone fit: what a part's mating features print at, and whether they fit what they mate with.

A part that takes a screw, a peg, a bearing or a lid fits only if its printed size is right, and
FDM prints miss the model in known ways: a round hole is a polygon whose flats sit inside the
modeled circle (exact geometry, from the side count OpenSCAD's $fn, $fa and $fs give), holes print
small, outer sizes print close to true, the first layer squashes out, and some materials shrink.
Every number comes from recipes/lib/refs/fit.json with its source, or from this printer's own
numbers under [fit] in ~/.config/smoothstone/stone.toml.

The round features come from the mesh: it is cut across each axis with slicer.py's own
cross-section, each closed loop is followed by the mesh edges it crosses, straight runs merge into
the polygon's sides, and a loop that is a regular polygon is a hole or a peg.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import config
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


# this printer's numbers

@dataclass
class Printer:
    hole_side: float  # mm per side a hole prints small
    outer_side: float  # mm per side an outer size prints large (negative: small)
    slide: float  # per side, the tightest coupon hole the peg slides in
    band: float  # plus or minus on a predicted size
    calibrated: bool = False
    model: str | None = None
    material: str | None = None  # what the coupon was printed in
    cites: list[str] = field(default_factory=list)

    @property
    def shift(self) -> float:
        """How much looser this printer needs every fit than a typical one."""
        return self.slide - float(val("fit.slide_ref"))


def printer_model(job_root: Path | None) -> str | None:
    try:  # the printer profiles (track D), when present
        from . import printers  # type: ignore

        cur = printers.current(job_root)
        if isinstance(cur, dict) and cur.get("id"):
            return str(cur["id"])
    except Exception:
        pass
    raw = config._toml(job_root).get("printer")
    m = raw.get("model") if isinstance(raw, dict) else None
    return str(m) if m else None


def _stored(job_root: Path | None, model: str | None) -> dict:
    raw = config._toml(job_root).get("fit")
    if not isinstance(raw, dict):
        return {}
    if model and isinstance(raw.get(model), dict):
        return raw[model]
    return {k: v for k, v in raw.items() if not isinstance(v, dict)}


def printer(job_root: Path | None = None) -> Printer:
    model = printer_model(job_root)
    got = _stored(job_root, model)
    typical = Printer(float(val("fit.hole_error")) / 2, float(val("fit.outer_error")), float(val("fit.slide_ref")),
                      float(val("fit.accuracy")), model=model,
                      cites=[cite("fit.hole_error"), cite("fit.accuracy")])
    if not isinstance(got.get("slide"), (int, float)):
        return typical
    return Printer(float(got.get("hole_side", typical.hole_side)), float(got.get("outer_side", typical.outer_side)),
                   float(got["slide"]), CALIBRATED_BAND, True, model, got.get("material"),
                   ["this printer's coupon" + (f", {got['date']}" if got.get("date") else "")])


def shrink(material: str | None) -> tuple[float, str | None]:
    """XY shrink as a fraction, and its cite (None: no sourced value, 0 assumed)."""
    key = SHRINK.get((material or "PLA").upper())
    if not key:
        return 0.0, None
    e = lib()[f"fit.shrink.{key}"]
    return float(e["value"]) / 100, e["cite"]


def printed_hole(d: float, n: int, pr: Printer, s: float) -> float:
    return inscribed(d, n) * (1 - s) - 2 * pr.hole_side


def printed_peg(d: float, pr: Printer, s: float) -> float:
    return d * (1 - s) + 2 * pr.outer_side


def model_hole_for(target: float, n: int, pr: Printer, s: float) -> float:
    """The modeled diameter that prints a hole at target, to the nearest STEP."""
    raw = (target + 2 * pr.hole_side) / (math.cos(math.pi / n) * (1 - s))
    return round(round(raw / STEP) * STEP, 2)


# what a feature fits

CLASSES = ("press", "snug", "slide", "loose")


def band(cls: str, pr: Printer, material: str | None) -> tuple[float, float]:
    """Per side modeled clearance this fit takes on this printer: the class's band moved by how far
    this printer's tightest sliding peg sits from a typical printer's."""
    lo, hi = val("fit.class.tpu") if (material or "").upper() == "TPU" else val(f"fit.class.{cls}")
    return lo + pr.shift, hi + pr.shift


def verdict(c: float, b: tuple[float, float]) -> str:
    if c < b[0] - 1e-6:
        return "tight"
    if c > b[1] + 1e-6:
        return "loose"
    return "fits"


def target(b: tuple[float, float]) -> float:
    return round(round((b[0] + b[1]) / 2 / STEP) * STEP, 2)


def iso273(printed: float) -> tuple[str, dict] | None:
    """The metric screw a hole that prints at this size is most likely for: the one whose ISO 273
    fine to coarse range is nearest, within 0.5 mm. A guess only; a screw the recipe or the request
    names, or the one recorded on the job's first stone fit, comes first (screw_for)."""
    best, gap = None, 0.5 + 1e-9
    for k, e in lib().items():
        if k.startswith("iso273."):
            v = e["value"]
            g = max(v["fine"] - printed, printed - v["coarse"], 0.0)
            if g < gap:
                best, gap = (k.split(".", 1)[1].upper(), v), g
    return best


def iso_row(size: str | None) -> dict | None:
    return lib().get(f"iso273.{size.lower()}", {}).get("value") if size else None


def request_screw(text: str) -> str | None:
    """The one metric screw the request names ("two M2.5 screw holes"), when it names exactly one."""
    sizes = {f"M{m}" for m in re.findall(r"\bM(\d+(?:\.\d)?)\b", text or "", re.I)}
    sizes = {s for s in sizes if iso_row(s)}
    return sizes.pop() if len(sizes) == 1 else None


def screw_size(help_text: str) -> str | None:
    """The screw a setting names for its holes ("screw size, M (4 = M4)" names none by itself)."""
    m = re.search(r"\bfor (?:an? )?M(\d+(?:\.\d)?) screw", help_text or "")
    return f"M{m.group(1)}" if m else None


@dataclass
class Line:
    text: str
    verdict: str = ""  # fits | tight | loose | "" (size only)
    param: str | None = None
    value: float | None = None


def screw_line(what: str, d: float, n: int, pr: Printer, s: float, size: str, row: dict,
               param: str | None) -> Line:
    p = printed_hole(d, n, pr, s)
    v = "tight" if p < row["fine"] - 0.02 else ("loose" if p > row["coarse"] + 0.02 else "fits")
    text = (f"{what}: prints {num(p)} mm; {size} screw takes {num(row['fine'], 1)} to {num(row['coarse'], 1)} mm "
            f"(ISO 273): {v}")
    if v == "fits":
        return Line(text, v)
    new = model_hole_for(row["medium"], n, pr, s)
    how = f"set {param}={new:g}" if param else f"model it at {new:g} mm or drill it to {num(row['medium'], 1)} mm"
    return Line(f"{text}. Change: {how}, prints {num(printed_hole(new, n, pr, s))} mm "
                f"(ISO 273 medium for {size}: {num(row['medium'], 1)} mm)", v, param, new)


def bearing_line(f: Feature, pr: Printer, s: float, material: str | None) -> Line | None:
    b = val("bearing.608")
    if f.kind == "hole" and abs(f.size - b["outside"]) <= 0.8:
        c, what = (f.size - b["outside"]) / 2, f"608 bearing seat ({num(b['outside'], 0)} mm)"
    elif f.kind == "peg" and abs(f.size - b["bore"]) <= 0.4:
        c, what = (b["bore"] - f.size) / 2, f"608 bearing bore ({num(b['bore'], 0)} mm)"
    else:
        return None
    bd = band("press", pr, material)
    v = verdict(c, bd)
    text = f"{what}: {num(c)} mm per side, a press takes {num(bd[0])} to {num(bd[1])}: {v}"
    if v != "fits":
        t = target(bd)
        new = b["outside"] + 2 * t if f.kind == "hole" else b["bore"] - 2 * t
        if f.kind == "hole":
            new = new / math.cos(math.pi / f.n)
        text += f". Change: model it at {num(new)} mm"
    return Line(text, v)


# recipe parameters

def param_kind(p) -> str | None:
    """What a recipe setting means for fit: press, clearance, screw (size M), hole or None."""
    words = f"{p.name} {p.help}".lower()
    if p.type not in ("number", "int"):
        return None
    if re.search(r"\bpress\b|smaller than the shaft", words):
        return "press"
    if re.search(r"room per side|gap between|\bclearance\b|^fit\b", words) and (p.unit == "mm" or "gap" in words):
        return "clearance"
    if re.search(r"screw size, m", words):
        return "screw"
    if p.unit == "mm" and re.search(r"diameter|\bbore\b", words) and re.search(r"hole|\bbore\b|shaft", words):
        return "hole"
    return None


def intended(p, summary: str = "") -> str:
    words = f"{p.name} {p.help}".lower()
    if re.search(r"\bpress\b|smaller than", words):
        return "press"
    if re.search(r"\blid\b|\bcap\b", words):
        return "snug"
    return "slide"


def recipe_lines(r, params: dict, feats: list[Feature], pr: Printer, s: float, material: str | None,
                 screw: str | None = None, known: dict | None = None) -> tuple[list[Line], set]:
    """One line per fit setting, and the features those settings made (so they are not listed twice).
    screw is the one the recipe or request names; known holds the screws guessed on an earlier run,
    by setting, and gets this run's guesses: the guess must not follow the size stone's fix changes."""
    known = {} if known is None else known
    out: list[Line] = []
    used: set[int] = set()
    n_default = int(params.get("quality") or 0)
    for p in r.params:
        kind = param_kind(p)
        v = params.get(p.name)
        if kind is None or not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        v = float(v)
        if kind in ("hole", "screw") and v <= 0:
            continue  # 0 = none, or sized by the recipe from something else
        if kind in ("press", "clearance"):
            cls = "press" if kind == "press" else intended(p, r.summary)
            c = -v if kind == "press" else v
            bd = band(cls, pr, material)
            vd = verdict(c, bd)
            text = f"{p.name}={v:g} ({p.help}): {num(c)} mm per side, {cls} takes {num(bd[0])} to {num(bd[1])}: {vd}"
            if vd != "fits":
                t = target(bd)
                new = -t if kind == "press" else t
                if p.min is not None:
                    new = max(new, p.min)
                if p.max is not None:
                    new = min(new, p.max)
                out.append(Line(f"{text}. Change: set {p.name}={new:g}", vd, p.name, new))
            else:
                out.append(Line(text, vd))
            continue
        if kind == "screw":
            continue  # its holes are read from the mesh below, with the screw it names
        match = [i for i, f in enumerate(feats) if f.kind == "hole" and abs(f.d - v) <= 0.05]
        used.update(match)
        n = feats[match[0]].n if match else (n_default or fragments(v / 2))
        count = sum(feats[i].count for i in match)
        what = f"{p.name}={v:g}" + (f", {count} hole{'s' if count != 1 else ''}" if count else "") + f", {n} sides"
        if re.search(r"shaft", f"{p.help}".lower()):
            shaft = math.floor(v * 2 + 1e-6) / 2
            c = (inscribed(v, n) - shaft) / 2
            bd = band("snug", pr, material)
            vd = verdict(c, bd)
            text = f"{what}: on a {shaft:g} mm shaft {num(c)} mm per side, snug takes {num(bd[0])} to {num(bd[1])}: {vd}"
            if vd != "fits":
                new = round(round((shaft + 2 * target(bd)) / math.cos(math.pi / n) / STEP) * STEP, 2)
                out.append(Line(f"{text}. Change: set {p.name}={new:g}", vd, p.name, new))
            else:
                out.append(Line(text, vd))
            continue
        size = next((x for x in (screw_size(p.help), screw, known.get(p.name))
                     if iso_row(x) and float(x[1:]) - 1 <= v <= iso_row(x)["coarse"] + 1.5), None)
        row = iso_row(size)
        if row is None:
            got = iso273(printed_hole(v, n, pr, s))
            if got:
                size, row = got
                known[p.name] = size
        if row is None:
            out.append(Line(f"{what}: prints {num(printed_hole(v, n, pr, s))} mm"))
            continue
        out.append(screw_line(what, v, n, pr, s, size, row, p.name))
    return out, used


def feature_line(f: Feature, pr: Printer, s: float, material: str | None, screw: str | None = None) -> Line:
    many = f"{f.count} {f.kind}s" if f.count > 1 else f"{f.kind}"
    side = " teardrop" if f.shape == "teardrop" else ("" if f.axis == "z" else " on its side")
    what = f"{many} {num(f.d)} mm, {f.n} sides, {num(f.depth, 1)} mm deep{side}"
    b = bearing_line(f, pr, s, material)
    if b:
        b.text = f"{what}: {b.text}"
        return b
    if f.kind == "hole":
        got = None
        if screw:
            row = lib().get(f"iso273.{screw.lower()}", {}).get("value")
            if row and float(screw[1:]) <= f.d + 0.05 <= row["coarse"] + 1.0:
                got = (screw, row)
        if got:
            return screw_line(what, f.d, f.n, pr, s, got[0], got[1], None)
        p = printed_hole(f.d, f.n, pr, s)
        text = f"{what}: prints {num(p)} mm"
        got = iso273(p)
        if got:  # nothing says a screw goes here: what it would mean for one, with no change asked
            size, row = got
            v = "tight" if p < row["fine"] - 0.02 else ("loose" if p > row["coarse"] + 0.02 else "fits")
            text += f"; if it is for an {size} screw: {v} (ISO 273 takes {num(row['fine'], 1)} to {num(row['coarse'], 1)} mm)"
        return Line(text)
    return Line(f"{what}: prints {num(printed_peg(f.d, pr, s))} mm")


# the command

def _out():
    from .cli import Out

    return Out


def part_file(job) -> Path | None:
    for name in ("part.off", "part.stl"):
        f = job.build_dir / name
        if f.is_file():
            return f
    return None


def report(job, path: Path | None = None) -> tuple[list[str], list[Line], dict]:
    """The fit lines for the job's part (or any STL): what each feature prints at and what it fits."""
    from . import recipes as rc
    from .job import read_json

    r, params, request = None, {}, ""
    if path is None:
        path = part_file(job)
        plan = job.plan() or {}
        r = rc.load(plan["recipe"]) if plan.get("recipe") else None
        built = read_json(job.build_dir / "params.json") or {}
        params = built.get("params") or (r.merged(plan.get("params") or {}) if r else {})
        request = job.request()
    mesh = load_mesh(path)
    feats = find_features(mesh, axes=("z",) if len(mesh.faces) > 400_000 else ("z", "x", "y"))
    pr = printer(job.root if job.exists() else None)
    material = reftool.material_for(request, r, params).material if r else "PLA"
    s, s_cite = shrink(material)
    head = []
    who = f"this printer ({pr.model})" if pr.model and pr.calibrated else ("this printer" if pr.calibrated else "a typical printer")
    o = 2 * pr.outer_side
    outer = f"{num(abs(o))} mm {'big' if o > 0.005 else 'small'}" if abs(o) > 0.005 else "true"
    head.append(f"Fit on {who}: holes {num(2 * pr.hole_side)} mm small, outer sizes {outer}, sizes +/- {num(pr.band)} mm "
                f"({'; '.join(pr.cites)})")
    head.append(f"{reftool.MATERIALS[material].name if material in reftool.MATERIALS else material} shrinks "
                + (f"{num(s * 100)}% ({s_cite})" if s_cite else "by no sourced amount: 0 assumed"))
    lines: list[Line] = []
    used: set[int] = set()
    screw = request_screw(request)
    if r is not None:
        for p in r.params:
            if param_kind(p) == "screw" and isinstance(params.get(p.name), (int, float)) and params[p.name] > 0:
                screw = f"M{params[p.name]:g}"
        st = job.status() if job.exists() else {}
        known = dict((st.get("fit_screws") or {}).get(r.name) or {})
        before = dict(known)
        rl, used = recipe_lines(r, params, feats, pr, s, material, screw, known)
        lines.extend(rl)
        if known != before and job.exists():
            job.update(fit_screws={**(st.get("fit_screws") or {}), r.name: known})
    for i, f in enumerate(feats):
        if i not in used:
            lines.append(feature_line(f, pr, s, material, screw))
    bed = [f for f in feats if f.at_bed and f.kind == "hole"]
    if bed and not all(f.flare for f in bed):
        lines.append(Line(f"Holes open on the bed: the first layer squashes in about {num(val('fit.elephant_foot'))} mm "
                          f"per side; turn on elephant foot compensation ({cite('fit.elephant_foot')})"))
    info = {"recipe": r.name if r else None, "material": material, "calibrated": pr.calibrated,
            "features": [vars(f) | {"size": f.size} for f in feats]}
    return head, lines, info


def cmd(args, job):
    Out = _out()
    items = list(getattr(args, "items", []) or [])
    return cmd_check(items, job, Out)


def _continue(job) -> str:
    from .cli import DONE_NEXT, NEW_NEXT

    if not job.exists():
        return NEW_NEXT
    st = job.status()
    nxt = str(st.get("next") or "")
    if not nxt or nxt.startswith("stone fit"):
        return DONE_NEXT if st.get("passed") else ("stone build" if job.plan() else "stone recipes")
    return nxt


def cmd_check(items: list[str], job, Out):
    out = Out(owns_next=False)
    path = None
    if items:
        path = Path(items[0]).expanduser().resolve()
        if not path.is_file():
            out.fix(f"no file at {path}")
            out.next = "stone fit <file.stl>"
            return out
    elif not job.exists() or part_file(job) is None:
        out.fix("no built part yet; build first or name an STL file")
        out.next = "stone build" if job.exists() and job.plan() else _continue(job)
        return out
    head, lines, info = report(job, path)
    out.add(*head)
    if not lines:
        out.add("No round holes, pegs or fit settings found: nothing here has to fit another part.")
    for i, ln in enumerate(lines[:12], 1):
        out.add(f"{i} {ln.text}")
    if len(lines) > 12:
        out.add(f"({len(lines) - 12} more in fit.json)")
    if job.exists() and path is None:
        from .job import write_json

        write_json(job.build_dir / "fit.json", {**info, "lines": [vars(x) for x in lines]})
    fixes = {ln.param: ln.value for ln in lines if ln.param and ln.value is not None and ln.verdict in ("tight", "loose")}
    out.result = f"fit: {sum(ln.verdict in ('tight', 'loose') for ln in lines)} to change"
    if fixes and info["recipe"]:
        out.next = f"stone set {info['recipe']} " + " ".join(f"{k}={v:g}" for k, v in fixes.items())
        out.owns_next = True
    elif path is not None:
        out.next = "none, the fit report is done"
    else:
        out.next = _continue(job)
        out.owns_next = str(job.status().get("next") or "").startswith("stone fit")
    return out

