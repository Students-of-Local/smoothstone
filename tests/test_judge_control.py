import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("judge_control", ROOT / "evals" / "judge_control.py")
jc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jc)


def test_the_control_seeds_the_painted_figure_not_a_reference_file(tmp_path):
    (tmp_path / "jensen-cut4.3mf").write_text("reference")
    (tmp_path / "figure.3mf").write_text("painted")
    assert jc.painted_3mf(tmp_path).name == "figure.3mf"


def test_the_control_falls_back_to_the_recipe_3mf_and_says_when_none(tmp_path):
    (tmp_path / "plan.json").write_text(json.dumps({"recipe": "keychain"}))
    with pytest.raises(SystemExit, match="no painted 3MF"):
        jc.painted_3mf(tmp_path)
    (tmp_path / "keychain.3mf").write_text("painted")
    assert jc.painted_3mf(tmp_path).name == "keychain.3mf"


def test_the_control_line_must_be_a_drawn_row():
    pick = [{"n": i} for i in range(9)]
    assert jc.pick_line(pick, 6) == {"n": 5}
    for bad in (0, 7):
        with pytest.raises(SystemExit, match="lines 1 to 6"):
            jc.pick_line(pick, bad)
    with pytest.raises(SystemExit, match="lines 1 to 2"):
        jc.pick_line(pick[:2], 3)


def test_the_tab_takes_the_majority_side_near_the_stretch():
    # a flat strip of faces along x, line at y = 0: three rows of filament 1 below, one of 2 above
    V, F, fil = [], [], []
    for row, (y0, c) in enumerate([(-3, 1), (-2, 1), (-1, 1), (0, 2)]):
        for x in range(6):
            b = len(V)
            V += [(x, y0, 0), (x + 1, y0, 0), (x, y0 + 1, 0), (x + 1, y0 + 1, 0)]
            F += [(b, b + 1, b + 2), (b + 1, b + 3, b + 2)]
            fil += [c, c]
    V, F, fil = np.array(V, float), np.array(F), np.array(fil)
    line = {"pts": [(x, 0.0, 0.0) for x in np.arange(0, 6.01, 0.5)], "pair": (2, 1)}
    out = jc.seed_tab(V, F, fil, line, depth=1.6, length=10)
    assert ((fil == 1) & (out == 2)).any() and not ((fil == 2) & (out == 1)).any()
