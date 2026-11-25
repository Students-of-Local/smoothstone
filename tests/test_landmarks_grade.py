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

    cited = {"length_m": {"value": 102, "source": "survey"}, "width_m": {"value": 55, "source": "survey"}}
    spec["expect"]["landmarks"]["references"] = cited
    wrong = landmarks_grade.grade(job, spec)
    assert wrong["why"] == ["built width is 50.0 m at scale, survey says 55 m (4% tolerance)"]
    cited["width_m"]["tolerance"] = .1
    assert landmarks_grade.grade(job, spec)["pass"]
    tower = "https://www.openstreetmap.org/way/2"
    refs["reference_dimensions_m"]["length"] = 80
    refs["plan_dimensions_m"] = {"length": 100, "width": 50, "associated_outlines": [tower]}
    ref_path.write_text(json.dumps(refs))
    assert f"linked towers the spec does not name: {tower}" in landmarks_grade.grade(job, spec)["why"]
    cited["linked_outlines"] = [tower]
    assert landmarks_grade.grade(job, spec)["pass"]
    del spec["expect"]["landmarks"]["references"], refs["plan_dimensions_m"]
    refs["reference_dimensions_m"]["length"] = 100

    drawn = {"length": 120, "width": 50, "source": "https://example.org/survey"}
    spec["expect"]["landmarks"]["dimensions"] = drawn
    ref_path.write_text(json.dumps(refs))
    assert landmarks_grade.grade(job, spec)["pass"]  # without a reason the map's own outline counts
    drawn["why"] = "redrawn from a survey"
    assert any("height/length" in why for why in landmarks_grade.grade(job, spec)["why"])
    drawn["length"], refs["reference_dimensions_m"]["length"] = 100, 120
    ref_path.write_text(json.dumps(refs))
    assert landmarks_grade.grade(job, spec)["pass"]
    refs["reference_dimensions_m"]["length"] = 100
    del spec["expect"]["landmarks"]["dimensions"]
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


@pytest.mark.parametrize("turn", [0., .5, 1.4])
def test_pinnacles_are_counted_in_the_file_that_prints(tmp_path, turn):
    """The print step lost one of two posts. The generator's own mesh still has both."""
    at = trimesh.transformations.translation_matrix
    base = trimesh.creation.box((100, 40, 10), transform=at([0, 0, 5]))
    posts = [trimesh.creation.box((2, 2, 32), transform=at([x, 5, 16])) for x in (-30, 10)]
    frame = trimesh.transformations.rotation_matrix(turn, [0, 0, 1])
    generated = trimesh.util.concatenate([base, *posts]).apply_transform(frame)
    labels = []
    for x in (-30, 10):
        ring = np.array([[x - 1, 4, 0, 1], [x + 1, 4, 0, 1], [x + 1, 6, 0, 1], [x - 1, 6, 0, 1]]) @ frame.T
        labels.append({"height": {"metres": 30.}, "footprint": [ring[:, :2].tolist()]})
    whole = landmarks_grade.modelprint.footprint_turn(generated, [])
    kept = landmarks_grade.trimesh.util.concatenate(
        [piece for piece in whole.split(only_watertight=False) if piece.extents[2] < 20 or piece.centroid[0] < 50])
    to_print = at([7, 8, 0])
    counted = []
    for name, mesh in (("whole", whole), ("kept", kept)):
        path = tmp_path / f"{name}.stl"
        mesh.copy().apply_transform(to_print).export(path)
        printed = landmarks_grade.printed_mesh(generated, [{"file": str(path), "to_print": to_print.tolist()}])
        counted.append(landmarks_grade.standing_in_mesh(printed, labels, 1., 2.))
    assert counted == [2, 1]
    half = tmp_path / "half.stl"
    whole.copy().apply_scale(.5).export(half)
    assert landmarks_grade.printed_mesh(generated, [{"file": str(half), "to_print": np.eye(4).tolist()}]) is None


@pytest.mark.parametrize("lead", [{"original": {"source": "https://up/Logo.svg?utm=x"}}, {}])
def test_an_article_that_leads_with_a_logo_or_nothing_is_judged_by_its_first_photo(tmp_path, monkeypatch, lead):
    """Petronas Towers leads with a logo and Chrysler Building with nothing: the judge could not answer."""
    import io
    import judge_likeness as jl
    import models_grade
    from PIL import Image

    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "views.png").write_bytes(b"views")
    items = [{"title": "File:Logo.svg", "srcset": [{"src": "//up/logo.svg.png"}]}, {"title": "File:Anthem.ogg"},
             {"title": "File:Twins 2019.JPG", "srcset": [{"src": "//up/small.jpg"}, {"src": "//up/large.jpg"}]}]

    def get(url, timeout=60):
        if "media-list/Petronas_Towers" in url:
            return json.dumps({"items": items}).encode()
        if "api.php" in url:
            return json.dumps({"query": {"pages": {"1": {"title": "Petronas Towers", **lead}}}}).encode()
        picture = io.BytesIO()
        Image.new("RGB", (8, 8)).save(picture, "JPEG")
        return picture.getvalue() if url == "https://up/large.jpg" else b"<svg/>"

    monkeypatch.setattr(jl, "_get", get)
    monkeypatch.setattr(jl, "claude", lambda *a, **k: '{"score": 9, "conflicts": []}')
    result = models_grade.judge(tmp_path, "Petronas Towers", "Petronas Towers")
    assert result["pass"] and result["reference"]["url"] == "https://up/large.jpg"
    del items[2]
    with pytest.raises(jl.JudgeProblem, match="no photo"):
        models_grade.judge(tmp_path, "Petronas Towers", "Petronas Towers")
