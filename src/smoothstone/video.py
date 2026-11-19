"""stone video: a vertical clip of a finished painted job, in the Omarchy look.

The clip is built from the job and the run log that made it, nothing else:
- the terminal shows the request and every command the model sent, exactly as sent but for a path,
  which is cut to …/<its last name>, with lines copied from what stone printed back (a long line
  is wrapped, or cut with a closing "…");
- the photos, the design and the turning figure come from the job's own files; the figure turns
  from the painted 3MF itself (Blender, one material per filament), so its colors are the print's;
- the sound is made here from sine partials (nothing to license), set to -16 LUFS.

Layout follows X's vertical player: no text in the top 200 px or the bottom 300 px. Every text
box is recorded as it is drawn and checked against that zone, against the tile it sits in, and
against the font's glyphs, so a missing glyph or a clipped line fails the build, not the viewer.
Cuts are short cross-fades only: no spins of the camera, zooms or flashes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

W, H, FPS = 1080, 1920, 30
SAFE_TOP, SAFE_BOTTOM = 200, 1620  # X draws its own controls over the top 200 and bottom 300 px
FADE = 6  # frames of cross-fade at each card change
TURN = 144  # frames for one full turn of the figure (4.8 s)
END_S = 2.2
HOOK_S = 1.1  # the cold open: the finished figure first, then how it was made
CARD_S = 1.4  # the photos card and the design card
TYPE_CPF = 4  # characters typed per frame
DURATION = (13.0, 16.0)
LUFS, LUFS_TOL, TRUE_PEAK = -16.0, 1.0, -1.5

# Tokyo Night, as Omarchy ships it
DESK, BG = "#13141c", "#1a1b26"
FG, STRONG, MUTED, EDGE = "#a9b1d6", "#c0caf5", "#565f89", "#414868"
ACCENT, GREEN, YELLOW, PURPLE = "#7aa2f7", "#9ece6a", "#e0af68", "#bb9af7"

GAP, IN, BORDER = 20, 14, 3  # Hyprland gaps_out, gaps_in and border, at 2x
BAR = (SAFE_TOP, SAFE_TOP + 64)  # the Waybar sits just under X's top overlay
CAP = (BAR[1] + GAP, BAR[1] + GAP + 160)  # the caption tile
BODY = CAP[1] + IN  # the first tile row under the caption
LH = 43  # terminal line height
PAD = 30  # terminal text inset

FONT_FILE = "JetBrainsMonoNerdFont-{}.ttf"
FONT_DIRS = ["~/Library/Fonts", "~/.local/share/fonts", "~/.fonts", "/usr/share/fonts/TTF",
             "/usr/share/fonts", "/usr/local/share/fonts", "/Library/Fonts"]


class VideoProblem(Exception):
    """The clip cannot be made from this job (missing file, tool or font)."""


# ---- fonts ---------------------------------------------------------------------------------------

def font_path(weight: str = "Regular") -> Path:
    """JetBrains Mono Nerd Font of this weight, from STONE_FONT_DIR or the usual font folders."""
    name = FONT_FILE.format(weight)
    dirs = [os.environ["STONE_FONT_DIR"]] if os.environ.get("STONE_FONT_DIR") else []
    for d in dirs + FONT_DIRS:
        p = Path(d).expanduser()
        if (p / name).is_file():
            return p / name
        if p.is_dir():
            hit = next(iter(sorted(p.rglob(name))), None)
            if hit:
                return hit
    raise VideoProblem(f"font {name} not found; install JetBrains Mono Nerd Font or set STONE_FONT_DIR")


_FONTS: dict = {}


def mono(size: int, weight: str = "Regular"):
    from PIL import ImageFont

    k = (size, weight)
    if k not in _FONTS:
        _FONTS[k] = ImageFont.truetype(str(font_path(weight)), size)
    return _FONTS[k]


_NOTDEF: dict = {}


def missing_glyphs(font, text: str) -> list[str]:
    """The characters of text this font draws as its notdef box."""
    k = (font.path, font.size)
    if k not in _NOTDEF:
        m = font.getmask("\uffff")
        _NOTDEF[k] = (m.size, bytes(m))
    out = []
    for ch in sorted(set(text)):
        if ch.isspace():
            continue
        m = font.getmask(ch)
        if (m.size, bytes(m)) == _NOTDEF[k]:
            out.append(ch)
    return out


# ---- what the clip shows: the plan, from the job and its run log ------------------------------------

KEEP = re.compile(r"^(NEXT:|FIX:|PASS |Found |Figure:|Size:|filament \d|From the request:|Plan:|Tier:)")
PRINT_CHECKS = ("watertight", "slicer", "bodies", "min_wall", "overhang")


def has_path(line: str) -> bool:
    """A folder path anywhere in the line: after a space, a quote, a bracket or an = sign."""
    return bool(re.search(r"(?<![\w])(~|/)[\w.-]+/", line))


# an absolute or home path in a command: after neither a word, a URL's colon or slash, nor a cut path's …
PATH = re.compile(r"(?<![\w~.:/…-])(?:~/|/)[^\s'\"()]+")


def redact(cmd: str) -> str:
    """The command as the clip shows it: each absolute or home path cut to …/<its last name>, so no
    home folder or user name reaches a public post."""
    return PATH.sub(lambda m: "…/" + m.group(0).rstrip("/").rsplit("/", 1)[-1], cmd)


def commands(log: dict) -> list[tuple[str, list[str]]]:
    """(command, the lines stone printed) for every tool call of the run, in order."""
    out = []
    for s in log.get("steps") or []:
        for c in s.get("tool_calls") or []:
            cmd = ((c.get("args") or {}).get("command") or "").strip()
            if cmd:
                out.append((cmd, (c.get("result") or "").splitlines()))
    return out


def subcommand(cmd: str) -> tuple[str, list[str]]:
    """(the stone subcommand, its words) as stone itself reads the command: a synonym like paint is
    colors, a path after build is dropped, and --job may come first."""
    from .cli import _tidy

    try:
        argv = shlex.split(cmd)
    except ValueError:
        argv = cmd.split()
    if argv[:1] == ["stone"]:
        argv = argv[1:]
    argv = _tidy(argv)
    i = next((k for k, a in enumerate(argv) if not a.startswith("-") and (k == 0 or argv[k - 1] != "--job")), None)
    return ("", argv) if i is None else (argv[i], argv[i + 1:])


def excerpt(lines: list[str], most: int = 4) -> list[str]:
    """The lines worth showing: status, FIX, PASS and NEXT lines, never one with a path in it."""
    keep = [ln for ln in lines if KEEP.match(ln) and not has_path(ln)]
    if not keep:
        keep = [ln for ln in lines[:1] if not has_path(ln)]
    if len(keep) > most:
        nxt = [ln for ln in keep if ln.startswith("NEXT:")]
        keep = [ln for ln in keep if not ln.startswith("NEXT:")][:most - len(nxt)] + nxt
    return keep


@dataclass
class Plan:
    request: str
    model: str
    date: str
    ws1: list[tuple[str, list[str]]]  # the commands typed in the first terminal, each with its lines
    find: tuple[str, list[str]] | None  # the find command and its credit lines
    design: tuple[str, list[str]] | None  # the passing build and its figure line
    checks: list[tuple[str, list[str]]]  # the build's print checks, then the colors command
    paint: str  # what the colors command asked, in words
    photos: list[Path] = field(default_factory=list)
    style: Path | None = None


def make_plan(job_root: Path, log: dict) -> Plan:
    cmds = commands(log)
    if not cmds:
        raise VideoProblem("the run log has no commands")
    m = re.search(r"^Request: (.+)$", log.get("setup") or "", re.M)
    request = m.group(1).strip() if m else ""
    model = (log.get("model") or "a small model").split()[0]
    try:
        date = datetime.fromisoformat(log["started"]).strftime("%A %-d %b")
    except (KeyError, ValueError):
        date = ""
    subs = [subcommand(c) for c, _ in cmds]
    i_find = max((i for i, (sub, _) in enumerate(subs) if sub == "find"), default=None)
    i_build = max((i for i, (c, r) in enumerate(cmds) if subs[i][0] == "build" and any(ln.startswith("Size:") for ln in r)),
                  default=None)
    i_colors = max((i for i, (c, r) in enumerate(cmds) if subs[i][0] == "colors"
                    and any(ln.startswith("NEXT: none") for ln in r)), default=None)
    if i_build is None or i_colors is None:
        raise VideoProblem("the run log has no passing build and colors: the clip shows a finished part")
    cut = i_find + 1 if i_find is not None and i_find < i_build else i_build
    ws1 = [(redact(c), excerpt(r)) for c, r in cmds[:cut]]
    find = None
    photos = sorted((job_root / "image" / "found").glob("photo_*.jpg"))
    if i_find is not None and photos:
        c, r = cmds[i_find]
        drawn = tuple(f"{p.name}:" for p in photos[:3])  # the credits of the photos on screen, no others
        find = (redact(c), [ln for ln in r if ln.startswith(drawn + ("NEXT:",)) and not has_path(ln)])
    build_c, build_r = cmds[i_build]
    build_c = redact(build_c)
    style = None
    latest = job_root / "image" / "figure" / "latest.txt"
    if latest.is_file():
        p = Path(latest.read_text().strip()).with_name("style.png")
        style = p if p.is_file() else None
    design = (build_c, [ln for ln in build_r if ln.startswith(("Figure:", "Size:"))]) if style else None
    checks_b = [ln for ln in build_r if ln.startswith("Size:")] + [
        ln for ln in build_r if ln.startswith("PASS ") and ln.split()[1].rstrip(":") in PRINT_CHECKS]
    col_c, col_r = cmds[i_colors]
    col_c = redact(col_c)
    checks_c = [ln for ln in col_r if (ln.startswith(("filament ", "PASS ", "NEXT:"))) and not has_path(ln)]
    asked = [a.split("=", 1) for a in subs[i_colors][1] if "=" in a and not a.startswith("-")]
    paint = ", ".join(("the rest" if k == "rest" else k) + " " + v for k, v in asked)
    return Plan(request, model, date, ws1, find, design, [(build_c, checks_b), (col_c, checks_c)], paint,
                photos, style)


def wrap(text: str, cols: int, rows: int = 2) -> list[str]:
    """text in at most `rows` rows of `cols` characters, broken at spaces; a longer text is cut and
    ends in " …"."""
    words, out, line = text.split(" "), [], ""
    for w in words:
        while len(w) > cols:  # a word longer than a row: break it
            if line:
                out.append(line)
                line = ""
            out.append(w[:cols])
            w = w[cols:]
        if line and len(line) + 1 + len(w) > cols:
            out.append(line)
            line = w
        else:
            line = (line + " " + w) if line else w
    out.append(line)
    if len(out) > rows:
        out = out[:rows]
        last = out[-1]
        while len(last) + 2 > cols:
            last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
        out[-1] = last + " …"
    return out


# ---- drawing ---------------------------------------------------------------------------------------

class Frame:
    """One 1080 x 1920 picture, recording every text box drawn and the tile it must stay in."""

    def __init__(self):
        from PIL import Image, ImageDraw

        self.im = Image.new("RGB", (W, H), DESK)
        self.d = ImageDraw.Draw(self.im)
        self.texts: list[tuple] = []

    def text(self, xy, s, font, fill, anchor="la", inside=None):
        self.d.text(xy, s, font=font, fill=fill, anchor=anchor)
        if s.strip():
            self.texts.append((self.d.textbbox(xy, s, font=font, anchor=anchor), inside, s, font))

    def tile(self, box, focused=False):
        x0, y0, x1, y1 = box
        self.d.rectangle(box, fill=ACCENT if focused else EDGE)
        self.d.rectangle([x0 + BORDER, y0 + BORDER, x1 - BORDER, y1 - BORDER], fill=BG)
        return (x0 + BORDER, y0 + BORDER, x1 - BORDER, y1 - BORDER)


def layout_faults(fr: Frame) -> list[str]:
    """Text in X's overlays, text past its tile's border, and glyphs the font lacks."""
    out = []
    for (x0, y0, x1, y1), inside, s, font in fr.texts:
        if y0 < SAFE_TOP or y1 > SAFE_BOTTOM:
            out.append(f"text in the X overlay zone (y {y0} to {y1}): {s!r}")
        if x0 < 0 or x1 > W:
            out.append(f"text off the frame: {s!r}")
        if inside and (x0 < inside[0] or y0 < inside[1] or x1 > inside[2] or y1 > inside[3]):
            out.append(f"text crosses its tile border: {s!r}")
        for ch in missing_glyphs(font, s):
            out.append(f"no glyph for U+{ord(ch):04X} in {s!r}")
    return out


def bar(fr: Frame, ws: int, date: str, model: str):
    y0, y1 = BAR
    cy = (y0 + y1) // 2
    fr.d.rectangle([0, y0, W, y1], fill=BG)
    fr.text((GAP + 4, cy), "\uf303", mono(34), ACCENT, "lm")  # the Arch mark, as on Omarchy's bar
    x = GAP + 64
    for k in range(1, 5):
        fr.text((x, cy), str(k), mono(28, "Bold"), ACCENT if k == ws else MUTED, "lm")
        if k == ws:
            fr.d.rectangle([x - 4, y1 - 8, x + 21, y1 - 4], fill=ACCENT)
        x += 46
    if date:
        fr.text((W // 2, cy), date, mono(28, "Bold"), FG, "mm")
    fr.text((W - GAP - 4, cy), f"\uf2db {model}", mono(26), MUTED, "rm")


def desktop(ws: int, plan: Plan, title: str, sub: str) -> Frame:
    fr = Frame()
    bar(fr, ws, plan.date, plan.model)
    inner = fr.tile([GAP, CAP[0], W - GAP, CAP[1]])
    fr.text((GAP + 40, CAP[0] + 58), title, mono(46, "Bold"), STRONG, "lm", inner)
    fr.text((GAP + 40, CAP[0] + 115), sub, mono(30), MUTED, "lm", inner)
    return fr


def line_color(text: str) -> str:
    if text.startswith("NEXT:"):
        return ACCENT
    if text.startswith("PASS"):
        return GREEN
    if text.startswith("FIX"):
        return YELLOW
    if text.startswith("#"):
        return MUTED
    return FG


PROMPT = "~/job ❯ "


def term_cols(box) -> int:
    return int((box[2] - box[0] - 2 * BORDER - 2 * PAD) // mono(30).getlength("M"))


def term_rows(kind: str, text: str, cols: int, short: bool = False) -> list[tuple[str, str, str]]:
    """(kind, row text, color) rows for one terminal line, wrapped to the pane. short: a PASS line
    takes one row (cut with " …"), so a small pane keeps more lines."""
    if kind == "cmd":
        parts = wrap(text, cols - len(PROMPT), rows=3) if text else [""]
        return [("cmd", parts[0], STRONG)] + [("cont", p, STRONG) for p in parts[1:]]
    if kind == "req":
        return [("req", p, PURPLE) for p in wrap(text, cols, rows=4)]
    color = line_color(text)
    return [("out", p, color) for p in wrap(text, cols, rows=1 if short and text.startswith("PASS") else 2)]


def draw_term(fr: Frame, box, lines, focused=True, cursor=False, short=False):
    """lines: (kind, text) with kind cmd, req or out. Shows the last whole lines that fit above the
    safe line, as a terminal scrolls: never the tail of a wrapped line without its head."""
    inner = fr.tile(box, focused)
    cols = term_cols(box)
    y0 = inner[1] + 28
    fit = (SAFE_BOTTOM - 10 - y0) // LH
    groups = [term_rows(k, t, cols, short) for k, t in lines]
    rows: list = []
    for g in reversed(groups):
        if len(rows) + len(g) > fit:
            break
        rows = g + rows
    term, termb = mono(30), mono(30, "Bold")
    y = y0
    for i, (kind, text, color) in enumerate(rows):
        x = inner[0] + PAD
        if kind == "cmd":
            fr.text((x, y), "~/job", termb, ACCENT, inside=inner)
            x += term.getlength("~/job ")
            fr.text((x, y), "❯", termb, GREEN, inside=inner)
            x += term.getlength("❯ ")
        elif kind == "cont":
            x += term.getlength(PROMPT)
        fr.text((x, y), text, termb if kind == "req" else term, color, inside=inner)
        x += term.getlength(text)
        if cursor and i == len(rows) - 1:
            fr.d.rectangle([x + 4, y + 2, x + 22, y + 36], fill=FG)
        y += LH


def picture(fr: Frame, img, box, focused=False, how="cover", fill=BG, bias=0.25):
    from PIL import Image

    inner = fr.tile(box, focused)
    w, h = inner[2] - inner[0] + 1, inner[3] - inner[1] + 1
    if how == "cover":
        w0, h0 = img.size
        sc = max(w / w0, h / h0)
        im = img.resize((round(w0 * sc), round(h0 * sc)), Image.LANCZOS)
        l0, t0 = (im.width - w) // 2, int((im.height - h) * bias)
        fr.im.paste(im.crop((l0, t0, l0 + w, t0 + h)), (inner[0], inner[1]))
    else:
        fr.d.rectangle(inner, fill=fill)
        pic = img.copy()
        pic.thumbnail((w - 40, h - 40), Image.LANCZOS)
        fr.im.paste(pic, (inner[0] + (w - pic.width) // 2, inner[1] + (h - pic.height) // 2))


# ---- the figure turning, from the 3MF's own paint -----------------------------------------------------

TURN_BOX = [GAP, BODY, W - GAP, 1250]


def turn_size() -> tuple[int, int]:
    return TURN_BOX[2] - TURN_BOX[0] - 2 * BORDER + 1, TURN_BOX[3] - TURN_BOX[1] - 2 * BORDER + 1


def painted_3mf(job_root: Path) -> Path:
    names = ["figure.3mf"]
    try:
        r = json.loads((job_root / "plan.json").read_text()).get("recipe")
        if r:
            names.append(f"{r}.3mf")
    except (OSError, ValueError):
        pass
    for n in names:
        if (job_root / n).is_file():
            return job_root / n
    raise VideoProblem("no painted 3MF in the job: run stone colors first")


def paint_npz(job_root: Path, out: Path) -> dict:
    """The painted 3MF as V, F, fil (each face's filament) and rgb (each filament's color) in an
    npz for Blender. Returns {"faces", "filaments": [(name, rgb, share of the surface)]}."""
    from . import colors as C

    f3 = painted_3mf(job_root)
    V, F, codes, main = C.read_3mf(f3)
    fil = np.array([C.decode_paint(c) if c else main for c in codes], np.int32)
    st = json.loads((job_root / "status.json").read_text()).get("colors") or {}
    names = [str(x) for x in st.get("filaments") or []]
    if not names or fil.max() > len(names):
        raise VideoProblem("the job's colors do not name every filament in its 3MF")
    rgb = np.array([C.filament_rgb(n) or (150, 150, 150) for n in names], np.uint8)
    np.savez(out, V=V, F=F, fil=fil, rgb=rgb)
    area = np.linalg.norm(np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]), axis=1)
    share = [float(area[fil == k + 1].sum() / area.sum()) for k in range(len(names))]
    return {"3mf": str(f3), "faces": int(len(F)),
            "filaments": [(n, rgb[k].tolist(), round(share[k], 4)) for k, n in enumerate(names)]}


def blender() -> str:
    b = os.environ.get("STONE_BLENDER") or shutil.which("blender")
    if not b:
        raise VideoProblem("Blender not found; install it or set STONE_BLENDER")
    return b


def turntable(npz: Path, out: Path, frames: int = TURN, log=None, size=None) -> list[Path]:
    """frames PNGs of the figure turning once, front first, size (w, h) or the turntable tile's.
    Reuses frames rendered from the same mesh, script and size (out/stamp.json)."""
    w, h = size or turn_size()
    script = Path(__file__).with_name("turntable_blender.py")
    stamp = {"mesh": hashlib.sha256(npz.read_bytes()).hexdigest()[:16],
             "script": hashlib.sha256(script.read_bytes()).hexdigest()[:16], "frames": frames, "size": [w, h]}
    want = [out / f"f_{i:04d}.png" for i in range(frames)]
    sp = out / "stamp.json"
    if sp.is_file() and json.loads(sp.read_text()) == stamp and all(p.is_file() for p in want):
        return want
    out.mkdir(parents=True, exist_ok=True)
    for p in out.glob("f_*.png"):
        p.unlink()
    p = subprocess.run([blender(), "-b", "--factory-startup", "--python", str(script), "--",
                        str(npz), str(out), str(frames), str(w), str(h)],
                       capture_output=True, text=True)
    if log:
        log.write_text(p.stdout[-20000:] + p.stderr[-5000:])
    if p.returncode != 0 or not all(q.is_file() for q in want):
        raise VideoProblem(f"Blender failed ({p.returncode}): {(p.stderr or p.stdout)[-400:]}")
    sp.write_text(json.dumps(stamp))
    return want


# ---- the timeline ----------------------------------------------------------------------------------

@dataclass
class Shots:
    frames: list = field(default_factory=list)  # PIL images, in order
    faults: list[str] = field(default_factory=list)
    taps: list[float] = field(default_factory=list)
    marks: dict = field(default_factory=dict)  # name -> first frame of a card
    rows: list[dict] = field(default_factory=list)  # every terminal line shown, with its source
    _last: object = None
    _fade: int = 0
    _from: object = None

    def emit(self, fr: Frame):
        from PIL import Image

        for f in layout_faults(fr):
            if f not in self.faults:
                self.faults.append(f)
        im = fr.im
        if self._fade:
            im = Image.blend(self._from, fr.im, 1 - self._fade / (FADE + 1))
            self._fade -= 1
        self.frames.append(im)
        self._last = fr.im

    def hold(self, fr: Frame, seconds: float):
        for _ in range(round(seconds * FPS)):
            self.emit(fr)

    def card(self, name: str):
        self.marks[name] = len(self.frames)
        if self._last is not None:
            self._from, self._fade = self._last, FADE


def model_size(model: str) -> str:
    """ "1.7B" from "LFM3-1.7B", or the model's name when it states no size."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*([BM])\b", model, re.I)
    return f"{m.group(1)}{m.group(2).upper()}" if m else model


def figure_tile(fr: Frame, tile, box, focused=True):
    """A turntable frame (RGBA) on the tile's background."""
    from PIL import Image

    inner = fr.tile(box, focused)
    w, h = inner[2] - inner[0] + 1, inner[3] - inner[1] + 1
    t = tile.convert("RGBA")
    if t.size != (w, h):
        sc = min(w / t.width, h / t.height)
        t = t.resize((round(t.width * sc), round(t.height * sc)), Image.LANCZOS)
    bg = Image.new("RGBA", (w, h), BG)
    bg.alpha_composite(t, ((w - t.width) // 2, (h - t.height) // 2))
    fr.im.paste(bg.convert("RGB"), (inner[0], inner[1]))
    return inner


def legend(fr: Frame, inner, filaments):
    """One swatch per filament, top right of the figure's tile: its color, name and share."""
    font = mono(28, "Bold")
    x1 = inner[2] - 28
    y = inner[1] + 30
    for name, rgb, share in filaments:
        label = f"{name} {round(share * 100)}%"
        x0 = x1 - int(font.getlength(label)) - 58
        fr.d.rounded_rectangle([x0, y, x0 + 40, y + 40], 8, fill=tuple(rgb), outline=FG, width=3)
        fr.text((x0 + 56, y + 20), label, font, STRONG, "lm", inner)
        y += 58


def compose(plan: Plan, turn_frames: list[Path], filaments=()) -> Shots:
    from PIL import Image

    sh = Shots()
    term1 = [GAP, BODY, W - GAP, H - GAP]
    size = model_size(plan.model)
    tiles = [Image.open(p) for p in turn_frames]

    # 0. the cold open: the painted figure already turning, and the one sentence it came from
    sh.card("hook")
    n_hook = round(HOOK_S * FPS)
    k0 = len(tiles) * 7 // 8  # a three-quarter view turning to the front
    for i in range(n_hook):
        fr = desktop(4, plan, f"a {size} model made this", "from one sentence, on a CPU, no cloud")
        inner = figure_tile(fr, tiles[(k0 + i) % len(tiles)], TURN_BOX)
        legend(fr, inner, filaments)
        box = fr.tile([GAP, TURN_BOX[3] + IN, W - GAP, H - GAP])
        y = box[1] + 40
        for row in wrap(f"\u201c{plan.request}\u201d", 46, rows=6):
            fr.text((box[0] + PAD, y), row, mono(34, "Bold"), PURPLE, "la", box)
            y += 50
        sh.emit(fr)

    # 1. the request, then the model's own commands
    def f1(lines, cursor=True):
        fr = desktop(1, plan, "one sentence, one small model", f"{plan.model} picks every command")
        draw_term(fr, term1, lines, cursor=cursor)
        return fr

    sh.card("terminal")
    lines = [("out", "# the request, typed by a person:")]
    req = plan.request
    for i in range(0, len(req) + TYPE_CPF, TYPE_CPF):
        if i and (i // TYPE_CPF) % 2 == 0:
            sh.taps.append(len(sh.frames) / FPS)
        sh.emit(f1(lines + [("req", req[:i])]))
    lines += [("req", req), ("out", f"# from here on, {plan.model} alone:")]
    sh.rows.append({"kind": "req", "text": req})
    sh.hold(f1(lines), 0.3)
    for cmd, outs in plan.ws1:
        for c in range(TYPE_CPF, len(cmd) + TYPE_CPF, TYPE_CPF):
            sh.taps.append(len(sh.frames) / FPS)
            sh.emit(f1(lines + [("cmd", cmd[:c])]))
        lines.append(("cmd", cmd))
        sh.hold(f1(lines, cursor=False), 0.13)
        lines += [("out", o) for o in outs]
        sh.rows += [{"kind": "cmd", "text": cmd}] + [{"kind": "out", "cmd": cmd, "text": o} for o in outs]
        sh.hold(f1(lines + [("cmd", "")]), 0.27)
    sh.hold(f1(lines + [("cmd", "")]), 0.3)

    # 2. the photos it found
    if plan.find and plan.photos:
        sh.card("photos")
        n = len(plan.photos)
        fr = desktop(2, plan, f"it found {n} free photo{'s' if n > 1 else ''}", "credited, from Wikimedia Commons")
        pics = [Image.open(p).convert("RGB") for p in plan.photos[:3]]
        row_end = 1180
        if len(pics) == 1:
            picture(fr, pics[0], [GAP, BODY, W - GAP, row_end], focused=True)
        else:
            mid = GAP + (W - 2 * GAP - IN) // 2
            picture(fr, pics[0], [GAP, BODY, mid, row_end], focused=True, bias=0.2)
            if len(pics) == 2:
                picture(fr, pics[1], [mid + IN, BODY, W - GAP, row_end], bias=0.2)
            else:
                half = BODY + (row_end - BODY - IN) // 2
                picture(fr, pics[1], [mid + IN, BODY, W - GAP, half], bias=0.1)
                picture(fr, pics[2], [mid + IN, half + IN, W - GAP, row_end], bias=0.2)
        cmd, outs = plan.find
        draw_term(fr, [GAP, row_end + IN, W - GAP, H - GAP], [("cmd", cmd)] + [("out", o) for o in outs],
                  focused=False)
        sh.rows += [{"kind": "cmd", "text": cmd}] + [{"kind": "out", "cmd": cmd, "text": o} for o in outs]
        sh.hold(fr, CARD_S)

    # 3. the design
    if plan.design and plan.style:
        sh.card("design")
        fr = desktop(3, plan, "it designed the figure", "drawn from the photos by a local model")
        end = 1240
        picture(fr, Image.open(plan.style).convert("RGB"), [GAP, BODY, W - GAP, end], focused=True,
                how="fit", fill=(253, 253, 253))
        cmd, outs = plan.design
        draw_term(fr, [GAP, end + IN, W - GAP, H - GAP], [("cmd", cmd)] + [("out", o) for o in outs],
                  focused=False)
        sh.rows += [{"kind": "cmd", "text": cmd}] + [{"kind": "out", "cmd": cmd, "text": o} for o in outs]
        sh.hold(fr, CARD_S)

    # 4. the painted figure turning, and the checks it passed
    sh.card("turntable")
    cb = [GAP, TURN_BOX[3] + IN, W - GAP, H - GAP]
    feed = []
    for cmd, outs in plan.checks:
        feed += [("cmd", cmd)] + [("out", o) for o in outs]
        sh.rows += [{"kind": "cmd", "text": cmd}] + [{"kind": "out", "cmd": cmd, "text": o} for o in outs]
    total = FADE + len(turn_frames)
    step = max(1, (total - 24) // max(1, len(feed)))  # every line is up with 0.8 s to read the last
    for i in range(total):
        fr = desktop(4, plan, "painted and print-ready", plan.paint)
        inner = figure_tile(fr, tiles[(i - FADE) % len(tiles)], TURN_BOX)  # angle 0 just as the fade ends
        legend(fr, inner, filaments)
        draw_term(fr, cb, feed[:min(len(feed), 1 + i // step)], focused=False, short=True)
        sh.emit(fr)

    # 5. the end card
    sh.card("end")
    fr = Frame()
    bar(fr, 1, plan.date, plan.model)
    split = 1000
    figure_tile(fr, tiles[0], [GAP, BAR[1] + GAP, W - GAP, split], focused=False)
    box = fr.tile([GAP, split + IN, W - GAP, H - GAP], focused=True)
    fr.text((W // 2, split + 150), size, mono(200, "Bold"), ACCENT, "mm", box)
    fr.text((W // 2, split + 285), "a tiny model ran every step", mono(36, "Bold"), STRONG, "mm", box)
    fr.text((W // 2, split + 345), "one sentence \u2192 a painted, printable figure", mono(30), FG, "mm", box)
    fr.text((W // 2, split + 400), "on a CPU \u00b7 local \u00b7 no cloud", mono(30), GREEN, "mm", box)
    fr.text((W // 2, split + 500), "smoothstone", mono(44, "Bold"), PURPLE, "mm", box)
    sh.hold(fr, END_S)
    return sh


def row_faults(rows: list[dict], log: dict) -> list[str]:
    """Every command shown is one the model sent, and every line shown is a line stone printed back
    to that command, in the run log the clip claims."""
    sent = commands(log)
    said = {c for c, _ in sent} | {redact(c) for c, _ in sent}  # the shown form maps back to the logged one
    printed: dict[str, set] = {}
    for c, r in sent:
        printed.setdefault(c, set()).update(r)
        printed.setdefault(redact(c), set()).update(r)
    m = re.search(r"^Request: (.+)$", log.get("setup") or "", re.M)
    out = []
    for r in rows:
        if r["kind"] == "req":
            if not m or r["text"] != m.group(1).strip():
                out.append(f"the request shown is not the run's request: {r['text']!r}")
        elif r["kind"] == "cmd":
            if r["text"] not in said:
                out.append(f"a command the model never sent: {r['text']!r}")
            if redact(r["text"]) != r["text"]:
                out.append(f"a command shown with a path in it: {r['text']!r}")
        elif r["text"] not in printed.get(r["cmd"], set()):
            out.append(f"a line stone never printed for {r['cmd']!r}: {r['text']!r}")
    return out


# ---- the sound ---------------------------------------------------------------------------------------

SR = 48000


def soundtrack(path: Path, marks: dict, taps: list[float], total: float, seed: int = 7):
    """A soft tonal bed, sums of sine partials only (no noise, nothing to license): a low open fifth
    under everything, a low thump as each card lands, key taps while typing, music-box plucks as the
    design appears, a stepper-motor song and a hum under the turning figure, a wooden tap at the end."""
    from scipy.io import wavfile
    from scipy.signal import butter, sosfilt

    rng = np.random.default_rng(seed)
    N = int(round(total * SR))
    L, R = np.zeros(N), np.zeros(N)

    def lowpass(x, f):
        return sosfilt(butter(2, f, "lowpass", fs=SR, output="sos"), x)

    def env(n, a, r):
        e = np.ones(n)
        a, r = min(a, n // 2), min(r, n // 2)
        if a:
            e[:a] = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, a))
        if r:
            e[-r:] = 0.5 + 0.5 * np.cos(np.linspace(0, np.pi, r))
        return e

    def put(sig, t, pan=0.0, gain=1.0):
        i = int(t * SR)
        if i >= N:
            return
        sig = sig[: N - i] * gain
        L[i:i + len(sig)] += sig * np.sqrt(0.5 * (1 - pan))
        R[i:i + len(sig)] += sig * np.sqrt(0.5 * (1 + pan))

    def partials(dur, parts, attack=0.004):
        n = int(dur * SR)
        t = np.arange(n) / SR
        s = sum(a * np.sin(2 * np.pi * f * t) * np.exp(-t * d) for f, a, d in parts)
        return s * env(n, int(attack * SR), int(0.02 * SR))

    def thump():
        n = int(0.3 * SR)
        t = np.arange(n) / SR
        f = 70 + 80 * np.exp(-t * 30)
        return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 16) * env(n, int(0.003 * SR), int(0.05 * SR))

    def stepper(dur, f0, f1):
        n = int(dur * SR)
        ph = 2 * np.pi * np.cumsum(np.linspace(f0, f1, n)) / SR
        s = np.sin(ph) + 0.3 * np.sin(3 * ph) + 0.1 * np.sin(5 * ph)
        return lowpass(s, 1500) * env(n, int(0.04 * SR), int(0.06 * SR))

    t_of = {k: v / FPS for k, v in marks.items()}
    order = sorted(t_of.items(), key=lambda kv: kv[1])  # a series has terminal_0, pair_0, turntable_0, ...

    def after(name):
        later = [t for k, t in order if t > t_of[name]]
        return later[0] if later else total

    def of(*bases):
        return [(k, t) for k, t in order if k.split("_")[0] in bases]
    tt = np.arange(N) / SR
    bed = sum(a * np.sin(2 * np.pi * f * tt + ph) for f, a, ph in [(55, 1.0, 0), (82.4, 0.6, 1.1), (110, 0.35, 2.3)])
    bed = lowpass(bed * (1 + 0.2 * np.sin(2 * np.pi * 0.13 * tt)), 300) * env(N, int(0.8 * SR), int(1.0 * SR))
    L += bed * 0.05
    R += np.roll(bed, int(0.011 * SR)) * 0.05

    for i, t0 in enumerate(taps):
        f = 880 * (1.0, 1.06, 0.94, 1.12)[i % 4]
        put(partials(0.12, [(f, 1.0, 60), (2.4 * f, 0.2, 90)], attack=0.002), t0 + rng.uniform(0, 0.01),
            pan=rng.uniform(-0.2, 0.2), gain=0.05 * rng.uniform(0.8, 1.0))
    gains = {"photos": 1.0, "design": 0.85, "pair": 0.85, "turntable": 0.8, "end": 0.9}
    for k, t in order:
        if k.split("_")[0] in gains:
            put(thump(), t, gain=0.5 * gains[k.split("_")[0]])
    for _, th in of("hook"):  # a bright chord under the cold open, after the first 10 ms stay quiet
        for f, pan in ((392.0, -0.25), (493.9, 0.0), (587.3, 0.25)):
            put(partials(1.1, [(f, 1.0, 4), (2 * f, 0.2, 9)], attack=0.03), th + 0.08, pan=pan, gain=0.07)
    for _, tp in of("photos"):
        put(partials(0.35, [(330, 1.0, 22), (660, 0.3, 35)]), tp + 0.55, pan=-0.15, gain=0.14)
    for name, td in of("design", "pair"):
        t, nxt = td + 0.3, after(name) - 0.4
        for k, f in enumerate([659.3, 784.0, 880.0, 1046.5, 1174.7, 1318.5]):
            if t >= nxt:
                break
            put(partials(0.9, [(f, 1.0, 6), (2 * f, 0.25, 12), (3 * f, 0.06, 20)]), t, pan=-0.3 + 0.12 * k, gain=0.09)
            t += 0.32
    for name, t0 in of("turntable"):
        t1 = after(name)
        t, k = t0 + 0.2, 0
        song = [440, 523, 392, 587, 494, 330, 440, 659, 523, 392]
        while t < t1 - 0.4:
            d = rng.uniform(0.2, 0.5)
            f = song[k % len(song)] * rng.choice([0.5, 1.0])
            put(stepper(d, f * 0.97, f), t, pan=rng.uniform(-0.3, 0.3), gain=0.04)
            t += d + rng.uniform(0.06, 0.2)
            k += 1
        n = int((t1 - t0) * SR)
        th = np.arange(n) / SR
        hum = (np.sin(2 * np.pi * 58 * th) + 0.3 * np.sin(2 * np.pi * 116 * th)) * (1 + 0.05 * np.sin(np.pi * th))
        put(lowpass(hum, 300) * env(n, int(0.5 * SR), int(0.5 * SR)), t0, gain=0.03)
    for _, te in of("end"):
        put(partials(0.8, [(196, 1.0, 14), (547, 0.45, 26), (1180, 0.15, 40)], attack=0.002), te + 0.12,
            gain=0.2)
    st = np.stack([L, R], 1)
    st *= 10 ** (-3.0 / 20) / np.abs(st).max()  # headroom; the loudness is set at the encode
    st *= env(N, int(0.05 * SR), int(0.5 * SR))[:, None]  # no edge starts or stops on a step
    wavfile.write(str(path), SR, (st * 32767).astype(np.int16))


# ---- encode, measure, contact sheet ------------------------------------------------------------------

def ffmpeg() -> str:
    f = shutil.which("ffmpeg")
    if not f:
        raise VideoProblem("ffmpeg not found")
    return f


def ffprobe() -> str:
    f = shutil.which("ffprobe")
    if not f:
        raise VideoProblem("ffprobe not found")
    return f


def encode(frames: list, wav: Path, out: Path, total: float):
    """H.264 yuv420p at 30 fps with faststart, AAC 48 kHz at -16 LUFS (two-pass loudnorm)."""
    silent = out.with_suffix(".silent.mp4")
    p = subprocess.Popen([ffmpeg(), "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "18",
                          "-preset", "slow", "-pix_fmt", "yuv420p", str(silent)], stdin=subprocess.PIPE)
    try:
        for im in frames:
            p.stdin.write(im.tobytes())
        p.stdin.close()
    except OSError:  # the encoder died mid-write (a broken pipe)
        p.kill()
    if p.wait() != 0:
        raise VideoProblem("ffmpeg could not encode the frames")
    probe = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(wav), "-af",
                            f"loudnorm=I={LUFS}:TP={TRUE_PEAK - 0.5}:LRA=11:print_format=json", "-f", "null", "-"],
                           capture_output=True, text=True).stderr
    try:
        m = json.loads(probe[probe.rindex("{"):probe.rindex("}") + 1])
    except ValueError:
        raise VideoProblem(f"ffmpeg could not measure the sound: {probe[-300:]}") from None
    af = (f"loudnorm=I={LUFS}:TP={TRUE_PEAK - 0.5}:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
          f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}"
          f":linear=true,aresample=48000,afade=t=in:d=0.05,afade=t=out:st={total - 0.5:.3f}:d=0.5")
    r = subprocess.run([ffmpeg(), "-loglevel", "error", "-y", "-i", str(silent), "-i", str(wav), "-map", "0:v",
                        "-map", "1:a", "-c:v", "copy", "-af", af, "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                        "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)], capture_output=True, text=True)
    silent.unlink(missing_ok=True)
    if r.returncode != 0:
        raise VideoProblem(f"ffmpeg could not add the sound: {r.stderr[-300:]}")


def atoms(path: Path) -> list[str]:
    """The top-level MP4 boxes in file order."""
    out = []
    with open(path, "rb") as f:
        while True:
            h = f.read(8)
            if len(h) < 8:
                return out
            size, kind = int.from_bytes(h[:4], "big"), h[4:].decode("latin-1")
            if size == 1:
                size = int.from_bytes(f.read(8), "big") - 8
            out.append(kind)
            if size < 8:
                return out
            f.seek(size - 8, 1)


def check_clip(mp4: Path, duration: tuple[float, float] = DURATION) -> tuple[dict, list[str]]:
    """(facts, faults) for the delivery spec: 1080 x 1920, 30 fps, 13 to 16 s (a series: SERIES),
    H.264 yuv420p, faststart, AAC 48 kHz, -16 LUFS within 1, true peak under -1.5 dB, quiet first
    and last 10 ms."""
    pr = json.loads(subprocess.run([ffprobe(), "-v", "error", "-show_streams", "-show_format", "-of", "json",
                                    str(mp4)], capture_output=True, text=True).stdout or "{}")
    v = next((s for s in pr.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in pr.get("streams", []) if s.get("codec_type") == "audio"), {})
    dur = float((pr.get("format") or {}).get("duration") or 0)
    eb = subprocess.run([ffmpeg(), "-hide_banner", "-nostats", "-i", str(mp4), "-af", "ebur128=peak=true",
                         "-f", "null", "-"], capture_output=True, text=True).stderr
    summ = eb[eb.rfind("Summary:"):]
    lufs = float(re.search(r"I:\s+(-?[\d.]+) LUFS", summ).group(1))
    peak = float(re.search(r"Peak:\s+(-?[\d.]+|-inf) dBFS", summ).group(1))
    raw = subprocess.run([ffmpeg(), "-loglevel", "error", "-i", str(mp4), "-map", "0:a", "-ac", "1", "-f", "f32le",
                          "-ar", str(SR), "-"], capture_output=True).stdout
    s = np.frombuffer(raw, np.float32)
    k = SR // 100

    def dbfs(x):
        return float(20 * np.log10(np.sqrt(np.mean(x.astype(float) ** 2)) + 1e-12))

    top = atoms(mp4)
    facts = {"width": v.get("width"), "height": v.get("height"), "fps": v.get("r_frame_rate"),
             "video": v.get("codec_name"), "pix_fmt": v.get("pix_fmt"), "seconds": round(dur, 3),
             "audio": a.get("codec_name"), "sample_rate": int(a.get("sample_rate") or 0),
             "lufs": lufs, "true_peak": peak, "start_dbfs": round(dbfs(s[:k]), 1), "end_dbfs": round(dbfs(s[-k:]), 1),
             "faststart": "moov" in top and "mdat" in top and top.index("moov") < top.index("mdat")}
    bad = []
    if (facts["width"], facts["height"]) != (W, H):
        bad.append(f"size {facts['width']} x {facts['height']}, not {W} x {H}")
    if facts["fps"] != f"{FPS}/1":
        bad.append(f"frame rate {facts['fps']}")
    if facts["video"] != "h264" or facts["pix_fmt"] != "yuv420p":
        bad.append(f"video {facts['video']} {facts['pix_fmt']}, not h264 yuv420p")
    if not duration[0] <= dur <= duration[1]:
        bad.append(f"{dur:.2f} s long, not {duration[0]:.0f} to {duration[1]:.0f} s")
    if facts["audio"] != "aac" or facts["sample_rate"] != SR:
        bad.append(f"audio {facts['audio']} at {facts['sample_rate']} Hz, not AAC at 48 kHz")
    if abs(lufs - LUFS) > LUFS_TOL:
        bad.append(f"loudness {lufs} LUFS, not {LUFS} within {LUFS_TOL}")
    if peak >= TRUE_PEAK:
        bad.append(f"true peak {peak} dB, not under {TRUE_PEAK}")
    if facts["start_dbfs"] > -45 or facts["end_dbfs"] > -45:
        bad.append(f"the sound starts or stops abruptly ({facts['start_dbfs']} / {facts['end_dbfs']} dBFS)")
    if not facts["faststart"]:
        bad.append("not faststart: the moov box comes after the media")
    return facts, bad


def stills(mp4: Path, out: Path, at: dict[str, float]):
    """A contact sheet at 1 fps (sheet.png) and a full-size frame at each named time."""
    out.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([ffmpeg(), "-loglevel", "error", "-y", "-i", str(mp4), "-vf",
                        "fps=1,scale=270:-1,tile=8x2:padding=6:color=0x13141c", "-frames:v", "1",
                        str(out / "sheet.png")], check=True, capture_output=True, text=True)
        for name, t in at.items():
            subprocess.run([ffmpeg(), "-loglevel", "error", "-y", "-i", str(mp4), "-ss", f"{t:.4f}", "-frames:v",
                            "1", str(out / f"{name}.png")], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise VideoProblem(f"ffmpeg could not take the stills: {(e.stderr or '')[-300:]}") from None


# ---- the whole step ----------------------------------------------------------------------------------

def make(job_root: Path, log_path: Path, out: Path, turn: int = TURN) -> dict:
    """The clip of a finished painted job: out/clip.mp4, clip.wav, sheet.png, the key frames and
    report.json. Raises VideoProblem when the job or a tool is missing."""
    if turn < 8:
        raise VideoProblem(f"--turn {turn} is too few frames: one turn takes at least 8")
    try:
        log = json.loads(log_path.read_text())
    except (ValueError, UnicodeDecodeError):
        raise VideoProblem("the run log is not JSON") from None
    if not isinstance(log, dict):
        raise VideoProblem("the run log is not JSON")
    plan = make_plan(job_root, log)
    out.mkdir(parents=True, exist_ok=True)
    paint = paint_npz(job_root, out / "mesh.npz")
    frames = turntable(out / "mesh.npz", out / "turn", turn, log=out / "blender.log")
    sh = compose(plan, frames, paint["filaments"])
    faults = sh.faults + row_faults(sh.rows, log)
    total = len(sh.frames) / FPS
    soundtrack(out / "clip.wav", sh.marks, sh.taps, total)
    mp4 = out / "clip.mp4"
    encode(sh.frames, out / "clip.wav", mp4, total)
    facts, bad = check_clip(mp4)
    at = {f"card_{k + 1}_{name}": (sh.marks[name] + FADE + 1) / FPS
          for k, name in enumerate(n for n in ("hook", "terminal", "photos", "design", "turntable", "end") if n in sh.marks)}
    term_end = sh.marks.get("photos", sh.marks.get("design", sh.marks["turntable"]))
    at["card_2_terminal"] = (term_end - 2) / FPS  # the terminal at its fullest, just before the cut
    t0 = sh.marks["turntable"] + FADE
    for deg in (0, 90, 180, 270):
        at[f"turn_{deg:03d}"] = (t0 + round(deg / 360 * len(frames)) + 0.5) / FPS
    stills(mp4, out / "stills", at)
    report = {"clip": str(mp4), "log": str(log_path), "job": str(job_root), "seconds": round(total, 3),
              "frames": len(sh.frames), "marks": sh.marks, "paint": paint, "paint_words": plan.paint, "spec": facts,
              "faults": faults + bad, "rows": sh.rows, "stills": sorted(at)}
    (out / "report.json").write_text(json.dumps(report, indent=1))
    return report


# ---- several figures in one clip ---------------------------------------------------------------------
# The same honesty as one figure: each run's terminal lines check against that run's own log, and
# each figure turns from its own painted 3MF. The cold open puts them side by side.

SERIES = (24.0, 34.0)  # seconds, for two to four figures
SERIES_TURN = 120  # frames for each figure's own turn (4 s)
HOOK3_S, PAIR_S, END3_S = 2.2, 1.4, 2.6
FAST_CPF = 9  # characters typed per frame in a series: the same lines, typed faster
ROW_END = 1250  # the three-up tiles end where the turntable tile does


@dataclass
class Run:
    plan: Plan
    log: dict
    label: str  # the base name ("ELON"), else the found subject
    wide: list  # turntable frames for its own card (paths or images)
    narrow: list  # the same turn at the three-up tile size
    filaments: list = field(default_factory=list)


def label_of(job_root: Path) -> str:
    try:
        name = (json.loads((job_root / "plan.json").read_text()).get("params") or {}).get("name")
        if name:
            return str(name)
    except (OSError, ValueError):
        pass
    try:
        return str(json.loads((job_root / "image" / "found" / "found.json").read_text())["subject"])
    except (OSError, ValueError, KeyError):
        return job_root.parent.name


def columns(n: int, y0: int, y1: int) -> list[list[int]]:
    """n tiles side by side between y0 and y1, Hyprland gaps between them."""
    cell = (W - 2 * GAP - (n - 1) * IN) // n
    return [[GAP + k * (cell + IN), y0, GAP + k * (cell + IN) + cell, y1] for k in range(n)]


def narrow_size(n: int) -> tuple[int, int]:
    x0, y0, x1, y1 = columns(n, BODY, ROW_END)[0]
    return x1 - x0 - 2 * BORDER + 1, y1 - y0 - 2 * BORDER + 1


def _img(f):
    from PIL import Image

    return f if hasattr(f, "size") else Image.open(f)


def compose_series(runs: list[Run]) -> Shots:
    from PIL import Image

    sh = Shots()
    n = len(runs)
    p0 = runs[0].plan
    size = model_size(p0.model)
    cols = columns(n, BODY, ROW_END)
    words = {2: "both", 3: "all three", 4: "all four"}.get(n, f"all {n}")

    # 0. the cold open: every painted figure turning, side by side
    sh.card("hook")
    for i in range(round(HOOK3_S * FPS)):
        fr = desktop(4, p0, f"a {size} model made {words}", "one sentence each, on a CPU, no cloud")
        for r, box in zip(runs, cols):
            figure_tile(fr, _img(r.narrow[(len(r.narrow) * 7 // 8 + i) % len(r.narrow)]), box)
        inner = fr.tile([GAP, ROW_END + IN, W - GAP, H - GAP])
        for r, box in zip(runs, cols):
            fr.text(((box[0] + box[2]) // 2, ROW_END + IN + 70), r.label, mono(40, "Bold"), PURPLE, "mm", inner)
        fr.text((W // 2, ROW_END + IN + 170), f"{n} sentences in, {n} painted figures out", mono(32, "Bold"),
                STRONG, "mm", inner)
        fr.text((W // 2, ROW_END + IN + 230), f"{p0.model} picked every command", mono(30), GREEN, "mm", inner)
        sh.emit(fr)

    for k, r in enumerate(runs):
        plan, ws = r.plan, k + 1

        # 1. the request and the model's own commands, typed fast
        def term(lines, cursor=True):
            fr = desktop(ws, plan, f"{k + 1} of {n}: {r.label}", f"{plan.model} picks every command")
            draw_term(fr, [GAP, BODY, W - GAP, H - GAP], lines, cursor=cursor)
            return fr

        sh.card(f"terminal_{k}")
        lines = [("out", "# the request, typed by a person:")]
        req = plan.request
        for i in range(0, len(req) + FAST_CPF, FAST_CPF):
            if i and (i // FAST_CPF) % 2 == 0:
                sh.taps.append(len(sh.frames) / FPS)
            sh.emit(term(lines + [("req", req[:i])]))
        lines += [("req", req), ("out", f"# from here on, {plan.model} alone:")]
        sh.rows.append({"run": k, "kind": "req", "text": req})
        sh.hold(term(lines), 0.2)
        for cmd, outs in plan.ws1:
            for c in range(FAST_CPF, len(cmd) + FAST_CPF, FAST_CPF):
                sh.taps.append(len(sh.frames) / FPS)
                sh.emit(term(lines + [("cmd", cmd[:c])]))
            lines.append(("cmd", cmd))
            lines += [("out", o) for o in outs]
            sh.rows += [{"run": k, "kind": "cmd", "text": cmd}] + [
                {"run": k, "kind": "out", "cmd": cmd, "text": o} for o in outs]
            sh.hold(term(lines + [("cmd", "")]), 0.2)
        sh.hold(term(lines + [("cmd", "")]), 0.25)

        # 2. the photo it found beside the design drawn from it
        if plan.photos and plan.style:
            sh.card(f"pair_{k}")
            fr = desktop(ws, plan, "a free photo in, a design out", "photos credited, from Wikimedia Commons")
            end = 1180
            mid = GAP + (W - 2 * GAP - IN) // 2
            picture(fr, Image.open(plan.photos[0]).convert("RGB"), [GAP, BODY, mid, end], bias=0.2)
            picture(fr, Image.open(plan.style).convert("RGB"), [mid + IN, BODY, W - GAP, end], focused=True,
                    how="fit", fill=(253, 253, 253))
            shown = []
            if plan.find:
                cmd, outs = plan.find
                shown += [(cmd, [o for o in outs if not o.startswith("NEXT:")][:1])]
            if plan.design:
                shown += [plan.design]
            feed = []
            for cmd, outs in shown:
                feed += [("cmd", cmd)] + [("out", o) for o in outs]
                sh.rows += [{"run": k, "kind": "cmd", "text": cmd}] + [
                    {"run": k, "kind": "out", "cmd": cmd, "text": o} for o in outs]
            draw_term(fr, [GAP, end + IN, W - GAP, H - GAP], feed, focused=False, short=True)
            sh.hold(fr, PAIR_S)

        # 3. the painted figure turning once, and the checks it passed
        sh.card(f"turntable_{k}")
        cb = [GAP, TURN_BOX[3] + IN, W - GAP, H - GAP]
        feed = []
        for cmd, outs in plan.checks:
            feed += [("cmd", cmd)] + [("out", o) for o in outs]
            sh.rows += [{"run": k, "kind": "cmd", "text": cmd}] + [
                {"run": k, "kind": "out", "cmd": cmd, "text": o} for o in outs]
        total = FADE + len(r.wide)
        step = max(1, (total - 24) // max(1, len(feed)))
        for i in range(total):
            fr = desktop(ws, plan, f"{r.label}: painted and print-ready", plan.paint)
            inner = figure_tile(fr, _img(r.wide[(i - FADE) % len(r.wide)]), TURN_BOX)
            legend(fr, inner, r.filaments)
            draw_term(fr, cb, feed[:min(len(feed), 1 + i // step)], focused=False, short=True)
            sh.emit(fr)

    # 4. the end card: every figure from the front
    sh.card("end")
    fr = Frame()
    bar(fr, 4, p0.date, p0.model)
    split = 1000
    for r, box in zip(runs, columns(n, BAR[1] + GAP, split)):
        figure_tile(fr, _img(r.narrow[0]), box, focused=False)
    box = fr.tile([GAP, split + IN, W - GAP, H - GAP], focused=True)
    fr.text((W // 2, split + 150), size, mono(200, "Bold"), ACCENT, "mm", box)
    fr.text((W // 2, split + 285), "a tiny model ran every step", mono(36, "Bold"), STRONG, "mm", box)
    fr.text((W // 2, split + 345), f"{n} sentences → {n} painted, printable figures", mono(30), FG, "mm", box)
    fr.text((W // 2, split + 400), "on a CPU · local · no cloud", mono(30), GREEN, "mm", box)
    fr.text((W // 2, split + 500), "smoothstone", mono(44, "Bold"), PURPLE, "mm", box)
    sh.hold(fr, END3_S)
    return sh


def series_row_faults(rows: list[dict], logs: list[dict]) -> list[str]:
    """row_faults for each run's own rows against that run's own log."""
    out = []
    for k, log in enumerate(logs):
        out += [f"figure {k + 1}: {f}" for f in row_faults([r for r in rows if r.get("run") == k], log)]
    return out


def make_series(items: list[tuple[Path, Path]], out: Path, turn: int = SERIES_TURN) -> dict:
    """One clip of several finished painted jobs, each from its own run log: out/clip.mp4 and the
    same report as make(), with "runs" naming each job and log."""
    if not 2 <= len(items) <= 4:
        raise VideoProblem("a series clip takes two to four runs")
    if turn < 8:
        raise VideoProblem(f"--turn {turn} is too few frames: one turn takes at least 8")
    runs, info = [], []
    out.mkdir(parents=True, exist_ok=True)
    for k, (job_root, log_path) in enumerate(items):
        try:
            log = json.loads(Path(log_path).read_text())
        except (OSError, ValueError, UnicodeDecodeError):
            raise VideoProblem(f"the run log {log_path} is not JSON") from None
        if not isinstance(log, dict):
            raise VideoProblem(f"the run log {log_path} is not JSON")
        plan = make_plan(job_root, log)
        d = out / f"run{k + 1}"
        d.mkdir(exist_ok=True)
        paint = paint_npz(job_root, d / "mesh.npz")
        wide = turntable(d / "mesh.npz", d / "turn", turn, log=d / "blender.log")
        narrow = turntable(d / "mesh.npz", d / "turn3", turn, log=d / "blender3.log", size=narrow_size(len(items)))
        runs.append(Run(plan, log, label_of(job_root), wide, narrow, paint["filaments"]))
        info.append({"job": str(job_root), "log": str(log_path), "label": runs[-1].label, "request": plan.request,
                     "paint": paint, "paint_words": plan.paint})
    sh = compose_series(runs)
    faults = sh.faults + series_row_faults(sh.rows, [r.log for r in runs])
    total = len(sh.frames) / FPS
    soundtrack(out / "clip.wav", sh.marks, sh.taps, total)
    mp4 = out / "clip.mp4"
    encode(sh.frames, out / "clip.wav", mp4, total)
    facts, bad = check_clip(mp4, SERIES)
    at = {"card_hook": (sh.marks["hook"] + FADE + 1) / FPS, "card_end": (sh.marks["end"] + FADE + 1) / FPS}
    for k in range(len(runs)):
        nxt = sh.marks.get(f"pair_{k}", sh.marks[f"turntable_{k}"])
        at[f"fig{k + 1}_terminal"] = (nxt - 2) / FPS
        if f"pair_{k}" in sh.marks:
            at[f"fig{k + 1}_pair"] = (sh.marks[f"pair_{k}"] + FADE + 1) / FPS
        t0 = sh.marks[f"turntable_{k}"] + FADE
        for deg in (0, 90, 180, 270):
            at[f"fig{k + 1}_turn_{deg:03d}"] = (t0 + round(deg / 360 * len(runs[k].wide)) + 0.5) / FPS
    stills(mp4, out / "stills", at)
    report = {"clip": str(mp4), "seconds": round(total, 3), "frames": len(sh.frames), "marks": sh.marks,
              "runs": info, "spec": facts, "faults": faults + bad, "rows": sh.rows, "stills": sorted(at)}
    (out / "report.json").write_text(json.dumps(report, indent=1))
    return report
