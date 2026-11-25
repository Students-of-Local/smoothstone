"""stone timelapse --fail: this print failing the way failsim's physics says it would, on stone
timelapse's own toolpaths, renderer and camera. A model, not a recording.

auto shows the first failure failsim.predict finds. A named mode (supports, detach, droop, bridge) shows
that one where the model's own rules put it; detach also on a part that holds. What the print as asked
does not do is labeled a what-if. Up to the failure the frames are the normal timelapse's, at most LEAD of
them. From it on, every piece that fails by failsim's rules moves, and the rest prints:
- supports: each layer's lines over air are strands (strand.py), held where they lie on printed plastic,
  falling and piling on what is below; lines above them print into air too;
- droop: lines past the reach bend down (failsim.droop) and curl up as layers go on (failsim.curl);
- bridge: lines held at both ends hang as a catenary (failsim.bridge_sag); layers above rest on what hangs;
- detach and topple: the part slides (failsim.rigid_slide) or tips (rigid_tip), every later layer
  prints into air as a strand the hotend drags along, and plastic builds on the nozzle: what its tip carries
  (failsim.nozzle_hold), and everything where the pile reaches it.
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

from . import failsim, strand, timelapse

MODES = ("auto", "supports", "detach", "droop", "bridge")
AFTER = 12  # layers drawn after the failure (assumption: enough to see it; the printer would go on)
LEAD = 30  # frames before the failure, evenly picked, so the failure is a good part of the video
MOTION = 8  # frames of the failure itself
SIM = 60.0  # s of printing into air followed in all, shared by the layers; more is left out and said
LIMIT = "s of printing into air is not drawn: the video follows"
FALL = 480  # steps of strand.DT a dropped piece is followed, 2 s
FALLS = 40000  # and all of them together
KEEP = 60.0  # mm of strand behind the nozzle that stays free to move
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
    unsaid = failsim.note("k2_air") if failsim.note("k2_air") in m.stand_ins else None  # its profile names no chamber
    if chamber and enclosed:
        m = replace(m, chamber=chamber, stand_ins=tuple(x for x in m.stand_ins if x != unsaid))
    m = replace(m, nozzle=nozzle or m.nozzle)
    got = {"bed": bed, "infill": tp.infill, "speed": speed, "width": width}
    said = [f"{k} {v:.3g} {u}" for k, v, u in (("bed", bed, "C"), ("nozzle", nozzle, "C"), ("chamber", chamber if enclosed else None, "C"),
            ("fan", None if fan is None else 100 * fan, "%"), ("infill", tp.infill, "%"), ("inner wall", speed, "mm/s"),
            ("line", width, "mm")) if v is not None]
    missing = [k for k, v in (("bed", bed), ("nozzle", nozzle), ("fan", fan), ("infill", tp.infill),
                                ("inner wall speed", speed), ("line width", width)) if v is None]
    if enclosed and chamber is None and not unsaid:
        missing.append("chamber")
    notes = [f"this print's own settings: {', '.join(said)}"] if said else []
    if missing:
        notes.append(f"the K2 profile's, not the print's own: {', '.join(missing)}" + (" (fan full on)" if fan is None else ""))
    if enclosed and chamber is None and unsaid:
        notes.append(unsaid)
    return {**got, "material": m, "fan": True if fan is None else fan, "notes": notes}


def moves_of(tp, *features) -> np.ndarray:
    F = timelapse.gcode.FEATURES
    return tp.extruding() & (tp.layer >= 0) & np.isin(tp.feature, [F.index(k) for k in features])


def inputs(tp, material: str = "PLA", clean: float = 1.0, enclosed: bool = True, heat: bool = True) -> failsim.Inputs:
    """failsim's per-layer masks from the toolpath's extruding moves, the part's and its supports': a skirt and a prime
    tower are not its footprint or its weight. The gaps in sparse infill are filled: failsim's masks are outlines, and
    it counts the infill's density itself."""
    from scipy import ndimage

    F = timelapse.gcode.FEATURES
    ext, skirt = tp.extruding() & (tp.layer >= 0), moves_of(tp, "skirt")
    sup = moves_of(tp, "support", "support interface")
    z = np.asarray(tp.layer_z, float)
    thick = float(np.median(np.diff(z))) if len(z) > 1 else float(z[0]) if len(z) else 0.2  # the first layer may differ
    masks = lambda of, z, **kw: failsim.inputs_from_segments(  # noqa: E731  # every move sizes the grid, some are drawn
        tp.p0[ext, :2], tp.p1[ext, :2], tp.width[ext], np.where(of, tp.layer, -1)[ext], z, **kw)
    inp = masks(ext & ~skirt & ~moves_of(tp, "prime tower"), z, layer_t=layer_times(tp), layer=thick, clean=clean, supports=bool(sup.any()), enclosed=enclosed)
    inp = replace(inp, **settings(tp, material, enclosed, heat))
    rim, foot = masks(skirt, z[:1]).masks[0], inp.masks[0]
    lab, _ = ndimage.label(ndimage.binary_dilation(rim | foot))  # a slicer leaves a hair between brim and part
    inp.brim = rim & np.isin(lab, np.setdiff1d(lab[foot], 0))
    if inp.brim.any():
        inp.notes.append("assumption: the brim holds against sliding only; what it holds against tipping and curling corners is not "
                         "counted, so this print holds better than the model says")
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


def _below(inp: failsim.Inputs, i: int) -> np.ndarray:
    """What layer i is printed on: the layer under it, and the brim round the first."""
    mk = np.asarray(inp.masks[i - 1], bool)
    return mk if i > 1 or inp.brim is None else mk | inp.brim


def _first(inp: failsim.Inputs, mode: str):
    """The first layer with a piece that fails the asked way: (layer, piece mask, mm past)."""
    for i in range(1, len(inp.masks)):
        for comp, big, kind in pieces(np.asarray(inp.masks[i], bool), _dist(_below(inp, i), inp.cell), inp):
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
        self.gone = np.zeros(tp.n, bool)
        self.rch, self.cell = failsim.reach(inp.layer), inp.cell
        self.field = np.zeros(np.shape(inp.masks[0]))  # mm, top of what is printed or piled
        self.origin = inp.origin
        skirt = moves_of(tp, "skirt")  # this and a prime tower stay when the part goes; a brim goes with it
        if inp.brim is not None:
            skirt[skirt] &= ~((tp.layer[skirt] == 0) & inp.brim[self.px(tp.p1[skirt, :3])])
        self.prints = tp.extruding() & (tp.layer >= 0)
        self.ext = self.prints & ~skirt & ~moves_of(tp, "prime tower")
        self.links: list[tuple] = []  # (from layer, A, B, width): fallen strands, for good
        self.rod, self.live = None, {}  # the strand on the nozzle, and where it was when each layer ended
        self.blob, self.blobs, self.left = 0.0, {}, 0.0  # mm3 on the nozzle, by layer; s of printing left out
        self.hold = failsim.nozzle_hold(inp.material)["blob_mm3"]
        self.bent: list[tuple] = []  # (layer, points, dz, dist, droops, the layer that bent first, width, height)
        self.dz, self.far = np.zeros(self.field.shape), np.zeros(self.field.shape)  # mm down, mm past the reach
        self.droops, self.since = np.zeros(self.field.shape, bool), np.full(self.field.shape, -1)
        self.notes: list[str] = []
        took = np.maximum(tp.t1 - tp.t0, 1e-9)
        self.speed = np.linalg.norm((tp.p1 - tp.p0)[:, :3], axis=1) / took  # mm/s, the mean of each move
        self.flows = np.where(self.ext, tp.width * tp.height * self.speed, 0.0)  # mm3/s
        self.flew = np.zeros(tp.n, bool)  # printed into air
        self.told, self.cut, self.falls = 0.0, 0, FALLS  # s of it followed; pieces drawn before they lay still; steps left for them
        self.owed = 0.0  # mm3 a strand started with that has not come out yet
        self.mean = lambda q, of: float(np.average(q[of], weights=took[of])) if of.any() else 0.0
        self.flow, self.mean_speed = self.mean(self.flows, self.ext), self.mean(self.speed, self.ext)

    def px(self, p):
        h, w = self.field.shape
        ox, oy = self.origin
        return (np.clip(((p[:, 1] - oy) / self.cell).astype(int), 0, h - 1),
                np.clip(((p[:, 0] - ox) / self.cell).astype(int), 0, w - 1))

    def off(self, p):
        """Past the grid's edge: bare plate."""
        q = (p[:, :2] - self.origin) / self.cell
        return ((q < 0) | (q >= self.field.shape[::-1])).any(1)

    def line(self, j, step=1.0) -> np.ndarray:
        a, b = self.tp.p0[j, :3].copy(), self.tp.p1[j, :3]
        a[2] = b[2]
        n = max(1, int(math.ceil(math.hypot(*(b[:2] - a[:2])) / step)))
        return a + (b - a) * np.linspace(0, 1, n + 1)[:, None]

    def runs(self, i, air):
        """Layer i's lines in air and the travels after them, in print order: what one strand does until the nozzle
        prints on plastic again."""
        out, now = [], []
        for j in np.flatnonzero(self.tp.layer == i):
            if self.prints[j] and not air[j]:
                out.append(now)
                now = []
            elif self.ext[j] or now:
                now.append(j)
        return [np.array(r) for r in [*out, now] if r]

    def stamp(self, p, k):
        """Points as tops of the field, k cells round each."""
        for off in np.ndindex(2 * k + 1, 2 * k + 1):
            at = p + np.array([*((np.array(off) - k) * self.cell), 0.0])
            at = at[~self.off(at)]
            np.maximum.at(self.field, self.px(at), at[:, 2])

    def lay(self, moves, T=np.eye(4)):
        """Printed lines in the field, where T has taken them."""
        ps = [self.line(j, self.cell) for j in moves]
        k = np.repeat(np.round(self.tp.width[moves] / 2 / self.cell).astype(int), [len(p) for p in ps])
        for n in np.unique(k):
            self.stamp(np.vstack(ps)[k == n] @ T[:3, :3].T + T[:3, 3], n)

    def pile(self, i, pts, d, skip=0):
        """A strand that lies still: drawn for good, and something to land on."""
        if len(pts) < 2:
            return
        self.links.append((i, pts[:-1], pts[1:], d))
        pts = pts[:len(pts) - skip]
        for a, b, w in zip(pts[:-1], pts[1:], d):
            n = int(math.ceil(np.linalg.norm(b - a) / self.cell)) + 1
            p = a + (b - a) * np.linspace(0, 1, n)[:, None]
            self.stamp(p + (0, 0, w / 2), int(round(w / 2 / self.cell)))

    def drop(self, i, s, pin=False):
        """What the nozzle let go, or pressed onto plastic, falls until it lies still; where it necks to a hair it breaks."""
        s.nozzle = False
        s.fixed[-1] |= pin
        for k in range(FALL):
            if len(s.x) < 2:
                return
            self.falls -= 1
            if self.falls < 0:
                self.cut += 1
                break
            s.step()
            off = s.snap()
            for piece in off:
                self.drop(i, piece)
            if not off and k > 10 and np.abs(s.v).max() < 0.005:
                break
        else:
            self.cut += 1
        self.pile(i, s.points(), s.diameters())

    def strand(self, i, run, loose, secs, keep=False):
        """The moves of one run, followed for at most secs: one strand.Strand out of the nozzle, at the print's own speed
        and flow. Travels lay nothing; the nozzle drags the strand. Returns (pieces of this layer, nozzle) as it goes, when keep."""
        tp, m, d, dt = self.tp, self.inp.material, strand.exit_diameter(), strand.DT
        z, t0, t1 = float(self.inp.layer_z[i]), tp.t0[run], tp.t1[run]
        came = np.r_[0.0, np.cumsum(self.flows[run] * (t1 - t0))]  # mm3 out of the nozzle by each move's end
        first, snaps = len(self.links), []
        high = max(z - d, 0.0)  # what lies higher, the nozzle pushes down
        ground = lambda x, y: np.where(self.off(np.c_[x, y]), 0.0, np.minimum(self.field[self.px(np.c_[x, y])], high))  # noqa: E731
        plastic = lambda x, y: ground(x, y) > 0  # noqa: E731
        if self.rod is not None:
            self.rod.ground, self.rod.plastic = ground, plastic
        took = float(t1[-1] - t0[0])
        n = math.ceil(took / dt - 1e-9) if took <= secs else int(secs / dt)
        was = tp.p0[run[0], :3]
        for q in range(n):
            t = t0[0] + (q + 1) * dt
            k = min(int(np.searchsorted(t1, t)), len(run) - 1)
            head = tp.p0[run[k], :3] + float(np.clip((t - t0[k]) / max(t1[k] - t0[k], 1e-9), 0, 1)) * (tp.p1[run[k], :3] - tp.p0[run[k], :3])
            out = float(np.diff(np.interp([t - dt, t], np.r_[t0[0], t1], came))[0]) / dt
            at = self.px(head[None])
            solid = not loose[at][0]
            if self.kind == "detach" and (self.blob < self.hold or self.field[at][0] > head[2] - (z - float(self.inp.layer_z[i - 1])) / 2):
                self.blob, out = self.blob + out * dt, 0.0  # the tip carries it, or it has nowhere to go
            if self.rod is None:
                if out <= 0:
                    was = head
                    continue
                first_up = was - (0, 0, min(d, max(was[2] - d / 2, d / 4)))
                self.rod = strand.Strand([first_up, was], d, m, bore=d / failsim.fact("die_swell"), fan=self.inp.fan, air=self.inp.air,
                                         ground=ground, plastic=plastic, nozzle=True, held=() if loose[self.px(was[None])][0] else (0,))
                self.owed += float(self.rod.vol[0]) * 1e9
            s, was, paid = self.rod, head, min(self.owed, out * dt)  # what it starts with comes out of the flow that follows
            self.owed -= paid
            s.flow = (out - paid / dt) * 1e-9
            s.step(dt, head)
            if solid and out > 0 and len(s.x) > 2 and not loose[self.px(s.points()[-2:-1])][0]:  # printed on plastic as usual
                s.fixed[-2], s.v[-2], s.x[-2, 2] = True, 0.0, max(z - d / 2, d / 2) * 1e-3
            if q % 40 == 0 and len(s.x) > 250:
                self.pile(i, *s.lay(2 * KEEP), skip=3)
            for piece in s.snap():
                self.drop(i, piece)
            if len(s.x) < 2:
                self.rod = None
            if keep and q % max(1, n // 60) == 0:
                got = [(np.vstack([a, b[-1:]]), w) for _, a, b, w in self.links[first:]]
                snaps.append((got + ([(s.points(), s.diameters())] if self.rod else []), head))
        self.left += max(0.0, took - n * dt)
        cut = took > secs
        for j in run[self.ext[run] & (t1 > t0[0] + n * dt)] if cut else ():  # not followed, but laid where there is plastic under it
            p = self.line(j, 0.5)
            on = ~loose[self.px(p)] & (tp.t0[j] + np.linspace(0, 1, len(p)) * (tp.t1[j] - tp.t0[j]) >= t0[0] + n * dt)
            for part in np.split(np.arange(len(p)), np.flatnonzero(np.diff(on)) + 1):
                if on[part[0]] and len(part) > 1:
                    flat = np.zeros(len(part))
                    self.bent.append((i, p[part], flat, flat, flat > 0, flat.astype(int) + i, float(tp.width[j]), float(tp.height[j])))
        if self.rod is not None:
            if self.kind != "detach" or cut:
                s, self.rod = self.rod, None
                self.drop(i, s, pin=not cut and not loose[self.px(tp.p1[run[-1:], :3])][0])
            else:
                self.pile(i, *self.rod.lay(KEEP), skip=3)
                self.live[i] = (self.rod.points(), self.rod.diameters())
        return snaps

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
            self.field[_below(inp, j + 1)] = inp.layer_z[j]
        other = self.prints & ~self.ext  # a skirt, a prime tower
        self.lay(np.flatnonzero(other & (tp.layer < L)))
        solid = _below(inp, L) if L > 0 else np.zeros(self.field.shape, bool)
        motion = []
        if self.kind == "detach":
            motion = self.loose(fps)
            self.moved()
            self.blob = min(self.hold, self.flow * len(motion) / fps)
            self.notes.append(failsim.note("nozzle_tip"))
        layers = range(L + (self.kind == "detach"), last + 1)
        for i in layers:
            secs = (SIM - self.told) / (last + 1 - i)
            moves, was = np.flatnonzero(self.ext & (tp.layer == i)), self.field.copy()
            self.lay(np.flatnonzero(other & (tp.layer == i)))  # the tower grows on
            tower = self.field > was
            if self.kind == "detach":
                self.gone[moves] = True
                if len(moves):
                    run = np.flatnonzero(tp.layer == i)
                    self.strand(i, run, np.ones(self.field.shape, bool), secs)
                    self.told += min(secs, float(tp.t1[run[-1]] - tp.t0[run[0]]))
                    self.flew[moves] = True
                self.blobs[i] = self.blob
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
            loose = (d > self.rch) & ~held & ~tower
            air = [j for j in moves if loose[self.px(self.line(j))].any()]
            self.gone[air] = self.flew[air] = True
            over = np.zeros(tp.n, bool)
            over[air] = True
            for run in self.runs(i, over):
                took = float(tp.t1[run[-1]] - tp.t0[run[0]])
                before = [(np.vstack([a, b[-1:]]), w) for k, a, b, w in self.links if k == i]  # where the runs before lie
                got = self.strand(i, run, loose, secs, keep=i == L)
                self.told, secs = self.told + min(secs, took), max(0.0, secs - took)
                if i == L and self.kind == "supports":
                    motion += [(before + pieces, head) for pieces, head in got]
            if i == L and motion:  # and where they come to lie
                motion.append(([(np.vstack([a, b[-1:]]), w) for k, a, b, w in self.links if k == i], motion[-1][1]))
            self.bend(i, np.setdiff1d(moves, air))
        if self.flew.any():
            self.flow, self.mean_speed = self.mean(self.flows, self.flew), self.mean(self.speed, self.flew)
        if self.cut:
            self.notes.append(f"{self.cut} pieces were followed no further (2 s each, {FALLS} steps in all) and are drawn as they were then")
        if self.links:
            self.notes += [failsim.note(k) for k in ("die_swell", "strand_friction", "weld_rule", "fan_reach", "thread_limit")]
            self.notes.append("assumption: a 0.4 mm nozzle, whatever the lines' width")
        if self.left > 0.5:
            self.notes.append(f"{self.left:.0f} {LIMIT} {self.told:.0f} s of it, the start of each layer")
        if any((b[2] != 0).any() for b in self.bent):
            self.notes.append("assumption: layers above a sagged or drooped piece lie on it, bent the same way")
        return motion

    def loose(self, fps):
        """The part so far as one rigid body: tipped about its footprint edge, or slid along the nozzle's path."""
        tp, inp, L, f = self.tp, self.inp, self.L, self.fail
        sel = self.ext & (tp.layer <= L)
        self.part = timelapse.ribbons(tp.p0[sel, :3], tp.p1[sel, :3], np.maximum(tp.width[sel], 0.1), np.maximum(tp.height[sel], 0.05))
        r, c = np.nonzero(np.asarray(inp.masks[0], bool))
        fx, fy = inp.origin[0] + (c + 0.5) * self.cell, inp.origin[1] + (r + 0.5) * self.cell
        foot = sel & (tp.layer == 0)  # all that moves with it, a brim too
        ends, half = np.vstack([tp.p0[foot, :2], tp.p1[foot, :2]]), np.tile(tp.width[foot] / 2, 2)[:, None]
        last = np.flatnonzero(sel & (tp.layer == L))
        if f.kind == "topple" and f.numbers.get("direction"):
            u = np.asarray(f.numbers["direction"], float)
        else:
            u = (tp.p1[last[-1], :2] - tp.p0[last[-1], :2]) if len(last) else np.array([1.0, 0.0])
            u = u / max(np.linalg.norm(u), 1e-9)
        a = np.array([np.asarray(m, bool).sum() for m in inp.masks[:L + 1]], float)
        z = np.asarray(inp.layer_z[:L + 1]) - inp.layer / 2
        com = np.array([fx.mean(), fy.mean(), float((a * z).sum() / max(a.sum(), 1))])
        proj = ends @ u
        near, far = float((proj - half[:, 0]).min()), float((proj + half[:, 0]).max())
        if f.kind == "topple":
            edge = com[:2] + (far - com[:2] @ u) * u
            mats = failsim.rigid_tip(edge, u, com, fps=fps)
            self.notes.append("the part tips as a solid box about its footprint edge (failsim.rigid_tip)")
        else:
            room = [(b - hi if c > 0 else lo) / abs(c) for b, lo, hi, c in zip(self.bed, (ends - half).min(0), (ends + half).max(0), u) if abs(c) > 1e-6]
            mats = failsim.rigid_slide(u, max(0.0, min(far - near, *room)), MOTION)
            self.notes.append("assumption: the nozzle drags the loose part one footprint length along its last line, or to the plate's edge; "
                              "a skirt or tower in its way does not stop it")
        self.mats = [mats[k] for k in sorted(set(np.linspace(0, len(mats) - 1, MOTION).round().astype(int)))]
        return self.mats

    def moved(self):
        """The field once the part has come loose, as wide as the plate: its plastic where it lies now, and what stays."""
        tp, T, (h, w) = self.tp, self.mats[-1], self.field.shape
        lo = np.minimum(0.0, self.origin)
        hi = np.maximum(self.bed, np.add(self.origin, (w * self.cell, h * self.cell)))
        self.origin, self.field = tuple(lo), np.zeros(tuple(np.ceil((hi - lo) / self.cell).astype(int)[::-1] + 1))
        on = self.prints & (tp.layer <= self.L)
        self.lay(np.flatnonzero(on & self.ext), T)
        self.lay(np.flatnonzero(on & ~self.ext))

    def items(self, layer: int, t_s: float, head, motion=None, scale=1.0) -> list[dict]:
        """The extra geometry of a frame showing layer (from the failure on)."""
        out, A, B, W, H = [], [], [], [], []

        def add(a, b, w, h):
            A.append(a), B.append(b), W.append(np.full(len(a), w)), H.append(np.full(len(a), h))

        falling = motion is not None and self.kind == "supports"
        for i, a, b, w in self.links:
            if i <= layer and not (falling and i == layer):  # this layer's strand is still on its way down
                add(a, b, w, w)
        for p, d in (motion[0] if falling else [self.live[layer]] if layer in self.live and motion is None else []):
            add(p[:-1], p[1:], d, d)
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
            stays = self.prints & ~self.ext & (self.tp.layer <= layer)  # skirt, prime tower
            if stays.any():
                out.append({"mesh": timelapse.ribbons(self.tp.p0[stays, :3], self.tp.p1[stays, :3], np.maximum(self.tp.width[stays], 0.1),
                                                      np.maximum(self.tp.height[stays], 0.05)), "rgb": self.rgb})
            vol = self.blobs.get(layer, 0.0) if motion is None else min(self.hold, self.flow * max(0.0, t_s - float(self.fail.time or 0.0)))
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
        head = list(mo[1]) if st.kind == "supports" else fl["head"]
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
    if "island" in n or "island_mm2" in n:
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
    if failsim.like(mat) != mat:
        note.append(failsim.note("like"))
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
        remedy = REMEDY[fail.kind]
        if inp.brim is not None and inp.brim.any():  # it has one
            remedy = {"detach": "a clean plate", "topple": "the part lying down"}.get(fail.kind, remedy)
        done = f"ask the person: the model says this print fails ({fail.kind}); print it with {remedy}?"
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
            "predicted": [x.kind for x in fails], "strand": strand.numbers(inp.material, st.flow, st.mean_speed, air_c=inp.air, fan=float(inp.fan)), "source": what, "input": str(f), "printer": prof.get("id"), "camera": cam, "video_s": round(secs, 2),
            "pre_failure_frame": str(files[first - 1].relative_to(dest)) if first else None,
            "first_failure_frame": str(files[first].relative_to(dest)),
            "frames": [{"t_s": round(fr["t_s"], 2), "layer": fr["layer"], "z_mm": fr["z_mm"], "failing": k >= first,
                        "frame": str(p.relative_to(dest))} for k, (fr, p) in enumerate(zip(frs, files))]}
    js.write_text(json.dumps(data, indent=1, default=float))
    out.add(f"Video: {mp4} ({len(files)} frames, {secs:.1f} s; from layer {(fail.layer or 0) + 1} on: the model, closer in, "
            "only the nozzle drawn)")
    if st.links:
        n = data["strand"]
        out.add(f"Strand: {n['strand_mm']} mm thick, it leaves the nozzle at {n['payout_mm_s']} mm/s while the nozzle moves at {n['nozzle_mm_s']}. "
                f"Pulling it that fast takes {n['draw_mn']} mN; 100 mm of it on the plate holds {n['plate_grip_mn_per_100mm']} mN, so "
                f"the hotend {'lets it fall slack' if not n['draw_mn'] else 'drags it along' if n['draw_mn'] > n['plate_grip_mn_per_100mm'] else 'draws it thin'} until something holds it.")
        out.add(f"Air and heat: it falls at {n['fall_mm_s'] / 1000:.1f} m/s at most, and sets in {n['set_s_still_air']} s"
                + (f" ({n['set_s_fan']} s in the fan's air)" if inp.fan else "") + f". The nozzle's tip carries {n['blob_mm3']} mm3.")
    for x in (x for x in st.notes if LIMIT in x):
        out.add(f"Limit: {x}.")
    out.add(f"Sheet: {png}")
    out.add(f"Data: {js} ({time.time() - t_start:.0f} s)")
    out.result = f"failure video made: {fail.kind}{' (what-if)' if what_if else ''}"
    out.next = done
    return out
