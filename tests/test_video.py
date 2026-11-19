"""stone video: the plan read from a run log, the checks that keep the clip honest, the CLI, and
the turntable's framing."""
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from smoothstone import cli, video

REPO = Path(__file__).resolve().parent.parent


def run_log(colors_ok=True):
    def call(cmd, result):
        return {"tool_calls": [{"args": {"command": cmd}, "result": result}]}

    steps = [
        call("stone status", "Tier: S\nNEXT: stone recipes"),
        call("stone find \"Jensen Huang\"", "Found 3 free-licensed photos\nphoto_1.jpg: CC BY 4.0, by A\n"
             "/home/x/job/image/found\nNEXT: stone build"),
        call("stone build", "Figure: chibi person\nSize: 61.0 x 61.0 x 90.0 mm\nPASS watertight: closed\n"
             "NEXT: stone colors"),
        call("stone colors jacket=black rest=white",
             "filament 1 white: 82%\nPASS color_edges: smooth\n"
             + ("NEXT: none, the part is ready" if colors_ok else "FIX: an edge\nNEXT: stone colors")),
    ]
    return {"setup": "Request: A mini figure of Jensen Huang\n", "model": "LFM3-1.7B q4",
            "started": "2026-11-18T20:27:13", "steps": steps}


def test_the_model_size_comes_from_its_name():
    assert video.model_size("LFM3-1.7B") == "1.7B"
    assert video.model_size("tiny-600m") == "600M"
    assert video.model_size("gpt") == "gpt"


def test_a_long_line_wraps_into_its_rows_and_ends_in_an_ellipsis():
    rows = video.wrap("one two three four five six seven eight nine ten", 12, rows=2)
    assert len(rows) == 2 and rows[-1].endswith(" …")
    assert all(len(r) <= 12 for r in rows)


def test_the_plan_shows_the_run_and_never_a_path():
    plan = video.make_plan(Path("/nonexistent"), run_log())
    assert plan.request == "A mini figure of Jensen Huang"
    assert plan.model == "LFM3-1.7B"
    assert plan.paint == "jacket black, the rest white"
    shown = [ln for _, lines in plan.ws1 for ln in lines]
    assert shown and not any(video.has_path(ln) for ln in shown)


def test_a_run_whose_paint_never_passed_makes_no_clip():
    with pytest.raises(video.VideoProblem):
        video.make_plan(Path("/nonexistent"), run_log(colors_ok=False))


def test_a_line_the_run_never_printed_is_a_fault():
    log = run_log()
    good = [{"kind": "req", "text": "A mini figure of Jensen Huang"},
            {"kind": "cmd", "text": "stone build"},
            {"kind": "out", "cmd": "stone build", "text": "Size: 61.0 x 61.0 x 90.0 mm"}]
    assert video.row_faults(good, log) == []
    bad = good + [{"kind": "cmd", "text": "stone paint jacket=red"},
                  {"kind": "out", "cmd": "stone build", "text": "PASS everything"}]
    faults = video.row_faults(bad, log)
    assert len(faults) == 2
    assert any("never sent" in f for f in faults) and any("never printed" in f for f in faults)


def test_text_in_the_x_overlay_or_past_its_tile_is_a_fault():
    try:
        font = video.mono(34)
    except video.VideoProblem:
        pytest.skip("JetBrains Mono Nerd Font is not installed")
    fr = video.Frame()
    fr.text((60, 400), "inside", font, video.FG, inside=(40, 380, 1040, 500))
    assert video.layout_faults(fr) == []
    fr.text((60, 60), "under the top overlay", font, video.FG)
    fr.text((1000, 400), "past the border", font, video.FG, inside=(40, 380, 1040, 500))
    faults = video.layout_faults(fr)
    assert any("overlay" in f for f in faults) and any("tile border" in f for f in faults)


def test_stone_video_without_a_run_log_says_how_to_give_one(jobenv):
    cli.run(["new", "a mini figure"])
    text, code = cli.run(["video"])
    assert code == 1
    assert "FIX: no run log" in text and text.splitlines()[-1].startswith("NEXT: ")


def test_stone_video_reports_the_clip_it_made(jobenv, monkeypatch, tmp_path):
    cli.run(["new", "a mini figure"])
    log = tmp_path / "log.json"
    log.write_text("{}")
    seen = {}

    def fake_make(job_root, log_path, out, turn):
        seen.update(job=job_root, log=log_path, out=out, turn=turn)
        return {"clip": str(out / "clip.mp4"), "seconds": 15.7, "faults": [],
                "spec": {"width": 1080, "height": 1920, "lufs": -16.0}}

    monkeypatch.setattr(video, "make", fake_make)
    text, code = cli.run(["video", str(log), "--turn", "12"])
    assert code == 0, text
    assert "15.7 s, 1080x1920, -16.0 LUFS" in text and "PASS video" in text
    assert seen["log"] == log and seen["turn"] == 12 and seen["out"] == seen["job"] / "video"


@pytest.mark.skipif(not shutil.which("blender"), reason="Blender is not installed")
def test_the_turntable_frames_the_whole_figure_with_room_to_spare(tmp_path):
    """The figure fills the tile yet touches no edge (a 1.08 margin clipped the base on the
    Jensen figure; 1.15 leaves room)."""
    # a plinth and a tall body, the proportions of a figure on its base
    plinth = _prism(30.5, 0, 12)
    body = _prism(12, 12, 90)
    V = np.vstack([plinth[0], body[0]])
    F = np.vstack([plinth[1], body[1] + len(plinth[0])])
    npz = tmp_path / "mesh.npz"
    np.savez(npz, V=V.astype(np.float32), F=F, fil=np.zeros(len(F), int), rgb=np.array([[240, 240, 240]]))
    w, h = 414, 314
    subprocess.run([shutil.which("blender"), "-b", "--factory-startup", "--python",
                    str(REPO / "src" / "smoothstone" / "turntable_blender.py"), "--",
                    str(npz), str(tmp_path / "turn"), "8", str(w), str(h), "0", "0"],
                   check=True, capture_output=True, timeout=600)
    a = np.asarray(Image.open(tmp_path / "turn" / "f_0000.png"))[..., 3]
    ys, xs = np.where(a > 8)
    assert ys.min() >= 2 and ys.max() <= h - 3, (ys.min(), ys.max())  # clear of both edges
    assert ys.max() - ys.min() >= 0.8 * h


def _prism(r, z0, z1, n=32):
    """A closed n-sided prism around the z axis: a round base or a body."""
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ring = np.c_[r * np.cos(a), r * np.sin(a)]
    V = np.vstack([np.c_[ring, np.full(n, z0)], np.c_[ring, np.full(n, z1)], [[0, 0, z0], [0, 0, z1]]])
    F = []
    for i in range(n):
        j = (i + 1) % n
        F += [[i, j, n + i], [j, n + j, n + i], [2 * n, j, i], [2 * n + 1, n + i, n + j]]
    return V, np.array(F)
