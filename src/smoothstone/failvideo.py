"""stone timelapse --fail: this print failing the way failsim's physics says it would, on stone
timelapse's own toolpaths, renderer and camera. A model, not a recording.

auto shows the first failure failsim.predict finds; a named mode (supports, detach, droop, bridge)
shows that failure even when the model says the print holds, labeled a what-if. Up to the failure the
frames are the normal timelapse's. From it on, the physics moves what is drawn:
- supports: each layer's lines over air are one strand (failsim.drop_strand), held where it lies on
  printed plastic, falling and piling on what is below; lines above them print into air too;
- droop: lines past the reach bend down (failsim.droop) and curl up as layers go on (failsim.curl);
- bridge: lines held at both ends hang as a catenary (failsim.bridge_sag);
- detach and topple: the part slides (failsim.rigid_slide) or tips (rigid_tip), every later layer
  prints into air, and plastic builds on the nozzle (failsim.blob_volume).
Writes build/fail.mp4, fail_sheet.png and fail.json.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from . import failsim, timelapse

MODES = ("auto", "supports", "detach", "droop", "bridge")
AFTER = 12  # layers drawn after the failure (assumption: enough to see it; the printer would go on)
MOTION = 8  # frames of the failure itself
STEP = 1.0  # mm between strand vertices
MAX_SIM = 600.0  # mm of each layer's strand simulated; the rest drops straight down (assumption: speed)
WHAT = {"supports": "lines with nothing under them print into air and fall (spaghetti)",
        "droop": "a ledge past the reach droops while soft, then curls up",
        "bridge": "a bridge past the usable length sags",
        "detach": "the part comes loose from the plate; later layers print into air",
        "topple": "the nozzle's drag tips the part over; later layers print into air"}
DOMINANT = {"supports": "droop_rule", "droop": "droop_rule", "bridge": "bridge_rule", "detach": "warp_rule",
            "topple": "nozzle_tip"}


def layer_times(tp) -> np.ndarray:
    out = np.zeros(len(tp.layer_z))
    for k in range(len(out)):
        sel = tp.layer == k
        out[k] = tp.t1[sel].max() if sel.any() else 0.0
    return np.maximum.accumulate(out)


def inputs(tp, material: str = "PLA", clean: float = 1.0) -> failsim.Inputs:
    """failsim's per-layer masks from the toolpath's extruding moves; supports count when it prints them."""
    ext = tp.extruding() & (tp.layer >= 0)
    F = timelapse.gcode.FEATURES
    sup = bool((ext & np.isin(tp.feature, [F.index("support"), F.index("support interface")])).any())
    return failsim.inputs_from_segments(tp.p0[ext, :2], tp.p1[ext, :2], tp.width[ext], tp.layer[ext], tp.layer_z,
                                        layer_times(tp), material=material, clean=clean, supports=sup)


def _dist(below: np.ndarray, cell: float) -> np.ndarray:
    from scipy import ndimage

    return ndimage.distance_transform_edt(~below) * cell if below.any() else np.full(below.shape, np.inf)


def _first(inp: failsim.Inputs, mode: str):
    """The first layer with a piece of the asked kind past the reach: (layer, piece mask, mm past)."""
    from scipy import ndimage

    eight, rch = np.ones((3, 3)), failsim.reach(inp.layer)
    for i in range(1, len(inp.masks)):
        mk = np.asarray(inp.masks[i], bool)
        d = _dist(np.asarray(inp.masks[i - 1], bool), inp.cell)
        free = mk & (d > rch)
        lab, n = ndimage.label(free, eight)
        for k in range(1, n + 1):
            comp = lab == k
            ring = ndimage.binary_dilation(comp, eight) & mk & ~free
            two = ring.any() and (ndimage.label(ring, eight)[1] >= 2 or ndimage.binary_fill_holes(mk & ~free)[comp].all())
            if two and 2 * float(d[comp].max()) <= failsim.fact("max_bridge_length"):
                continue  # a short bridge (top skin over infill) prints fine: nothing to show
            if mode == "supports" or (mode == "droop" and ring.any() and not two) or (mode == "bridge" and two):
                return i, comp, float(d[comp].max())
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
            {"ledge_mm": round(big, 2), "droop_mm": round(-float(failsim.droop([big], inp.material, lay)[0]), 3)} if mode == "droop" else
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

    def __init__(self, tp, inp: failsim.Inputs, fail: failsim.Failure, rgb):
        self.tp, self.inp, self.fail, self.rgb = tp, inp, fail, rgb
        self.kind = "detach" if fail.kind in ("detach", "topple") else fail.kind
        self.L = int(fail.layer or 0)
        self.ext = tp.extruding() & (tp.layer >= 0)
        self.gone = np.zeros(tp.n, bool)
        self.rch, self.cell = failsim.reach(inp.layer), inp.cell
        self.field = np.zeros(np.shape(inp.masks[0]))  # mm, top of what is printed or piled
        self.links: list[tuple] = []  # (from layer, A, B, width): fallen strands, for good
        self.bent: list[tuple] = []  # (layer, points, dz, dist, droops, width)
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

    def strand(self, moves, d, scale=1.0, keep=False):
        """One layer's air moves as one strand, in print order. Returns drop_strand's frames when keep."""
        parts, printed = [], []
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
        pins = np.flatnonzero(d[r, c] <= self.rch)
        sel = self.ext[moves]
        speed = float(np.median(self.tp.feed[moves][sel])) if sel.any() else 200.0
        flow = self.flow * scale
        rad = math.sqrt(flow / speed / math.pi)
        hf = failsim.Heightfield(self.field.copy(), self.cell, self.inp.origin)
        m = int(np.searchsorted(s, MAX_SIM, "right"))
        steps = int(min(2400, (s[min(m, len(s)) - 1] / speed + 0.5) * 300))
        frs = failsim.drop_strand(R[:m], speed, flow, hf, steps=steps, dt=1 / 300, iters=10, seg_mm=STEP,
                                  pins=pins[pins < m])
        rest = frs[-1] if frs else R[:0]
        tail = R[len(rest):].copy()  # past MAX_SIM, or not laid when the steps ran out: straight down
        free = d[self.px(tail)] > self.rch
        tail[free, 2] = hf(tail[free, 0], tail[free, 1]) + rad
        rest = np.vstack([rest, tail])
        if m < len(R):
            self.notes.append(f"past the first {MAX_SIM:.0f} mm of a layer's strand, plastic drops straight down (no simulation)")
        rr, cc = self.px(rest)
        np.maximum.at(self.field, (rr, cc), rest[:, 2] + rad)
        self.links.append((self.layer_now, rest[:-1][seg], rest[1:][seg], 2 * rad))
        return [(f, seg[:max(0, len(f) - 1)], 2 * rad) for f in frs] if keep else []

    def bend(self, i, moves, d):
        lay = self.inp.layer
        for j in moves:
            p = self.line(j, 0.5)
            dd = np.minimum(d[self.px(p)], 100.0)
            free = dd > self.rch
            if not free.any():
                continue
            self.gone[j] = True
            dz, droops = np.zeros(len(p)), np.zeros(len(p), bool)
            if self.kind == "bridge":  # every line over the gap hangs with the span, by its distance from a side
                span = float(self.fail.numbers.get("span_mm") or 2 * dd[free].max())
                dz[free] = failsim.bridge_sag(span, np.minimum(dd[free], span / 2), lay)
            else:
                dz[free] = failsim.droop(dd[free], self.inp.material, lay, float(self.tp.width[j]))
                droops = free
            self.bent.append((i, p, dz, dd, droops, float(self.tp.width[j])))

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
                self.strand(moves, np.full(self.field.shape, np.inf), 1 - failsim.fact("blob_stick"))
                continue
            mk = np.asarray(inp.masks[i], bool)
            if self.kind in ("droop", "bridge"):
                self.bend(i, moves, _dist(np.asarray(inp.masks[i - 1], bool), self.cell) if i else np.zeros(mk.shape))
                continue
            d = _dist(solid, self.cell)
            solid = mk & (d <= self.rch)  # what fell supports nothing above it
            self.field[solid] = np.maximum(self.field[solid], inp.layer_z[i])
            air = [j for j in moves if (d[self.px(self.line(j))] > self.rch).any()]
            self.gone[air] = True
            if air:
                got = self.strand(np.asarray(air), d, keep=i == L)
                if i == L:
                    motion = got
        if self.kind == "supports":
            self.notes.append(failsim.note("strand_friction"))
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
            mats = failsim.rigid_slide(u, reach, MOTION)
            self.notes.append("assumption: the nozzle drags the loose part one footprint length along its last line")
        self.mats = [mats[k] for k in sorted(set(np.linspace(0, len(mats) - 1, MOTION).round().astype(int)))]
        return self.mats

    def items(self, layer: int, t_s: float, head, motion=None, scale=1.0) -> list[dict]:
        """The extra geometry of a frame showing layer (from the failure on)."""
        out, A, B, W = [], [], [], []
        for i, a, b, w in self.links:
            if i <= layer and len(a):
                A.append(a), B.append(b), W.append(np.full(len(a), w))
        if motion is not None and self.kind == "supports":
            f, seg, w = motion
            A.append(f[:-1][seg]), B.append(f[1:][seg]), W.append(np.full(int(seg.sum()), w))
        mat, lay = self.inp.material, self.inp.layer
        for i, p, dz, dd, droops, w in self.bent:
            if i > layer:
                continue
            up = failsim.curl(dd, mat, lay, layer - i) if layer > i else 0.0
            q = p.copy()
            q[:, 2] = np.maximum(p[:, 2] + scale * dz + np.where(droops, up, 0.0), w / 2)
            A.append(q[:-1]), B.append(q[1:]), W.append(np.full(len(q) - 1, w))
        if A:
            W = np.concatenate(W)
            out.append({"mesh": timelapse.ribbons(np.vstack(A), np.vstack(B), W, W), "rgb": self.rgb})
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


def plan(tp, inp, fail, rgb):
    """(scene toolpath, frames, extras per frame, index of the first failure frame, story)."""
    st = Story(tp, inp, fail, rgb)
    L, nl = st.L, len(tp.layer_z)
    last = min(nl - 1, L + AFTER)
    motion = st.run(last)
    base = {f["layer"]: f for f in timelapse.frames(tp, "per-layer")}
    lt = layer_times(tp)
    frs, extra = [dict(base[k], note="") for k in sorted(base) if k < L], []
    extra = [[] for _ in frs]
    first = len(frs)
    tag = WHAT[fail.kind]
    full = (lambda i: 1) if st.kind == "detach" else (lambda i: i + 2)
    t0 = float(lt[L - 1]) if L else 0.0
    fl = base.get(L) or {"head": None, "z_mm": inp.layer_z[L], "t_s": lt[L]}
    picks = motion if st.kind != "supports" else [motion[k] for k in sorted(set(np.linspace(0, len(motion) - 1, MOTION).round().astype(int)))] if motion else []
    if st.kind in ("droop", "bridge"):
        picks = list(np.linspace(0.25, 1.0, MOTION // 2))
    for k, mo in enumerate(picks):
        frac = (k + 1) / len(picks)
        head = list(mo[0][-1]) if st.kind == "supports" else fl["head"]
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
    p1 = tp.p1.copy()
    p1[st.gone, 3] = tp.p0[st.gone, 3]  # the physics draws these: out of the scene
    return replace(tp, p1=p1), frs, extra, first, st


def caption(png: Path, text: str) -> None:
    from PIL import Image, ImageDraw, ImageFont

    im = Image.open(png).convert("RGB")
    d = ImageDraw.Draw(im)
    font = ImageFont.load_default(size=max(12, im.size[1] // 28))
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


def cmd(args, job, out):
    """stone timelapse --fail [mode]: build/fail.mp4, fail_sheet.png and fail.json."""
    from . import refs

    t_start = time.time()
    mode = args.fail
    if mode != "auto" and mode != "detach":
        args.supports = "off"  # the what-if of a part printed without them
    prof = timelapse.printer(job, args.printer)
    f = Path(args.file).expanduser().resolve() if args.file else job.build_dir / "part.stl"
    if not args.gcode and not f.is_file():
        out.fix(f"no file at {f}" if args.file else "no built part yet; build first, or name an STL or --gcode file")
        out.next = "stone build" if not args.file else "stone timelapse <file.stl> --fail"
        return out
    tp, what, f = timelapse.toolpath_from(args, job, prof)
    mat = refs.material_for(job.request()).material.upper() if job.exists() else "PLA"
    note = []
    if mat not in failsim.MATERIALS:
        note.append(f"failsim has no model for {mat}; PLA used")
        mat = "PLA"
    clean = failsim.fact("contamination") if args.plate == "dirty" else 1.0
    inp = inputs(tp, mat, clean)
    fails = failsim.predict(inp)
    fail, what_if = choose(fails, mode, inp)
    out.add("This is a model, not a recording: failsim's physics on stone's own toolpaths.")
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
            out.add(f"This part has nothing for --fail {mode} to show. --fail detach shows a loose part anyway.")
            out.result = "nothing to show"
            out.next = "stone timelapse --fail detach" + (f" {args.file}" if args.file else "")
        return out
    cam = timelapse.camera(job, prof)
    dest = job.build_dir if job.exists() and not args.file and not args.gcode else f.parent
    dest.mkdir(parents=True, exist_ok=True)
    cname, rgb = timelapse.color(job)
    w = timelapse.SIZE[0]
    size = (w, int(round(w / float(cam.get("aspect") or 4 / 3) / 2)) * 2)
    scene, frs, extra, first, st = plan(tp, inp, fail, rgb)
    label = "MODEL, not a recording" + (": what-if" if what_if else "") + f": {WHAT[fail.kind]}"
    files = timelapse.render(scene, frs, prof, cam, dest / "fail", rgb, args.night, size, extras=lambda k, fr: extra[k],
                             log=job.log if job.exists() else None)
    for p in files[first:]:
        caption(p, label)
    mp4, png, js = dest / "fail.mp4", dest / "fail_sheet.png", dest / "fail.json"
    secs = timelapse.video(files, mp4, None)
    pick = list(range(max(0, first - 2), first)) + sorted(set(np.linspace(first, len(files) - 1, 7).round().astype(int).tolist()))
    timelapse.sheet(files, frs, png, pick=pick)
    for x in (dest / "fail").glob("*.npz"):
        x.unlink()
    dom = failsim.note("contamination") if clean < 1 and fail.kind == "detach" else failsim.note(DOMINANT[fail.kind])
    if what_if:
        dom = fail.assumptions[-1]
    data = {"model_not_recording": True, "mode": mode, "what_if": what_if, "kind": fail.kind, "taxonomy": fail.taxonomy,
            "what": WHAT[fail.kind], "layer": fail.layer, "layer_number": (fail.layer or 0) + 1, "z_mm": fail.z,
            "time_s": fail.time, "where_mm": fail.where, "numbers": fail.numbers, "dominant_assumption": dom,
            "assumptions": [*fail.assumptions, *note, *dict.fromkeys(st.notes)], "material": mat, "plate": args.plate,
            "predicted": [x.kind for x in fails], "source": what, "input": str(f), "camera": cam, "video_s": round(secs, 2),
            "pre_failure_frame": str(files[first - 1].relative_to(dest)) if first else None,
            "first_failure_frame": str(files[first].relative_to(dest)),
            "frames": [{"t_s": round(fr["t_s"], 2), "layer": fr["layer"], "z_mm": fr["z_mm"], "failing": k >= first,
                        "frame": str(p.relative_to(dest))} for k, (fr, p) in enumerate(zip(frs, files))]}
    js.write_text(json.dumps(data, indent=1, default=float))
    out.add(f"{'What-if (you asked for it, the model does not predict it)' if what_if else 'Predicted'}: "
            f"{fail.kind} at layer {(fail.layer or 0) + 1} (z {fail.z} mm, {timelapse.clock(fail.time or 0)} in): {WHAT[fail.kind]}.")
    out.add(f"Why: {numbers_line(fail)}.")
    out.add(f"Main assumption: {dom}")
    out.add(f"Video: {mp4} ({len(files)} frames, {secs:.1f} s; frames from layer {(fail.layer or 0) + 1} on are the model)")
    out.add(f"Sheet: {png}")
    out.add(f"Data: {js} ({time.time() - t_start:.0f} s)")
    out.result = f"failure video made: {fail.kind}{' (what-if)' if what_if else ''}"
    out.next = nxt if nxt and nxt != "stone status" else "none, the failure video is made"
    return out
