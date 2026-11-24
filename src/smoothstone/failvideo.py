"""stone timelapse --fail: this print failing the way failsim's physics says it would, on stone
timelapse's own toolpaths, renderer and camera. A model, not a recording.

auto shows the first failure failsim.predict finds. A named mode (supports, detach, droop, bridge) shows
that one where the model's own rules put it; detach also on a part that holds. What the print as asked
does not do is labeled a what-if. Up to the failure the frames are the normal timelapse's, at most LEAD of
them. From it on, every piece that fails by failsim's rules moves, and the rest prints:
- supports: each layer's lines over air are one strand (failsim.drop_strand), held where it lies on
  printed plastic, falling and piling on what is below; lines above them print into air too;
- droop: lines past the reach bend down (failsim.droop) and curl up as layers go on (failsim.curl);
- bridge: lines held at both ends hang as a catenary (failsim.bridge_sag); layers above rest on what hangs;
- detach and topple: the part slides (failsim.rigid_slide) or tips (rigid_tip), every later layer
  prints into air, and plastic builds on the nozzle (failsim.blob_volume).
Writes build/fail.mp4, fail_sheet.png and fail.json.
"""

from __future__ import annotations

import json
import math
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from . import failsim, timelapse

MODES = ("auto", "supports", "detach", "droop", "bridge")
AFTER = 12  # layers drawn after the failure (assumption: enough to see it; the printer would go on)
LEAD = 30  # frames before the failure, evenly picked, so the failure is a good part of the video
MOTION = 8  # frames of the failure itself
STEP = 1.0  # mm between strand vertices
MAX_SIM = 600.0  # mm of each layer's strand simulated; the rest is drawn dropped straight down
LIMIT = (f"past the first {MAX_SIM:.0f} mm of each layer, the plastic is drawn dropped straight down, neater than the "
         "loose strands it makes")
WHAT = {"supports": "lines with nothing under them print into air and fall (spaghetti)",
        "droop": "a ledge past the reach droops while soft, then curls up",
        "bridge": "a bridge past the usable length sags",
        "detach": "the part comes loose from the plate; later layers print into air",
        "topple": "the nozzle's drag tips the part over; later layers print into air"}
DOMINANT = {"supports": "droop_rule", "droop": "droop_rule", "bridge": "bridge_rule", "detach": "warp_rule",
            "topple": "nozzle_tip"}
REMEDY = {"supports": "supports, or the part turned over", "droop": "supports, or the part turned over",
          "bridge": "supports, or a shorter bridge", "detach": "a clean plate and a brim", "topple": "a brim, or the part lying down"}


def layer_times(tp) -> np.ndarray:
    out = np.zeros(len(tp.layer_z))
    for k in range(len(out)):
        sel = tp.layer == k
        out[k] = tp.t1[sel].max() if sel.any() else 0.0
    return np.maximum.accumulate(out)


def settings(tp, material: str, enclosed: bool, heat: bool = True) -> dict:  # heat False: the file's is for another plastic
    """failsim.Inputs of what this print is run at: the median over its part's moves past the first layer."""
    F = timelapse.gcode.FEATURES
    on = tp.part() & (tp.layer > 0)
    run = np.full((4, 1), np.nan) if tp.run is None else np.where([True, heat, heat, heat], tp.run[on, :4], np.nan).T
    fan, bed, nozzle, chamber = (float(np.median(c[ok])) if (ok := np.isfinite(c)).any() else None for c in run)
    speed, width = (float(np.median(q[s])) if (s := on & (tp.feature == F.index(k))).any() else None
                    for q, k in ((tp.feed, "inner wall"), (tp.width, "outer wall")))
    m = failsim.material(material)
    m = replace(m, nozzle=nozzle or m.nozzle, chamber=chamber if chamber and enclosed else m.chamber)
    got = {"bed": bed, "infill": tp.infill, "speed": speed, "width": width}
    said = [f"{k} {v:.3g} {u}" for k, v, u in (("bed", bed, "C"), ("nozzle", nozzle, "C"), ("chamber", chamber if enclosed else None, "C"),
            ("fan", None if fan is None else 100 * fan, "%"), ("infill", tp.infill, "%"), ("inner wall", speed, "mm/s"),
            ("line", width, "mm")) if v is not None]
    missing = [k for k, v in (("bed", bed), ("nozzle", nozzle), ("fan", fan), ("infill", tp.infill),
                                ("inner wall speed", speed), ("line width", width)) if v is None]
    if enclosed and chamber is None:
        missing.append("chamber")
    notes = [f"this print's own settings: {', '.join(said)}"] if said else []
    if missing:
        notes.append(f"the K2 profile's, not the print's own: {', '.join(missing)}" + (" (fan full on)" if fan is None else ""))
    return {**got, "material": m, "fan": True if fan is None else fan, "notes": notes}


def inputs(tp, material: str = "PLA", clean: float = 1.0, enclosed: bool = True, heat: bool = True) -> failsim.Inputs:
    """failsim's per-layer masks from the toolpath's extruding moves; supports count when it prints them. The gaps
    in sparse infill are filled: failsim's masks are outlines, and it counts the infill's density itself."""
    from scipy import ndimage

    ext = tp.extruding() & (tp.layer >= 0)
    F = timelapse.gcode.FEATURES
    sup = bool((ext & np.isin(tp.feature, [F.index("support"), F.index("support interface")])).any())
    z = np.asarray(tp.layer_z, float)
    thick = float(np.median(np.diff(z))) if len(z) > 1 else float(z[0]) if len(z) else 0.2  # the first layer may differ
    inp = failsim.inputs_from_segments(tp.p0[ext, :2], tp.p1[ext, :2], tp.width[ext], tp.layer[ext], z, layer_times(tp),
                                       layer=thick, clean=clean, supports=sup, enclosed=enclosed)
    inp = replace(inp, **settings(tp, material, enclosed, heat))
    infill = ext & (tp.feature == F.index("sparse infill"))
    for i in np.unique(tp.layer[infill]):
        sel, mk = infill & (tp.layer == i), inp.masks[i]
        a, d = tp.p0[sel, :2], tp.p1[sel, :2] - tp.p0[sel, :2]
        n = int(np.ceil(np.linalg.norm(d, axis=1).max() / inp.cell)) + 1
        at = ((a + d * np.linspace(0, 1, n + 1)[:, None, None]).reshape(-1, 2) - inp.origin) // inp.cell
        near = np.zeros(mk.shape, bool)
        near[at[:, 1].astype(int), at[:, 0].astype(int)] = True
        near = ndimage.binary_dilation(near, iterations=int(np.ceil(np.median(tp.width[sel]) / 2 / inp.cell)))
        lab, _ = ndimage.label(~mk)
        mk |= np.isin(lab, np.setdiff1d(lab[near], [0, lab[0, 0]]))  # a gap that touches infill, never one walls close off
    return inp


def _dist(below: np.ndarray, cell: float) -> np.ndarray:
    from scipy import ndimage

    return ndimage.distance_transform_edt(~below) * cell if below.any() else np.full(below.shape, np.inf)


def pieces(mk: np.ndarray, d: np.ndarray, inp: failsim.Inputs):
    """Each piece of a layer past the reach, with what failsim.predict's rules say of it: (mask, mm past,
    supports, droop, bridge or fine). d is the distance to the layer below."""
    from scipy import ndimage

    eight = np.ones((3, 3))
    free = mk & (d > failsim.reach(inp.layer))
    lab, n = ndimage.label(free, eight)
    whole = ndimage.binary_fill_holes(mk & ~free) if n else None
    for k in range(1, n + 1):
        comp = lab == k
        big, ring = float(d[comp].max()), ndimage.binary_dilation(comp, eight) & mk & ~free
        if not ring.any():
            yield comp, big, "supports"
        elif ndimage.label(ring, eight)[1] >= 2 or whole[comp].all():
            yield comp, big, "bridge" if 2 * big > failsim.fact("max_bridge_length") else "fine"
        else:
            tip, rule = -float(failsim.droop([big], inp.material, inp.layer, _width(inp), inp.fan, inp.air)[0]), failsim.fact("droop_rule")
            yield comp, big, next((m for m in ("supports", "droop") if tip >= rule[m] * inp.layer), "fine")


def _width(inp) -> float:
    return inp.width or failsim.fact("k2_widths")["outer_wall"]


def _first(inp: failsim.Inputs, mode: str):
    """The first layer with a piece that fails the asked way: (layer, piece mask, mm past)."""
    for i in range(1, len(inp.masks)):
        for comp, big, kind in pieces(np.asarray(inp.masks[i], bool), _dist(np.asarray(inp.masks[i - 1], bool), inp.cell), inp):
            if kind == mode:
                return i, comp, big
    return None


def choose(fails: list, mode: str, inp: failsim.Inputs):
    """(the failure to show or None, whether it is a what-if)."""
    real = [f for f in fails if f.kind != "none"]
    if mode == "auto":
        return (real[0] if real else None), False
    want = ("detach", "topple") if mode == "detach" else (mode,)
    for f in real:
        if f.kind in want:
            return f, False
    held = fails[0].numbers if fails and fails[0].kind == "none" else {}
    lay, cell, (ox, oy) = inp.layer, inp.cell, inp.origin
    if mode == "detach":
        i, piece = len(inp.masks) // 3, np.asarray(inp.masks[0], bool)
        nums = {k: held[k] for k in ("push_n", "tip_drive_nmm", "tip_hold_nmm", "edge_stress_mpa", "bond_mpa", "margin") if k in held}
        tax = "bed_adhesion"
    else:
        got = _first(inp, mode)
        if got is None:
            return None, True
        i, piece, big = got
        span = 2 * big
        nums = ({"island": True} if math.isinf(big) else {"past_reach_mm": round(big - failsim.reach(lay), 2)}) if mode == "supports" else (
            {"ledge_mm": round(big, 2), "droop_mm": round(-float(failsim.droop([big], inp.material, lay, _width(inp), inp.fan, inp.air)[0]), 3)} if mode == "droop" else
            {"span_mm": round(span, 1), "sag_mm": round(-float(failsim.bridge_sag(span, [span / 2], lay)[0]), 3),
             "usable_mm": failsim.fact("max_bridge_length")})
        tax = failsim.TAXONOMY[mode]
    r, c = np.nonzero(piece)
    where = (round(ox + (c.mean() + 0.5) * cell, 1), round(oy + (r.mean() + 0.5) * cell, 1))
    why = f"what-if: --fail {mode} asked for it; the model does not predict it for this print"
    base = fails[0].assumptions if fails else []
    return failsim.Failure(mode, i, round(float(inp.layer_z[i]), 2), round(float(inp.layer_t[i]), 1), tax, where, nums,
                           [*base, why]), True


class Story:
    """What the physics draws after the failure: the scene with the moves it took over removed, and per
    frame the extra geometry (ribbons of fallen or bent lines, the loose part, the blob)."""

    def __init__(self, tp, inp: failsim.Inputs, fail: failsim.Failure, rgb, bed):
        self.tp, self.inp, self.fail, self.rgb, self.bed = tp, inp, fail, rgb, bed
        self.kind = "detach" if fail.kind in ("detach", "topple") else fail.kind
        self.L = int(fail.layer or 0)
        self.ext = tp.extruding() & (tp.layer >= 0)
        self.gone = np.zeros(tp.n, bool)
        self.rch, self.cell = failsim.reach(inp.layer), inp.cell
        self.field = np.zeros(np.shape(inp.masks[0]))  # mm, top of what is printed or piled
        self.links: list[tuple] = []  # (from layer, A, B, width): fallen strands, for good
        self.bent: list[tuple] = []  # (layer, points, dz, dist, droops, the layer that bent first, width, height)
        self.dz, self.far = np.zeros(self.field.shape), np.zeros(self.field.shape)  # mm down, mm past the reach
        self.droops, self.since = np.zeros(self.field.shape, bool), np.full(self.field.shape, -1)
        self.notes: list[str] = []
        self.flow = float(np.median((tp.width * tp.height * tp.feed)[self.ext])) if self.ext.any() else 0.0

    def px(self, p):
        h, w = self.field.shape
        ox, oy = self.inp.origin
        return (np.clip(((p[:, 1] - oy) / self.cell).astype(int), 0, h - 1),
                np.clip(((p[:, 0] - ox) / self.cell).astype(int), 0, w - 1))

    def line(self, j, step=STEP) -> np.ndarray:
        a, b = self.tp.p0[j, :3].copy(), self.tp.p1[j, :3]
        a[2] = b[2]
        n = max(1, int(math.ceil(math.hypot(*(b[:2] - a[:2])) / step)))
        return a + (b - a) * np.linspace(0, 1, n + 1)[:, None]

    def strand(self, moves, loose, scale=1.0, keep=False):
        """One layer's air moves as one strand, in print order, free where loose. Returns drop_strand's frames and the
        nozzle's place on the path in each, when keep."""
        parts, printed = [], []
        if not len(moves):
            return []
        for j in moves:
            p = self.line(j)
            if parts:
                if np.linalg.norm(parts[-1][-1] - p[0]) > 1e-6:
                    printed.append(False)  # a travel: the strand trails from the nozzle, nothing is laid
                else:
                    p = p[1:]
                    printed.append(True)
            printed += [True] * (len(p) - 1)
            parts.append(p)
        P = np.vstack(parts)
        if len(P) < 2:
            return []
        cum = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))]
        if cum[-1] < STEP:
            return []
        R = failsim._resample(P, STEP)
        s = np.linspace(0, cum[-1], len(R))
        seg = np.asarray(printed)[np.clip(np.searchsorted(cum, (s[1:] + s[:-1]) / 2, "right") - 1, 0, len(printed) - 1)]
        r, c = self.px(R)
        pins = np.flatnonzero(~loose[r, c])
        sel = self.ext[moves]
        speed = float(np.median(self.tp.feed[moves][sel])) if sel.any() else 200.0
        area = float(np.median((self.tp.width * self.tp.height)[moves][sel])) if sel.any() else self.flow / speed
        flow = area * speed * scale  # the plastic these moves lay
        rad = math.sqrt(flow / speed / math.pi)
        hf = failsim.Heightfield(self.field.copy(), self.cell, self.inp.origin)
        m = int(np.searchsorted(s, MAX_SIM, "right"))
        steps = int(min(2400, (s[min(m, len(s)) - 1] / speed + 0.5) * 300))
        frs = failsim.drop_strand(R[:m], speed, flow, hf, steps=steps, dt=1 / 300, iters=10, seg_mm=None,
                                  pins=pins[pins < m])
        rest = frs[-1] if frs else R[:0]
        tail = R[len(rest):].copy()  # past MAX_SIM, or not laid when the steps ran out: straight down
        free = loose[self.px(tail)]
        tail[free, 2] = hf(tail[free, 0], tail[free, 1]) + rad
        rest = np.vstack([rest, tail])
        if m < len(R):
            self.notes.append(LIMIT)
        laid = rest[np.r_[seg, False] | np.r_[False, seg]]  # a travel between two pieces lays nothing
        np.maximum.at(self.field, self.px(laid), laid[:, 2] + rad)
        self.links.append((self.layer_now, rest[:-1][seg], rest[1:][seg], 2 * rad))
        return [(f, seg[:max(0, len(f) - 1)], 2 * rad, R[len(f) - 1]) for f in frs] if keep else []

    def bend(self, i, moves):
        """The lines of layer i over a piece that bends, or over what bent below."""
        for j in moves:
            p = self.line(j, 0.5)
            at = self.px(p)
            if (self.since[at] >= 0).any():
                self.gone[j] = True
                self.bent.append((i, p, self.dz[at], self.far[at], self.droops[at], self.since[at], float(self.tp.width[j]),
                                  float(self.tp.height[j])))

    def run(self, last: int, fps: float = 30.0):
        """Steps the physics layer by layer from the failure to last. Returns the failure's own motion."""
        tp, inp, L = self.tp, self.inp, self.L
        for j in range(L):
            self.field[np.asarray(inp.masks[j], bool)] = inp.layer_z[j]
        solid = np.asarray(inp.masks[L - 1], bool) if L > 0 else np.zeros(self.field.shape, bool)
        motion = []
        if self.kind == "detach":
            motion = self.loose(fps)
            self.field[:] = 0.0  # the part has moved off its spot: later layers fall to the plate
            self.notes.append(failsim.note("blob_stick"))
        for i in range(L + (self.kind == "detach"), last + 1):
            self.layer_now = i
            moves = np.flatnonzero(self.ext & (tp.layer == i))
            if self.kind == "detach":
                self.gone[moves] = True
                self.strand(moves, np.ones(self.field.shape, bool), 1 - failsim.fact("blob_stick"))
                continue
            mk = np.asarray(inp.masks[i], bool)
            d = _dist(solid, self.cell)
            falls, held = np.zeros(mk.shape, bool), np.zeros(mk.shape, bool)
            self.since[~mk] = -1
            for comp, big, kind in pieces(mk, d, inp):
                if kind == "supports":
                    falls |= comp
                    continue
                held |= comp
                if kind != "fine":
                    dd = d[comp]
                    self.dz[comp] = (failsim.bridge_sag(2 * big, np.minimum(dd, big), inp.layer) if kind == "bridge" else
                                     failsim.droop(dd, inp.material, inp.layer, _width(inp), inp.fan, inp.air))
                    self.far[comp], self.droops[comp], self.since[comp] = np.minimum(dd, 100.0), kind == "droop", i
            solid = mk & ~falls  # what fell supports nothing above it
            self.since[falls] = -1
            self.field[solid] = np.maximum(self.field[solid], inp.layer_z[i])
            loose = (d > self.rch) & ~held
            air = [j for j in moves if loose[self.px(self.line(j))].any()]
            self.gone[air] = True
            got = self.strand(np.asarray(air, int), loose, keep=i == L)
            if i == L and self.kind == "supports":
                motion = got
            self.bend(i, np.setdiff1d(moves, air))
        if self.links and self.kind != "detach":
            self.notes.append(failsim.note("strand_friction"))
        if self.bent:
            self.notes.append("assumption: layers above a sagged or drooped piece lie on it, bent the same way")
        return motion

    def loose(self, fps):
        """The part so far as one rigid body: tipped about its footprint edge, or slid along the nozzle's path."""
        tp, inp, L, f = self.tp, self.inp, self.L, self.fail
        sel = self.ext & (tp.layer <= L)
        self.part = timelapse.ribbons(tp.p0[sel, :3], tp.p1[sel, :3], np.maximum(tp.width[sel], 0.1), np.maximum(tp.height[sel], 0.05))
        r, c = np.nonzero(np.asarray(inp.masks[0], bool))
        fx, fy = inp.origin[0] + (c + 0.5) * self.cell, inp.origin[1] + (r + 0.5) * self.cell
        last = np.flatnonzero(sel & (tp.layer == L))
        if f.kind == "topple" and f.numbers.get("direction"):
            u = np.asarray(f.numbers["direction"], float)
        else:
            u = (tp.p1[last[-1], :2] - tp.p0[last[-1], :2]) if len(last) else np.array([1.0, 0.0])
            u = u / max(np.linalg.norm(u), 1e-9)
        a = np.array([np.asarray(m, bool).sum() for m in inp.masks[:L + 1]], float)
        z = np.asarray(inp.layer_z[:L + 1]) - inp.layer / 2
        com = np.array([fx.mean(), fy.mean(), float((a * z).sum() / max(a.sum(), 1))])
        proj = fx * u[0] + fy * u[1]
        if f.kind == "topple":
            edge = com[:2] + (proj.max() + self.cell / 2 - com[:2] @ u) * u
            mats = failsim.rigid_tip(edge, u, com, fps=fps)
            self.notes.append("the part tips as a solid box about its footprint edge (failsim.rigid_tip)")
        else:
            reach = float(proj.max() - proj.min()) + self.cell
            room = [(b - v.max() if c > 0 else v.min()) / abs(c) for b, v, c in zip(self.bed, (fx, fy), u) if abs(c) > 1e-6]
            mats = failsim.rigid_slide(u, max(0.0, min(reach, *room)), MOTION)
            self.notes.append("assumption: the nozzle drags the loose part one footprint length along its last line, or to the plate's edge")
        self.mats = [mats[k] for k in sorted(set(np.linspace(0, len(mats) - 1, MOTION).round().astype(int)))]
        return self.mats

    def items(self, layer: int, t_s: float, head, motion=None, scale=1.0) -> list[dict]:
        """The extra geometry of a frame showing layer (from the failure on)."""
        out, A, B, W, H = [], [], [], [], []

        def add(a, b, w, h):
            A.append(a), B.append(b), W.append(np.full(len(a), w)), H.append(np.full(len(a), h))

        falling = motion is not None and self.kind == "supports"
        for i, a, b, w in self.links:
            if i <= layer and len(a) and not (falling and i == layer):  # this layer's strand is still on its way down
                add(a, b, w, w)
        if falling:
            f, seg, w, _ = motion
            add(f[:-1][seg], f[1:][seg], w, w)
        for i, p, dz, dd, droops, since, w, h in self.bent:
            if i > layer:
                continue
            q = p.copy()
            q[:, 2] += scale * dz
            for k in np.unique(since[droops]):
                if layer > k:
                    sel = droops & (since == k)
                    q[sel, 2] += failsim.curl(dd[sel], self.inp.material, self.inp.layer, int(layer - k), self.inp.air)
            q[:, 2] = np.maximum(q[:, 2] - h / 2, h / 2)  # the middle of the line
            add(q[:-1], q[1:], w, h)
        if A:
            out.append({"mesh": tubes(np.vstack(A), np.vstack(B), np.concatenate(W), np.concatenate(H)), "rgb": self.rgb})
        if self.kind == "detach":
            T = motion if motion is not None else self.mats[-1]
            V, Q = self.part
            out.append({"mesh": ((V @ T[:3, :3].T + T[:3, 3]).astype(np.float32), Q), "rgb": self.rgb})
            vol = float(failsim.blob_volume(self.flow, max(0.0, t_s - float(self.fail.time or 0.0))))
            if vol > 0 and head is not None:
                import trimesh

                ball = trimesh.creation.icosphere(2, radius=(3 * vol / 4 / math.pi) ** (1 / 3))
                out.append({"mesh": (ball.vertices + np.add(head, (0, 0, ball.bounds[1][2] * 0.3)), ball.faces), "rgb": self.rgb,
                            "name": "blob"})
        return out


def tubes(a: np.ndarray, b: np.ndarray, w: np.ndarray, h: np.ndarray):
    """Each segment (xyz of its middle line) as a box w wide and h high along it, at any slope, stretched half a
    width at each end so a strand has no gaps: 8 vertices, 6 quads."""
    L = np.linalg.norm(b - a, axis=1)
    ok = L > 1e-9
    a, b, w, h, t = a[ok], b[ok], w[ok, None], h[ok, None], (b - a)[ok] / L[ok, None]
    side = np.c_[-t[:, 1], t[:, 0], np.zeros(len(t))]
    n = np.linalg.norm(side, axis=1, keepdims=True)
    side = np.where(n > 1e-6, side / np.maximum(n, 1e-6), [1.0, 0.0, 0.0])
    up = np.cross(t, side)
    ends = [(a - t * w / 2, sy, sz) for sz in (-0.5, 0.5) for sy in (-0.5, 0.5)] + [
        (b + t * w / 2, sy, sz) for sz in (-0.5, 0.5) for sy in (-0.5, 0.5)]
    V = np.stack([e + side * w * sy + up * h * sz for e, sy, sz in ends], 1).reshape(-1, 3)
    quads = np.array([[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]])
    Q = (quads[None] + (np.arange(len(a)) * 8)[:, None, None]).reshape(-1, 4)
    return V.astype(np.float32), Q.astype(np.int32)


def plan(tp, inp, fail, rgb, bed):
    """(scene toolpath, frames, extras per frame, index of the first failure frame, story)."""
    st = Story(tp, inp, fail, rgb, bed)
    L, nl = st.L, len(tp.layer_z)
    last = min(nl - 1, L + AFTER)
    motion = st.run(last)
    base = {f["layer"]: f for f in timelapse.frames(tp, "per-layer")}
    lt = layer_times(tp)
    lead = [k for k in sorted(base) if k < L]
    lead = [lead[k] for k in sorted(set(np.linspace(0, len(lead) - 1, min(LEAD, len(lead))).round().astype(int)))]
    frs, extra = [dict(base[k], note="") for k in lead], [[] for _ in lead]
    first = len(frs)
    tag = WHAT[fail.kind]
    full = (lambda i: 1) if st.kind == "detach" else (lambda i: i + 2)
    t0 = float(lt[L - 1]) if L else 0.0
    fl = base.get(L) or base[max(base)]  # only its nozzle place is used
    picks = motion if st.kind != "supports" else [motion[k] for k in sorted(set(np.linspace(0, len(motion) - 1, MOTION).round().astype(int)))] if motion else []
    if st.kind in ("droop", "bridge"):
        picks = list(np.linspace(0.25, 1.0, MOTION // 2))
    for k, mo in enumerate(picks):
        frac = (k + 1) / len(picks)
        head = list(mo[3]) if st.kind == "supports" else fl["head"]
        t = (float(fail.time or 0) + k / 30.0) if st.kind == "detach" else t0 + frac * (float(lt[L]) - t0)
        frs.append({"t_s": t, "layer": L, "z_mm": float(tp.layer_z[L]), "full": full(L), "part": None, "head": head, "note": tag})
        extra.append(st.items(L, t, head, motion=None if st.kind in ("droop", "bridge") else mo,
                              scale=mo if st.kind in ("droop", "bridge") else 1.0))
    for i in range(L + bool(picks), last + 1):  # the motion frames already showed layer L
        b = base.get(i)
        if b is None:
            continue
        frs.append(dict(b, full=full(i), note=tag))
        extra.append(st.items(i, b["t_s"], b["head"]))
    seen = [it["mesh"][0] for e in extra[first:] for it in e if it.get("name") != "blob"]
    seen += [tp.p1[st.ext & (tp.layer <= L), :3]]
    lo, hi = (f([f(v, axis=0) for v in seen if len(v)], axis=0) for f in (np.min, np.max))
    for fr in frs[first:]:  # close in on the failure: the head's box would hide it
        fr["close"] = [[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]
    p1 = tp.p1.copy()
    p1[st.gone, 3] = tp.p0[st.gone, 3]  # the physics draws these: out of the scene
    return replace(tp, p1=p1), frs, extra, first, st


def caption(png: Path, text: str) -> None:
    from PIL import Image, ImageDraw, ImageFont

    im = Image.open(png).convert("RGB")
    d = ImageDraw.Draw(im)
    size = max(12, im.size[1] // 28)
    while size > 8 and ImageFont.load_default(size=size).getlength(text) > im.size[0] - 16:
        size -= 1
    font = ImageFont.load_default(size=size)
    d.rectangle((0, im.size[1] - font.size - 10, im.size[0], im.size[1]), fill=(0, 0, 0))
    d.text((8, im.size[1] - font.size - 6), text, fill=(255, 90, 70), font=font)
    im.save(png)


def numbers_line(f) -> str:
    n = f.numbers
    if "edge_stress_mpa" in n and "bond_mpa" in n:
        return f"edge pull {n['edge_stress_mpa']} MPa against a plate bond of {n['bond_mpa']} MPa (margin {n.get('margin')})"
    if "drive_nmm" in n:
        return f"nozzle drag {n['push_n']} N at {n['height_mm']} mm tips with {n['drive_nmm']} N mm against {n['adhesion_nmm']} N mm of hold"
    if "push_n" in n and "hold_n" in n:
        return f"nozzle drag {n['push_n']} N against {n['hold_n']} N of plate shear hold"
    if "span_mm" in n:
        return f"span {n['span_mm']} mm (usable {n.get('usable_mm')} mm) sags {n['sag_mm']} mm"
    if "droop_mm" in n:
        return f"ledge {n.get('ledge_mm')} mm past the layer below droops {n['droop_mm']} mm"
    if n.get("island"):
        return "a piece starts in mid air"
    return ", ".join(f"{k} {v}" for k, v in n.items()) or "no numbers"


def cmd(args, job, prof, out):
    """stone timelapse --fail [mode]: fail.mp4, fail_sheet.png and fail.json."""
    from . import refs

    t_start = time.time()
    if args.fail not in MODES and not args.file and Path(args.fail).suffix:  # stone timelapse --fail part.stl
        args.file, args.fail = args.fail, "auto"
    mode = args.fail
    if mode not in MODES:
        out.fix(f"--fail {mode}: one of {', '.join(MODES)}")
        args.fail = "auto"
        out.next = timelapse.again(args)
        return out
    if args.mode != "per-layer":
        out.fix("--fail draws one frame a layer; drop --mode")
        out.next = timelapse.again(args, **{"--mode": None})
        return out
    if args.material and not failsim.named(args.material):
        out.fix(f"--material {args.material}: the model has no numbers for it; it has {', '.join(failsim.MATERIALS)}")
        out.next = "ask the person: which of these is closest? Then: " + timelapse.again(args, **{"--material": "<" + "|".join(failsim.MATERIALS) + ">"})
        return out
    asked, without = args.supports, mode not in ("auto", "detach") and not args.gcode
    args.supports = "off" if without else asked  # these modes draw the part without them
    got = timelapse.start(args, job, prof, out)
    args.supports = asked
    if got is None:
        return out
    tp, what, f = got
    if without and asked != "off":  # a what-if when the print as asked has supports
        from . import supports

        without = asked == "on" or supports.analyze(supports.load(f), columns=True)["needed"]
    asked_for = refs.material_for(job.request()).material.upper() if job.exists() else ""
    said = (args.material or tp.material or asked_for).upper()
    own, file = failsim.named(said), failsim.named(tp.material)
    mat = own or failsim.named(asked_for) or "PLA"
    note = [f"material: PLA is assumed; say --material {', '.join(failsim.MATERIALS[1:-1])} or {failsim.MATERIALS[-1]}" if not said else
            f"material: the model has no numbers for {said}, so this is {mat}'s; it has {', '.join(failsim.MATERIALS)}" if not own else
            f"material: {mat}" + ("" if mat == said else f", for {said}") + ("" if args.material or not tp.material else ", the G-code says")]
    heat = file == mat or bool(own) and not file  # the file's is for this plastic
    clean = failsim.fact("contamination") if args.plate == "dirty" else 1.0
    inp = inputs(tp, mat, clean, prof.get("enclosed", True), heat)
    fails = failsim.predict(inp)
    fail, what_if = choose(fails, mode, inp)
    taken = without and asked != "off"
    out.add(f"This is a model, not a recording: failsim's physics on the toolpath {what}.", *(f"{x[0].upper()}{x[1:]}." for x in (*note, *inp.notes)))
    nxt = job.status().get("next") if job.exists() else None
    if fail is None:
        if mode == "auto":
            out.add("No failure predicted; nothing to show. --fail detach shows a loose part anyway.")
            n = fails[0].numbers if fails else {}
            if "margin" in n:
                out.add(f"Plate bond margin {n['margin']} (above 1 holds).")
            out.result = "no failure predicted"
            out.next = nxt if nxt and nxt != "stone status" else "none, no failure predicted"
        else:
            out.add(f"Nothing here fails by {mode}, so there is nothing to show. --fail detach shows a loose part anyway.")
            out.result = "nothing to show"
            out.next = "none, nothing to show"
        return out
    loose = fail.kind in ("detach", "topple")
    dom = failsim.note("contamination" if clean < 1 and loose else "nozzle_tip" if "hold_n" in fail.numbers else DOMINANT[fail.kind])
    said = "What-if (drawn without supports, which this print has)" if taken else (
        "What-if (you asked for it, the model does not predict it)" if what_if else "Predicted")
    what_if = what_if or taken
    real = fails[0] if fails[0].kind != "none" and (fails[0].layer or 0) < (fail.layer or 0) else None
    if real:
        out.add(f"Before that, the model predicts {real.kind} at layer {(real.layer or 0) + 1}; --fail shows it.")
    out.add(f"{said}: "
            f"{fail.kind} at layer {(fail.layer or 0) + 1} (z {fail.z} mm, {timelapse.clock(fail.time or 0)} in): {WHAT[fail.kind]}.")
    out.add(f"Why: {numbers_line(fail)}.")
    out.add(f"Main assumption: {dom}")
    done = nxt if nxt and nxt != "stone status" else "none, the failure video is made"
    if not what_if:
        done = f"ask the person: the model says this print fails ({fail.kind}); print it with {REMEDY[fail.kind]}?"
    no = timelapse.missing()
    if no:
        out.fix(f"no video: {no}")
        out.next = done if not what_if else "none, the what-if is above; the video needs that program"
        return out
    dest = timelapse.out_dir(args, job, f)
    rgb = timelapse.color(job)[1]
    scene, frs, extra, first, st = plan(tp, inp, fail, rgb, prof["build_volume_mm"][:2])
    label = "MODEL, not a recording" + (": what-if" if what_if else "") + f": {WHAT[fail.kind]}"
    mp4, png, js = dest / "fail.mp4", dest / "fail_sheet.png", dest / "fail.json"
    try:
        cam = timelapse.camera(job, prof)
        size = (timelapse.SIZE[0], int(round(timelapse.SIZE[0] / timelapse.aspect(cam.get("aspect")) / 2)) * 2)
        files = timelapse.render(scene, frs, prof, cam, dest / "fail", rgb, args.night, size, extras=lambda k, fr: extra[k],
                                 log=job.log if job.exists() else None)
        for p in files[first:]:
            caption(p, label)
        secs = timelapse.video(files, mp4, args.seconds)
        pick = list(range(max(0, first - 2), first)) + sorted(set(np.linspace(first, len(files) - 1, 7).round().astype(int).tolist()))
        timelapse.sheet(files, frs, png, pick=pick)
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as e:
        out.fix(f"no video: {timelapse.why(e)}")
        out.next = done if not what_if else "none, the what-if is above"
        return out
    finally:
        for x in (dest / "fail").glob("*.npz"):
            x.unlink()
    data = {"model_not_recording": True, "mode": mode, "what_if": what_if, "kind": fail.kind, "taxonomy": fail.taxonomy,
            "what": WHAT[fail.kind], "layer": fail.layer, "layer_number": (fail.layer or 0) + 1, "z_mm": fail.z,
            "time_s": fail.time, "where_mm": fail.where, "numbers": fail.numbers, "dominant_assumption": dom,
            "assumptions": [*fail.assumptions, *note, *dict.fromkeys(st.notes)], "material": mat, "plate": args.plate,
            "predicted": [x.kind for x in fails], "source": what, "input": str(f), "printer": prof.get("id"), "camera": cam, "video_s": round(secs, 2),
            "pre_failure_frame": str(files[first - 1].relative_to(dest)) if first else None,
            "first_failure_frame": str(files[first].relative_to(dest)),
            "frames": [{"t_s": round(fr["t_s"], 2), "layer": fr["layer"], "z_mm": fr["z_mm"], "failing": k >= first,
                        "frame": str(p.relative_to(dest))} for k, (fr, p) in enumerate(zip(frs, files))]}
    js.write_text(json.dumps(data, indent=1, default=float))
    out.add(f"Video: {mp4} ({len(files)} frames, {secs:.1f} s; from layer {(fail.layer or 0) + 1} on: the model, closer in, "
            "only the nozzle drawn)")
    if LIMIT in st.notes:
        out.add(f"Limit: {LIMIT}.")
    out.add(f"Sheet: {png}")
    out.add(f"Data: {js} ({time.time() - t_start:.0f} s)")
    out.result = f"failure video made: {fail.kind}{' (what-if)' if what_if else ''}"
    out.next = done
    return out
