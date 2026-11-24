"""G-code in, toolpath out: every move with its print time, for stone timelapse.

Reads what OrcaSlicer, PrusaSlicer, Bambu Studio, Creality Print and Cura write: G0/G1/G2/G3 (arcs
cut into 1 mm chords, Klipper's default arc resolution), G90/G91, M82/M83, G92, G4, layer markers
(;LAYER_CHANGE with ;Z:, ; CHANGE_LAYER with ; Z_HEIGHT:, Cura's ;LAYER:n, M73 L), feature comments
(;TYPE:, Bambu's ; FEATURE:), line widths (;WIDTH: / ;HEIGHT:, ; LINE_WIDTH: / ; LAYER_HEIGHT:) and the motion limits (M201, M203, M204, M205, M566,
SET_VELOCITY_LIMIT).

Time: each move is a trapezoid (accelerate, cruise, decelerate) at the acceleration in force, and
the speed at each corner is limited by the jerk the file sets, the planner Marlin uses and that
PrusaSlicer's and OrcaSlicer's own estimators copy: a reverse pass so every move can stop in time, a
forward pass so every move can reach its speed.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

ARC_CHORD = 1.0  # mm, Klipper's default [gcode_arcs] resolution
FEATURES = ("outer wall", "inner wall", "sparse infill", "solid infill", "top surface", "bottom surface",
            "bridge", "support", "support interface", "skirt", "prime tower", "other")
_FEATURE_WORDS = (  # first match wins, on the lower-cased ;TYPE: text
    ("support interface", "support interface"), ("support-interface", "support interface"),
    ("support", "support"), ("external perimeter", "outer wall"), ("outer wall", "outer wall"),
    ("wall-outer", "outer wall"), ("overhang", "outer wall"), ("perimeter", "inner wall"), ("wall", "inner wall"),
    ("top", "top surface"), ("bottom", "bottom surface"), ("bridge", "bridge"), ("solid", "solid infill"),
    ("skin", "solid infill"), ("gap", "solid infill"), ("infill", "sparse infill"), ("fill", "sparse infill"),
    ("skirt", "skirt"), ("brim", "skirt"), ("tower", "prime tower"))
_WORD = re.compile(r"([A-Za-z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")


def feature_of(text: str) -> int:
    t = text.strip().lower()
    for word, name in _FEATURE_WORDS:
        if word in t:
            return FEATURES.index(name)
    return FEATURES.index("other")


@dataclass
class Limits:
    """The motion limits in force. Speeds mm/s, accelerations mm/s2."""
    print_accel: float = 1500.0
    travel_accel: float = 1500.0
    retract_accel: float = 1500.0
    max_accel: list = field(default_factory=lambda: [1e9, 1e9, 1e9, 1e9])  # x y z e
    max_feed: list = field(default_factory=lambda: [1e9, 1e9, 1e9, 1e9])
    jerk: list = field(default_factory=lambda: [8.0, 8.0, 0.4, 5.0])


@dataclass
class Toolpath:
    """Every move, in file order. Arrays of n moves; layer is -1 before the first layer."""
    p0: np.ndarray  # (n, 4) x y z e at the start, mm
    p1: np.ndarray  # (n, 4) at the end
    feed: np.ndarray  # mm/s asked for
    accel: np.ndarray  # mm/s2 in force
    layer: np.ndarray  # int
    feature: np.ndarray  # index into FEATURES
    width: np.ndarray  # mm, line width of an extruding move (0 elsewhere)
    height: np.ndarray  # mm, its layer height
    dwell: np.ndarray  # s of G4 before the move
    layer_z: list  # mm, each layer's height as the file names it
    jerk: list  # x y z e mm/s
    max_feed: list
    max_accel: list
    source: str = "gcode"
    slicer: str = ""
    estimate_s: float | None = None  # the slicer's own estimate from the file, s
    header_layers: int | None = None
    t0: np.ndarray | None = None  # s, filled by plan()
    t1: np.ndarray | None = None

    @property
    def n(self) -> int:
        return len(self.feed)

    def extruding(self) -> np.ndarray:
        d = self.p1 - self.p0
        return (d[:, 3] > 1e-9) & (np.hypot(d[:, 0], d[:, 1]) > 1e-6)

    def total_s(self) -> float:
        return float(self.t1[-1]) if self.t1 is not None and self.n else 0.0


_TIME = (re.compile(r";\s*estimated printing time \(normal mode\)\s*=\s*(.+)"),
         re.compile(r";\s*total estimated time:\s*([^;\n]+)"),
         re.compile(r";\s*model printing time:\s*([^;\n]+)"),
         re.compile(r";TIME:(\d+(?:\.\d+)?)"))


def duration(text: str) -> float | None:
    """'1d 2h 3m 4s' or '1h 2m' or '754' (s) as seconds."""
    text = text.strip()
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)
    parts = re.findall(r"(\d+(?:\.\d+)?)\s*([dhms])", text)
    if not parts:
        return None
    return sum(float(v) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[u] for v, u in parts)


def slicer_estimate(text: str) -> float | None:
    for pat in _TIME:
        m = pat.search(text)
        if m:
            got = duration(m.group(1))
            if got is not None:
                return got
    return None


def _arc(x0, y0, x1, y1, i, j, cw: bool, turns: int = 0):
    """Points along a G2 (cw) / G3 arc from (x0, y0) to (x1, y1) about (x0 + i, y0 + j), excluding the start."""
    cx, cy = x0 + i, y0 + j
    r = math.hypot(i, j)
    a0, a1 = math.atan2(y0 - cy, x0 - cx), math.atan2(y1 - cy, x1 - cx)
    sweep = a1 - a0
    if cw:
        sweep = sweep if sweep < 0 else sweep - 2 * math.pi
        if abs(x1 - x0) + abs(y1 - y0) < 1e-9:
            sweep = -2 * math.pi
        sweep -= 2 * math.pi * turns
    else:
        sweep = sweep if sweep > 0 else sweep + 2 * math.pi
        if abs(x1 - x0) + abs(y1 - y0) < 1e-9:
            sweep = 2 * math.pi
        sweep += 2 * math.pi * turns
    k = max(1, int(math.ceil(abs(sweep) * r / ARC_CHORD)))
    a = a0 + sweep * np.arange(1, k + 1) / k
    pts = np.c_[cx + r * np.cos(a), cy + r * np.sin(a)]
    pts[-1] = (x1, y1)
    return pts


def read(path) -> str:
    """A G-code file's text; .gz files are read through gzip."""
    path = Path(path)
    if path.suffix == ".gz":
        import gzip

        return gzip.decompress(path.read_bytes()).decode(errors="replace")
    return path.read_text(errors="replace")


def parse(source, limits: Limits | None = None) -> Toolpath:
    """A G-code file (path or text) as a Toolpath, times not yet planned."""
    text = read(source) if isinstance(source, Path) or (isinstance(source, str) and "\n" not in source) else str(source)
    lim = limits or Limits()
    pos = [0.0, 0.0, 0.0, 0.0]
    absolute, e_abs = True, True
    scale = 1.0
    feed = 25.0
    layer, feature, width, height = -1, FEATURES.index("other"), 0.0, 0.0
    layer_z: list[float] = []
    pending_z = False  # a layer began but its height is not known yet
    last_z_comment = None
    dwell = 0.0
    fil_area = math.pi * (1.75 / 2) ** 2
    rows: list[tuple] = []
    slicer = ""
    head = text[:4000]
    m = re.search(r"generated (?:by|with) ([^\n]+)", head, re.I) or re.search(r";\s*(Cura_SteamEngine [^\n]+)", head)
    if m:
        slicer = m.group(1).strip()[:60]
    m = re.search(r";\s*filament_diameter\s*[:=]\s*([\d.]+)", text)
    if m:
        fil_area = math.pi * (float(m.group(1)) / 2) ** 2
    m = re.search(r";\s*total layer number:\s*(\d+)", head) or re.search(r";LAYER_COUNT:(\d+)", head)
    header_layers = int(m.group(1)) if m else None
    # Cura marks layers with ;LAYER:n; others write ;LAYER_CHANGE, and a Klipper start script may add
    # ;LAYER:n beside it for the printer's display: count those only when nothing else marks layers
    cura_layers = not re.search(r"^;\s*(LAYER_CHANGE|CHANGE_LAYER)\s*$", text, re.M)
    for key, k in (("x", 0), ("y", 1), ("z", 2), ("e", 3)):  # Orca and Creality write the machine limits in their config block
        mj = re.search(rf";\s*machine_max_jerk_{key}\s*=\s*([\d.]+)", text)
        if mj:
            lim.jerk[k] = float(mj.group(1))

    def new_layer(z=None):
        nonlocal layer, pending_z
        layer += 1
        layer_z.append(z if z is not None else float("nan"))
        pending_z = z is None

    def move(target, f, cw=None, ij=None, turns=0):
        nonlocal pos
        e_move = target[3] - pos[3]
        accel = lim.print_accel if e_move > 0 else lim.travel_accel
        if abs(e_move) > 0 and all(abs(target[k] - pos[k]) < 1e-9 for k in range(3)):
            accel = lim.retract_accel
        pts = [target[:2]] if cw is None else _arc(pos[0], pos[1], target[0], target[1], ij[0], ij[1], cw, turns)
        n = len(pts)
        seg = np.hypot(*np.diff(np.vstack([pos[:2], pts]), axis=0).T) if n > 1 else np.ones(1)
        share = seg / seg.sum() if seg.sum() > 0 else np.full(n, 1.0 / n)
        start = list(pos)
        done = 0.0
        for (x, y), s in zip(pts, share):
            done += s
            end = [x, y, start[2] + (target[2] - start[2]) * done, start[3] + e_move * done]
            w = width
            if e_move > 0 and not w:
                ln = math.hypot(end[0] - pos[0], end[1] - pos[1])
                w = (end[3] - pos[3]) * fil_area / max(ln * (height or 0.2), 1e-9) if ln > 0 else 0.0
            rows.append((*pos, *end, f, accel, layer, feature, w if e_move > 0 else 0.0, height, dwell))
            pos = end
        pos = list(target)

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line[0] == ";":
            c = line[1:].strip()
            cl = c.lower()
            if cl in ("layer_change", "change_layer"):
                new_layer(None)
            elif cura_layers and re.match(r"layer:-?\d+$", cl):
                new_layer(None)
            elif cl.startswith("z:") or cl.startswith("z_height:"):
                z = float(c.split(":", 1)[1])
                last_z_comment = z
                if layer >= 0 and pending_z:
                    layer_z[layer] = z
                    pending_z = False
            elif cl.startswith(("type:", "feature:")):  # Bambu Studio: ; FEATURE: Outer wall
                feature = feature_of(c.split(":", 1)[1])
            elif cl.startswith(("width:", "line_width:")):
                width = float(c.split(":", 1)[1])
            elif cl.startswith(("height:", "layer_height:")):
                height = float(c.split(":", 1)[1])
            continue
        code = line.split(";", 1)[0].strip()
        if not code:
            continue
        up = code.upper()
        if up.startswith("SET_VELOCITY_LIMIT"):
            for k, v in re.findall(r"(\w+)=([\d.]+)", up):
                if k == "ACCEL":
                    lim.print_accel = lim.travel_accel = float(v)
                elif k == "SQUARE_CORNER_VELOCITY":
                    lim.jerk[0] = lim.jerk[1] = float(v)
                elif k == "VELOCITY":
                    lim.max_feed[0] = lim.max_feed[1] = float(v)
            continue
        words = {k.upper(): float(v) for k, v in _WORD.findall(code[1:] if up[0] in "GM" else code)}
        cmd = up.split()[0]
        if cmd in ("G0", "G1", "G2", "G3", "G00", "G01", "G02", "G03"):
            if "F" in words:
                feed = words["F"] * scale / 60.0
            target = list(pos)
            for k, a in enumerate("XYZ"):
                if a in words:
                    target[k] = words[a] * scale + (pos[k] if not absolute else 0.0)
            if "E" in words:
                target[3] = words["E"] * scale + (pos[3] if not (absolute and e_abs) else 0.0)
            if pending_z and "Z" in words and layer >= 0 and last_z_comment is None:
                pass
            if layer >= 0 and pending_z and target[3] > pos[3] and math.isnan(layer_z[layer]):
                layer_z[layer] = target[2]  # Cura names no height: the first extrusion's z is the layer's
                pending_z = False
            if target == pos:
                continue
            if cmd in ("G2", "G3", "G02", "G03") and ("I" in words or "J" in words):
                move(target, feed, cw=cmd in ("G2", "G02"), ij=(words.get("I", 0.0) * scale, words.get("J", 0.0) * scale),
                     turns=int(words.get("P", 1)) - 1 if "P" in words else 0)
            else:
                move(target, feed)
            dwell = 0.0
        elif cmd == "G4":
            dwell += words.get("P", 0.0) / 1000.0 + words.get("S", 0.0)
        elif cmd == "G90":
            absolute = True
        elif cmd == "G91":
            absolute = False
        elif cmd == "M82":
            e_abs = True
        elif cmd == "M83":
            e_abs = False
        elif cmd == "G20":
            scale = 25.4
        elif cmd == "G21":
            scale = 1.0
        elif cmd == "G92":
            for k, a in enumerate("XYZE"):
                if a in words:
                    pos[k] = words[a] * scale
        elif cmd == "G28":
            pos[:3] = [0.0, 0.0, 0.0]
        elif cmd == "M204":
            if "S" in words:
                lim.print_accel = lim.travel_accel = words["S"]
            if "P" in words:
                lim.print_accel = words["P"]
            if "T" in words:
                lim.travel_accel = words["T"]
            if "R" in words:
                lim.retract_accel = words["R"]
        elif cmd == "M201":
            for k, a in enumerate("XYZE"):
                if a in words:
                    lim.max_accel[k] = words[a]
        elif cmd == "M203":
            for k, a in enumerate("XYZE"):
                if a in words:
                    lim.max_feed[k] = words[a]
        elif cmd == "M205":
            for k, a in enumerate("XYZE"):
                if a in words:
                    lim.jerk[k] = words[a]
        elif cmd == "M566":  # RepRapFirmware jerk, mm/min
            for k, a in enumerate("XYZE"):
                if a in words:
                    lim.jerk[k] = words[a] / 60.0
        elif cmd == "M73" and "L" in words and not slicer.lower().startswith(("orca", "prusa", "creality")):
            pass  # Bambu numbers layers with M73 L as well as ; CHANGE_LAYER; the comment is the one counted
    a = np.array(rows, float).reshape(-1, 15)
    tp = Toolpath(a[:, 0:4], a[:, 4:8], a[:, 8], a[:, 9], a[:, 10].astype(int), a[:, 11].astype(int),
                  a[:, 12], a[:, 13], a[:, 14], layer_z, list(lim.jerk), list(lim.max_feed), list(lim.max_accel), "gcode", slicer,
                  slicer_estimate(text), header_layers)
    _fill_heights(tp)
    return tp


def _fill_heights(tp: Toolpath) -> None:
    """A layer the file gave no ;HEIGHT: for gets the step from the layer below."""
    z = np.asarray(tp.layer_z, float)
    step = np.diff(np.r_[0.0, z])
    miss = (tp.height <= 0) & (tp.layer >= 0)
    if miss.any():
        tp.height[miss] = np.clip(step[tp.layer[miss]], 0.05, None)


def _cruise(tp: Toolpath):
    """Each move's length (mm), its direction per mm on each axis, and the speed it cruises at (mm/s)."""
    d = tp.p1 - tp.p0
    xyz = np.linalg.norm(d[:, :3], axis=1)
    length = np.where(xyz > 1e-9, xyz, np.abs(d[:, 3]))
    unit = d / np.maximum(length, 1e-12)[:, None]  # per mm of the move, each axis
    v = np.maximum(tp.feed, 1e-3)
    mf = np.asarray(tp.max_feed, float)
    over = np.max(np.abs(unit) * v[:, None] / mf, axis=1)
    v = np.where(over > 1, v / over, v)
    return length, unit, v


def corner_speeds(tp: Toolpath):
    """Per move, mm/s: safe, the speed it may start or end at from rest; vj, the jerk-limited speed at
    its corner with the move before (safe for the first move); junction, the corner speed the planner
    starts from."""
    _, unit, v = _cruise(tp)
    n = tp.n
    jerk = np.asarray(tp.jerk, float)
    axis_v = unit * v[:, None]  # mm/s along each axis at cruise
    # the speed a move may start or end at from rest, as PrusaSlicer's GCodeProcessor::process_G1
    # (the estimator the slicer's own time comes from): the smallest jerk of the axes that run over
    # theirs, not the product of their ratios
    safe = v.copy()
    for k in range(4):
        safe = np.where(np.abs(axis_v[:, k]) > jerk[k], np.minimum(safe, jerk[k]), safe)
    # corner speed between move i-1 and i, as GCodeProcessor::process_G1 (Marlin classic jerk): once an
    # axis has limited, the next axis's exit and entry speeds are scaled by the running factor first
    junction = safe.copy()
    vjs = safe.copy()
    if n > 1:
        pv, cv = v[:-1], v[1:]
        lim_v = np.minimum(pv, cv)
        pa, ca = axis_v[:-1] * (lim_v / pv)[:, None], axis_v[1:] * (lim_v / cv)[:, None]
        factor = np.ones(n - 1)
        for k in range(4):
            ve, vn = pa[:, k] * factor, ca[:, k] * factor  # factor is 1 until an axis limits
            jump = np.where(ve > vn, np.where((vn > 0) | (ve < 0), ve - vn, np.maximum(ve, -vn)),
                            np.where((vn < 0) | (ve > 0), vn - ve, np.maximum(-ve, vn)))
            factor = np.where(jump > jerk[k], factor * jerk[k] / np.maximum(jump, 1e-12), factor)
        vj = lim_v * factor
        vjs[1:] = vj
        both = (safe[:-1] > vj * 0.99) & (safe[1:] > vj * 0.99)
        junction[1:] = np.where(both, np.minimum(safe[1:], lim_v), vj)
    return safe, vjs, junction


def plan(tp: Toolpath) -> Toolpath:
    """Fill t0 and t1 (s) for every move with the trapezoid and jerk model."""
    length, unit, v = _cruise(tp)
    acc = tp.accel.copy()
    lim_acc = np.asarray(tp.max_accel, float)
    acc = np.minimum(acc, np.min(np.where(np.abs(unit) > 1e-9, lim_acc / np.maximum(np.abs(unit), 1e-12), np.inf), axis=1))
    safe, _, junction = corner_speeds(tp)
    entry = np.minimum(junction, v)
    tp.t0, tp.t1 = _passes(entry, v, acc, length, safe, tp.dwell)
    return tp


def _passes(entry, v, acc, length, safe, dwell):
    n = len(v)
    ent = entry.tolist()
    vl, al, ll = v.tolist(), acc.tolist(), length.tolist()
    nxt = float(safe[-1]) if n else 0.0
    nxt = min(nxt, 0.0)  # the print ends at rest
    for i in range(n - 1, -1, -1):  # every move can slow to the next one's entry
        ent[i] = min(ent[i], math.sqrt(nxt * nxt + 2 * al[i] * ll[i]))
        nxt = ent[i]
    for i in range(n - 1):  # and every move can reach the next one's entry from its own
        ent[i + 1] = min(ent[i + 1], math.sqrt(ent[i] * ent[i] + 2 * al[i] * ll[i]))
    out = np.empty(n)
    dw = dwell.tolist()
    for i in range(n):
        v0, v1 = ent[i], (ent[i + 1] if i + 1 < n else 0.0)
        vc, a, L = vl[i], al[i], ll[i]
        da, dd = (vc * vc - v0 * v0) / (2 * a), (vc * vc - v1 * v1) / (2 * a)
        if da + dd <= L:
            t = (vc - v0) / a + (vc - v1) / a + (L - da - dd) / vc
        else:
            vp = math.sqrt(max((2 * a * L + v0 * v0 + v1 * v1) / 2, 0.0))
            t = max(vp - v0, 0.0) / a + max(vp - v1, 0.0) / a
        out[i] = t + dw[i]
    t1 = np.cumsum(out)
    return t1 - out + dwell, t1


def load(path) -> Toolpath:
    return plan(parse(path))
