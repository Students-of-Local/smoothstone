import importlib.util
import json
from pathlib import Path

import numpy as np
import trimesh

from smoothstone import colors as C

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_evals_grade", ROOT / "evals" / "run.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)

FIL = ["white", "black", "blue"]


def _job(tmp_path, parts, slivers=None):
    """A painted figure job of separate boxes, one region each: parts is [(part, filament)]."""
    job = tmp_path / "job"
    (job / "build").mkdir(parents=True)
    meshes, num, face = [], [], []
    for n, (part, f) in enumerate(parts, 1):
        b = trimesh.creation.box((4, 4, 4))
        b.apply_translation((n * 10.0, 0, 2))
        meshes.append(b)
        num += [n] * len(b.faces)
        face += [f] * len(b.faces)
    m = trimesh.util.concatenate(meshes)
    C.write_3mf(job / "figure.3mf", np.asarray(m.vertices), np.asarray(m.faces), np.array(face), "figure")
    np.save(job / "build" / "paint.npy", np.array(num))
    regs = [{"n": n, "part": p if p != "other" else "other", "base": p == "base"} for n, (p, _) in enumerate(parts, 1)]
    (job / "build" / "regions.json").write_text(json.dumps({"regions": regs}))
    if slivers is not None:
        (job / "build" / "slivers.json").write_text(json.dumps({str(k): v for k, v in slivers.items()}))
    (job / "status.json").write_text(json.dumps({"colors": {"filaments": FIL, "wobble": 0}}))
    return job


WANT = {"black": ["jacket", "shoes"], "blue": ["pants"], "rest": "white"}


def test_the_name_is_graded_by_whether_it_stands_out_from_the_plinth(tmp_path):
    """Run r3_black_shoes 2026-11-19: stone colors painted JENSEN black on the white plinth, as it
    should, and the grader failed it with "name is black (want white)", the rest color."""
    tmp = tmp_path
    job = _job(tmp, [("base", 1), ("top", 2), ("pants", 3), ("shoes", 2), ("name", 2)])
    assert run.grade_colors(job, "figure", WANT)["why"] == []
    job = _job(tmp / "b", [("base", 1), ("top", 2), ("pants", 3), ("shoes", 2), ("name", 1)])
    assert any("name is white, the plinth's own color" in w for w in run.grade_colors(job, "figure", WANT)["why"])
    # a name color the request gives is the one it must take
    job = _job(tmp / "c", [("base", 1), ("top", 2), ("pants", 3), ("shoes", 2), ("name", 2)])
    assert any(w.startswith("name is black (want blue)")
               for w in run.grade_colors(job, "figure", dict(WANT, blue=["pants", "name"]))["why"])


def test_a_sliver_boxed_in_by_a_part_is_graded_as_that_part(tmp_path):
    """Run r3_black_shoes 2026-11-19: four slivers of the jacket's edge took the jacket's black, as
    they should, and the grader failed it with "other is 43% not white"."""
    parts = [("base", 1), ("top", 2), ("pants", 3), ("shoes", 2), ("other", 1), ("other", 2)]
    job = _job(tmp_path, parts, slivers={6: 2})
    assert run.grade_colors(job, "figure", WANT)["why"] == []
    # with no record of it, black on an unnamed region is still wrong
    job = _job(tmp_path / "b", parts)
    assert any(w.startswith("other is") for w in run.grade_colors(job, "figure", WANT)["why"])
