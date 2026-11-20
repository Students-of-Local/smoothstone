"""Donovan, 2026-11-20: "it needs to be able to render the photos live in ghostty as well, and also
progress live and well". stone go draws the pictures in the terminal and keeps a live status line."""
import base64
import io
import re

from PIL import Image

from smoothstone import cli, term
from smoothstone.go import go


def _png(path, size=(300, 400), color="red"):
    Image.new("RGB", size, color).save(path)
    return path


def test_ghostty_and_kitty_draw_with_the_kitty_protocol_and_iterm_with_its_own():
    assert term.protocol({"TERM": "xterm-ghostty"}, tty=True) == "kitty"
    assert term.protocol({"TERM_PROGRAM": "ghostty", "TERM": "xterm-256color"}, tty=True) == "kitty"
    assert term.protocol({"TERM": "xterm-kitty"}, tty=True) == "kitty"
    assert term.protocol({"TERM_PROGRAM": "iTerm.app"}, tty=True) == "iterm"
    assert term.protocol({"TERM": "linux"}, tty=True, ask=lambda: None) is None
    # a model reading stone's output never gets escape codes
    assert term.protocol({"TERM": "xterm-ghostty"}, tty=False) is None
    assert term.protocol({"TERM": "xterm-ghostty", "STONE_IMAGES": "off"}, tty=True) is None
    assert term.protocol({"STONE_IMAGES": "kitty"}, tty=False) == "kitty"


def test_a_kitty_picture_is_sent_in_chunks_that_add_up_to_the_png():
    png = bytes(range(256)) * 40  # over one 4096 byte chunk once encoded
    text = term.escape(png, "kitty", 30)
    parts = re.findall(r"\x1b_G([^;]*);([^\x1b]*)\x1b\\", text)
    assert len(parts) >= 3
    assert parts[0][0] == "a=T,f=100,q=2,c=30,m=1" and parts[-1][0] == "m=0"
    assert all(len(data) <= term.CHUNK for _, data in parts)
    assert base64.b64decode("".join(data for _, data in parts)) == png


def test_photos_are_drawn_side_by_side_as_one_picture(tmp_path):
    a, b = _png(tmp_path / "a.png"), _png(tmp_path / "b.png", (600, 400), "blue")
    out = []
    assert term.picture([a, b, tmp_path / "missing.png"], "Photos found", write=out.append, how="kitty")
    text = "".join(out)
    assert text.startswith("    Photos found:")
    data = "".join(re.findall(r"\x1b_G[^;]*;([^\x1b]*)\x1b\\", text))
    im = Image.open(io.BytesIO(base64.b64decode(data)))
    assert im.height == 360 and im.width > 360 * (300 / 400 + 600 / 400)
    assert not term.picture([tmp_path / "missing.png"], "x", write=out.append, how="kitty")
    assert not term.picture([a], "x", write=out.append, how=None) or term.protocol() is not None


def test_the_live_line_says_the_step_and_how_long_it_took_last_time(tmp_path):
    stream = io.StringIO()
    timings = tmp_path / "timings.json"
    live = term.Live(stream=stream, timings=timings, tick=0.01)
    live.start("Running stone build")
    live.note("Styling the photo (FLUX.2 klein 4B, about 2 minutes)...")
    live.since -= 90  # as if it ran for a minute and a half
    live.pause()
    live.stop()
    assert "    Styling the photo (FLUX.2 klein 4B, about 2 minutes)...\n" in stream.getvalue()
    again = term.Live(stream=io.StringIO(), timings=timings, tick=0.01)
    assert 89 <= again.took["Styling the photo"] <= 92
    again.what, again.since = "Styling the photo (FLUX.2 klein 4B)", 0
    again._draw()
    assert "Styling the photo" in again.stream.getvalue() and "last time" in again.stream.getvalue()


def test_stone_go_draws_the_pictures_a_step_shows_and_prints_its_progress(tmp_path, monkeypatch):
    monkeypatch.setenv("STONE_IMAGES", "kitty")
    monkeypatch.setenv("STONE_LIVE", "0")
    monkeypatch.setenv("STONE_OPEN", "0")
    photo = _png(tmp_path / "photo_1.jpg")
    views = _png(tmp_path / "views.png", (800, 400))
    drawn, said = [], []
    monkeypatch.setattr(term, "picture", lambda paths, caption, how=None, **k: drawn.append((caption, how)) or True)

    def run(argv):
        if argv[0] == "new":
            return "Job started.\nNEXT: stone find", 0
        if argv[0] == "find":
            cli.show([photo], "Photos found of Sam Altman")
            return "Found 1 free-licensed photos of Sam Altman on Wikimedia Commons:\nNEXT: stone build", 0
        cli.progress(cli.Job(tmp_path / "job"), "Lifting the render to 3D (Hunyuan3D-2mini, about 4 minutes)...")
        cli.show([views], "The finished part")
        return f"PASS printable\nViews: {views} (look at every panel)\nPart ready: {tmp_path}/figure.stl\nNEXT: none", 0

    assert go(["a figure of Sam Altman"], run, say=said.append, hooks=cli.HOOKS) == 0
    assert drawn == [("Photos found of Sam Altman", "kitty"), ("The finished part", "kitty")]
    assert "    Lifting the render to 3D (Hunyuan3D-2mini, about 4 minutes)..." in said
    assert f"Views: {views}" in said  # drawn in the terminal: no outside viewer opened
    assert cli.HOOKS == {}  # a model's run after stone go gets no pictures or live line


def test_a_models_run_never_gets_escape_codes(jobenv, monkeypatch):
    monkeypatch.setenv("STONE_IMAGES", "kitty")
    assert cli.HOOKS == {}
    cli.show(["/nowhere.png"], "nothing")  # no hook: nothing is drawn, nothing fails
    text, _ = cli.run(["new", "a small plate with one hole"])
    assert "\x1b" not in text


def _unsixel(text):
    """A small sixel reader: the picture's pixels as {(x, y): (r, g, b) in percent}."""
    body = text[text.index("q") + 1:text.rindex("\x1b")]
    body = body[body.index('"'):]
    body = body[body.index("#"):]
    pal, px, x, y, color = {}, {}, 0, 0, None
    for m in re.finditer(r"#(\d+);2;(\d+);(\d+);(\d+)|#(\d+)|!(\d+)(.)|([?-~])|(\$)|(-)", body):
        if m.group(1):
            pal[int(m.group(1))] = tuple(int(m.group(i)) for i in (2, 3, 4))
        elif m.group(5):
            color = int(m.group(5))
        elif m.group(6) or m.group(8):
            n, ch = (int(m.group(6)), m.group(7)) if m.group(6) else (1, m.group(8))
            for _ in range(n):
                for bit in range(6):
                    if (ord(ch) - 63) >> bit & 1:
                        px[(x, y + bit)] = pal[color]
                x += 1
        elif m.group(9):
            x = 0
        elif m.group(10):
            x, y = 0, y + 6
    return px


def test_foot_gets_sixel_that_reads_back_as_the_picture():
    assert term.protocol({"TERM": "foot"}, tty=True) == "sixel"
    im = Image.new("RGB", (40, 14), "white")
    im.paste(Image.new("RGB", (10, 7), (255, 0, 0)), (5, 2))
    im.paste(Image.new("RGB", (8, 14), (0, 0, 255)), (30, 0))
    px = _unsixel(term.sixel(im))
    assert px[(0, 0)] == (100, 100, 100) and px[(39, 13)] == (100, 100, 100)
    assert px[(5, 2)] == px[(14, 8)] == (100, 0, 0) and px[(15, 8)] == (100, 100, 100)
    assert px[(30, 0)] == px[(37, 13)] == (0, 0, 100)
    assert len(px) == 40 * 14


def test_a_terminal_that_says_another_name_is_asked_what_it_draws():
    """Live, 2026-11-20: foot on this seat says TERM=xterm-256color, and the guess drew nothing."""
    assert term.protocol({"TERM": "xterm-256color"}, tty=True, ask=lambda: "sixel") == "sixel"
    assert term.answer(b"\x1b[?62;4;22c") == "sixel"  # foot
    assert term.answer(b"\x1b_Gi=31;OK\x1b\\\x1b[?62;22c") == "kitty"  # Ghostty, Kitty
    assert term.answer(b"\x1b[?62;22c") is None and term.answer(b"") is None


def test_sixel_reads_back_with_many_colors():
    """Live, 2026-11-20: a photo's palette index over 85 overflowed as a numpy byte and drew nothing."""
    import numpy as np
    a = np.random.default_rng(1).integers(0, 255, (12, 30, 3), dtype=np.uint8)
    im = Image.fromarray(a)
    px = _unsixel(term.sixel(im))
    assert len(px) == 30 * 12
