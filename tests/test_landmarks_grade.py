import json
import sys
from pathlib import Path

import numpy as np
import pytest
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals"))
import landmarks_grade


def test_missing_parts_grade_requires_mapped_evidence_and_the_cli_handoff(tmp_path):
    refs = tmp_path / "refs"
    refs.mkdir()
    reference = {"source": "https://www.wikidata.org/wiki/Q1", "requested_name": "Example Hall",
                 "geometry_source": "https://www.openstreetmap.org/relation/1", "mapped_parts": [],
                 "parts": [], "height_source_parts": 0, "height_source_coverage": 0.0}
    path = refs / "landmark.json"
    path.write_text(json.dumps(reference))
    want = {"allow_missing_parts": True, "references": {"identity": reference["source"],
                                                        "footprint": reference["geometry_source"]}}
    spec = {"expect": {"landmarks": want}}
    steps = [{"tool_calls": [{"args": {"command": "stone landmark"},
        "result": "FIX: insufficient mapped 3D parts with heights\nNEXT: stone models 'Example Hall'"}]}]
    result = landmarks_grade.missing_parts_result(tmp_path, spec, steps)
    assert result["pass"] and result["judge"] is None
    assert landmarks_grade.missing_parts_result(tmp_path, spec, []) is None
    reference["height_source_parts"] = 1
    reference["parts"] = [{"id": 1}]
    path.write_text(json.dumps(reference))
    assert landmarks_grade.missing_parts_result(tmp_path, spec, steps) is None


def test_landmark_grade_uses_printed_geometry_and_sourced_parts(tmp_path):
    job = tmp_path / "job"
    for subdir in ("model", "refs", "build/model"):
        (job / subdir).mkdir(parents=True)
    stl = job / "cathedral.stl"
    mesh = trimesh.creation.box((100, 50, 52))
    mesh.apply_transform(trimesh.transformations.rotation_matrix(0.4, [0, 0, 1]))
    to_print = trimesh.transformations.rotation_matrix(1.57, [1, 0, 0], point=[100, 100, 100])
    mesh.apply_transform(to_print)
    mesh.export(stl)
    data = {"model": {"source": "landmark"}, "passed": True, "parts": [
        {"file": str(stl), "to_print": to_print.tolist(), "checks": [{"name": "closed", "ok": True}]},
    ]}
    (job / "build/model/parts.json").write_text(json.dumps(data))
    wd = "https://www.wikidata.org/wiki/Q4176"
    wiki = "https://en.wikipedia.org/wiki/Cologne_Cathedral"
    refs = {
        "source": wd, "sources": {"height": wd}, "height": 50, "scale_mm_per_metre": 1,
        "wikipedia_url": wiki,
        "reference_dimensions_m": {"length": 100, "width": 50, "source": "https://www.openstreetmap.org/way/1"},
        "parts": [
            {"id": 1, "feature": "west_spire", "height": {"metres": 50}},
            {"id": 2, "feature": "west_spire", "height": {"metres": 49.5}},
            {"id": 3, "feature_of": 1, "height": {"metres": 50}},
            {"id": 4, "height": {"metres": 40}},
        ],
    }
    ref_path = job / "refs/landmark.json"
    ref_path.write_text(json.dumps(refs))
    credits = job / "model/credits.txt"
    credits.write_text(f"OpenStreetMap contributors, ODbL\n{wd}\n{wiki}\n")
    spec = {"expect": {"landmarks": {
        "size": {"mode": "z", "mm": 52}, "bed": [220] * 3,
        "features": {"west_spire": {"count": 2, "tallest": True}},
    }}}
    good = landmarks_grade.grade(job, spec)
    assert good["pass"], good
    assert good["ratios"]["length"]["built"] == pytest.approx(.5, abs=.00001)
    assert good["ratios"]["width"]["built"] == pytest.approx(1, abs=.00001)
    assert good["height_m"]["built"] == pytest.approx(50, abs=.0001)
    assert good["features"] == {"west_spire": 2}

    refs["parts"][2].pop("feature_of")
    refs["reference_dimensions_m"]["width"] = 55
    ref_path.write_text(json.dumps(refs))
    credits.write_text(f"OpenStreetMap contributors, ODbL\n{wd}\n")
    failed = landmarks_grade.grade(job, spec)
    assert not failed["pass"]
    assert any("height/width" in why for why in failed["why"])
    assert any("must be taller" in why for why in failed["why"])
    assert f"credits missing {wiki}" in failed["why"]

    data["parts"][0]["checks"] = [{"name": "closed", "ok": False}]
    (job / "build/model/parts.json").write_text(json.dumps(data))
    assert any("print checks fail: closed" in why for why in landmarks_grade.grade(job, spec)["why"])


def test_labelled_pinnacles_must_stand_in_the_printed_mesh():
    def part(x):
        return {"feature": "pinnacle", "height": {"metres": 30.},
                "footprint": [[[x - 1, -1], [x + 1, -1], [x + 1, 1], [x - 1, 1]]]}

    base = trimesh.creation.box((100, 20, 10), transform=trimesh.transformations.translation_matrix([0, 0, 5]))
    posts = [trimesh.creation.box((2, 2, 32), transform=trimesh.transformations.translation_matrix([x, 0, 16]))
             for x in (-30, 0)]
    mesh = trimesh.util.concatenate([base, *posts])
    labels = [part(-30), part(0), part(30), part(0)]  # one is missing from the mesh, one is counted twice
    assert landmarks_grade.standing_in_mesh(mesh, labels, 1., 2.) == 2
    block = trimesh.creation.box((100, 20, 32), transform=trimesh.transformations.translation_matrix([0, 0, 16]))
    assert landmarks_grade.standing_in_mesh(block, labels, 1., 2.) == 0


def _block_job(tmp_path, *pieces):
    job = tmp_path / "job"
    (job / "build/model").mkdir(parents=True)
    parts = []
    for i, m in enumerate(pieces):
        m.export(job / f"p{i}.stl")
        parts.append({"file": str(job / f"p{i}.stl"), "to_print": np.eye(4).tolist()})
    (job / "build/model/parts.json").write_text(json.dumps({"parts": parts}))
    return job


def test_side_views_show_a_two_millimetre_pier(tmp_path):
    # views.png's head-on light and square panels lost it (Milan's front, judge 7 three times)
    from PIL import Image

    wall = trimesh.creation.box((120, 60, 60))
    wall.apply_translation((0, 0, 30))
    pier = trimesh.creation.box((4, 4, 50))
    pier.apply_translation((0, -30, 25))  # 2 mm proud of the front
    jobs = {"plain": _block_job(tmp_path / "a", wall),
            "piered": _block_job(tmp_path / "b", trimesh.boolean.union([wall, pier]))}
    panels = {}
    for name, job in jobs.items():
        out = landmarks_grade.side_views(job, tmp_path / f"{name}.png", px=240)
        im = Image.open(out)
        assert im.size == (480, 480)
        # the pier's face may be any panel: the box is squared to the camera, not to north
        panels[name] = np.asarray(im.convert("L"), float)
    a, b = panels["plain"], panels["piered"]
    moved = [int((np.abs(a[r:r + 240, c:c + 240] - b[r:r + 240, c:c + 240]) > 40).sum())
             for r in (0, 240) for c in (0, 240)]
    assert max(moved) > 100, moved


def test_side_views_put_split_parts_back_together(tmp_path):
    whole = trimesh.creation.box((80, 40, 20))
    left, right = (trimesh.creation.box((40, 40, 20)) for _ in range(2))
    left.apply_translation((-20, 0, 0))
    right.apply_translation((20, 0, 0))
    one = _block_job(tmp_path / "one", whole)
    two = _block_job(tmp_path / "two", left, right)
    data = json.loads((two / "build/model/parts.json").read_text())
    shift = np.eye(4)
    shift[0, 3] = 300  # laid out elsewhere on the bed
    moved = trimesh.load(two / "p1.stl")
    moved.apply_transform(shift)
    moved.export(two / "p1.stl")
    data["parts"][1]["to_print"] = shift.tolist()
    (two / "build/model/parts.json").write_text(json.dumps(data))
    from PIL import Image

    a = np.asarray(Image.open(landmarks_grade.side_views(one, tmp_path / "1.png", px=120)), float)
    b = np.asarray(Image.open(landmarks_grade.side_views(two, tmp_path / "2.png", px=120)), float)
    assert np.abs(a - b).mean() < 3


def test_a_judge_without_its_side_views_fails_the_run(tmp_path):
    import models_grade

    def broken():
        raise ValueError("no parts")

    spec = {"request": "Milan Cathedral", "expect": {"landmarks": {"wikipedia": "Milan Cathedral"}}}
    got = models_grade.judged(tmp_path, tmp_path, spec, {"pass": True, "why": ["all checks pass"]},
                              suite="landmarks", minimum=8, sides=broken)
    assert not got["pass"] and "could not answer" in got["why"][0]
