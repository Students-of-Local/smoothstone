"""stone models: the search, ranking, licenses and credits from recorded replies (no network), the
repair, scaling, bed split with pins and thin feature report on small meshes, and the routing."""

import json
import os
import shlex
import sys
from pathlib import Path

import numpy as np
import pytest
import trimesh

from smoothstone import cli, landmark_refs, modelprint, models

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
    plan = modelprint.plan_split(man, tower.extents, [220, 220, 220])
    cuts = modelprint.plan_cuts_of(plan)
    assert list(cuts) == [2] and len(cuts[2]) == 1 and modelprint.plan_parts(plan) == 2
    log = []
    parts = modelprint.split(man, plan, log)
    assert [p.number for p in parts] == [1, 2]
    for p in parts:
        assert max(np.ptp(np.asarray(p.man.bounding_box()).reshape(2, 3), axis=0)) <= 219
    js = modelprint.joints(parts, cuts, log)
    assert len(js) == 1 and js[0].kind == "pin" and len(js[0].pins) >= 2
    # the pin holes are cut into both parts: each lost the holes' volume
    lost = 40 * 40 * 300 - sum(p.man.volume() for p in parts)
    hole = modelprint.PIN_HOLE ** 2 * modelprint.PIN_DEPTH
    assert lost == pytest.approx(2 * len(js[0].pins) * hole, rel=0.1)
    pins = modelprint.to_trimesh(modelprint.pins_mesh([2 * modelprint.PIN_DEPTH - modelprint.PIN_SHORT] * len(js[0].pins), (220, 220, 220)))
    assert pins.body_count == len(js[0].pins) and pins.is_watertight


def test_no_cut_when_it_fits():
    box = trimesh.creation.box((100, 100, 100))
    box.apply_translation(-box.bounds[0])
    plan = modelprint.plan_split(modelprint.to_manifold(box), box.extents, [220, 220, 220])
    assert modelprint.plan_cuts_of(plan) == {} and modelprint.plan_parts(plan) == 1


def test_a_wide_base_is_cut_across_only_where_it_is_wider_than_the_bed():
    """A 300 mm base under a 300 mm tower: the z cut takes the tower's top whole, and only the band
    with the base gets an x cut, at its narrowest and off the tower (3 parts, not 4)."""
    base = trimesh.creation.box((300, 60, 20))
    tower = trimesh.creation.box((40, 40, 300))
    tower.apply_translation((130, 0, 160))
    base.apply_translation((0, 0, 10))
    body = trimesh.boolean.union([base, tower], engine="manifold")
    body.apply_translation(-body.bounds[0])
    man = modelprint.to_manifold(body)
    plan = modelprint.plan_split(man, body.extents, [220, 220, 220])
    assert modelprint.plan_parts(plan) == 3, plan
    assert len(plan["z"]) == 1 and sum(bool(b.get(0)) or bool(b.get(1)) for b in plan["bands"]) == 1
    xs = [c for b in plan["bands"] for c in b.get(0, [])]
    assert xs and all(x < 260 - 1 for x in xs), xs  # the tower stands on the base's end, 260 to 300 mm
    parts = modelprint.split(man, plan, [])
    assert len(parts) == 3
    for p in parts:
        assert max(np.ptp(np.asarray(p.man.bounding_box()).reshape(2, 3), axis=0)) <= 219


def test_lay_flat_keeps_a_flat_bottom_down():
    box = trimesh.creation.box((30, 20, 10))
    flat, T, why = modelprint.lay_flat(box, (220, 220, 220))
    assert why is None and np.allclose(T, np.eye(4)) and modelprint.flat_bottom(flat) == pytest.approx(600)
    spike = trimesh.creation.cone(5, 30)  # stands on its point when turned over
    spike.apply_transform(trimesh.transformations.rotation_matrix(np.pi, (1, 0, 0)))
    flat, T, why = modelprint.lay_flat(spike, (220, 220, 220))
    assert why and modelprint.flat_bottom(flat) > 20


def test_lay_flat_lays_a_part_on_its_largest_flat_face():
    slab = trimesh.creation.box((100, 5, 80))  # stands on a 500 mm2 edge; its side is 8000 mm2
    flat, T, why = modelprint.lay_flat(slab, (220, 220, 220))
    assert why and "largest flat face" in why and modelprint.flat_bottom(flat) == pytest.approx(8000)


def test_a_tall_box_on_a_non_cube_bed_splits_into_parts_that_fit(tmp_path):
    """A 60 x 60 x 300 box on a 220 x 220 x 250 bed: a 249 mm band laid on its side would run past
    the 220 mm x axis, so every part keeps an orientation that fits (review first-F1)."""
    box = trimesh.creation.box((60, 60, 300))
    root = tmp_path / "job"
    (root / "model").mkdir(parents=True)
    box.export(root / "model" / "model.stl")
    (root / "model" / "model.json").write_text(json.dumps({"stl": str(root / "model" / "model.stl"),
                                                           "name": "Box tower", "subject": "Box tower"}))
    got = modelprint.make(root, "A 300 mm tall model of a tower for my 220 x 220 x 250 mm bed", (220, 220, 250))
    parts = got["data"]["parts"]
    assert len(parts) >= 2
    room = np.array([220, 220, 250]) - modelprint.BED_ROOM
    for rec in parts:
        assert np.all(np.array(rec["size_mm"]) <= room + 1e-6), rec["size_mm"]
        bed = [x for x in rec["checks"] if x["name"] == "bed"]
        assert bed and bed[0]["ok"], bed


def test_lay_flat_keeps_a_part_on_the_bed():
    band = trimesh.creation.box((60, 60, 240))
    flat, T, why = modelprint.lay_flat(band, (220, 220, 250))
    assert np.all(flat.extents <= np.array([219, 219, 249]) + 1e-6), flat.extents


def test_forty_pins_fit_a_220_bed():
    lengths = [2 * modelprint.PIN_DEPTH - modelprint.PIN_SHORT] * 40
    pins = modelprint.to_trimesh(modelprint.pins_mesh(lengths, (220, 220, 220)))
    assert pins.body_count == 40 and pins.is_watertight
    assert np.all(pins.extents[:2] <= 220 - modelprint.BED_ROOM), pins.extents


# a found model's checks: thin walls measured, overhangs on supports


def _part(tmp_path, mesh, name="part.stl"):
    mesh.apply_translation(-mesh.bounds[0] + (10, 10, 0))
    f = tmp_path / name
    mesh.export(f)
    return str(f)


def test_a_few_thin_spires_are_reported_not_failed(tmp_path):
    block = trimesh.creation.box((30, 30, 20))
    spire = trimesh.creation.box((0.3, 0.3, 8))
    spire.apply_translation((0, 0, 14))
    got = modelprint.found_checks(_part(tmp_path, trimesh.util.concatenate([block, spire])), (220, 220, 220))
    wall = {c["name"]: c for c in got["checks"]}["min_wall"]
    assert wall["ok"] and 0 < got["shares"]["one_line"] < modelprint.DROP_LIMIT, (wall, got["shares"])
    assert "under one line" in wall["detail"]


def test_a_lattice_past_the_limit_fails_min_wall(tmp_path):
    bars = []
    for i in range(12):  # twelve 0.3 mm fins on a thin plinth: most of the volume is under one line
        f = trimesh.creation.box((0.3, 30, 20))
        f.apply_translation((i * 2.5, 0, 10.5))
        bars.append(f)
    plinth = trimesh.creation.box((30, 30, 1))
    plinth.apply_translation((13.75, 0, 0.5))
    got = modelprint.found_checks(_part(tmp_path, trimesh.util.concatenate([plinth, *bars])), (220, 220, 220))
    wall = {c["name"]: c for c in got["checks"]}["min_wall"]
    assert not wall["ok"] and got["shares"]["one_line"] > modelprint.DROP_LIMIT
    assert "0.2 mm nozzle" in wall["advice"]


def test_an_overhang_prints_on_supports(tmp_path):
    post = trimesh.creation.box((30, 30, 30))
    top = trimesh.creation.box((60, 60, 4))  # a table top 15 mm out past its post on every side
    top.apply_translation((0, 0, 16))
    table = trimesh.boolean.union([post, top], engine="manifold")
    got = modelprint.found_checks(_part(tmp_path, table), (220, 220, 220))
    by = {c["name"]: c for c in got["checks"]}
    assert by["overhang"]["ok"] and "supports" in by["overhang"]["detail"]
    assert by["supports"]["ok"] and got["support_g"] >= modelprint.SUPPORT_MIN, got["support_g"]
    assert not [c["name"] for c in got["checks"] if not c["ok"]], got["checks"]


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
    ("Can you print Taj Mahal, about 19 cm across?", "Taj Mahal"),
    ("Can you print the Eiffel Tower, around 20 cm tall?", "Eiffel Tower"),
])
def test_names_landmark(request_, subject):
    assert models.names_landmark(request_) == subject


def test_names_landmark_leaves_ordinary_parts_alone():
    assert models.names_landmark("a wall hook for a 20 mm rail") is None


def test_a_landmark_request_routes_to_stone_landmark(jobenv, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(EVALS.parent / "recipes"))  # the real catalog: no recipe fits
    stone("new", "A model of Cologne Cathedral that fits my 220 mm bed")
    text, code, nxt = stone("recipes")
    assert nxt == "stone landmark 'Cologne Cathedral'", text


def _route(monkeypatch, request_):
    monkeypatch.setenv("STONE_RECIPES", str(EVALS.parent / "recipes"))  # the real catalog: no recipe fits
    stone("new", request_)
    text, code, nxt = stone("recipes")
    return shlex.split(nxt)[:2], text


@pytest.mark.parametrize("request_", [
    "Find me an open model of the Eiffel Tower",
    "Download an STL of the Taj Mahal",
    "Find the Eiffel Tower on Thingiverse",
    "Grab the Cologne Cathedral file from Printables",
    "Find me a 3D printable model of the Eiffel Tower",
])
def test_a_find_request_routes_to_stone_models(jobenv, monkeypatch, request_):
    cmd, text = _route(monkeypatch, request_)
    assert cmd == ["stone", "models"], text


@pytest.mark.parametrize("request_", ["Print me the Eiffel Tower", "A 200 mm tall model of the Eiffel Tower"])
def test_a_plain_landmark_request_routes_to_stone_landmark(jobenv, monkeypatch, request_):
    cmd, text = _route(monkeypatch, request_)
    assert cmd == ["stone", "landmark"], text


@pytest.mark.parametrize("spec", sorted((EVALS / "models").glob("m0*.json")), ids=lambda p: p.stem)
def test_every_models_eval_routes_to_stone_models(jobenv, monkeypatch, spec):
    cmd, text = _route(monkeypatch, json.loads(spec.read_text())["request"])
    assert cmd == ["stone", "models"], text


@pytest.mark.parametrize("spec", sorted((EVALS / "landmarks").glob("l0*.json")), ids=lambda p: p.stem)
def test_every_landmarks_eval_routes_to_stone_landmark(jobenv, monkeypatch, spec):
    cmd, text = _route(monkeypatch, json.loads(spec.read_text())["request"])
    assert cmd == ["stone", "landmark"], text


@pytest.mark.parametrize("request_", ["A stand for my Kindle Paperwhite", "A case for my Flipper Zero"])
def test_names_landmark_leaves_named_products_alone(request_):
    """A capitalised product name is no landmark: it keeps the ask-the-person path (review first-F3)."""
    assert models.names_landmark(request_) is None


@pytest.mark.parametrize("request_,subject", [
    ("A model of Cologne Cathedral", "Cologne Cathedral"),
    ("print me the Eiffel Tower", "Eiffel Tower"),
])
def test_names_landmark_still_names_buildings(request_, subject):
    assert models.names_landmark(request_) == subject


@pytest.mark.parametrize("request_, subject", [
    ("A 3D print of the Arc de Triomphe, 16 cm tall please.", "Arc de Triomphe"),
    ("Model Stonehenge for my 3D printer, 16 cm across.", "Stonehenge"),
    ("make me the alhambra, 15 cm", "alhambra"),
    ("a 3d model of petra, 12 cm", "petra"),
    ("A stand for my Kindle Paperwhite", None),
    ("A clip for the Arc de Triomphe", None),
    ("a wall thing", None),
    ("make me stonehenge, 16 cm", "stonehenge"),
    ("make me the alhambra in PLA", "alhambra"),
    ("a wall hook with a small Parthenon on it", None),
    ("a clip for St. Mark\u2019s", None),
    ("a birdhouse that looks like the parthenon", None),
    ("a model of a white house with a red roof", None),
    ("a 3D print of a pentagon", None),
    ("An Arc de Triomphe phone stand", None),
])
def test_a_structure_without_a_building_word_routes_to_stone_landmark(jobenv, monkeypatch, request_, subject):
    monkeypatch.setattr(landmark_refs, "is_structure", lambda name: name in (
        "Kindle Paperwhite", subject, "Arc de Triomphe", "Parthenon", "parthenon", "white house", "pentagon", "Saint Mark's"))
    assert models.known_landmark(request_) == subject
    if subject:
        assert _route(monkeypatch, request_)[0] == ["stone", "landmark"]


def test_a_named_statue_the_map_cannot_draw_goes_on_to_found_models(jobenv, monkeypatch):
    def refused(*args, **kwargs):
        raise landmark_refs.LandmarkProblem("A statue is a sculpture, and building maps do not have its shape.")

    monkeypatch.setattr(landmark_refs, "is_structure", lambda name: True)
    monkeypatch.setattr(landmark_refs, "resolve", refused)
    assert _route(monkeypatch, "A 3D print of Christ the Redeemer, 16 cm tall.")[0] == ["stone", "landmark"]
    text, code, nxt = stone("landmark", "Christ the Redeemer")
    assert shlex.split(nxt) == ["stone", "models", "Christ the Redeemer"]


def test_the_lookup_waits_until_no_recipe_fits(jobenv, monkeypatch):
    asked = []
    monkeypatch.setattr(landmark_refs, "is_structure", lambda name: asked.append(name) or True)
    request_ = "Print the Arc de Triomphe as a phone stand"
    assert models.known_landmark(request_) == "Arc de Triomphe" and asked
    asked.clear()
    assert _route(monkeypatch, request_)[0] != ["stone", "landmark"] and not asked


def test_the_eval_landmarks_still_route():
    for f in sorted((EVALS / "models").glob("m0*.json")):
        req = json.loads(f.read_text())["request"]
        assert models.names_landmark(req), req


ODD = 'Tower of "$(touch pwned)" `x`'


def test_models_route_quotes_the_subject_for_the_shell():
    out = cli.models_route(cli.Out(), ODD)
    assert shlex.split(out.next) == ["stone", "landmark", ODD], out.next


def test_models_take_quotes_the_subject_for_the_shell(jobenv, monkeypatch):
    stone("new", REQ)
    monkeypatch.setattr(models, "names_landmark", lambda request: ODD)
    text, code, nxt = stone("models", "--take", "1")
    assert shlex.split(nxt) == ["stone", "models", ODD], nxt



def test_landmark_creates_job_and_runs_shared_build(jobenv, monkeypatch):
    import types
    import smoothstone

    module = types.ModuleType("smoothstone.landmark")
    module.LandmarkProblem = type("LandmarkProblem", (Exception,), {})
    calls = []

    def generate(name, root, bed, size, detail):
        calls.append((name, size, detail))
        return {"stl": str(root / "model" / "model.stl"), "name": name, "subject": name, "source": "landmark"}

    module.generate = generate
    monkeypatch.setattr(smoothstone, "landmark", module, raising=False)
    monkeypatch.setitem(sys.modules, "smoothstone.landmark", module)
    monkeypatch.setattr(cli, "_models_build", lambda job: cli.Out(lines=["Part ready"], next=cli.DONE_NEXT))
    text, code, nxt = stone("landmark", "Cologne Cathedral", "--size", "150", "--detail", "low")
    assert code == 0 and nxt == cli.DONE_NEXT, text
    assert calls == [("Cologne Cathedral", 150.0, "low")]
    assert models.taken(jobenv / "stone-job")["source"] == "landmark"


def test_landmark_without_parts_routes_to_models_and_does_not_loop(jobenv, monkeypatch):
    import types
    import smoothstone

    module = types.ModuleType("smoothstone.landmark")
    module.LandmarkProblem = type("LandmarkProblem", (Exception,), {})

    def generate(*args):
        raise module.LandmarkProblem("no 3D building parts found")

    module.generate = generate
    monkeypatch.setattr(smoothstone, "landmark", module, raising=False)
    monkeypatch.setitem(sys.modules, "smoothstone.landmark", module)
    text, code, nxt = stone("landmark", "Cologne Cathedral")
    assert code == 1 and "FIX: no 3D building parts found" in text
    assert nxt == "stone models 'Cologne Cathedral'"
    found = {
        "subject": "Cologne Cathedral", "names": {"kind": "building", "label": "Cologne Cathedral"},
        "terms": [], "kept": [], "left_out": [],
        "sources": {"sketchfab": {"searched": False}, "printables": {"found": 0, "why": ""},
                    "commons": {"found": 0}},
    }
    monkeypatch.setattr(models, "search", lambda *args: found)
    text, code, nxt = stone("models", "Cologne Cathedral")
    assert code == 1 and nxt.startswith("ask the person:"), text


def test_landmark_done_reports_model_credits(jobenv):
    stone("new", "A model of Cologne Cathedral")
    root = jobenv / "stone-job"
    part = root / "cathedral.stl"
    part.touch()
    credits = root / "model" / "credits.txt"
    models.model_file(root).parent.mkdir(parents=True)
    models.model_file(root).write_text(json.dumps({"stl": str(part), "name": "Cologne Cathedral",
                                                  "source": "landmark", "credits": str(credits)}))
    data_file = root / "build" / "model" / "parts.json"
    data_file.parent.mkdir(parents=True)
    data_file.write_text(json.dumps({"parts": [{"file": str(part)}], "size_mm": [100, 100, 200]}))
    cli.Job(root).update(passed=True)
    text, code, nxt = stone("done")
    assert code == 0 and nxt == cli.DONE_NEXT, text
    assert f"Credits: {credits}" in text

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


# faults the first eval run found (LOG.md, models 1)


def test_saint_abbreviation_keeps_the_whole_name():
    # m06 searched "St" and took an egg cup named Stockholm
    assert models.subject_of("A 150 mm tall model of St. Basil's Cathedral.") == "Saint Basil's Cathedral"
    assert models.subject_of("A model of Mt. Rushmore") == "Mount Rushmore"


def test_lego_sets_and_egg_cups_are_not_models():
    nm = {**NM, "names": ["Taj Mahal"]}
    kept, out = models.rank([cand(name="Lego Taj Mahal 21056"), cand(name="Egg Cup Taj Mahal"), cand(name="Taj Mahal")],
                            nm, "A model of the Taj Mahal")
    assert [c["name"] for c in kept] == ["Taj Mahal"]
    assert sorted(c["why"] for c in out) == ["brick set", "vase"]


def test_two_years_of_one_model_are_not_merged():
    files = [{"id": "1", "name": "2014-eiffel-tower-miniworld3d.stl", "size": 5},
             {"id": "2", "name": "2022-eiffel-tower-miniworld3d.stl", "size": 4}]
    keep, left = models.choose_files(files)
    assert [f["id"] for f in keep] == ["2"] and "another year" in left[0][1]
    parts = [{"id": "3", "name": "tower_part1.stl", "size": 5}, {"id": "4", "name": "tower_part2.stl", "size": 5}]
    assert len(models.choose_files(parts)[0]) == 2


def test_read_3mf_without_lxml(tmp_path):
    import zipfile

    box = trimesh.creation.box((10, 20, 30))
    v = "".join(f'<vertex x="{a}" y="{b}" z="{c}"/>' for a, b, c in box.vertices)
    t = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in box.faces)
    xml = ('<?xml version="1.0" encoding="UTF-8"?><model unit="millimeter" '
           'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"><resources>'
           f'<object id="1" type="model"><mesh><vertices>{v}</vertices><triangles>{t}</triangles></mesh></object>'
           '<object id="2" type="model"><components><component objectid="1" transform="1 0 0 0 1 0 0 0 1 100 0 0"/>'
           '</components></object></resources><build><item objectid="1"/>'
           '<item objectid="2" transform="1 0 0 0 1 0 0 0 1 0 0 5"/></build></model>')
    f = tmp_path / "two.3mf"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("3D/3dmodel.model", xml)
    m = models.load_mesh([f])
    assert len(m.faces) == 24 and m.body_count == 2
    assert m.bounds[1] == pytest.approx([105, 10, 20])


def test_an_uncut_model_of_separate_towers_counts_its_bodies(tmp_path):
    a = trimesh.creation.box((10, 10, 30))
    b = trimesh.creation.box((10, 10, 30))
    b.apply_translation((30, 0, 0))
    root = tmp_path / "job"
    (root / "model").mkdir(parents=True)
    trimesh.util.concatenate([a, b]).export(root / "model" / "model.stl")
    (root / "model" / "model.json").write_text(json.dumps({"stl": str(root / "model" / "model.stl"),
                                                           "name": "Two towers", "subject": "Two towers"}))
    got = modelprint.make(root, "A 60 mm tall model of two towers", (256, 256, 256))
    rec = got["data"]["parts"][0]
    assert rec["bodies"] == 2
    assert not [x["name"] for x in rec["checks"] if not x["ok"] and x["name"] == "bodies"]


def test_a_clear_lead_is_taken_and_the_rest_offered(jobenv, recorded, monkeypatch):
    rec = recorded
    stone("new", REQ)
    kept = [cand(name="Eiffel Tower FDM printable", makes=180, likes=1735, match=2),
            cand(id="2", name="Eiffel Tower", makes=30, likes=500, match=2)]
    monkeypatch.setattr(models, "search", lambda subject, request, cache: {
        "subject": "Eiffel Tower", "names": NM, "terms": ["Eiffel Tower"], "kept": kept, "left_out": [],
        "sources": {"printables": {"found": 2, "why": ""}, "commons": {"found": 0}, "sketchfab": {"searched": False}}})
    taken = {}

    def take(n, job, out):
        taken["n"] = n
        out.next = "stone build"
        return out

    monkeypatch.setattr(cli, "_models_take", take)
    text, code, nxt = stone("models", "Eiffel Tower")
    assert taken == {"n": 1} and nxt == "stone build", text
    assert "stone models --take <n>" in text and "2. Eiffel Tower" in text


def test_clear_lead_needs_a_name_match_a_license_and_the_most_makes_and_likes():
    top = cand(makes=100, likes=900, match=2)
    assert models.clear_lead([top, cand(id="2", makes=10, likes=50, match=2)])
    assert not models.clear_lead([top, cand(id="2", makes=120, likes=50, match=2)])
    assert not models.clear_lead([{**top, "match": 1}, cand(id="2", makes=1, likes=1, match=2)])
    assert not models.clear_lead([{**top, "license_code": "", "license": ""}])
    assert not models.clear_lead([])


def test_a_model_whose_solids_save_broken_says_so_and_offers_the_next(jobenv, monkeypatch):
    stone("new", REQ)
    root = jobenv / "stone-job"
    (root / "models").mkdir(parents=True, exist_ok=True)
    (root / "models" / "found.json").write_text(json.dumps({"kept": [cand(), cand(id="2")]}))
    (root / "model").mkdir()
    (root / "model" / "model.json").write_text(json.dumps({"stl": str(root / "model" / "model.stl"), "index": 1,
                                                           "name": "Notre-Dame", "subject": "Notre-Dame"}))

    def make(root_, request, bed, progress=None):
        return {"ok": False, "lines": ["Part 1: fails bodies"], "fixes": [], "files": [str(root / "p1.stl")],
                "pins": None, "views": None, "layout": None, "data": {}, "broken": [1]}

    monkeypatch.setattr(modelprint, "make", make)
    text, code, nxt = stone("build")
    assert "solids only touch" in text and "part 1 save with broken edges" in text, text
    assert nxt == "stone models --take 2"


def test_get_my_files_is_no_found_model_request():
    from smoothstone import models as mdl
    assert not mdl.asks_found_model("A tray to get my files sorted beside my Steam Deck")
