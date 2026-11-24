"""stone timelapse: what the printer's own timelapse of this print will look like.

The toolpaths come from the G-code when there is one (gcode.py), else from stone's own layer cut
(toolpaths.py). Every printed line becomes a flat ribbon, line width x layer height, merged per layer,
and Blender (a separate process; timelapse_blender.py) renders them from the printer's camera: one
frame per layer like a printer's timelapse, or frames at equal print-time steps (realtime). Then
ffmpeg makes timelapse.mp4, with timelapse_sheet.png (9 frames) and timelapse.json (each frame's time,
layer, height and file): in build/ for the job's part, else in a folder named after the file.

Everything is drawn in the bed's own frame. A printer that moves its bed (down in z as the print grows, or
along y) is drawn by moving the camera the other way, so the still nozzle stays where the camera sees it.

Extra geometry per frame (drooped strands, a toppled part) goes in through render(..., extras=):
a function of (frame index, frame dict) returning a list of {"mesh": (V, F), "rgb"} or
{"polyline": (n, 3) points, "width": mm, "rgb"} in printer mm.
"""

from __future__ import annotations

import json
import math
import os
import shlex
import shutil
import subprocess
import time
import zlib
from pathlib import Path

import numpy as np

from . import config, gcode, printers

BLENDER = ("blender", "/opt/homebrew/bin/blender", "/Applications/Blender.app/Contents/MacOS/Blender")
FPS = 30  # frames a second in the video (assumption: a common phone and printer video rate)
SECONDS = 10.0  # realtime mode's default video length
MIN_SECONDS = 4.0  # a per-layer video of a short print plays slower than FPS, to last this long (assumption: watchable)
SIZE = (640, 480)
HEAD_MM = (50.0, 50.0, 60.0)  # the toolhead box drawn in fixed mode (assumption: roughly a K2 head)
NOZZLE_MM = 12.0  # nozzle tip to the bottom of the head (assumption: heater block and nozzle)
SHEET = 9
FIT_PX = 3.0  # a camera fit whose corners land farther off than this is refused
MAX_FRAMES = 1800  # realtime mode renders at most this many frames and holds each longer (about 12 min of Blender)
FLYING_GANTRY = ("voron_24", "sovol_sv08")  # corexy printers whose gantry climbs over a still bed
BED_AXIS = {"corexy": "z", "bedslinger": "y", "corexz": "y"}
# A camera for a printer whose profile gives no pose: low at the front left, looking back across the bed
# (assumption: where most enclosed printers put it; --camera-from fits the real one). pos and look_at are
# shares of the bed's width and depth, then mm up.
ANY_CAMERA = {"pos": (-0.04, -0.08, 70.0), "look_at": (0.58, 0.65, 10.0), "hfov_deg": 80.0}


def printer(job, pid: str | None) -> dict:
    """The printer profile: --printer, else the one `stone printer set` keeps, else the Creality K2."""
    if pid:
        p = printers.get(pid)
        if p is None:
            raise ValueError(f"no printer profile {pid}; stone printer lists them")
        return p
    p = printers.current(job.root if job.exists() else None)
    return p or {**printers.get("creality_k2"), "assumed": True}


def bed_axis(prof: dict) -> str:
    """The axis the printer moves its bed along: z (it sinks as the print grows), y, or "" for a still bed."""
    return "" if prof.get("id") in FLYING_GANTRY else BED_AXIS.get(prof.get("kinematics"), "")


def camera_shift(prof: dict, fr: dict, parked: bool) -> list[float]:
    """How far the still camera is from its pose, in the bed's frame, at this frame. The pose is for a bed with
    the nozzle at z 0 (or, on a bed-slinger, at the bed's middle y)."""
    axis = bed_axis(prof)
    if axis == "z":  # the nozzle's own height, so a z-hop moves the bed and not the head
        return [0.0, 0.0, fr["z_mm"] if parked else fr["head"][2]]
    if axis == "y" and not parked:
        return [0.0, fr["head"][1] - prof["build_volume_mm"][1] / 2, 0.0]
    return [0.0, 0.0, 0.0]


def aspect(v) -> float:
    """A camera's width over height, from a number or "16:9"."""
    if isinstance(v, str) and ":" in v:
        w, h = v.split(":")
        return float(w) / float(h)
    return float(v or 4 / 3)


def camera(job, prof: dict) -> dict:
    """The camera: the last pose fit with --camera-from (the job's or the machine's), else the profile's, else ANY_CAMERA."""
    cam = dict(prof.get("camera") or {})
    kept = [f for f in camera_files(job, prof) if f.is_file()]
    if kept:
        f = max(kept, key=lambda f: f.stat().st_mtime_ns)
        try:
            return {**cam, **json.loads(f.read_text()), "from": str(f)}
        except ValueError as e:
            raise ValueError(f"{f} is not a saved camera ({e}); fit it again or remove it") from e
    if not (cam.get("pos_mm") and cam.get("look_at_mm") and cam.get("hfov_deg")):
        bx, by = prof["build_volume_mm"][:2]
        at = {k: [v[0] * bx, v[1] * by, v[2]] for k, v in ANY_CAMERA.items() if k != "hfov_deg"}
        cam.update(pos_mm=at["pos"], look_at_mm=at["look_at"], hfov_deg=ANY_CAMERA["hfov_deg"],
                   assumption="pose not in the profile; assumed low at the front left")
    return cam


def camera_files(job, prof: dict) -> list[Path]:
    """Where a fitted camera for this printer is kept: the job, the machine (--save-camera)."""
    return [d / f"camera-{prof['id']}.json" for d in (job.root, config.user_config_dir())]


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
    n = min(MAX_FRAMES, max(2, int(round((seconds or SECONDS) * fps))))
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
    for b in (os.environ.get("STONE_BLENDER") or "", *BLENDER):
        found = shutil.which(b) or (b if Path(b).is_file() else None)
        if found:
            return found
    return None


def missing() -> str | None:
    """What a video needs and this computer does not have, in words for a FIX line."""
    if not blender():
        return "Blender not found; ask the person to install it, or set STONE_BLENDER"
    return None if shutil.which("ffmpeg") else "ffmpeg not found; ask the person to install it"


def render(tp: gcode.Toolpath, frs: list[dict], prof: dict, cam: dict, out: Path, rgb=(240, 240, 240),
           night: bool = False, size=SIZE, extras=None, log=None) -> list[Path]:
    """Render every frame to out/f_0000.png ... with Blender. Returns the frame files."""
    b = blender()
    if not b:
        raise RuntimeError("Blender not found; install it or set STONE_BLENDER")
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("f_*.png"):
        f.unlink()
    scene = out / "scene.npz"
    write_scene(tp, scene, prof["build_volume_mm"], rgb)
    parked = (cam.get("timelapse_mode") or "fixed") != "fixed"
    items = []
    for k, fr in enumerate(frs):
        ex = _extras(extras(k, fr), out / f"extras_{k:04d}.npz") if extras else None
        items.append({"full": fr["full"], "part": fr["part"], "head": None if parked else fr["head"], "extras": str(ex) if ex else None,
                      "shift": camera_shift(prof, fr, parked)})
    cfg = {"camera": cam, "size": list(size), "frames": items, "head_mm": list(HEAD_MM), "nozzle_mm": NOZZLE_MM}
    (out / "frames.json").write_text(json.dumps(cfg))
    script = Path(__file__).with_name("timelapse_blender.py")
    run = subprocess.run([b, "-b", "--factory-startup", "--python", str(script), "--", str(scene), str(out / "frames.json"), str(out)],
                         capture_output=True, text=True, timeout=600 + 4 * len(frs))
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
    """The night view: an infrared camera sees plastic bright and gray, the chamber dark, with sensor
    grain (a look, matched by eye to one K2 night snapshot)."""
    from PIL import Image

    a = np.asarray(Image.open(png).convert("RGB"), float) / 255.0
    g = a @ [0.299, 0.587, 0.114]
    g = np.clip((g - 0.06) * 1.35, 0, 1) ** 0.9
    rng = np.random.default_rng(zlib.crc32(png.name.encode()))
    g = np.clip(g + rng.normal(0, 0.025, g.shape), 0, 1)
    Image.fromarray((np.repeat(g[..., None], 3, 2) * 255).astype(np.uint8)).save(png)


def video(files: list[Path], mp4: Path, seconds: float | None) -> float:
    """h264 yuv420p mp4 of the frames, seconds long (default: FPS frames a second, at least MIN_SECONDS).
    Returns its length, s."""
    rate = len(files) / seconds if seconds else min(FPS, len(files) / MIN_SECONDS)
    frames_at = str(files[0].parent).replace("%", "%%")  # a % in a folder's name is not ffmpeg's pattern
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", f"{rate:.6f}", "-i", f"{frames_at}/f_%04d.png",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS), "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    "-movflags", "+faststart", str(mp4)], check=True, capture_output=True)
    return len(files) / rate


def sheet(files: list[Path], frs: list[dict], png: Path, pick: list[int] | None = None) -> None:
    from PIL import Image, ImageDraw, ImageFont

    pick = pick or sorted(set(np.linspace(0, len(files) - 1, min(SHEET, len(files))).round().astype(int).tolist()))
    ims = [Image.open(files[k]).convert("RGB") for k in pick]
    w, h = ims[0].size
    cols = 3
    out = Image.new("RGB", (w * cols, h * math.ceil(len(ims) / cols)), (0, 0, 0))
    font = ImageFont.load_default(size=max(12, h // 24))
    for j, (k, im) in enumerate(zip(pick, ims)):
        d = ImageDraw.Draw(im)
        fr = frs[k]
        d.text((8, 6), f"layer {fr['layer'] + 1}  z {fr['z_mm']:.2f} mm  {clock(fr['t_s'])}", fill=(255, 220, 80), font=font)
        if fr.get("note"):
            d.text((8, 10 + font.size), fr["note"], fill=(255, 90, 70), font=font)
        out.paste(im, ((j % cols) * w, (j // cols) * h))
    out.save(png)


def clock(s: float) -> str:
    s = int(round(s))
    return f"{s // 3600} h {s % 3600 // 60} min" if s >= 3600 else f"{s // 60} min {s % 60} s" if s >= 60 else f"{s} s"


# camera fit


def fit_camera(corners_px, image_size, bed_mm) -> dict:
    """The camera pose from the bed's four corners in a snapshot, in order front left, front right,
    back right, back left (printer x, y = 0, 0 is front left). Focal length from the homography with
    square pixels and the principal point at the center (both of Zhang's constraints by least squares, so one
    the view cannot settle weighs nothing), then cv2.solvePnP. ValueError when no camera above the bed fits.
    Returns pos_mm, rot (columns: Blender camera right, up and back axes in printer space), hfov_deg,
    and each corner's reprojection error in px."""
    import cv2

    img = np.asarray(corners_px, np.float64).reshape(4, 2)
    bx, by = float(bed_mm[0]), float(bed_mm[1])
    obj = np.array([[0, 0, 0], [bx, 0, 0], [bx, by, 0], [0, by, 0]], np.float64)
    w, h = image_size
    cx, cy = w / 2.0, h / 2.0
    if not np.isfinite(img).all() or cv2.contourArea(img.astype(np.float32)) < 100 or not cv2.isContourConvex(img.astype(np.float32)):
        raise ValueError("the four corners are not a four-sided shape; check each one, and their order")
    H, _ = cv2.findHomography(obj[:, :2], img)
    Hc = np.array([[1, 0, -cx], [0, 1, -cy], [0, 0, 1.0]]) @ H
    (h11, h12, _), (h21, h22, _), (h31, h32, _) = Hc
    a = np.array([h31 * h32, h31 ** 2 - h32 ** 2])
    b = np.array([-(h11 * h12 + h21 * h22), h12 ** 2 + h22 ** 2 - h11 ** 2 - h21 ** 2])
    f2 = a @ b / (a @ a) if a @ a > 1e-18 else (w / 2 / math.tan(math.radians(80) / 2)) ** 2  # straight down: assume 80
    if f2 <= (w / 8) ** 2:
        raise ValueError("no camera fits those corners; check each one, and their order")
    f = math.sqrt(f2)
    K = np.array([[f, 0, cx], [0, f, cy], [0, 0, 1.0]])
    ok, rv, tv = cv2.solvePnP(obj, img, K, None, flags=cv2.SOLVEPNP_IPPE)
    ok, rv, tv = cv2.solvePnP(obj, img, K, None, rv, tv, useExtrinsicGuess=True, flags=cv2.SOLVEPNP_ITERATIVE)
    proj, _ = cv2.projectPoints(obj, rv, tv, K, None)
    err = np.linalg.norm(proj[:, 0, :] - img, axis=1)
    R, _ = cv2.Rodrigues(rv)
    pos = (-R.T @ tv).ravel()
    if pos[2] <= 0:
        raise ValueError("those corners put the camera under the bed; give them in order: front left, front right, back right, back left")
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


def color(job) -> tuple[str, tuple, bool]:
    """(name, rgb, whether stone.toml says so): slot 1 of its [filaments], white when the name is not a plain color."""
    from . import colors

    root = job.root if job.exists() else None
    name = (config.filaments(root) or ["white"])[0].lower()
    for word in name.replace("-", " ").split():
        word = colors.ALIASES.get(word, word)
        if word in colors.NAMES:
            return word, colors.NAMES[word], bool(config._toml(root).get("filaments"))
    return "white", colors.NAMES["white"], False


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
    sl = toolpaths.profile(prof)
    tp = toolpaths.generate(mesh, sl, 0.2, sup if on else None, place)
    sh = sl["shells"]
    what = (f"generated by stone, no G-code: {sh['wall_loops']} walls, {sh['sparse_infill_density']:g}% grid infill, "
            f"{sh['bottom_shell_layers']} bottom and {sh['top_shell_layers']} top solid layers, supports "
            f"{'on' if on else 'off'}{' (stone supports says needed)' if on and args.supports == 'auto' else ''}, "
            f"OrcaSlicer's K2 speeds{' scaled to this printer' if sl['scaled'] else ''}")
    return tp, what, f


def side(cam: dict, bed) -> str:
    """Where over the bed the camera sits, in words: "front right"."""
    x, y = cam["pos_mm"][0] / bed[0], cam["pos_mm"][1] / bed[1]
    words = ["front" if y < 1 / 3 else "back" if y > 2 / 3 else "", "left" if x < 1 / 3 else "right" if x > 2 / 3 else ""]
    return " ".join(w for w in words if w) or "middle"


def fit_from(args, job, prof, out):
    """--camera-from: fit the camera, keep it, and ask the person if it is where their camera is (a fit cannot
    tell which corner of a square bed came first)."""
    from PIL import Image

    snap = Path(args.camera_from).expanduser().resolve()
    bed, axis = prof["build_volume_mm"], bed_axis(prof)
    mine = f" --printer {shlex.quote(args.printer)}" if args.printer else ""
    refit = (f'stone timelapse{mine} --camera-from {shlex.quote(str(snap))} --bed-corners "<x1,y1 x2,y2 x3,y3 x4,y4>"'
             + ("" if args.snap_at is None else f" --snap-at {args.snap_at:g}"))
    job_file, machine_file = camera_files(job, prof)
    dest = machine_file if args.save_camera else job_file if job.exists() else None
    if prof.get("assumed"):
        out.fix("the fit needs this printer's bed size, and no printer is set")
        out.next = "ask the person: which printer is it? Then: stone printer set <id>, and run this again"
        return out
    out.next = refit = refit + (" --save-camera" if args.save_camera or not dest else "")
    if not args.bed_corners or not dest:
        out.fix('--camera-from needs the bed corners in pixels: front left, front right, back right, back left'
                if not args.bed_corners else "no job here to keep the camera in; add --save-camera")
        return out
    try:
        with Image.open(snap) as im:
            size = im.size
        cam = fit_camera(parse_corners(args.bed_corners), size, bed)
    except (OSError, ValueError) as e:
        out.fix(f"--camera-from: {e}")
        return out
    off = max(cam["fit_error_px"])
    if off > FIT_PX:
        out.fix(f"the corners do not fit one camera (off by up to {off:.0f} px); check each one, and their order")
        return out
    if axis:
        ref = 0.0 if axis == "z" else bed[1] / 2
        at = ref if args.snap_at is None else args.snap_at
        cam["pos_mm"]["xyz".index(axis)] -= at - ref
        out.add(f"The snapshot counts as taken with the printer at {axis.upper()} {at:g} mm"
                + ("; if it was not, run this again with --snap-at." if args.snap_at is None else "."))
    profcam = prof.get("camera") or {}
    cam.update({"printer": prof["id"], "timelapse_mode": profcam.get("timelapse_mode", "fixed"),
                "ir_night": profcam.get("ir_night", False), "source": f"fit to {snap.name}"})
    dest.parent.mkdir(parents=True, exist_ok=True)
    old = dest.with_suffix(".json.old")
    if dest.is_file():
        dest.replace(old)  # the person may say the new fit is wrong
    dest.write_text(json.dumps(cam, indent=1))
    where = f"at the {side(cam, bed)} of the bed, {cam['pos_mm'][2]:.0f} mm above it"
    out.add(f"Camera fit to {snap.name}: corners land within {off:.1f} px, {cam['hfov_deg']:.0f} degrees wide, {where}.",
            f"Saved: {dest}" + (f" (the one before: {old.name})" if old.is_file() else ""))
    out.next = (f"ask the person: is the printer's camera {where}? If so: stone timelapse{mine}. "
                f"If not, the corners started at the wrong one: {refit}")
    return out


def out_dir(args, job, f: Path) -> Path:
    """build/ for the job's own part, else a folder beside the file and named after it."""
    return job.build_dir if job.exists() and not args.file and not args.gcode else f.parent / f"{f.name}-timelapse"


def again(args, **change) -> str:
    """The command as typed, with some options changed or dropped (None)."""
    v = {"file": args.file, "--gcode": args.gcode, "--printer": args.printer, "--mode": args.mode, "--supports": args.supports,
         "--seconds": args.seconds, **change}
    out = ["stone timelapse"] + ([shlex.quote(v.pop("file"))] if v.get("file") else [])
    out += [f"{k} {shlex.quote(str(x))}" for k, x in v.items() if x not in (None, "auto", "per-layer") and k.startswith("--")]
    return " ".join(out + (["--night"] if args.night else []))


def cmd(args, job, out):
    """stone timelapse: timelapse.mp4, timelapse_sheet.png and timelapse.json."""
    t_start = time.time()
    try:
        prof = printer(job, args.printer)
    except ValueError as e:
        out.fix(str(e))
        out.next = "stone printer"
        return out
    if args.camera_from:
        return fit_from(args, job, prof, out)
    if args.gcode and (args.file or args.supports != "auto"):
        out.fix("the G-code already has its own part and supports; drop the file and --supports")
        out.next = again(args, file=None, **{"--supports": None})
        return out
    if not args.gcode:
        f = Path(args.file).expanduser().resolve() if args.file else job.build_dir / "part.stl"
        if not f.is_file():
            out.fix(f"no file at {f}" if args.file else "no built part yet; build first, or name an STL or --gcode file")
            out.next = "stone build" if not args.file else again(args, file="<file.stl>")
            return out
    elif not Path(args.gcode).expanduser().is_file():
        out.fix(f"no G-code at {args.gcode}")
        out.next = again(args, **{"--gcode": "<file.gcode>"})
        return out
    if args.seconds is not None and not 1 <= args.seconds <= 600:
        out.fix("--seconds: give 1 to 600")
        out.next = again(args, **{"--seconds": None})
        return out
    try:
        tp, what, f = toolpath_from(args, job, prof)
    except (OSError, ValueError) as e:
        out.fix(str(e))
        out.next = "ask the person for another file: " + again(args) if args.file or args.gcode else "stone build"
        return out
    total = tp.total_s()
    est = f" (the slicer says {clock(tp.estimate_s)})" if tp.estimate_s else ""
    cname, rgb, named = color(job)
    shade = f"{cname} filament" if named and not args.gcode else f"all drawn {cname}" + (
        "; the G-code's own colors are not read" if args.gcode else ", no filament color named")
    head = [f"Toolpaths: {what}.", f"Print time: {clock(total)}{est}, {len(tp.layer_z)} layers, {shade}."]
    no = missing()
    if no:
        out.add(*head)
        out.fix(f"no video: {no}")
        out.next = "none, the print time is above; the video needs that program"
        return out
    dest = out_dir(args, job, f)
    frs = frames(tp, args.mode, args.seconds)
    mp4, png, js = dest / "timelapse.mp4", dest / "timelapse_sheet.png", dest / "timelapse.json"
    t_render = time.time()
    try:
        cam = camera(job, prof)
        size = (SIZE[0], int(round(SIZE[0] / aspect(cam.get("aspect")) / 2)) * 2)
        files = render(tp, frs, prof, cam, dest / "timelapse", rgb, args.night, size, log=job.log if job.exists() else None)
        render_s = time.time() - t_render
        secs = video(files, mp4, args.seconds or (SECONDS if args.mode == "realtime" else None))
        sheet(files, frs, png)
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as e:
        said = (getattr(e, "stderr", None) or b"").decode(errors="replace")[-200:] if isinstance(e, subprocess.CalledProcessError) else ""
        out.add(*head)
        out.fix(f"no video: {e} {said}".rstrip())
        out.next = "none, the print time is above"
        return out
    finally:
        for x in (dest / "timelapse").glob("*.npz"):
            x.unlink()
    data = {"source": what, "input": str(f), "printer": prof.get("id"), "printer_assumed": bool(prof.get("assumed")),
            "mode": args.mode, "night": args.night, "color": cname, "print_s": round(total, 1), "slicer_estimate_s": tp.estimate_s,
            "layers": len(tp.layer_z), "video_s": round(secs, 2), "render_s": round(render_s, 1), "size_px": list(size),
            "camera": cam, "frames": [{"t_s": round(fr["t_s"], 2), "layer": fr["layer"], "z_mm": fr["z_mm"],
                                       "frame": str(p.relative_to(dest))} for fr, p in zip(frs, files)]}
    js.write_text(json.dumps(data, indent=1))
    pname = prof.get("name") or prof.get("id")
    out.add(head[0], f"Printer: {pname}{' (none set; stone printer set <id>)' if prof.get('assumed') else ''}; camera "
            + (f"from {cam['from']}" if cam.get("from") else cam.get("assumption") or "pose from the profile"))
    out.add(head[1])
    out.add(f"Video: {mp4} ({len(files)} frames, {secs:.1f} s, {args.mode}{', night view' if args.night else ''})")
    out.add(f"Sheet: {png} ({min(SHEET, len(files))} frames)")
    out.add(f"Data: {js} (rendered in {render_s:.0f} s, {time.time() - t_start:.0f} s in all)")
    out.result = f"timelapse made, {len(files)} frames"
    nxt = job.status().get("next") if job.exists() else None
    out.next = nxt if nxt and nxt != "stone status" else "none, the timelapse is made"
    return out
