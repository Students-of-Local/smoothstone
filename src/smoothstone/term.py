"""What a person at a terminal sees while stone go runs: pictures drawn in the terminal and a live
line that says which step is running, how long it has taken and how long it took last time.

Pictures use the Kitty graphics protocol (Ghostty, Kitty), the iTerm2 inline image protocol
(iTerm2, WezTerm) or sixel (foot, Windows Terminal). STONE_IMAGES=kitty, iterm, sixel or off
overrides the guess. Nothing here runs when
stdout is not a terminal, so a model reading stone's output never gets escape codes.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path

SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
CHUNK = 4096  # the Kitty protocol's largest base64 piece per escape


_ASKED: list = []  # the terminal's own answer, asked once


def answer(buf: bytes) -> str | None:
    """What the terminal's reply says it draws."""
    if b"_Gi=31;OK" in buf:
        return "kitty"
    da = re.search(rb"\x1b\[\?([\d;]*)c", buf)
    if da and "4" in da.group(1).decode().split(";"):
        return "sixel"
    return None


def ask_terminal(timeout: float = 0.5) -> str | None:
    """Ask the terminal what it draws: a Kitty graphics query, then the device attributes, which
    every terminal answers (4 in them is sixel). Works whatever TERM says (foot here says
    xterm-256color). None when it cannot draw or does not answer."""
    if _ASKED:
        return _ASKED[0]
    got = None
    try:
        import select
        import termios
        import tty as ttymod

        fd = sys.stdin.fileno()
        if os.isatty(fd) and sys.stdout.isatty():
            old = termios.tcgetattr(fd)
            buf = b""
            try:
                ttymod.setcbreak(fd)
                os.write(sys.stdout.fileno(), b"\x1b_Gi=31,s=1,v=1,a=q,t=d,f=24;AAAA\x1b\\\x1b[c")
                end = time.time() + timeout
                while time.time() < end and not re.search(rb"\x1b\[\?[\d;]*c", buf):
                    ready, _, _ = select.select([fd], [], [], max(0.0, end - time.time()))
                    if not ready:
                        break
                    buf += os.read(fd, 1024)
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            got = answer(buf)
    except (OSError, ValueError, ImportError, AttributeError):  # no terminal to ask (a pipe, Windows)
        got = None
    _ASKED.append(got)
    return got


def protocol(env=None, tty=None, ask=None) -> str | None:
    """kitty, iterm, sixel or None: how this terminal draws a picture, if it can."""
    env = os.environ if env is None else env
    want = env.get("STONE_IMAGES", "").lower()
    if want in ("off", "0", "no", "none"):
        return None
    if want in ("kitty", "iterm", "sixel"):
        return want
    if not (sys.stdout.isatty() if tty is None else tty):
        return None
    term, prog = env.get("TERM", ""), env.get("TERM_PROGRAM", "").lower()
    if prog == "ghostty" or "ghostty" in term or "kitty" in term or env.get("KITTY_WINDOW_ID"):
        return "kitty"
    if prog in ("iterm.app", "wezterm") or env.get("LC_TERMINAL") == "iTerm2":
        return "iterm"
    if term.startswith("foot") or env.get("WT_SESSION") or "mlterm" in term:
        return "sixel"
    return (ask or ask_terminal)()


def sixel(im, colors: int = 128) -> str:
    """A PIL image as sixel text: up to colors colors, six pixel rows per band, runs packed."""
    import numpy as np
    from PIL import Image

    q = im.convert("RGB").quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    pal = q.getpalette() or []
    a = np.asarray(q)
    h, w = a.shape
    out = ["\x1bPq", f'"1;1;{w};{h}']
    for i in map(int, np.unique(a)):  # numpy bytes overflow at 3 * i
        r, g, b = pal[3 * i:3 * i + 3]
        out.append(f"#{i};2;{r * 100 // 255};{g * 100 // 255};{b * 100 // 255}")
    for y in range(0, h, 6):
        band = a[y:y + 6]
        weights = (1 << np.arange(band.shape[0]))[:, None]
        lines = []
        for c in np.unique(band):
            bits = ((band == c) * weights).sum(axis=0)
            last = np.flatnonzero(bits)
            bits = bits[:last[-1] + 1]
            cut = np.flatnonzero(np.diff(bits)) + 1
            starts = np.concatenate(([0], cut))
            ends = np.concatenate((cut, [len(bits)]))
            row = []
            for s0, e0 in zip(starts, ends):
                ch, n = chr(63 + int(bits[s0])), int(e0 - s0)
                row.append(f"!{n}{ch}" if n > 3 else ch * n)
            lines.append(f"#{c}" + "".join(row))
        out.append("$".join(lines) + "-")
    out.append("\x1b\\")
    return "".join(out)


def strip(paths: list[Path], height: int = 360, gap: int = 12):
    """The pictures side by side at one height, on white, as one PIL image."""
    from PIL import Image

    ims = []
    for p in paths:
        try:
            im = Image.open(p)
            im.load()
        except (OSError, ValueError):
            continue
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGBA", im.size, "white")
            im = Image.alpha_composite(bg, im)
        im = im.convert("RGB")
        ims.append(im.resize((max(1, round(im.width * height / im.height)), height)))
    if not ims:
        return None
    out = Image.new("RGB", (sum(i.width for i in ims) + gap * (len(ims) - 1), height), "white")
    x = 0
    for im in ims:
        out.paste(im, (x, 0))
        x += im.width + gap
    if out.width > 2400:
        out = out.resize((2400, round(out.height * 2400 / out.width)))
    return out


def escape(png: bytes, how: str, cols: int) -> str:
    """The escape text that draws png cols cells wide, its height from its own shape."""
    data = base64.b64encode(png).decode()
    if how == "iterm":
        return (f"\x1b]1337;File=inline=1;size={len(png)};width={cols};preserveAspectRatio=1:"
                f"{data}\x07")
    parts = [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)] or [""]
    out = []
    for i, part in enumerate(parts):
        more = 1 if i < len(parts) - 1 else 0
        keys = f"a=T,f=100,q=2,c={cols},m={more}" if i == 0 else f"m={more}"
        out.append(f"\x1b_G{keys};{part}\x1b\\")
    return "".join(out)


def picture(paths: list[Path], caption: str, write=None, how: str | None = None, rows: int = 14) -> bool:
    """Draw the pictures in the terminal under a caption. False when this terminal cannot."""
    how = how or protocol()
    if not how:
        return False
    im = strip([Path(p) for p in paths])
    if im is None:
        return False
    width = shutil.get_terminal_size((100, 30)).columns
    # a cell is about twice as tall as wide: rows tall keeps the picture's shape at this many columns
    cols = max(16, min(width - 6, round(rows * 2 * im.width / im.height)))
    write = write or (lambda s: (sys.stdout.write(s), sys.stdout.flush()))
    if how == "sixel":  # sixel draws pixels, not cells: about 20 pixels a row
        scale = min(rows * 20 / im.height, (width - 6) * 10 / im.width)
        im = im.resize((max(1, round(im.width * scale)), max(6, round(im.height * scale))))
        write(f"    {caption}:\n" + sixel(im) + "\n")
        return True
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    write(f"    {caption}:\n    " + escape(buf.getvalue(), how, cols) + "\n")
    return True


def _timings_file() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "smoothstone" / "timings.json"


def _key(text: str) -> str:
    return text.split(" (", 1)[0].rstrip(". ").strip()


def _clock(secs: float) -> str:
    secs = int(secs)
    return f"{secs // 60}:{secs % 60:02d}"


class Live:
    """One status line under the step that is running: a spinner, what it is doing, the time it has
    taken and what it took last time on this computer. Progress lines from the step print above it."""

    def __init__(self, stream=None, timings: Path | None = None, tick: float = 0.2):
        self.stream = stream or sys.stderr
        self.file = timings or _timings_file()
        try:
            self.took = json.loads(self.file.read_text())
        except (OSError, ValueError):
            self.took = {}
        self.lock = threading.Lock()
        self.tick = tick
        self.what, self.since, self.started = "", 0.0, 0.0
        self.running = False
        self.thread: threading.Thread | None = None
        self.n = 0

    def _draw(self) -> None:
        if not self.what:
            return
        now = time.time()
        last = self.took.get(_key(self.what))
        line = f"    {SPIN[self.n % len(SPIN)]} {_key(self.what)}  {_clock(now - self.since)}"
        if last:
            line += f" (about {_clock(last)} last time)"
        self.stream.write("\r\x1b[2K" + line[:shutil.get_terminal_size((100, 30)).columns - 1])
        self.stream.flush()

    def _loop(self) -> None:
        while self.running:
            with self.lock:
                self._draw()
                self.n += 1
            time.sleep(self.tick)

    def _clear(self) -> None:
        self.stream.write("\r\x1b[2K")
        self.stream.flush()

    def _record(self) -> None:
        if self.what and self.since:
            secs = time.time() - self.since
            if secs >= 3:  # quick steps are not worth a guess
                k = _key(self.what)
                self.took[k] = round(secs if k not in self.took else 0.5 * self.took[k] + 0.5 * secs, 1)

    def start(self, what: str) -> None:
        with self.lock:
            self.what, self.since = what, time.time()
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()

    def note(self, text: str) -> None:
        """A step said what it is doing now: print it above the live line, which then follows it."""
        with self.lock:
            self._record()
            self._clear()
            self.stream.write(f"    {text}\n")
            self.what, self.since = text, time.time()
            self._draw()

    def above(self, write) -> None:
        """Run write (a picture, a line) above the live line without the two mixing."""
        with self.lock:
            self._clear()
            write()
            self._draw()

    def pause(self) -> None:
        """The step ended: keep its time, clear the line until the next one starts."""
        with self.lock:
            self._record()
            self.what = ""
            self._clear()

    def stop(self) -> None:
        with self.lock:
            self._record()
            self.running = False
            self.what = ""
            self._clear()
        if self.thread:
            self.thread.join(timeout=1)
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            self.file.write_text(json.dumps(self.took, indent=1))
        except OSError:
            pass
