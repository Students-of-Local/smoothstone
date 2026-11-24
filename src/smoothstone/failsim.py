"""Print-failure physics: how a print fails, as numbers a renderer can draw.

Four models in plain numpy, each fed by sourced facts (recipes/lib/refs/failsim.json, and Track S's
materials.json once it is on main) and each with its assumptions named:

1. drop_strand: plastic laid onto nothing falls as a chain of short segments (position based
   dynamics: gravity, segment lengths, ground or printed-part contact, friction) and comes to rest.
2. droop and curl: a bead past the reach hangs as a soft cantilever while it is above Tg (lumped
   Newton cooling, melt viscosity, Trouton's 3 eta for E); the layers above curl it up as they shrink.
3. bridge_sag: a bridge strand hangs as a catenary; past the usable length it sags more than a layer.
4. detachment and toppling: corner lift (the layers below Tg pull on the plate's free edge; their
   temperatures come from steady conduction up the printed column) against the bond at the plate
   temperature, nozzle drag against pull-off and shear strength, and the moment balance about the
   footprint edge; then rigid_tip, rigid_slide and blob_volume for what follows.

predict() runs the checks layer by layer in print order and returns the first failures. Every
answer is a model, not a recording.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import config

REFS = config.REPO_ROOT / "recipes" / "lib" / "refs"
KINDS = ("supports", "droop", "bridge", "detach", "topple", "none")
TAXONOMY = {"supports": "spaghetti", "droop": "overhang_droop", "bridge": "poor_bridging", "topple": "toppled"}
MATERIALS = ("PLA", "PETG", "ABS")


@lru_cache(maxsize=1)
def facts() -> dict[str, dict]:
    return {e["id"]: e for e in json.loads((REFS / "failsim.json").read_text())["entries"]}


def fact(key: str):
    return facts()["failsim." + key]["value"]


def note(key: str) -> str:
    """An assumption line as the output prints it: what stone assumed and where it is written down."""
    e = facts()["failsim." + key]
    return f"{e.get('assumption') or e['note']} (failsim.{key})"


# materials

@dataclass(frozen=True)
class Material:
    name: str
    density: float  # g/cm3
    tg: float  # C
    cte: float  # 1/K
    e: float  # MPa, X-Y, at 20 C
    curve: tuple  # (C, E/E20) pairs, never rising on heating
    tensile_z: float  # MPa, between layers
    cp: float  # J/(kg K)
    k: float  # W/(m K)
    peel: float  # N, 90 degree peel peak on glass
    bed: float  # C, K2 profile
    chamber: float
    nozzle: float
    stand_ins: tuple = ()  # data borrowed from PLA, said out loud
    source: str = ""

    def ratio(self, t) -> np.ndarray:
        c = np.asarray(self.curve, float)
        return np.interp(t, c[:, 0], c[:, 1])


def _props(m: str) -> tuple[dict, str]:
    pre, found, src = m.lower() + ".", {}, "failsim.json copies of Track S"
    p = REFS / "materials.json"
    if p.exists():
        for e in json.loads(p.read_text())["entries"]:
            if e["id"].startswith(pre):
                found[e["key"]] = e
        src = "materials.json"
    for e in facts().values():
        if e["id"].startswith("failsim.mat." + pre):
            found.setdefault(e["key"], e)
    return found, src


@lru_cache(maxsize=None)
def material(name: str = "PLA") -> Material:
    m = name.upper()
    if m not in MATERIALS:
        raise ValueError(f"failsim models PLA, PETG and ABS (the K2 profile's three), not {name}")
    p, src = _props(m)
    curve = np.asarray(p["modulus_vs_temp"]["value"], float)
    curve[:, 1] = np.minimum.accumulate(curve[:, 1])  # Track S's rule: no credit for a rise on heating
    k2 = fact(f"k2.{m.lower()}")
    stand = []
    if m == "ABS":  # average cp from Tg to the nozzle on Bhandari's table
        tab = np.asarray(fact("abs.cp_k"), float)
        ts = np.linspace(p["tg"]["value"], k2["nozzle"], 50)
        cp = float(np.interp(ts, tab[:, 0], tab[:, 2]).mean())
        k = float(np.interp(np.linspace(fact("room_air"), p["tg"]["value"], 50), tab[:, 0], tab[:, 1]).mean())
    else:
        cp, k = fact("pla.cp"), fact("pla.k")
        if m != "PLA":
            stand.append(f"{m} uses PLA's specific heat and thermal conductivity (no sourced values)")
    if m != "PLA":
        stand.append(f"{m} uses PLA's melt viscosity (Cross-WLF of PLA 3251D)")
    peel = {"PLA": fact("peel.pla"), "PETG": fact("peel.petg")}.get(m)
    if peel is None:
        peel = fact("peel.pla")
        stand.append(f"{m} uses PLA's peel force on glass")
    return Material(m, p["density"]["value"], p["tg"]["value"], p["cte"]["value"] * 1e-6, p["e_xy"]["value"],
                    tuple(map(tuple, curve)), p["tensile_z"]["value"], cp, k, peel, k2["bed"], k2["chamber"],
                    k2["nozzle"], tuple(stand), src)


def _mat(m) -> Material:
    return m if isinstance(m, Material) else material(m)


# melt, bead cooling, droop and curl

def viscosity(t_c, rate=0.0) -> np.ndarray:
    """Pa s of PLA melt at t_c (C) and shear rate (1/s): Cross-WLF, Pricci 2025 Table 2. Infinite at
    and below the WLF pole (T* - A2, 48.4 C), where the fit stops meaning anything."""
    p = fact("pla.cross_wlf")
    dt = np.asarray(t_c, float) + 273.15 - p["T_star_K"]
    den = p["A2_K"] + dt
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        eta0 = np.where(den > 0, p["D1_Pa_s"] * np.exp(-p["A1"] * dt / np.where(den > 0, den, 1.0)), np.inf)
        rate = np.asarray(rate, float)
        thin = np.where(rate > 0, (eta0 * rate / p["tau_star_Pa"]) ** (1.0 - p["n"]), 0.0)
        return eta0 / (1.0 + thin)


def _bead(width: float, layer: float) -> tuple[float, float]:
    """Cross-section (mm2) and perimeter (mm) of a line: a rectangle with round ends (OrcaSlicer's flow model)."""
    return (width - layer) * layer + math.pi * layer * layer / 4, 2 * (width - layer) + math.pi * layer


def cooling(mat="PLA", layer: float = 0.2, width: float = 0.42, fan: bool = True) -> dict:
    """Lumped Newton cooling of a bead: h, time constant tau, Biot number, seconds above Tg."""
    m = _mat(mat)
    a, per = _bead(width, layer)
    d = 4 * a / per * 1e-3  # hydraulic diameter, m
    if fan:
        air = fact("air_400k")
        re, pr = fact("fan_air_speed") * d / air["nu"], air["pr"]
        nu = 0.3 + 0.62 * re ** 0.5 * pr ** (1 / 3) / (1 + (0.4 / pr) ** (2 / 3)) ** 0.25 * (1 + (re / 282000) ** 0.625) ** 0.8
        h = nu * air["k"] / d
    else:
        h = fact("h_still")
    tau = m.density * 1000 * m.cp * (a / per * 1e-3) / h
    soft = tau * math.log((m.nozzle - m.chamber) / (m.tg - m.chamber)) if m.tg > m.chamber else math.inf
    return {"h": h, "tau_s": tau, "biot": h * (a / per * 1e-3) / fact("pla.k"), "soft_s": soft}


def _compliance(m: Material, layer: float, width: float, fan: bool) -> float:
    """The integral of dt / (3 eta) while the bead cools from the nozzle to Tg, in mm2/N."""
    c = cooling(m, layer, width, fan)
    ts = np.linspace(m.tg, m.nozzle, 4001)
    f = c["tau_s"] / ((ts - m.chamber) * fact("trouton") * viscosity(ts))
    return float(np.sum((f[1:] + f[:-1]) * np.diff(ts)) / 2) * 1e6  # 1/Pa -> mm2/N


def reach(layer: float = 0.2) -> float:
    """How far a line may pass the one below unsupported: the slicer's support threshold angle."""
    return layer * math.tan(math.radians(90 - fact("support_threshold_angle")))


def droop(dist_mm, mat="PLA", layer: float = 0.2, width: float = 0.42, fan: bool = True) -> np.ndarray:
    """Downward displacement (mm, negative) of each ledge vertex, by its distance past the edge of the
    layer below. The free length starts at the reach; the ledge sags as a cantilever under its own
    weight while soft: y = q x^2 (6L^2 - 4Lx + x^2) / (24 I) x integral dt / (3 eta), and no vertex
    drops farther than its own free length."""
    m = _mat(mat)
    x = np.clip(np.asarray(dist_mm, float) - reach(layer), 0.0, None)
    big = float(x.max()) if x.size else 0.0
    if big <= 0:
        return np.zeros_like(x)
    a, _ = _bead(width, layer)
    q = m.density * 1e-6 * fact("gravity") * a  # N/mm
    i = width * layer ** 3 / 12  # mm4, the bead bends as a width x layer rectangle
    dz = -q * x * x * (6 * big * big - 4 * big * x + x * x) / (24 * i) * _compliance(m, layer, width, fan)
    return np.maximum(dz, -x)  # past this it hangs straight down: a falling strand (model 1), not a ledge


@lru_cache(maxsize=None)
def _stress_table(m: Material) -> tuple[np.ndarray, np.ndarray]:
    ts = np.linspace(-40.0, m.tg, 4001)
    r = m.ratio(ts)
    seg = (r[1:] + r[:-1]) / 2 * np.diff(ts)
    return ts, m.cte * m.e * np.append(np.cumsum(seg[::-1])[::-1], 0.0)


def layer_stress(mat="PLA", t_part=None):
    """MPa a layer carries once it cools bonded from Tg to t_part: alpha x integral of E(T) dT, and
    nothing while it is above Tg. Takes one temperature or an array of them."""
    m = _mat(mat)
    ts, s = _stress_table(m)
    out = np.interp(np.asarray(m.bed if t_part is None else t_part, float), ts, s, right=0.0)
    return float(out) if np.ndim(out) == 0 else out


def curl(dist_mm, mat="PLA", layer: float = 0.2, above: int = 1) -> np.ndarray:
    """Upward displacement (mm) of each ledge vertex after `above` more layers shrink on top of it in
    the chamber air. A layer of thickness t with misfit strain e on a stack s thick (same E) bends it by
    6 e t s / (s + t)^3 (force and moment balance across the pair; 3e/4t for one layer on one)."""
    m = _mat(mat)
    x = np.clip(np.asarray(dist_mm, float) - reach(layer), 0.0, None)
    e = layer_stress(m, m.chamber) / m.e
    k = np.arange(1, max(0, above) + 1)
    kappa = float(np.sum(6 * e * k / ((k + 1) ** 3 * layer)))
    return kappa * x * x / 2


def ledge(dist_mm, mat="PLA", layer: float = 0.2, width: float = 0.42, fan: bool = True, above: int = 1) -> np.ndarray:
    """Net dz per ledge vertex: droop when laid, then curl from the layers above."""
    return droop(dist_mm, mat, layer, width, fan) + curl(dist_mm, mat, layer, above)


# bridges

@lru_cache(maxsize=None)
def catenary_a(layer: float = 0.2) -> float:
    """The catenary constant (mm) that sags one layer at the usable bridge length."""
    lu, lo, hi = fact("max_bridge_length"), 1e-3, 1e6
    for _ in range(200):
        a = math.sqrt(lo * hi)
        lo, hi = (a, hi) if a * (math.cosh(lu / (2 * a)) - 1) > layer else (lo, a)
    return math.sqrt(lo * hi)


def bridge_sag(span_mm: float, x_mm=None, layer: float = 0.2) -> np.ndarray:
    """dz (mm, negative) along a bridge of span_mm at x_mm (default 21 points end to end)."""
    a = catenary_a(layer)
    x = np.linspace(0, span_mm, 21) if x_mm is None else np.asarray(x_mm, float)
    return a * (np.cosh((x - span_mm / 2) / a) - math.cosh(span_mm / (2 * a)))


def bridge_length(span_mm: float, layer: float = 0.2) -> float:
    """Arc length of the hanging bridge strand."""
    a = catenary_a(layer)
    return 2 * a * math.sinh(span_mm / (2 * a))


# falling strands

@dataclass
class Heightfield:
    """The top of what is printed so far: z (mm) on a grid of cell mm squares from origin (x, y)."""
    z: np.ndarray
    cell: float
    origin: tuple = (0.0, 0.0)

    def __call__(self, x, y) -> np.ndarray:
        r = np.clip(((np.asarray(y) - self.origin[1]) / self.cell).astype(int), 0, self.z.shape[0] - 1)
        c = np.clip(((np.asarray(x) - self.origin[0]) / self.cell).astype(int), 0, self.z.shape[1] - 1)
        return self.z[r, c]

    @classmethod
    def from_masks(cls, masks, layer_z, cell: float, origin=(0.0, 0.0)) -> Heightfield:
        z = np.zeros(np.shape(masks[0]))
        for mk, top in zip(masks, layer_z):
            z[mk] = top
        return cls(z, cell, origin)


def _resample(path: np.ndarray, seg: float) -> np.ndarray:
    d = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))]
    s = np.linspace(0, d[-1], max(2, int(math.ceil(d[-1] / seg)) + 1))
    return np.stack([np.interp(s, d, path[:, k]) for k in range(3)], 1)


def drop_strand(path_xyz, speed_mm_s: float = 200.0, flow_mm3_s: float = 10.0, ground=0.0, steps: int = 2000,
                dt: float = 1 / 600, mu: float | None = None, seg_mm: float = 0.5, iters: int = 30,
                pins=(), damping: float = 0.0, rest_mm_s: float = 1.0) -> list[np.ndarray]:
    """Frames of a strand laid along path_xyz (mm) into air. Vertex i leaves the nozzle at s_i / speed
    and is held on the path until then; the strand is flow / speed mm2 thick. ground is a z (mm), a
    Heightfield or any f(x, y) -> z. pins: vertex indices held for good (a bridge's ends). Each frame
    is the extruded part of the strand as an (n, 3) polyline; frames stop once it is at rest."""
    p = _resample(np.asarray(path_xyz, float), seg_mm)
    n = len(p)
    rest = np.linalg.norm(np.diff(p, axis=0), axis=1)
    out_t = np.r_[0.0, np.cumsum(rest)] / speed_mm_s
    r = math.sqrt(flow_mm3_s / speed_mm_s / math.pi)
    mu = fact("strand_friction") if mu is None else mu
    gz = (lambda x, y: np.full(np.shape(x), float(ground))) if np.isscalar(ground) else ground
    held = np.zeros(n, bool)
    held[list(pins)] = True
    x, v = p.copy(), np.zeros_like(p)
    g = np.array([0.0, 0.0, -fact("gravity") * 1000])
    frames = []
    halves = (np.arange(0, n - 1, 2), np.arange(1, n - 1, 2))
    for step in range(steps):
        t = step * dt
        w = ((out_t <= t) & ~held).astype(float)
        xp = x + w[:, None] * (v * (1 - damping) * dt + g * dt * dt)
        for _ in range(iters):
            for i in halves:
                d = xp[i + 1] - xp[i]
                ln = np.linalg.norm(d, axis=1)
                ws = w[i] + w[i + 1]
                c = np.where((ws > 0) & (ln > 0), (ln - rest[i]) / np.where(ws > 0, ws, 1) / np.where(ln > 0, ln, 1), 0)
                xp[i] += (w[i] * c)[:, None] * d
                xp[i + 1] -= (w[i + 1] * c)[:, None] * d
            floor = gz(xp[:, 0], xp[:, 1]) + r
            wall = (w > 0) & (floor > x[:, 2] + 1e-6)  # the ground here is above where it was: it hit a side
            xp[wall, :2] = x[wall, :2]
            floor = gz(xp[:, 0], xp[:, 1]) + r
            xp[:, 2] = np.where(w > 0, np.maximum(xp[:, 2], floor), xp[:, 2])
        nv = (xp - x) / dt
        touch = (w > 0) & (xp[:, 2] <= floor + 1e-9)
        nv[touch, :2] *= 1 - mu  # friction on the tangential velocity (Mueller et al. 2007, sec. 3.5)
        nv[touch, 2] = np.maximum(nv[touch, 2], 0)
        x, v = xp, nv
        m = int(np.searchsorted(out_t, t, side="right"))
        frames.append(x[:max(m, 1)].copy())
        if m >= n and float(np.abs(v[w > 0]).max(initial=0.0)) < rest_mm_s:
            break
    return frames


# detachment and toppling

def bond_stress(mat="PLA", clean: float = 1.0, bed: float | None = None) -> float:
    """MPa the plate's bond holds at the edge: the peel force as an edge stress, 2 P lambda / b
    (Hetenyi, first layer as the foundation), capped at the plastic's own strength between layers
    at the plate temperature (failsim.bond_hot), times the plate factor."""
    m = _mat(mat)
    sp = fact("peel_specimen")
    lam = (3 / (sp["thickness"] * sp["thickness"] ** 3)) ** 0.25
    hot = m.tensile_z * float(m.ratio(m.bed if bed is None else bed))
    return min(2 * m.peel * lam / sp["width"], hot) * clean


def printed_section(masks, cell: float, infill: float | None = None) -> dict:
    """Per layer: area (mm2), perimeter (mm) and the share of it the K2 profile prints (walls and
    top and bottom shells solid, sparse infill at its density; failsim.section_rule)."""
    from scipy import ndimage

    sh, wd = fact("k2_shells"), fact("k2_widths")
    fill = (sh["sparse_infill_density"] if infill is None else infill) / 100
    wall = wd["outer_wall"] + (sh["wall_loops"] - 1) * wd["inner_wall"]
    st = np.asarray(masks, bool)
    n = len(st)
    top, bot = np.ones_like(st), np.ones_like(st)  # covered by each of the next top / last bottom layers
    for s in range(1, sh["top_shell_layers"] + 1):
        nxt = np.zeros_like(st)
        if s < n:  # a part thinner than the shells: the offset reaches past the stack
            nxt[:n - s] = st[s:]
        top &= nxt
    for s in range(1, sh["bottom_shell_layers"] + 1):
        prv = np.zeros_like(st)
        if s < n:
            prv[s:] = st[:n - s]
        bot &= prv
    area, perim, share = np.zeros(n), np.zeros(n), np.zeros(n)
    for j in range(n):
        mk = st[j]
        a = int(mk.sum())
        if not a:
            continue
        rim = ndimage.distance_transform_edt(np.pad(mk, 1))[1:-1, 1:-1] * cell <= wall + cell / 2
        solid = int((mk & (rim | ~top[j] | ~bot[j])).sum())
        pad = np.pad(mk, 1).astype(np.int8)
        area[j] = a * cell * cell
        perim[j] = (np.abs(np.diff(pad, axis=0)).sum() + np.abs(np.diff(pad, axis=1)).sum()) * cell
        share[j] = (solid + fill * (a - solid)) / a
    return {"area": area, "perimeter": perim, "share": share}


def column_temps(mat, area, perimeter, share, layer: float = 0.2, bed: float | None = None,
                 air: float | None = None, fan: bool = True) -> np.ndarray:
    """C of each layer, steady, with the last one on top (failsim.column_rule): k x printed area / t
    between layers, the first layer's base at the plate temperature, h x exposed area to the air."""
    from scipy.linalg import solve_banded

    m = _mat(mat)
    a, p, f = (np.asarray(x, float) for x in (area, perimeter, share))
    n = len(a)
    tb = m.bed if bed is None else bed
    ta = m.chamber if air is None else air
    h = fact("h_part") if fan else fact("h_still")
    g = np.maximum(m.k * a * f / layer * 1e-3, 1e-12)  # W/K through one layer (mm2 / mm -> m)
    up = np.append(np.maximum(a[:-1] - a[1:], 0.0), a[-1])  # top faces the next layer leaves bare
    loss = h * (p * layer + up) * 1e-6
    link = 2 / (1 / g[:-1] + 1 / g[1:])
    diag = loss.copy()
    diag[0] += 2 * g[0]  # half a layer down to the plate
    diag[:-1] += link
    diag[1:] += link
    ab = np.zeros((3, n))
    ab[0, 1:], ab[1], ab[2, :-1] = -link, diag, -link
    rhs = loss * ta
    rhs[0] += 2 * g[0] * tb
    return solve_banded((1, 1), ab, rhs)


def edge_stress(mat, temps, layer: float = 0.2, band: float = math.inf, bed: float | None = None) -> dict:
    """MPa under the walls at the part's edge (failsim.warp_rule): the moment M of the layers' pull
    about the plate, from the layers within `band` mm of it, as min(2 M lambda^2, 6 M / d^2)."""
    m = _mat(mat)
    t = np.asarray(temps, float)
    z = (np.arange(len(t)) + 0.5) * layer
    keep = z <= max(band, layer / 2)
    t, z = t[keep], z[keep]
    d = min(len(t) * layer, band)
    sig, e = layer_stress(m, t), m.e * m.ratio(t)
    zc = float((e * z).sum() / e.sum())
    ei = layer * float((e * (z - zc) ** 2).sum() + e.sum() * layer * layer / 12)
    mom = layer * float((sig * z).sum())
    kf = m.e * float(m.ratio(m.bed if bed is None else bed)) / layer
    het, zone = 2 * mom * math.sqrt(kf / (4 * ei)), 6 * mom / (d * d)
    return {"edge": min(het, zone), "hetenyi": het, "zone": zone, "moment": mom}


def nozzle_drag(mat="PLA", speed_mm_s: float | None = None, layer: float = 0.2) -> float:
    """N the nozzle's flat tip drags the top layer with: melt shear stress x tip area."""
    m = _mat(mat)
    v = fact("k2_speeds")["inner_wall"] if speed_mm_s is None else speed_mm_s
    rate = v / layer
    tau = float(viscosity(m.nozzle, rate)) * rate * 1e-6  # MPa
    return tau * math.pi * (fact("nozzle_tip") / 2) ** 2


def blob_volume(flow_mm3_s, t_s, stick: float | None = None) -> np.ndarray:
    """mm3 stuck on the nozzle after t_s seconds of extruding into air (grows with flow)."""
    s = fact("blob_stick") if stick is None else stick
    return s * np.asarray(flow_mm3_s, float) * np.asarray(t_s, float)


def _turn(axis_pt, u, ang) -> np.ndarray:
    """4x4: rotate by ang about the horizontal line through axis_pt square to u (tipping toward u)."""
    k = np.array([-u[1], u[0], 0.0])  # right hand: positive angle takes +z toward +u
    kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    rot = np.eye(3) + math.sin(ang) * kx + (1 - math.cos(ang)) * kx @ kx
    t = np.eye(4)
    t[:3, :3] = rot
    t[:3, 3] = np.asarray(axis_pt) - rot @ np.asarray(axis_pt)
    return t


def rigid_tip(edge_xy, direction, com_xyz, fps: float = 30.0, push_deg_s: float = 30.0) -> list[np.ndarray]:
    """4x4 frames of a part tipping over the footprint edge through edge_xy toward direction: pushed
    slowly until its center of mass passes over the edge, then falling as a solid box about its edge
    (I = 4/3 m r^2) until it lies on its side."""
    u = np.r_[np.asarray(direction, float)[:2], 0.0]
    u /= np.linalg.norm(u)
    piv = np.r_[np.asarray(edge_xy, float)[:2], 0.0]
    c = np.asarray(com_xyz, float) - piv
    cu, cz = float(c @ u), float(c[2])
    phi, rr = math.atan2(cu, cz), math.hypot(cu, cz)
    th, w, out, h = 0.0, 0.0, [], 1 / fps
    while th < math.pi / 2:
        out.append(_turn(piv, u, th))
        if phi + th < 0:
            th = min(th + math.radians(push_deg_s) * h, -phi + 1e-6)
        else:
            w += 3 * fact("gravity") * 1000 / (4 * rr) * math.sin(phi + th) * h
            th += w * h
    out.append(_turn(piv, u, math.pi / 2))
    return out


def rigid_slide(direction, distance_mm: float, frames: int = 15) -> list[np.ndarray]:
    """4x4 frames of a part pushed distance_mm along direction, slowing to a stop."""
    u = np.r_[np.asarray(direction, float)[:2], 0.0]
    u /= np.linalg.norm(u)
    out = []
    for f in range(frames + 1):
        t = np.eye(4)
        s = f / frames
        t[:3, 3] = u * distance_mm * (1 - (1 - s) ** 2)
        out.append(t)
    return out


# predict

@dataclass
class Inputs:
    masks: list  # per layer, bool (rows along y, columns along x)
    cell: float  # mm per pixel
    layer: float = 0.2  # mm
    origin: tuple = (0.0, 0.0)  # x, y (mm) of pixel (0, 0)'s corner
    layer_z: np.ndarray | None = None  # mm, top of each layer
    layer_t: np.ndarray | None = None  # s, end of each layer
    material: str = "PLA"
    bed: float | None = None  # C, default the K2 profile's
    clean: float = 1.0  # 1 a clean plate, fact("contamination") a dirty one
    fan: bool = True
    enclosed: bool = True  # False: an open printer, air at fact("room_air")
    infill: float | None = None  # %, default the K2 profile's sparse infill; 100 prints solid
    supports: bool = False
    speed: float | None = None  # mm/s, default the K2 profile's inner wall
    width: float | None = None  # mm, default the K2 profile's outer wall
    drag: float | None = None  # N, a push to use instead of the nozzle's drag
    notes: list = field(default_factory=list)


@dataclass
class Failure:
    kind: str
    layer: int | None = None  # 0 based
    z: float | None = None  # mm, top of that layer
    time: float | None = None  # s from the start of the print
    taxonomy: str = ""
    where: tuple | None = None  # x, y mm
    numbers: dict = field(default_factory=dict)
    assumptions: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


DIRS = [(math.cos(a), math.sin(a)) for a in np.radians(np.arange(0, 360, 45))]


def _times(inp: Inputs, width: float, speed: float) -> np.ndarray:
    if inp.layer_t is not None:
        return np.asarray(inp.layer_t, float)
    area = np.array([m.sum() for m in inp.masks]) * inp.cell ** 2
    inp.notes.append("layer times estimated as area / (line width x speed)")
    return np.cumsum(area / (width * speed))


def predict(job_or_inputs, **kw) -> list[Failure]:
    """The first failures in print order (earliest first), or [Failure('none')]. Takes Inputs, a
    trimesh mesh, an STL path or a job folder (its build/part.stl)."""
    from scipy import ndimage

    inp = job_or_inputs if isinstance(job_or_inputs, Inputs) else inputs_from_mesh(job_or_inputs, **kw)
    m = material(inp.material)
    cell, lay = inp.cell, inp.layer
    width = inp.width or fact("k2_widths")["outer_wall"]
    speed = inp.speed or fact("k2_speeds")["inner_wall"]
    zs = np.asarray(inp.layer_z, float) if inp.layer_z is not None else (np.arange(len(inp.masks)) + 1) * lay
    ts = _times(inp, width, speed)
    bed = m.bed if inp.bed is None else inp.bed
    air = m.chamber if inp.enclosed else fact("room_air")
    where_air = f"{air:g} C chamber" if inp.enclosed else f"open printer, {air:g} C room air"
    base = [f"this is a model, not a recording; {m.name} on the K2 profile ({bed:g} C bed, {where_air})",
            *m.stand_ins, *inp.notes]
    if inp.clean < 1:
        base.append(note("contamination"))
    if not inp.enclosed:
        base.append(note("room_air"))
    warp = [note("warp_rule"), note("saint_venant"), note("column_rule"), note("section_rule"), note("bond_hot"),
            note("h_part") if inp.fan else note("h_still")]

    def xy(r, c):
        return (round(inp.origin[0] + (c + 0.5) * cell, 1), round(inp.origin[1] + (r + 0.5) * cell, 1))

    found: dict[str, Failure] = {}

    def hit(kind, i, where, numbers, why, tax=None):
        if kind not in found:
            found[kind] = Failure(kind, i, round(float(zs[i]), 2), round(float(ts[i]), 1), tax or TAXONOMY[kind],
                                  where, numbers, base + why)

    foot = np.asarray(inp.masks[0], bool)
    fr, fc = np.nonzero(foot)
    px, py = inp.origin[0] + (fc + 0.5) * cell, inp.origin[1] + (fr + 0.5) * cell
    area = foot.sum() * cell * cell
    pull, shear = fact("adhesion.pulloff") * inp.clean, fact("adhesion.shear") * inp.clean
    lever = []  # per direction: the far edge, and the sum of each footprint mm2's distance to it
    narrow = math.inf  # the footprint's narrowest width: the layers within it of the plate load it
    for u in DIRS:
        d = px * u[0] + py * u[1]
        half = cell / 2 * (abs(u[0]) + abs(u[1]))  # the pixel's far side, not its center
        edge = float(d.max()) + half
        lever.append((edge, float((edge - d).sum()) * cell * cell))
        narrow = min(narrow, edge - float(d.min()) + half)
    push = nozzle_drag(m, speed, lay) if inp.drag is None else inp.drag
    bond = bond_stress(m, inp.clean, bed)
    sec = printed_section(inp.masks, cell, inp.infill)
    worst = {"edge": -1.0}
    tipping = (math.inf, 0.0, 0.0)  # lowest hold / drive, and the two
    wpm = m.density * 1e-6 * fact("gravity")  # N per mm3
    vol, mx, my = 0.0, 0.0, 0.0
    rch = reach(lay) / cell
    prev = None
    for i, mk in enumerate(inp.masks):
        mk = np.asarray(mk, bool)
        rr, cc = np.nonzero(mk)
        dv = len(rr) * cell * cell * lay
        if dv:
            mx = (mx * vol + (inp.origin[0] + (cc.mean() + 0.5) * cell) * dv) / (vol + dv)
            my = (my * vol + (inp.origin[1] + (rr.mean() + 0.5) * cell) * dv) / (vol + dv)
            vol += dv
        if prev is not None and not inp.supports and mk.any():
            dist = ndimage.distance_transform_edt(~prev) if prev.any() else np.full(mk.shape, np.inf)
            free = mk & (dist > rch)
            sup = mk & ~free
            lab, nl = ndimage.label(free, np.ones((3, 3)))
            whole = ndimage.binary_fill_holes(sup)
            for k in range(1, nl + 1):
                comp = lab == k
                ring = ndimage.binary_dilation(comp, np.ones((3, 3))) & sup
                cr, ccol = np.nonzero(comp)
                far = int(np.argmax(dist[comp]))
                at = xy(cr[far], ccol[far])
                big = float(dist[comp].max()) * cell
                if not ring.any():
                    hit("supports", i, at, {"island_mm2": round(comp.sum() * cell * cell, 1)},
                        ["a piece with nothing under it prints into air and falls (model 1)"])
                elif ndimage.label(ring, np.ones((3, 3)))[1] >= 2 or whole[comp].all():
                    span = 2 * big
                    if span > fact("max_bridge_length"):
                        sag = -float(bridge_sag(span, [span / 2], lay)[0])
                        hit("bridge", i, at, {"span_mm": round(span, 1), "sag_mm": round(sag, 2),
                                              "usable_mm": fact("max_bridge_length")}, [note("bridge_rule")])
                else:
                    tip = -float(droop([big], m, lay, width, inp.fan)[0])
                    rule = fact("droop_rule")
                    nums = {"ledge_mm": round(big, 2), "reach_mm": round(reach(lay), 2), "droop_mm": round(tip, 3),
                            "soft_s": round(cooling(m, lay, width, inp.fan)["soft_s"], 2)}
                    why = [note("droop_rule"), note("fan_air_speed") if inp.fan else note("h_still")]
                    if tip >= rule["supports"] * lay:
                        hit("supports", i, at, nums, why)
                    elif tip >= rule["droop"] * lay:
                        hit("droop", i, at, nums, why)
        prev = mk
        # the part so far against the plate
        n = i + 1
        temps = column_temps(m, sec["area"][:n], sec["perimeter"][:n], sec["share"][:n], lay, bed, air, inp.fan)
        es = edge_stress(m, temps, lay, narrow, bed)
        if es["edge"] > worst["edge"]:
            worst = {**es, "layer": i, "temps": temps}
        if es["edge"] > bond:
            hit("detach", i, xy(fr.mean(), fc.mean()), {"edge_stress_mpa": round(es["edge"], 2), "bond_mpa": round(bond, 2),
                "margin": round(bond / es["edge"], 2), "hetenyi_mpa": round(es["hetenyi"], 2),
                "edge_zone_mpa": round(es["zone"], 2), "moment_nmm_per_mm": round(es["moment"], 2),
                "bottom_c": round(float(temps[0]), 1), "top_c": round(float(temps[-1]), 1), "air_c": air,
                "plate_factor": inp.clean}, [*warp, note("peel_specimen")], "bed_adhesion" if inp.clean < 1 else "warping")
        elif push > shear * area:
            hit("detach", i, None, {"push_n": round(push, 3), "hold_n": round(shear * area, 2)},
                [note("nozzle_tip")], "bed_adhesion")
        else:
            h = float(zs[i])
            for u, (edge, arm) in zip(DIRS, lever):
                drive, held = push * h, pull * arm + wpm * vol * (edge - (mx * u[0] + my * u[1]))
                if drive > 0 and held / drive < tipping[0]:
                    tipping = (held / drive, drive, held)
                if drive > held:
                    hit("topple", i, (round(mx, 1), round(my, 1)),
                        {"push_n": round(push, 4), "height_mm": round(h, 2), "drive_nmm": round(drive, 2),
                         "adhesion_nmm": round(pull * arm, 2), "weight_nmm": round(held - pull * arm, 3),
                         "direction": [round(u[0], 3), round(u[1], 3)]}, [note("nozzle_tip")])
                    break
        if "detach" in found or "topple" in found:
            break  # everything after prints onto a loose part
    out = sorted(found.values(), key=lambda f: (f.layer, KINDS.index(f.kind)))
    if out:
        return out
    t = worst.get("temps", np.zeros(1))
    return [Failure("none", numbers={"layers": len(inp.masks), "edge_stress_mpa": round(worst["edge"], 2),
                                     "bond_mpa": round(bond, 2), "margin": round(bond / max(worst["edge"], 1e-9), 2),
                                     "worst_layer": worst.get("layer"), "bottom_c": round(float(t[0]), 1),
                                     "top_c": round(float(t[-1]), 1), "air_c": air, "push_n": round(push, 4),
                                     "tip_drive_nmm": round(tipping[1], 2), "tip_hold_nmm": round(tipping[2], 2)},
                    assumptions=base + warp)]


def inputs_from_mesh(mesh, layer: float = 0.2, cell: float = 0.2, **kw) -> Inputs:
    """Per-layer masks cut from a mesh (a trimesh, an STL path or a job folder) at each layer's middle."""
    import trimesh

    from . import slicer

    if not hasattr(mesh, "triangles"):
        p = Path(mesh)
        mesh = trimesh.load(p / "build" / "part.stl" if p.is_dir() else p, force="mesh")
    lo, hi = mesh.bounds
    tris = np.asarray(mesh.triangles, float) - lo
    w, h = int(math.ceil((hi[0] - lo[0]) / cell)) + 2, int(math.ceil((hi[1] - lo[1]) / cell)) + 2
    n = max(1, int(math.floor((hi[2] - lo[2]) / layer + 0.5)))
    k = slicer.PIXEL / cell  # _raster draws in PIXEL units; scale so one pixel is one cell
    masks = [slicer._raster(slicer._segments(tris, (j + 0.5) * layer) * k, -cell * k, -cell * k, w, h) for j in range(n)]
    return Inputs(masks, cell, layer, (float(lo[0]) - cell, float(lo[1]) - cell), (np.arange(n) + 1) * layer, **kw)


def inputs_from_segments(xy0, xy1, width, layer_of, layer_z, layer_t=None, cell: float = 0.2, **kw) -> Inputs:
    """Per-layer masks from extruding moves (Track T's Toolpath: p0[:, :2], p1[:, :2], width, layer,
    layer_z, and each layer's last t1): each line drawn as a band its median width wide."""
    from scipy import ndimage

    a, b = np.asarray(xy0, float), np.asarray(xy1, float)
    lay_of, wid = np.asarray(layer_of, int), np.asarray(width, float)
    lz = np.asarray(layer_z, float)
    lo = np.minimum(a.min(0), b.min(0)) - wid.max()
    hi = np.maximum(a.max(0), b.max(0)) + wid.max()
    shape = (int(math.ceil((hi[1] - lo[1]) / cell)) + 1, int(math.ceil((hi[0] - lo[0]) / cell)) + 1)
    masks = []
    for j in range(len(lz)):
        sel = lay_of == j
        mk = np.zeros(shape, bool)
        if sel.any():
            sa, sb = a[sel], b[sel]
            cnt = np.maximum(1, np.ceil(np.linalg.norm(sb - sa, axis=1) / (cell / 2)).astype(int))
            f = np.concatenate([np.linspace(0, 1, c + 1) for c in cnt])
            idx = np.repeat(np.arange(len(sa)), cnt + 1)
            pts = sa[idx] + (sb[idx] - sa[idx]) * f[:, None]
            mk[((pts[:, 1] - lo[1]) / cell).astype(int), ((pts[:, 0] - lo[0]) / cell).astype(int)] = True
            rad = float(np.median(wid[sel])) / 2 / cell
            g = int(math.ceil(rad))
            yy, xx = np.mgrid[-g:g + 1, -g:g + 1]
            mk = ndimage.binary_dilation(mk, xx * xx + yy * yy <= rad * rad + 1e-9)
        masks.append(mk)
    thick = float(lz[0]) if len(lz) else 0.2
    return Inputs(masks, cell, kw.pop("layer", thick), (float(lo[0]), float(lo[1])), lz,
                  None if layer_t is None else np.asarray(layer_t, float), **kw)
