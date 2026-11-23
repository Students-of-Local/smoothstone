"""stone models: the search, ranking, licenses and credits from recorded replies (no network), the
repair, scaling, bed split with pins and thin feature report on small meshes, and the routing."""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest
import trimesh

from smoothstone import cli, modelprint, models

FIX = Path(__file__).resolve().parent / "fixtures" / "models"
EVALS = Path(__file__).resolve().parent.parent / "evals"
REQ = "A 200 mm tall model of the Eiffel Tower."


@pytest.fixture
def recorded(monkeypatch):
    """models.http plays back the replies recorded for the Eiffel Tower; anything else fails."""
    rec = json.loads((FIX / "eiffel_search.json").read_text())

    def http(url, body=None, headers=None, timeout=60):
        key = url + " " + json.dumps(body, sort_keys=True)
        if key not in rec["replies"]:
            raise OSError(f"not recorded: {key[:120]}")
        return json.dumps(rec["replies"][key]).encode()

    monkeypatch.setattr(models, "http", http)
    monkeypatch.setattr(models, "names", lambda subject: rec["names"])
    monkeypatch.delenv(models.SKETCHFAB_VAR, raising=False)
    return rec


def cand(**kw):
    c = {"source": "printables", "id": "1", "name": "Eiffel Tower", "summary": "", "author": "someone",
         "license": "Creative Commons - Attribution", "license_code": "CC-BY", "likes": 10, "makes": 0,
         "downloads": 100, "category": "Art & Design/Sculptures", "paid": False,
         "url": "https://www.printables.com/model/1"}
    return {**c, **kw}


NM = {"label": "Eiffel Tower", "wikidata": "Q243", "kind": "thing", "description": "", "names": ["Eiffel Tower", "Tour Eiffel"]}


# ranking and rejection


def test_search_ranks_the_fdm_model_first_and_leaves_out_what_is_not_a_model(recorded):
    found = models.search("Eiffel Tower", REQ, None)
    kept = found["kept"]
    assert kept[0]["id"] == "122954"  # "FDM printable", CC BY: the most made model for a nozzle
    assert [c["source"] for c in kept[:5]] == ["printables"] * 5
    why = {c["id"]: c["why"] for c in found["left_out"]}
    assert "keychain" in why.values() and "lamp" in why.values()
    # nothing kept is a keychain, a lamp or a map
    for c in kept:
        assert models.not_a_model(c, REQ) is None and models.license_ok(c)
    # the top five carry their files for the list
    assert all(c.get("files") for c in kept[:5] if c["source"] == "printables")
    assert found["sources"]["sketchfab"]["searched"] is False


def test_resin_models_rank_below_an_fdm_model_with_fewer_likes():
    resin = cand(id="1", name="Eiffel Tower for resin (SLA)", likes=1000)
    fdm = cand(id="2", name="Eiffel Tower", likes=600)
    kept, _ = models.rank([resin, fdm], NM, REQ)
    assert [c["id"] for c in kept] == ["2", "1"]


def test_rank_rejects_paid_unlicensed_other_subjects_and_accessories():
    cands = [cand(id="1"), cand(id="2", paid=True), cand(id="3", license="All rights reserved", license_code=""),
             cand(id="4", name="Big Ben"), cand(id="5", name="Eiffel Tower keychain"),
             cand(id="6", name="Eiffel Tower cookie cutter")]
    kept, out = models.rank(cands, NM, REQ)
    assert [c["id"] for c in kept] == ["1"]
    assert {c["id"]: c["why"] for c in out} == {"2": "a paid model", "3": "license All rights reserved",
                                               "4": "another subject", "5": "keychain", "6": "cookie cutter"}


def test_a_request_for_the_thing_keeps_it():
    kept, _ = models.rank([cand(name="Eiffel Tower keychain")], NM, "An Eiffel Tower keychain")
    assert len(kept) == 1


def test_choose_files_takes_the_whole_model_and_leaves_out_accessories():
    files = [{"id": "1", "name": "tower_part1.stl", "size": 10}, {"id": "2", "name": "tower_complete.stl", "size": 30},
             {"id": "3", "name": "crane.stl", "size": 5}]
    keep, left = models.choose_files(files)
    assert [f["id"] for f in keep] == ["2"]
    keep, left = models.choose_files([files[0], files[2], {"id": "4", "name": "tower_part2.stl", "size": 9}])
    assert [f["id"] for f in keep] == ["1", "4"] and left[0][1] == "an accessory, not the model"
    keep, _ = models.choose_files([{"id": "5", "name": "tower.stl", "size": 9},
                                   {"id": "6", "name": "tower_repaired.stl", "size": 9}])
    assert [f["id"] for f in keep] == ["6"]


# licenses and credits


@pytest.mark.parametrize("lic,code,short,note", [
    ("Creative Commons - Attribution", "CC-BY", "CC BY", None),
    ("Creative Commons - Attribution - Noncommercial", "CC-BY-NC", "CC BY-NC", "noncommercial: print it"),
    ("Creative Commons - Attribution - NoDerivatives", "CC-BY-ND", "CC BY-ND", "no derivatives: scaling"),
    ("Creative Commons - Attribution - Noncommercial - NoDerivatives", "CC-BY-NC-ND", "CC BY-NC-ND",
     "noncommercial, no derivatives"),
    ("Creative Commons - Public Domain", "CC0", "CC0 (public domain)", None),
    ("Standard Digital File License", "SDFL", "SDFL", "standard license"),
])
def test_license_notes(lic, code, short, note):
    c = cand(license=lic, license_code=code)
    assert models.license_short(c) == short
    got = models.license_note(c)
    assert (got is None) if note is None else got.startswith(note)


def test_credits_name_author_license_source_and_the_limit():
    c = cand(name="Sagrada Familia", author="MiniWorld3D", license="Creative Commons - Attribution - "
             "Noncommercial - NoDerivatives", license_code="CC-BY-NC-ND", url="https://www.printables.com/model/272038")
    text = models.credits_text(c, [{"name": "sagrada-complete.stl"}])
    lines = text.splitlines()
    assert lines[0] == "Sagrada Familia by MiniWorld3D"
    assert lines[1].startswith("License: CC BY-NC-ND")
    assert "Source: https://www.printables.com/model/272038" in lines
    assert "Files: sagrada-complete.stl" in lines
    assert any(ln.startswith("License note: noncommercial, no derivatives") for ln in lines)


# repair and standing it up


def test_repair_joins_overlapping_bodies_closes_holes_and_drops_crumbs():
    a = trimesh.creation.box((10, 10, 10))
    b = trimesh.creation.box((10, 10, 10))
    b.apply_translation((5, 0, 0))
    holed = trimesh.Trimesh(b.vertices, b.faces[:-2], process=False)  # one side open
    crumb = trimesh.creation.box((0.01, 0.01, 0.01))
    crumb.apply_translation((40, 0, 0))
    mesh = trimesh.util.concatenate([a, holed, crumb])
    assert not mesh.is_watertight
    log = []
    fixed = models.repair(mesh, log)
    assert fixed.is_watertight and fixed.body_count == 1
    assert fixed.volume == pytest.approx(1500, rel=0.01)
    text = " ".join(log)
    assert "Joined" in text and "Dropped" in text


def test_upright_stands_a_y_up_model_on_its_base():
    base = trimesh.creation.box((40, 5, 40))  # a y-up file: the base is flat across x and z
    tower = trimesh.creation.box((10, 40, 10))
    tower.apply_translation((0, 22.5, 0))
    log = []
    up = models.upright(trimesh.util.concatenate([base, tower]), log)
    assert up.extents[2] == pytest.approx(45, abs=0.01) and up.bounds[0] == pytest.approx([0, 0, 0])
    assert "Stood it on its base" in log[-1] and "-y" in log[-1]


# size asked for, and scaling


@pytest.mark.parametrize("request_,mode,mm,bed", [
    ("A model of Cologne Cathedral that fits my 220 mm bed.", "fit", None, [220, 220, 220]),
    ("A 150 mm long model of Notre-Dame de Paris.", "long", 150, [256, 256, 256]),
    ("A 300 mm tall model of the Sagrada Familia for my 220 mm bed.", "z", 300, [220, 220, 220]),
    ("A 200 mm tall model of the Eiffel Tower.", "z", 200, [256, 256, 256]),
    ("A model of the Taj Mahal, 150 mm across.", "long", 150, [256, 256, 256]),
    ("Big Ben, 25 cm high, for a 220 x 220 x 250 bed", "z", 250, [220, 220, 250]),
    ("A 6 inch Colosseum", "max", 152.4, [256, 256, 256]),
])
def test_target_reads_the_size_and_bed(request_, mode, mm, bed):
    t = models.target(request_, (256, 256, 256))
    assert (t["mode"], t["mm"], t["bed"]) == (mode, mm, bed)


@pytest.mark.parametrize("mode,mm,axis,want", [("z", 300, 2, 300), ("long", 150, 0, 150), ("max", 90, 2, 90)])
def test_scale_to_the_size_asked(mode, mm, axis, want):
    m = trimesh.creation.box((20, 10, 30))
    out, s = modelprint.scale_to(m, {"mode": mode, "mm": mm, "bed": [220, 220, 220]}, [])
    assert out.extents[axis] == pytest.approx(want)
    assert out.bounds[0] == pytest.approx([0, 0, 0])


def test_scale_to_fit_fills_the_bed_in_the_tightest_direction():
    m = trimesh.creation.box((20, 10, 30))
    out, _ = modelprint.scale_to(m, {"mode": "fit", "mm": None, "bed": [220, 220, 220]}, [])
    assert out.extents[2] == pytest.approx(220 * modelprint.FILL)
    assert max(out.extents) <= 220


# the bed split with pins


def test_split_a_tower_taller_than_the_bed_into_pinned_parts():
    tower = trimesh.creation.box((40, 40, 300))
    tower.apply_translation(-tower.bounds[0])
    man = modelprint.to_manifold(tower)
    cuts = modelprint.plan_cuts(man, tower.extents, [220, 220, 220])
    assert list(cuts) == [2] and len(cuts[2]) == 1
    log = []
    parts = modelprint.split(man, cuts, log)
    assert [p.number for p in parts] == [1, 2]
    for p in parts:
        assert max(np.ptp(np.asarray(p.man.bounding_box()).reshape(2, 3), axis=0)) <= 219
    js = modelprint.joints(parts, cuts, log)
    assert len(js) == 1 and js[0].kind == "pin" and len(js[0].pins) >= 2
    # the pin holes are cut into both parts: each lost the holes' volume
    lost = 40 * 40 * 300 - sum(p.man.volume() for p in parts)
    hole = modelprint.PIN_HOLE ** 2 * modelprint.PIN_DEPTH
    assert lost == pytest.approx(2 * len(js[0].pins) * hole, rel=0.1)
    pins = modelprint.to_trimesh(modelprint.pins_mesh([2 * modelprint.PIN_DEPTH - modelprint.PIN_SHORT] * len(js[0].pins)))
    assert pins.body_count == len(js[0].pins) and pins.is_watertight


def test_no_cut_when_it_fits():
    box = trimesh.creation.box((100, 100, 100))
    box.apply_translation(-box.bounds[0])
    assert modelprint.plan_cuts(modelprint.to_manifold(box), box.extents, [220, 220, 220]) == {}


def test_lay_flat_keeps_a_flat_bottom_down():
    box = trimesh.creation.box((30, 20, 10))
    flat, T, why = modelprint.lay_flat(box)
    assert why is None and np.allclose(T, np.eye(4)) and modelprint.flat_bottom(flat) == pytest.approx(600)
    spike = trimesh.creation.cone(5, 30)  # stands on its point when turned over
    spike.apply_transform(trimesh.transformations.rotation_matrix(np.pi, (1, 0, 0)))
    flat, T, why = modelprint.lay_flat(spike)
    assert why and modelprint.flat_bottom(flat) > 20


# the thin feature report


def test_thin_features_name_a_needle_and_stay_quiet_on_a_block():
    block = trimesh.creation.box((20, 20, 20))
    block.apply_translation((10, 10, 10))
    needle = trimesh.creation.box((0.3, 0.3, 10))
    needle.apply_translation((10, 10, 25))
    plain_man = modelprint.to_manifold(block)
    assert modelprint.thin_features(plain_man, 20.0) == []
    man = modelprint.to_manifold(trimesh.util.concatenate([block, needle]))
    found = modelprint.thin_features(man, 30.0)
    tips = [t for t in found if t.kind == "tip"]
    assert tips and tips[0].needles == 1 and tips[0].longest >= 9
    text = " ".join(modelprint.thin_lines(found, 30.0, 0.5))
    assert "needle" in text.lower() or "thin" in text.lower()


# routing: a landmark no recipe makes goes to stone models


def stone(*argv):
    text, code = cli.run(list(argv))
    lines = text.splitlines()
    assert len(lines) <= cli.MAX_LINES and lines[-1].startswith("NEXT: "), text
    assert "\u2014" not in text and "\u2013" not in text
    return text, code, lines[-1][len("NEXT: "):]


@pytest.mark.parametrize("request_,subject", [
    ("A model of Cologne Cathedral that fits my 220 mm bed", "Cologne Cathedral"),
    ("A 300 mm tall Sagrada Familia for my 220 mm bed", "Sagrada Familia"),
])
def test_names_landmark(request_, subject):
    assert models.names_landmark(request_) == subject


def test_names_landmark_leaves_ordinary_parts_alone():
    assert models.names_landmark("a wall hook for a 20 mm rail") is None


def test_a_landmark_request_routes_to_stone_models(jobenv, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(EVALS.parent / "recipes"))  # the real catalog: no recipe fits
    stone("new", "A model of Cologne Cathedral that fits my 220 mm bed")
    text, code, nxt = stone("recipes")
    assert nxt == 'stone models "Cologne Cathedral"', text


def test_stone_models_lists_candidates_and_offers_the_first(jobenv, recorded):
    stone("new", REQ)
    text, code, nxt = stone("models", "Eiffel Tower")
    assert code == 0 and nxt == "stone models --take 1", text
    assert "1. Eiffel Tower FDM printable by" in text and "CC BY" in text
    assert "Sketchfab not searched" in text and os.environ.get(models.SKETCHFAB_VAR) is None
    assert (jobenv / "stone-job" / "models" / "found.json").is_file()


def test_a_found_model_builds_through_modelprint(jobenv, monkeypatch):
    stone("new", REQ)
    root = jobenv / "stone-job"
    (root / "model").mkdir()
    (root / "model" / "model.json").write_text(json.dumps({"stl": str(root / "model" / "model.stl"),
                                                           "name": "Eiffel Tower", "subject": "Eiffel Tower"}))
    called = {}

    def make(root_, request, bed, progress=None):
        called["request"] = request
        return {"ok": True, "lines": ["Part: 90 x 90 x 200 mm, all 14 checks pass"], "fixes": [], "files": [str(root / "eiffel_tower.stl")],
                "pins": None, "views": None, "layout": None, "data": {}}

    monkeypatch.setattr(modelprint, "make", make)
    text, code, nxt = stone("build")
    assert called["request"] == REQ and "all 14 checks pass" in text, text


# the grader


def test_grader_size_and_credits(tmp_path):
    sys.path.insert(0, str(EVALS))
    import models_grade as mg

    bed = [220, 220, 220]
    assert mg.size_why(np.array([100, 50, 301]), {"mode": "z", "mm": 300}, bed) == []
    assert mg.size_why(np.array([100, 50, 320]), {"mode": "z", "mm": 300}, bed)
    assert mg.size_why(np.array([215, 100, 100]), {"mode": "fit"}, bed) == []
    assert mg.size_why(np.array([150, 100, 100]), {"mode": "fit"}, bed)
    assert mg.credits_why(tmp_path) == ["no credits.txt"]
    (tmp_path / "credits.txt").write_text(models.credits_text(cand(), [{"name": "a.stl"}]))
    assert mg.credits_why(tmp_path) == []


@pytest.mark.network
def test_printables_search_answers_live():
    found = models.search("Cologne Cathedral", "A model of Cologne Cathedral", None)
    assert found["sources"]["printables"]["why"] is None and found["kept"]
