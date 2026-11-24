"""stone timelapse: what the printer's own timelapse of this print will look like.

The toolpaths come from the G-code when there is one (gcode.py), else from stone's own layer cut
(toolpaths.py). Every printed line becomes a flat ribbon, line width x layer height, merged per layer,
and Blender (a separate process; timelapse_blender.py) renders them from the printer's camera: one
frame per layer like a printer's timelapse, or frames at equal print-time steps (realtime). Then
ffmpeg makes build/timelapse.mp4, with build/timelapse_sheet.png (9 frames) and build/timelapse.json
(each frame's time, layer, height and file).

Extra geometry per frame (drooped strands, a toppled part) goes in through render(..., extras=):
a function of (frame index, frame dict) returning a list of {"mesh": (V, F), "rgb"} or
{"polyline": (n, 3) points, "width": mm, "rgb"} in printer mm.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

from . import config, gcode, refs

BLENDER = ("/opt/homebrew/bin/blender", "/Applications/Blender.app/Contents/MacOS/Blender", "blender")
FPS = 30  # frames a second in the video (assumption: a common phone and printer video rate)
SECONDS = 10.0  # realtime mode's default video length
MIN_SECONDS = 4.0  # a per-layer video of a short print plays slower than FPS, to last this long (assumption: watchable)
SIZE = (640, 480)
HEAD_MM = (50.0, 50.0, 60.0)  # the toolhead box drawn in fixed mode (assumption: roughly a K2 head)
NOZZLE_MM = 12.0  # nozzle tip to the bottom of the head (assumption: heater block and nozzle)
SHEET = 9
FIT_PX = 3.0  # a camera fit whose corners land farther off than this gets a warning
# The K2's chamber camera, until the printer profiles (Track D) carry it or the person fits theirs with
# --camera-from: low at the front left, looking back across the bed, from the owner's own K2 night
# snapshot (ss-assets/k2-detached-plate-blob.jpg). An assumption, not a measured pose.
K2_CAMERA = {"where": "front left, low, inside the chamber", "pos_mm": [-10.0, -20.0, 70.0],
             "look_at_mm": [150.0, 170.0, 10.0], "hfov_deg": 80.0, "aspect": 4 / 3, "ir_night": True,
             "timelapse_mode": "fixed",
             "assumption": "pose read by eye from one K2 night snapshot; fit yours with --camera-from"}


def builtin_k2() -> dict:
    m = refs.get("slicer.k2_machine")["value"]
    return {"id": "creality_k2", "name": "Creality K2", "maker": "Creality", "firmware": "klipper",
            "build_volume_mm": [m["bed_x"], m["bed_y"], m["height"]], "nozzle_mm": 0.4, "camera": dict(K2_CAMERA),
            "speeds": {"typical_print_mm_s": refs.get("slicer.k2_speeds")["value"]["inner_wall"], "max_accel_mm_s2": m["max_accel"]},
            "builtin": True}


def printer(job, pid: str | None) -> dict:
    """The printer profile: --printer, else the job's or the machine's (Track D's printers module, when
    present), else the built-in K2."""
    try:
        from . import printers  # Track D
    except ImportError:
        printers = None
    p = None
    if printers is not None:
        try:
            p = printers.get(pid) if pid else printers.current(job)
        except Exception:
            p = None
    if p is None and pid and pid != "creality_k2":
        raise ValueError(f"no printer profile {pid}")
    return p or builtin_k2()


def slicing(prof: dict) -> dict:
    """Widths, speeds, accelerations and shells for generated toolpaths: OrcaSlicer's K2 profile, with
    speeds scaled down and accelerations capped for a slower printer (assumption: same proportions)."""
    v = lambda k: refs.get(k)["value"]  # noqa: E731
    sp, ac = dict(v("slicer.k2_speeds")), dict(v("slicer.k2_accels"))
    typical = float((prof.get("speeds") or {}).get("typical_print_mm_s") or sp["inner_wall"])
    cap = float((prof.get("speeds") or {}).get("max_accel_mm_s2") or v("slicer.k2_machine")["max_accel"])
    f = min(1.0, typical / sp["inner_wall"])
    speeds = {k: (x if k == "travel" else x * f) for k, x in sp.items()}
    accels = {k: min(x, cap) for k, x in ac.items() if not k.startswith("jerk")}
    accels.update({"sparse_infill": accels["default"], "solid_infill": accels["default"]})
    return {"widths": v("slicer.k2_widths"), "speeds": speeds, "accels": accels, "shells": v("slicer.k2_shells"),
            "support": v("slicer.support_spacing"), "jerk": ac["jerk_walls"], "scaled": f < 1.0}


def camera(job, prof: dict) -> dict:
    """The camera: a pose fit with --camera-from (the job's, then the machine's), else the profile's."""
    for f in (job.root / "camera.json", config.user_config_dir() / "camera.json"):
        if f.is_file():
            c = json.loads(f.read_text())
            if c.get("printer") in (None, prof.get("id")):
                return {**(prof.get("camera") or {}), **c, "from": str(f)}
    return dict(prof.get("camera") or K2_CAMERA)


# frames


def frames(tp: gcode.Toolpath, mode: str = "per-layer", seconds: float | None = None, fps: float = FPS) -> list[dict]:
    """Per frame: t_s, layer, z_mm, full (scene layers shown whole), part ([scene layer, lines] or
    None), head (nozzle mm). Scene layer 0 holds what the file prints before its first layer (a purge
    line); layer k of the file is scene layer k + 1."""
    ext = tp.extruding()
    t1, lay = tp.t1, tp.layer
    nl = len(tp.layer_z)
    out = []
    if mode == "per-layer":
        for k in range(nl):
            mine = np.flatnonzero(lay == k)
            if not len(mine):
                continue
            m = int(mine[-1])
            out.append({"t_s": float(t1[m]), "layer": k, "z_mm": float(tp.layer_z[k]), "full": k + 2, "part": None,
                        "head": tp.p1[m, :3].tolist()})
        return out
    total = tp.total_s()
    n = max(2, int(round((seconds or SECONDS) * fps)))
    done = np.zeros(tp.n, int)  # extruding lines of its own layer printed by the end of each move
    for L in np.unique(lay):
        sel = lay == L
        done[sel] = np.cumsum(ext[sel])
    for k in range(n):
        t = total * (k + 1) / n
        m = min(int(np.searchsorted(t1, t)), tp.n - 1)
        L = int(lay[m])
        span = t1[m] - tp.t0[m]
        f = 1.0 if span <= 0 else float(np.clip((t - tp.t0[m]) / span, 0, 1))
        lines = int(done[m]) - (int(ext[m]) if f < 1.0 else 0)
        head = (tp.p0[m, :3] + f * (tp.p1[m, :3] - tp.p0[m, :3])).tolist()
        z = float(tp.layer_z[L]) if L >= 0 else float(tp.p1[m, 2])
        out.append({"t_s": float(t), "layer": L, "z_mm": z, "full": L + 1, "part": [L + 1, lines], "head": head})
    return out


def ribbons(p0: np.ndarray, p1: np.ndarray, width: np.ndarray, height: np.ndarray):
    """Each line (xyz ends at the nozzle, so the top of the line) as a flat box: 8 vertices, 5 quads
    (top, both sides, both ends), stretched half a width at each end so lines meet at corners."""
    d = p1[:, :2] - p0[:, :2]
    L = np.maximum(np.hypot(d[:, 0], d[:, 1]), 1e-9)
    u = d / L[:, None]
    n = np.c_[-u[:, 1], u[:, 0]] * (width / 2)[:, None]
    a = p0[:, :2] - u * (width / 2)[:, None]
    b = p1[:, :2] + u * (width / 2)[:, None]
    zt, zb = p1[:, 2], p1[:, 2] - height
    corners = [(a + n, zt), (a - n, zt), (b - n, zt), (b + n, zt), (a + n, zb), (a - n, zb), (b - n, zb), (b + n, zb)]
    V = np.stack([np.c_[xy, z] for xy, z in corners], 1).reshape(-1, 3)
    base = (np.arange(len(p0)) * 8)[:, None, None]
    quads = np.array([[0, 1, 2, 3], [0, 3, 7, 4], [1, 5, 6, 2], [0, 4, 5, 1], [3, 2, 6, 7]])
    Q = (quads[None] + base).reshape(-1, 4)
    return V.astype(np.float32), Q.astype(np.int32)


def write_scene(tp: gcode.Toolpath, path: Path, bed, rgb) -> None:
    ext = np.flatnonzero(tp.extruding())
    ext = ext[np.argsort(tp.layer[ext], kind="stable")]  # grouped by layer, print order inside each
    lay = tp.layer[ext] + 1
    V, Q = ribbons(tp.p0[ext, :3], tp.p1[ext, :3], np.maximum(tp.width[ext], 0.1), np.maximum(tp.height[ext], 0.05))
    counts = np.bincount(lay, minlength=len(tp.layer_z) + 1)
    lv = np.r_[0, np.cumsum(counts * 8)]
    lq = np.r_[0, np.cumsum(counts * 5)]
    np.savez(path, V=V, Q=Q, lv=lv, lq=lq, bed=np.asarray(bed[:2], float), rgb=np.asarray(rgb, float))


def _extras(items: list[dict], path: Path) -> Path | None:
    arrays = {}
    for j, it in enumerate(items):
        if "mesh" in it:
            V, F = (np.asarray(a) for a in it["mesh"])
        else:
            p = np.asarray(it["polyline"], float)
            w = float(it.get("width", 0.4))
            V, F = ribbons(p[:-1], p[1:], np.full(len(p) - 1, w), np.full(len(p) - 1, w))
        arrays.update({f"V{j}": V, f"F{j}": F, f"C{j}": np.asarray(it.get("rgb", (200, 60, 60)), float)})
    if not arrays:
        return None
    np.savez(path, **arrays)
    return path


def blender() -> str | None:
    for b in BLENDER:
        found = shutil.which(b) or (b if Path(b).is_file() else None)
        if found:
            return found
    return None


def render(tp: gcode.Toolpath, frs: list[dict], prof: dict, cam: dict, out: Path, rgb=(240, 240, 240),
           night: bool = False, size=SIZE, extras=None, log=None) -> list[Path]:
    """Render every frame to out/f_0000.png ... with Blender. Returns the frame files."""
    b = blender()
    if not b:
        raise RuntimeError("Blender is not installed (stone looks in /opt/homebrew/bin and /Applications)")
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("f_*.png"):
        f.unlink()
    scene = out / "scene.npz"
    write_scene(tp, scene, prof["build_volume_mm"], rgb)
    parked = (cam.get("timelapse_mode") or "fixed") != "fixed"
    items = []
    for k, fr in enumerate(frs):
        ex = _extras(extras(k, fr), out / f"extras_{k:04d}.npz") if extras else None
        items.append({"full": fr["full"], "part": fr["part"], "head": None if parked else fr["head"], "extras": str(ex) if ex else None})
    cfg = {"camera": cam, "size": list(size), "frames": items, "head_mm": list(HEAD_MM), "nozzle_mm": NOZZLE_MM}
    (out / "frames.json").write_text(json.dumps(cfg))
    script = Path(__file__).with_name("timelapse_blender.py")
    run = subprocess.run([b, "-b", "--factory-startup", "--python", str(script), "--", str(scene), str(out / "frames.json"), str(out)],
                         capture_output=True, text=True, timeout=3600)
    if log:
        log(run.stdout[-4000:] + run.stderr[-4000:])
    files = [out / f"f_{k:04d}.png" for k in range(len(frs))]
    if run.returncode != 0 or not all(f.is_file() for f in files):
        raise RuntimeError(f"Blender failed (exit {run.returncode}): {(run.stderr or run.stdout)[-300:]}")
    if night:
        for f in files:
            ir(f)
    return files


def ir(png: Path) -> None:
    """The K2's night view: an infrared camera sees plastic bright and gray, the chamber dark, with
    sensor grain (a look, matched by eye to the owner's night snapshot)."""
    from PIL import Image

    a = np.asarray(Image.open(png).convert("RGB"), float) / 255.0
    g = a @ [0.299, 0.587, 0.114]
    g = np.clip((g - 0.06) * 1.35, 0, 1) ** 0.9
    rng = np.random.default_rng(abs(hash(png.name)) % (2 ** 32))
    g = np.clip(g + rng.normal(0, 0.025, g.shape), 0, 1)
    Image.fromarray((np.repeat(g[..., None], 3, 2) * 255).astype(np.uint8)).save(png)


def video(files: list[Path], mp4: Path, seconds: float | None) -> float:
    """h264 yuv420p mp4 of the frames, seconds long (default: FPS frames a second, at least MIN_SECONDS).
    Returns its length, s."""
    rate = len(files) / seconds if seconds else min(FPS, len(files) / MIN_SECONDS)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", f"{rate:.6f}", "-i", str(files[0].parent / "f_%04d.png"),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS), "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    "-movflags", "+faststart", str(mp4)], check=True, capture_output=True)
    return len(files) / rate


def sheet(files: list[Path], frs: list[dict], png: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    pick = sorted(set(np.linspace(0, len(files) - 1, min(SHEET, len(files))).round().astype(int).tolist()))
    ims = [Image.open(files[k]).convert("RGB") for k in pick]
    w, h = ims[0].size
    cols = 3
    out = Image.new("RGB", (w * cols, h * math.ceil(len(ims) / cols)), (0, 0, 0))
    font = ImageFont.load_default(size=max(12, h // 24))
    for j, (k, im) in enumerate(zip(pick, ims)):
        d = ImageDraw.Draw(im)
        fr = frs[k]
        d.text((8, 6), f"layer {fr['layer'] + 1}  z {fr['z_mm']:.2f} mm  {clock(fr['t_s'])}", fill=(255, 220, 80), font=font)
        out.paste(im, ((j % cols) * w, (j // cols) * h))
    out.save(png)


def clock(s: float) -> str:
    s = int(round(s))
    return f"{s // 3600} h {s % 3600 // 60} min" if s >= 3600 else f"{s // 60} min {s % 60} s" if s >= 60 else f"{s} s"


# camera fit


def fit_camera(corners_px, image_size, bed_mm) -> dict:
    """The camera pose from the bed's four corners in a snapshot, in order front left, front right,
    back right, back left (printer x, y = 0, 0 is front left). Focal length from the homography with
    square pixels and the principal point at the center (Zhang's constraints), then cv2.solvePnP.
    Returns pos_mm, rot (columns: Blender camera right, up and back axes in printer space), hfov_deg,
    and each corner's reprojection error in px."""
    import cv2

    img = np.asarray(corners_px, np.float64).reshape(4, 2)
    bx, by = float(bed_mm[0]), float(bed_mm[1])
    obj = np.array([[0, 0, 0], [bx, 0, 0], [bx, by, 0], [0, by, 0]], np.float64)
    w, h = image_size
    cx, cy = w / 2.0, h / 2.0
    H, _ = cv2.findHomography(obj[:, :2], img)
    Hc = np.array([[1, 0, -cx], [0, 1, -cy], [0, 0, 1.0]]) @ H
    (h11, h12, _), (h21, h22, _), (h31, h32, _) = Hc
    est = []
    if abs(h31 * h32) > 1e-12:
        est.append(-(h11 * h12 + h21 * h22) / (h31 * h32))
    if abs(h31 ** 2 - h32 ** 2) > 1e-12:
        est.append((h12 ** 2 + h22 ** 2 - h11 ** 2 - h21 ** 2) / (h31 ** 2 - h32 ** 2))
    good = [e for e in est if e > 0]
    f = math.sqrt(np.mean(good)) if good else w / 2 / math.tan(math.radians(80) / 2)
    K = np.array([[f, 0, cx], [0, f, cy], [0, 0, 1.0]])
    ok, rv, tv = cv2.solvePnP(obj, img, K, None, flags=cv2.SOLVEPNP_IPPE)
    ok, rv, tv = cv2.solvePnP(obj, img, K, None, rv, tv, useExtrinsicGuess=True, flags=cv2.SOLVEPNP_ITERATIVE)
    proj, _ = cv2.projectPoints(obj, rv, tv, K, None)
    err = np.linalg.norm(proj[:, 0, :] - img, axis=1)
    R, _ = cv2.Rodrigues(rv)
    pos = (-R.T @ tv).ravel()
    rot = R.T @ np.diag([1.0, -1.0, -1.0])  # OpenCV looks down +z with y down; Blender down -z with y up
    return {"pos_mm": pos.round(2).tolist(), "rot": rot.round(6).tolist(), "hfov_deg": round(math.degrees(2 * math.atan(w / 2 / f)), 3),
            "aspect": w / h, "image_px": [w, h], "focal_px": round(f, 2), "fit_error_px": err.round(3).tolist()}


def project(cam: dict, pts) -> np.ndarray:
    """Printer mm points to pixels for a camera dict as stored (pos_mm, rot, hfov_deg, image_px)."""
    w, h = cam["image_px"]
    f = w / 2 / math.tan(math.radians(cam["hfov_deg"]) / 2)
    R = np.asarray(cam["rot"]) @ np.diag([1.0, -1.0, -1.0])  # back to OpenCV axes
    p = (np.asarray(pts, float) - cam["pos_mm"]) @ R
    return np.c_[f * p[:, 0] / p[:, 2] + w / 2, f * p[:, 1] / p[:, 2] + h / 2]


def parse_corners(text: str) -> list[tuple[float, float]]:
    pts = [tuple(float(v) for v in p.split(",")) for p in text.replace(";", " ").split()]
    if len(pts) != 4 or any(len(p) != 2 for p in pts):
        raise ValueError('give four corners: --bed-corners "x1,y1 x2,y2 x3,y3 x4,y4"')
    return pts


# the command


def color(job) -> tuple[str, tuple]:
    """The filament color: slot 1 of stone.toml [filaments], white when the name is not a plain color."""
    from . import colors, config

    name = (config.filaments(job.root if job.exists() else None) or ["white"])[0].lower()
    for word in name.replace("-", " ").split():
        word = colors.ALIASES.get(word, word)
        if word in colors.NAMES:
            return word, colors.NAMES[word]
    return "white", colors.NAMES["white"]


def toolpath_from(args, job, prof):
    """(toolpath, words saying where it came from, the input file)."""
    if args.gcode:
        f = Path(args.gcode).expanduser().resolve()
        tp = gcode.load(f)
        what = f"from the G-code ({tp.slicer or 'slicer unknown'})"
        return tp, what, f
    from . import supports, toolpaths

    f = Path(args.file).expanduser().resolve() if args.file else job.build_dir / "part.stl"
    mesh = supports.load(f)
    sup, on = None, args.supports == "on"
    if args.supports != "off":
        sup = supports.analyze(mesh, columns=True)
        on = on or sup["needed"]
    lo, hi = mesh.bounds
    bx, by = prof["build_volume_mm"][:2]
    place = (bx / 2 - (lo[0] + hi[0]) / 2, by / 2 - (lo[1] + hi[1]) / 2)
    sl = slicing(prof)
    tp = toolpaths.generate(mesh, sl, 0.2, sup if on else None, place)
    sh = sl["shells"]
    what = (f"generated by stone, no G-code: {sh['wall_loops']} walls, {sh['sparse_infill_density']:g}% grid infill, "
            f"{sh['bottom_shell_layers']} bottom and {sh['top_shell_layers']} top solid layers, supports "
            f"{'on' if on else 'off'}{' (stone supports says needed)' if on and args.supports == 'auto' else ''}, "
            f"OrcaSlicer's K2 speeds{' scaled to this printer' if sl['scaled'] else ''}")
    return tp, what, f


def fit_from(args, job, prof, out) -> dict | None:
    from PIL import Image

    snap = Path(args.camera_from).expanduser().resolve()
    if not args.bed_corners:
        out.fix('--camera-from needs the bed corners: --bed-corners "x1,y1 x2,y2 x3,y3 x4,y4" '
                "(front left, front right, back right, back left, in pixels)")
        return None
    with Image.open(snap) as im:
        size = im.size
    cam = fit_camera(parse_corners(args.bed_corners), size, prof["build_volume_mm"])
    cam.update({"printer": prof.get("id"), "timelapse_mode": (prof.get("camera") or {}).get("timelapse_mode", "fixed"),
                "ir_night": (prof.get("camera") or {}).get("ir_night", False), "source": f"fit to {snap.name}"})
    dests = ([job.root / "camera.json"] if job.exists() else []) + ([config_camera()] if args.save_camera else [])
    for d in dests:
        d.parent.mkdir(parents=True, exist_ok=True)
        d.write_text(json.dumps(cam, indent=1))
    out.add(f"Camera fit to {snap.name}: corners land within {max(cam['fit_error_px']):.1f} px, "
            f"{cam['hfov_deg']:.0f} degrees wide, at {', '.join(f'{v:.0f}' for v in cam['pos_mm'])} mm.")
    if max(cam["fit_error_px"]) > FIT_PX:
        out.add(f"Warning: the corners do not fit one camera (off by up to {max(cam['fit_error_px']):.0f} px). "
                "Check their order: front left, front right, back right, back left.")
    if dests:
        out.add("Saved: " + ", ".join(str(d) for d in dests))
    if not args.save_camera:
        out.add("To use this camera for every job, run it again with --save-camera.")
    return cam


def config_camera() -> Path:
    from . import config

    return config.user_config_dir() / "camera.json"


def cmd(args, job, out):
    """stone timelapse: build/timelapse.mp4, timelapse_sheet.png and timelapse.json."""
    t_start = time.time()
    try:
        prof = printer(job, args.printer)
    except ValueError as e:
        out.fix(str(e))
        out.next = "stone timelapse"
        return out
    cam = fit_from(args, job, prof, out) if args.camera_from else None
    if out.code:
        return out
    if not args.gcode:
        f = Path(args.file).expanduser().resolve() if args.file else job.build_dir / "part.stl"
        if not f.is_file():
            if cam:  # a camera fit alone is a finished step
                out.next = "stone timelapse"
                return out
            out.fix(f"no file at {f}" if args.file else "no built part yet; build first, or name an STL or --gcode file")
            out.next = "stone build" if not args.file else "stone timelapse <file.stl>"
            return out
    elif not Path(args.gcode).expanduser().is_file():
        out.fix(f"no G-code at {args.gcode}")
        out.next = "stone timelapse --gcode <file.gcode>"
        return out
    tp, what, f = toolpath_from(args, job, prof)
    cam = cam or camera(job, prof)
    dest = job.build_dir if job.exists() and not args.file and not args.gcode else f.parent
    dest.mkdir(parents=True, exist_ok=True)
    frs = frames(tp, args.mode, args.seconds)
    w = SIZE[0]
    size = (w, int(round(w / float(cam.get("aspect") or 4 / 3) / 2)) * 2)
    cname, rgb = color(job)
    night = args.night
    t_render = time.time()
    files = render(tp, frs, prof, cam, dest / "timelapse", rgb, night, size, log=job.log if job.exists() else None)
    render_s = time.time() - t_render
    mp4, png, js = dest / "timelapse.mp4", dest / "timelapse_sheet.png", dest / "timelapse.json"
    secs = video(files, mp4, args.seconds or (SECONDS if args.mode == "realtime" else None))
    sheet(files, frs, png)
    for x in (dest / "timelapse").glob("*.npz"):
        x.unlink()
    total = tp.total_s()
    data = {"source": what, "input": str(f), "printer": prof.get("id"), "printer_builtin": bool(prof.get("builtin")),
            "mode": args.mode, "night": night, "color": cname, "print_s": round(total, 1), "slicer_estimate_s": tp.estimate_s,
            "layers": len(tp.layer_z), "video_s": round(secs, 2), "render_s": round(render_s, 1), "size_px": list(size),
            "camera": cam, "frames": [{"t_s": round(fr["t_s"], 2), "layer": fr["layer"], "z_mm": fr["z_mm"],
                                       "frame": str(p.relative_to(dest))} for fr, p in zip(frs, files)]}
    js.write_text(json.dumps(data, indent=1))
    out.add(f"Toolpaths: {what}.")
    pname = prof.get("name") or prof.get("id")
    out.add(f"Printer: {pname}{' (built-in profile)' if prof.get('builtin') else ''}; camera "
            + (f"from {Path(cam['from']).name}" if cam.get("from") else cam.get("source") or "pose from the profile, an assumption"))
    est = f" (the slicer says {clock(tp.estimate_s)})" if tp.estimate_s else ""
    out.add(f"Print time: {clock(total)}{est}, {len(tp.layer_z)} layers, {cname} filament.")
    out.add(f"Video: {mp4} ({len(files)} frames, {secs:.1f} s, {args.mode}{', night view' if night else ''})")
    out.add(f"Sheet: {png} (9 frames)")
    out.add(f"Data: {js} (rendered in {render_s:.0f} s, {time.time() - t_start:.0f} s in all)")
    out.result = f"timelapse made, {len(files)} frames"
    nxt = job.status().get("next") if job.exists() else None
    out.next = nxt if nxt and nxt != "stone status" else "none, the timelapse is made"
    return out
