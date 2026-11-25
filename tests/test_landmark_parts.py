"""Reference parts: the cases in docs/REFERENCE_PARTS.md."""

import json
import math
from pathlib import Path

import manifold3d as m3
import numpy as np
import pytest

from smoothstone import landmark, landmark_parts, landmark_refs, modelprint

SOURCE = "https://example.org/survey"
REFS = {"latitude": 0., "longitude": 0.}
BLOCK = {"kind": "prism", "rect": [4, 6], "from": 0, "to": 10}


def _pack(*parts, **more):
    return {"parts": {"source": SOURCE, "origin": [0, 0], "value": list(parts), **more}}


def _solid(*parts, scale=10., **more):
    """The joined parts at a scale so large that nothing is widened, measured in metres."""
    records, _, _ = landmark_parts.read(_pack(*parts, **more), REFS)
    solids = [s for r in records for s in r["_build"](scale, [])]
    return m3.Manifold.batch_boolean(solids, m3.OpType.Add).scale([1 / scale] * 3)


def _box(solid):
    return pytest.approx(np.array(solid.bounding_box()), abs=.02)


@pytest.mark.parametrize("part, more, box", [
    (BLOCK, {}, [-2, -3, 0, 2, 3, 10]),
    (BLOCK, {"axis": 90}, [-3, -2, 0, 3, 2, 10]),
    (BLOCK, {"origin": [10 / 111320, 20 / 111320]}, [18, 7, 0, 22, 13, 10]),
    ({**BLOCK, "at": [0, 20]}, {"axis": 90}, [17, -2, 0, 23, 2, 10]),  # y runs east
    ({**BLOCK, "at": [20, 0]}, {"axis": 90}, [-3, -22, 0, 3, -18, 10]),  # and x south, to its right
    ({**BLOCK, "turn": 90}, {}, [-3, -2, 0, 3, 2, 10]),
    ({**BLOCK, "top_shift": [3, 0]}, {}, [-2, -3, 0, 5, 3, 10]),
    ({"kind": "lathe", "at": [1, 0], "profile": [[0, 5], [10, 1]]}, {}, [-4, -5, 0, 6, 5, 10]),
    ({"kind": "beam", "path": [[0, 0, 5], [0, 20, 5]], "size": [2, 4]}, {}, [-1, 0, 3, 1, 20, 7]),
    ({"kind": "beam", "path": [[0, 0, 0], [0, 0, 9]], "size": [2, 4]}, {}, [-1, -2, 0, 1, 2, 9]),
    ({"kind": "prism", "ngon": [8, 5], "to": 3}, {}, [-5 * math.cos(math.pi / 8)] * 2 + [0] + [5 * math.cos(math.pi / 8)] * 2 + [3]),
    ({"kind": "prism", "ring": [[0, 0], [4, 0], [0, 4]], "to": 3}, {}, [0, 0, 0, 4, 4, 3]),
    ({**BLOCK, "roof": "gabled", "roof_rise": 3}, {}, [-2, -3, 0, 2, 3, 10]),
])
def test_a_part_stands_where_the_spec_says(part, more, box):
    assert np.array(box, float) == _box(_solid(part, **more))


def _frustum(h, a, b):
    return h * (a + b + math.sqrt(a * b)) / 3


def test_a_loft_goes_straight_from_section_to_section():
    loft = {"kind": "loft", "rect": [4, 6], "at": [1, 0]}
    solid = _solid({**loft, "sections": [[0, 1], [8, 1.2], [10, .5]]}, scale=100)
    assert np.array([-1.4, -3.6, 0, 3.4, 3.6, 10]) == _box(solid)
    assert solid.volume() == pytest.approx(_frustum(8, 24, 24 * 1.44) + _frustum(2, 24 * 1.44, 6), rel=.005)
    moved = _solid({**loft, "sections": [[0, 1, 1, 0, 0, 0], [10, 1, .5, 3, 0, 90]]}, scale=100)
    assert moved.trim_by_plane([0, 0, 1], 9.999).bounding_box()[:5] == pytest.approx((2.5, -2, 9.999, 5.5, 2), abs=.02)
    west = _solid({"kind": "loft", "ring": [[-2, 0], [2, 0], [2, 1], [-2, 1]], "sections": [[0, 1, 1, 0, 0, 0], [9, 1, 1, 0, 0, 30]]},
                  scale=100).trim_by_plane([0, 0, 1], 8.999)
    right = west.trim_by_plane([1, 0, 0], 1).bounding_box()
    assert right[1] < -.9 and right[4] < .6  # clockwise: its right end turned toward -y
    assert west.status() == m3.Error.NoError


def test_a_loft_keeps_a_print_minimum_at_every_section():
    cone = landmark_parts.read(_pack({"kind": "loft", "rect": [4, 6], "sections": [[0, 1], [10, 0]]}), REFS)[0][0]
    top = m3.Manifold.batch_boolean(cone["_build"](1., []), m3.OpType.Add).trim_by_plane([0, 0, 1], 9.999).bounding_box()
    assert top[3] - top[0] == pytest.approx(1.2, abs=.01) and top[4] - top[1] == pytest.approx(1.2, abs=.01)
    assert cone["print_modifications"] == ["Widened to 1.2 mm."]


def test_a_taper_is_half_at_the_top_and_a_cone_has_a_cones_volume():
    assert _solid({**BLOCK, "top_scale": .5}).volume() == pytest.approx(10 * (24 + 6 + 12) / 3, rel=.01)
    cone = _solid({"kind": "lathe", "profile": [[0, 5], [10, 0]]}, scale=100)
    assert cone.volume() == pytest.approx(math.pi * 25 * 10 / 3, rel=.02)


def test_a_tapered_roof_sits_on_the_narrowed_top():
    solid = _solid({**BLOCK, "to": 12, "top_scale": .5, "roof": "pyramidal", "roof_rise": 2})
    assert solid.volume() == pytest.approx(10 * (24 + 6 + 12) / 3 + 2 * 6 / 3, rel=.03)
    assert solid.bounding_box()[5] == pytest.approx(12, abs=.02)


@pytest.mark.parametrize("roof, ridge, x, y", [  # the half extents of what stands above 9.9 of 10
    ("gabled", None, .07, 3), ("gabled", 0, .07, 3), ("gabled", 90, 2, .11), ("hipped", 90, .07, .11), ("round", 90, 2, .76)])
def test_a_roofs_ridge_runs_the_way_it_is_told(roof, ridge, x, y):
    part = {**BLOCK, "roof": roof, "roof_rise": 3, **({} if ridge is None else {"ridge": ridge})}
    top = _solid(part, scale=100).trim_by_plane([0, 0, 1], 9.9).bounding_box()
    assert top[:2] + top[3:5] == pytest.approx((-x, -y, x, y), abs=.02)


def test_a_ridge_turns_clockwise_from_y():
    top = _solid({**BLOCK, "rect": [4, 4], "roof": "gabled", "roof_rise": 3, "ridge": 45}, scale=100).trim_by_plane([0, 0, 1], 9.9)
    right = top.trim_by_plane([1, 0, 0], .5)
    assert right.bounding_box()[1] > .3 and right.bounding_box()[4] == pytest.approx(2, abs=.02)


@pytest.mark.parametrize("copies, centres", [
    ({"around": [0, 0], "count": 4}, {(3, 4), (4, -3), (-3, -4), (-4, 3)}),
    ({"mirror": "x"}, {(3, 4), (-3, 4)}),
    ({"mirror": "y"}, {(3, 4), (3, -4)}),
    ({"mirror": "xy"}, {(3, 4), (-3, 4), (3, -4), (-3, -4)}),
    ({"row": [0, 5], "count": 3}, {(3, 4), (3, 9), (3, 14)}),
])
def test_copies(copies, centres):
    solid = _solid({"kind": "prism", "rect": [1, 1], "to": 2, "at": [3, 4], "copies": copies})
    boxes = [c.bounding_box() for c in solid.decompose()]
    assert {(round((b[0] + b[3]) / 2), round((b[1] + b[4]) / 2)) for b in boxes} == centres
    assert len(boxes) == len(centres) and solid.volume() == pytest.approx(2 * len(centres), rel=.01)


@pytest.mark.parametrize("part", [
    {"kind": "prism", "rect": [.1, 6], "to": 10},
    {"kind": "beam", "path": [[0, 0, 5], [0, 20, 5]], "size": [.1, .1]},
    {"kind": "lathe", "profile": [[0, .1], [10, .1]]},
])
def test_a_thin_part_is_widened_to_print(part):
    record = landmark_parts.read(_pack(part), REFS)[0][0]
    box = m3.Manifold.batch_boolean(record["_build"](1., []), m3.OpType.Add).bounding_box()
    assert box[3] - box[0] == pytest.approx(1.2, abs=.02) and record["print_modifications"]


@pytest.mark.parametrize("part, foot, top", [
    ({"kind": "prism", "rect": [27, 2737], "from": 67, "to": 74.6}, 5.596 - 1.2, 5.596),  # a bridge's deck
    ({"kind": "lathe", "profile": [[67, 40], [74.6, 30]]}, 5.596 - 1.2, 5.596),
    ({"kind": "prism", "rect": [40, 40], "from": 0, "to": 40}, 0, 3),
])
def test_a_sheet_is_thickened_under_its_top(part, foot, top):
    record = landmark_parts.read(_pack(part), REFS)[0][0]
    box = m3.Manifold.batch_boolean(record["_build"](.075, []), m3.OpType.Add).bounding_box()
    assert box[2] == pytest.approx(foot, abs=.02) and box[5] == pytest.approx(top, abs=.02)


def test_a_beams_heights_are_its_solids_and_a_skillion_falls_toward_y():
    beam = landmark_parts.read(_pack({"kind": "beam", "path": [[0, 0, 0], [0, 0, 9]], "size": [2, 4]}), REFS)[0][0]
    assert (beam["min_height"]["metres"], beam["height"]["metres"]) == pytest.approx((0, 9))
    roof = _solid({**BLOCK, "roof": "skillion", "roof_rise": 3})
    assert roof.slice(9.).bounds()[3] < 0 < -roof.slice(9.).bounds()[1]


def test_a_guess_is_marked_and_a_part_may_name_its_source():
    parts = [{**BLOCK, "guess": "a floor is 4 m"}, {**BLOCK, "id": "b", "source": SOURCE + "/b"}]
    a, b = landmark_parts.read(_pack(*parts), REFS)[0]
    assert a["height"] == {**a["height"], "metres": 10, "guessed": True, "reason": "a floor is 4 m"}
    assert not b["height"]["guessed"] and b["source"].endswith("/b")


@pytest.mark.parametrize("part, why", [
    ({"kind": "cube"}, "kind must be"),
    ("text", "kind must be"),
    ({"kind": "prism", "to": 3}, "give one plan"),
    ({**BLOCK, "circle": 4}, "give one plan"),
    ({**BLOCK, "to": 0}, "to must be above from"),
    ({**BLOCK, "to": "10"}, "to must be a number"),
    ({**BLOCK, "to": True}, "to must be a number"),
    ({**BLOCK, "to": float("nan")}, "to must be a number"),
    ({"kind": "prism", "from": 0}, "give one plan"),
    ({"kind": "prism", "rect": [4, 6]}, "to must be a number"),
    ({**BLOCK, "radius": 0}, "no field radius"),
    ({"kind": "prism", "circle": 0, "to": 3}, "more than 0"),
    ({"kind": "prism", "ngon": [2, 4], "to": 3}, "3 to 64"),
    ({"kind": "prism", "ring": [[0, 0], [1, 0], [2, 0]], "to": 3}, "encloses no area"),
    ({"kind": "prism", "ring": [[0, 0], [9, 0], [9, 9], [4, -1], [0, 9]], "to": 3}, "ring crosses itself"),
    ({**BLOCK, "roof": "dome"}, "needs roof_rise"),
    ({**BLOCK, "roof_rise": 2}, "needs roof_rise"),
    ({**BLOCK, "roof": "tent", "roof_rise": 2}, "roof must be"),
    ({**BLOCK, "roof": "dome", "roof_rise": 11}, "roof_rise must be"),
    ({**BLOCK, "top_scale": 0}, "more than 0"),
    ({"kind": "lathe", "profile": [[5, 1], [0, 1]]}, "must rise"),
    ({"kind": "lathe", "profile": [[0, 0], [5, 0]]}, "radius above 0"),
    ({**BLOCK, "roof": "pyramidal", "roof_rise": 3, "ridge": 0}, "ridge needs a roof"),
    ({**BLOCK, "ridge": 0}, "ridge needs a roof"),
    ({"kind": "lathe"}, "profile must list"),
    ({"kind": "beam", "path": [[0, 0, 0], [0, 0, 0]], "size": [1, 1]}, "repeats a point"),
    ({"kind": "beam", "path": [[0, 0, 0], [0, 0, 1]], "size": [0, 1]}, "more than 0"),
    ({"kind": "opening", "width": 4, "depth": 4, "from": 0, "to": 1, "arch": True}, "rises 2 m, more than"),
    ({"kind": "opening", "width": 4, "depth": 4, "to": 9, "arch": "ogee"}, "pointed or triangle"),
    ({"kind": "opening", "width": 4, "depth": 4, "to": 9, "arch": "pointed", "arch_rise": 1}, "at least half"),
    ({"kind": "opening", "width": 4, "depth": 4, "to": 9, "arch_rise": 1}, "needs an arch"),
    ({"kind": "opening", "outline": [[0, 0], [4, 0], [0, 4]], "depth": 4, "to": 9}, "takes no to"),
    ({"kind": "opening", "outline": [[0, 0], [4, 0], [8, 0]], "depth": 4}, "no area"),
    ({**BLOCK, "copies": {"around": [0, 0], "count": 401}}, "1 to 400"),
    ({**BLOCK, "copies": {"mirror": "z"}}, "mirror must be"),
    ({**BLOCK, "copies": 4}, "must be an object"),
    ({"kind": "loft", "rect": [4, 6], "sections": [[0, 1]]}, "2 to 100 rows"),
    ({"kind": "loft", "rect": [4, 6], "sections": [[0, 1], [9, 1, 1]]}, "same length"),
    ({"kind": "loft", "rect": [4, 6], "sections": [[0, 1], [0, 1]]}, "must rise"),
    ({"kind": "loft", "rect": [4, 6], "sections": [[0, 0], [9, 0]]}, "not 0 all"),
    ({"kind": "loft", "rect": [4, 6], "to": 9, "sections": [[0, 1], [9, 1]]}, "no field to"),
    ({**BLOCK, "guess": ""}, "guess must say"),
    ({**BLOCK, "source": "a book"}, "must be a URL"),
    ({**BLOCK, "at": [1]}, "at must be"),
])
def test_a_bad_part_is_refused_by_its_place(part, why):
    with pytest.raises(landmark_refs.LandmarkProblem, match=why) as stop:
        landmark_parts.read(_pack(BLOCK, part), REFS)
    assert "parts[1]" in str(stop.value)


@pytest.mark.parametrize("more", [{"origin": None}, {"origin": [0]}, {"axis": "north"}, {"replace": "some"}, {"value": []}, {"scale": 2},
                                  {"replace": ["7"]}, {"origin": [2.3, 48.9]}])
def test_a_bad_fact_is_refused(more):
    with pytest.raises(landmark_refs.LandmarkProblem, match="Reference parts"):
        landmark_parts.read(_pack(BLOCK, **more), REFS)


def test_too_many_parts_and_openings_alone_are_refused():
    rows = {**BLOCK, "copies": {"row": [9, 0], "count": 201}}
    with pytest.raises(landmark_refs.LandmarkProblem, match="more than 400"):
        landmark_parts.read(_pack({**rows, "id": "a"}, {**rows, "id": "b"}), REFS)
    with pytest.raises(landmark_refs.LandmarkProblem, match="needs a part"):
        landmark_parts.read(_pack({"kind": "opening", "width": 4, "depth": 9, "from": 0, "to": 5}), REFS)


@pytest.fixture
def build(monkeypatch, tmp_path):
    """Build a pack as `stone landmark --refs` does, with the map answering these parts."""
    asked = []

    def go(pack, parts=(), detail="low", outline=None, site=None):
        monkeypatch.setattr(landmark_refs, "resolve", lambda name, root: {
            **REFS, "label": "Example", "id": "Q1", "height": None, "style": [], "source": SOURCE, "sources": {}})
        ring = [[[-5, -5], [5, -5], [5, 5], [-5, 5]]]

        def fetch(refs, root):
            asked.append(1)
            return {"outline": ring if outline is None else outline, "source": SOURCE, "tags": {}, "linked_towers": [],
                **({"site": site} if site else {}), "parts": [
                {"id": i, "type": "way", "footprint": ring if i == 1 else [[[6, -5], [16, -5], [16, 5], [6, 5]]],
                 "tags": {"height": str(h)}, "source": SOURCE} for i, h in parts]}
        monkeypatch.setattr(landmark_refs, "fetch", fetch)
        path = tmp_path / "pack.json"
        path.write_text(json.dumps(pack))
        info = landmark.generate("Example", tmp_path / "job", [200, 200, 200], 100, detail, ref_pack=path)
        import trimesh
        mesh = trimesh.load(info["stl"])
        assert mesh.is_watertight
        return modelprint.to_manifold(mesh), json.loads((tmp_path / "job/refs/landmark.json").read_text()), info["scale"], asked
    return go


def test_the_map_is_not_asked_when_the_pack_replaces_it(build):
    man, refs, scale, asked = build(_pack(BLOCK, replace="all"))
    assert not asked and [p["id"] for p in refs["parts"]] == ["part-0"]
    assert man.bounding_box()[5] == pytest.approx(2 + 10 * scale, abs=.05)


def test_the_pack_adds_to_the_map_and_takes_the_listed_parts_from_it(build):
    tall = {**BLOCK, "at": [0, 0], "to": 30}
    _, refs, _, asked = build(_pack(tall), [(1, 10), (7, 12)])
    assert asked and [p["id"] for p in refs["parts"]] == [1, 7, "part-0"]
    _, refs, _, _ = build(_pack(tall, replace=[7]), [(1, 10), (7, 12)])
    assert [p["id"] for p in refs["parts"]] == [1, "part-0"]


def test_a_leg_set_on_the_ground_stops_at_the_bed(build):
    """A splayed leg's foot hung 2.5 mm under the base, which then stood on its corners."""
    leg = {"kind": "beam", "path": [[40, 40, 0], [10, 10, 57]], "size": [25, 25], "copies": {"mirror": "xy"}}
    man, _, scale, _ = build(_pack(leg, replace="all"))
    assert man.slice(.2).area() > 4 * (25 * scale) ** 2 * .9 and man.slice(1.9).area() == pytest.approx(man.slice(.2).area(), rel=.1)


def test_only_the_packs_own_parts_miss_the_ornament(build, monkeypatch):
    """The map's corrected records are 'reference' too, and lost theirs."""
    from smoothstone import landmark_architecture, landmark_style
    seen = []

    def corrected(records, sections, *_):
        records[0]["type"] = "reference"
        return records, sections, []
    monkeypatch.setattr(landmark_architecture, "reconcile", corrected)
    monkeypatch.setattr(landmark_style, "decorate", lambda man, records, *a, **k: (seen.extend(p["id"] for p in records) or man, []))
    build(_pack({**BLOCK, "to": 30}), [(1, 10)], "high")
    assert seen == [1]


def test_a_flagpole_is_not_the_landmark_and_replace_names_mapped_parts(build):
    pole = {"kind": "beam", "path": [[0, 0, 0], [0, 0, 30]], "size": [1, 1]}
    with pytest.raises(landmark_refs.LandmarkProblem, match="insufficient"):
        build(_pack(pole))
    with pytest.raises(landmark_refs.LandmarkProblem, match="no part 9"):
        build(_pack(BLOCK, replace=[9]), [(1, 10)])


def test_an_openings_source_and_guess_are_kept_and_the_map_is_not_credited(build, tmp_path):
    hole = {"kind": "opening", "width": 2, "depth": 12, "from": 0, "to": 6, "source": SOURCE + "/door", "guess": "a door"}
    _, refs, _, _ = build(_pack(BLOCK, hole, replace="all"))
    credits = (tmp_path / "job/model/credits.txt").read_text()
    assert "OpenStreetMap" not in credits and SOURCE + "/door" in credits
    build(_pack({**BLOCK, "source": "https://www.openstreetmap.org/way/7"}, replace="all"))
    assert "OpenStreetMap" in (tmp_path / "job/model/credits.txt").read_text()  # one part is traced from the map
    assert any("a door" in note for note in refs["modeling_additions"])
    fact = {**_pack(BLOCK, replace="all"), "axis_note": {"value": 4, "unit": "degrees", "source": "https://www.openstreetmap.org/way/7"}}
    build(fact)  # a fact about which way it faces draws nothing
    assert "ODbL" not in (tmp_path / "job/model/credits.txt").read_text()
    build(_pack(BLOCK, replace="all", plinth={"rect": [40, 60], "source": "https://www.openstreetmap.org/way/7"}))
    assert "ODbL" in (tmp_path / "job/model/credits.txt").read_text()  # its base is traced from the map


def test_an_opening_lets_light_through_and_cuts_the_maps_walls(build):
    hole = {"kind": "opening", "width": 4, "depth": 12, "from": 0, "to": 6}
    tower = {**BLOCK, "rect": [2, 2], "to": 20}
    whole, _, scale, _ = build(_pack(tower), [(1, 10)])
    man, _, scale, _ = build(_pack(tower, hole), [(1, 10)])
    assert whole.volume() - man.volume() == pytest.approx(4 * 10 * 6 * scale ** 3, rel=.02)
    arched, _, _, _ = build(_pack(tower, {**hole, "arch": True}), [(1, 10)])
    assert whole.volume() - arched.volume() == pytest.approx((4 * 4 + math.pi * 2) * 10 * scale ** 3, rel=.03)


@pytest.mark.parametrize("more, area", [
    ({}, 4 * 8),
    ({"arch": True}, 4 * 6 + math.pi * 2 ** 2 / 2),
    ({"arch": "round", "arch_rise": 1}, 4 * 7 + math.pi * 2 * 1 / 2),
    ({"arch": "pointed"}, 4 * (8 - 12 ** .5) + 16 * (math.pi / 3 - 3 ** .5 / 4)),
    ({"arch": "pointed", "arch_rise": 5}, 4 * 3 + 7.25 ** 2 * math.atan2(5, 5.25) - 5.25 * 5),
    ({"arch": "triangle", "arch_rise": 3}, 4 * 5 + 4 * 3 / 2),
])
def test_an_opening_has_the_head_it_asks_for(more, area):
    hole, width, *_ = landmark_parts.read(
        _pack(BLOCK, {"kind": "opening", "width": 4, "depth": 1, "from": 1, "to": 9, **more}), REFS)[2][0]
    solid = hole(1.)
    assert width == 4 and solid.volume() == pytest.approx(area, rel=.01)
    assert np.array(solid.bounding_box()) == pytest.approx(np.array([-2, -.5, 3, 2, .5, 11]), abs=.02)


def test_an_outline_cuts_its_own_shape_and_is_omitted_when_too_narrow_to_print():
    slot = {"kind": "opening", "outline": [[0, 0], [1, 0], [9, 8], [8, 8]], "depth": 1}
    records, _, openings = landmark_parts.read(_pack(BLOCK, slot), REFS)
    hole, width, *_ = openings[0]
    assert hole(1.).volume() == pytest.approx(8, rel=.01) and width == pytest.approx(.5 ** .5, rel=.02)
    wall, notes = m3.Manifold.cube([40, 1, 40]).translate([-20, -.5, -5]), []
    assert landmark_parts.cut(wall, openings, 1., notes).volume() == pytest.approx(1600 - 8, rel=1e-3) and not notes
    assert landmark_parts.cut(wall, openings, .5, notes).volume() == pytest.approx(1600) and "Omitted" in notes[0]


def test_an_opening_in_a_widened_wall_lets_light_through_and_a_recess_stays_shallow(build):
    """A bridge tower's portal, deeper than its 10 m wall and not than the wall as printed, was a sealed pocket."""
    tower = {"kind": "prism", "rect": [200, 10], "to": 227}
    deck = {"kind": "prism", "rect": [30, 2737], "to": 8}
    portal = {"kind": "opening", "width": 100, "depth": 12, "from": 100, "to": 180}
    man, _, scale, _ = build(_pack(tower, deck, portal, replace="all"))
    man = man.trim_by_plane([0, 0, 1], 2 + 110 * scale).trim_by_plane([0, 0, -1], -(2 + 170 * scale))
    assert len(man.decompose()) == 2
    block = {"kind": "prism", "rect": [60, 60], "to": 60}
    recess = {"kind": "opening", "at": [0, -30], "width": 20, "depth": .5, "from": 20, "to": 40}
    whole, _, scale, _ = build(_pack(block, replace="all"))
    man, _, _, _ = build(_pack(block, recess, replace="all"))
    assert whole.volume() - man.volume() == pytest.approx(20 * 20 * .25 * scale ** 3, rel=.1)


def test_a_pack_stands_in_for_a_map_with_no_outline_or_no_heights(build):
    _, refs, _, _ = build(_pack({**BLOCK, "rect": [10, 10]}, replace=[1]), [(1, 10)])
    assert [p["id"] for p in refs["parts"]] == ["part-0"]
    _, refs, _, _ = build(_pack(BLOCK, replace=[1]), [(1, 10)], outline=[])
    assert [p["id"] for p in refs["parts"]] == ["part-0"]


def test_a_lean_tips_all_above_a_level_base(build):
    tower = {"kind": "prism", "circle": 5, "to": 40}
    straight, _, scale, _ = build(_pack(tower, replace="all"))
    man, _, _, _ = build({**_pack(tower, replace="all"), "lean": {"source": SOURCE, "value": [4, 180]}})
    top = man.slice(2 + 39 * scale).bounds()
    assert (top[1] + top[3]) / 2 == pytest.approx(-39 * scale * math.tan(math.radians(4)), abs=.2)
    assert (top[0] + top[2]) / 2 == pytest.approx(0, abs=.1)
    assert man.slice(1.).bounds()[1] <= straight.slice(1.).bounds()[1] + .05


@pytest.mark.parametrize("value", [[0, 180], [16, 180], [4], "south"])
def test_a_bad_lean_is_refused(value, build):
    with pytest.raises(landmark_refs.LandmarkProblem, match="lean"):
        build({**_pack(BLOCK, replace="all"), "lean": {"source": SOURCE, "value": value}})


def test_a_beam_tapers_along_its_path_and_may_be_round():
    path = [[0, 0, 0], [0, 0, 10]]
    taper = _solid({"kind": "beam", "path": path, "size": [[4, 4], [2, 2]]})
    assert taper.volume() == pytest.approx(10 * (16 + 8 + 4) / 3, rel=.01)
    post = _solid({"kind": "beam", "path": path, "size": [2, 2], "round": True})
    assert post.volume() == pytest.approx(math.pi * 10, rel=.03)


def test_a_beam_whose_thin_end_is_widened_says_so():
    beam = {"kind": "beam", "path": [[0, 0, 0], [0, 0, 10]], "size": [[4, 4], [.2, .2]]}
    short = {"kind": "beam", "path": [[0, 0, 0], [0, 0, 100], [0, 0, 102]], "size": [[10, 10], [10, 10], [.5, .5]]}
    for part, widened in ((beam, True), (short, True), ({**beam, "size": [[4, 4], [2, 2]]}, False)):
        record = landmark_parts.read(_pack(part), REFS)[0][0]
        record["_build"](1., [])
        assert ("print_modifications" in record) is widened


def test_a_slender_part_may_ask_for_a_finer_minimum():
    part = {"kind": "beam", "path": [[0, 0, 5], [0, 20, 5]], "size": [.1, .1], "least": .8}
    box = _solid(part, scale=1.).bounding_box()
    assert box[3] - box[0] == pytest.approx(.8, abs=.02)


@pytest.mark.parametrize("part, says", [
    ({**BLOCK, "least": .5}, "least must be 0.8 to 1.2 mm"),
    ({"kind": "prism", "rect": [9, 9], "to": 9, "roof": "dome", "roof_rise": 3, "least": .8}, "a roof keeps"),
    ({"kind": "opening", "width": 4, "depth": 9, "from": 0, "to": 5, "least": .8}, "has no field least"),
    ({"kind": "beam", "path": [[0, 0, 0], [0, 0, 5], [0, 0, 9]], "size": [[1, 1], [2, 2]]}, "one for each point"),
    ({"kind": "beam", "path": [[0, 0, 0], [0, 0, 5]], "size": [1, 1], "round": 1}, "round must be"),
])
def test_a_bad_finer_part_is_refused(part, says):
    with pytest.raises(landmark_refs.LandmarkProblem, match=r"parts\[0\].*" + says):
        landmark_parts.read(_pack(part), REFS)


def test_a_plinth_stands_where_the_pack_puts_it():
    base = landmark_parts.plinth(_pack(BLOCK, axis=90, plinth={"rect": [40, 60], "at": [0, 10]}), REFS)
    assert base.bounds() == pytest.approx((-20, -20, 40, 20), abs=.02)
    assert landmark_parts.plinth(_pack(BLOCK), REFS) is None
    for bad in ({}, {"rect": [4, 0]}, {"rect": [4, 4], "to": 3}, 5):
        with pytest.raises(landmark_refs.LandmarkProblem, match="Reference plinth"):
            landmark_parts.plinth(_pack(BLOCK, plinth=bad), REFS)


def test_a_build_stands_on_the_packs_plinth_and_keeps_a_foot_past_it(build):
    man, _, scale, _ = build(_pack(BLOCK, replace="all", plinth={"rect": [40, 60]}))
    x0, y0, x1, y1 = man.slice(1.).bounds()
    assert (x1 - x0, y1 - y0) == pytest.approx((40 * scale, 60 * scale), abs=.05) and scale == pytest.approx(100 / 60, rel=.01)
    man, _, scale, _ = build(_pack(BLOCK, {**BLOCK, "at": [0, 50]}, replace="all", plinth={"rect": [40, 60]}))
    assert man.slice(1.).bounds()[3] == pytest.approx(53 * scale, abs=1) and len(man.decompose()) == 1


def test_a_low_part_past_the_plinth_joins_the_base(build):
    quay = {"kind": "prism", "rect": [10, 6], "at": [0, 40], "from": -3, "to": 0}
    man, *_ = build(_pack({**BLOCK, "to": 30}, quay, replace="all", plinth={"rect": [40, 60]}))
    assert len(man.decompose()) == 1


def test_the_plinth_replaces_a_sites_ground(build):
    man, _, scale, _ = build(_pack(BLOCK, plinth={"rect": [40, 60]}), parts=[(1, 20)],
                             site=[[[-90, -90], [90, -90], [90, 90], [-90, 90]]])
    x0, y0, x1, y1 = man.slice(1.).bounds()
    assert (x1 - x0, y1 - y0) == pytest.approx((40 * scale, 60 * scale), abs=.1)


def test_a_plinths_guess_is_noted_and_its_source_kept(build):
    asked = {"rect": [40, 60], "guess": "wide enough for the lawn", "source": "https://example.org/lawn"}
    _, refs, *_ = build(_pack(BLOCK, replace="all", plinth=asked))
    assert "Guessed the base's outline: wide enough for the lawn." in refs["modeling_additions"]
    assert "https://example.org/lawn" in json.dumps(refs)
    with pytest.raises(landmark_refs.LandmarkProblem, match="Reference plinth: guess"):
        landmark_parts.plinth(_pack(BLOCK, plinth={"rect": [4, 4], "guess": ""}), REFS)


def test_an_opening_another_part_covers_is_left_out_and_not_sealed_in():
    wall = m3.Manifold.cube([20, 20, 20]).translate([-10, -10, 0])
    window = {"kind": "opening", "id": "lancet", "width": 2, "depth": 2, "from": 8, "to": 11}
    shaft = {"kind": "opening", "at": [0, -5.5], "width": 1, "depth": 12, "from": 9, "to": 10}
    inner = {"kind": "opening", "at": [0, 1.7], "width": 2, "depth": 2, "from": 8, "to": 11}
    for parts, sealed in (([window], True), ([window, shaft], False), ([inner, window, shaft], False)):
        notes = []
        out = landmark_parts.cut(wall, landmark_parts.read(_pack(BLOCK, *parts), REFS)[2], 1., notes)
        assert len(out.decompose()) == 1 and out.genus() == 0
        assert [n for n in notes if "covers" in n] == ["Left out openings that another part covers: lancet."] * sealed
        assert (out.volume() == pytest.approx(8000)) == sealed


def test_each_covered_opening_is_named_in_one_note():
    pair = {"kind": "opening", "id": "lancet", "width": 2, "depth": 2, "from": 8, "to": 11, "at": [4, 0], "copies": {"mirror": "x"}}
    plain = {"kind": "opening", "width": 2, "depth": 2, "from": 14, "to": 17}
    wall, notes = m3.Manifold.cube([20, 20, 20]).translate([-10, -10, 0]), []
    landmark_parts.cut(wall, landmark_parts.read(_pack(BLOCK, pair, plain), REFS)[2], 1., notes)
    assert notes == ["Left out openings that another part covers: lancet-1, lancet-2, part-2."]


def test_a_lattice_tower_refuses_a_plinth(build, monkeypatch):
    facts = ("deck_widths_m", "deck_heights_m", "foot_width_m", "arch_height_m", "historic_top_m")
    monkeypatch.setattr("smoothstone.landmark_style.style_keys", lambda styles: {"steel"})
    pack = {**_pack(BLOCK, plinth={"rect": [40, 60]}), **{f: {"source": SOURCE, "value": 5} for f in facts}}
    with pytest.raises(landmark_refs.LandmarkProblem, match="Leave plinth out"):
        build(pack, parts=[(1, 20)])


SHIPPED = sorted(p for p in Path(landmark_refs.__file__).with_name("landmarks").glob("*.json") if "parts" in json.loads(p.read_text()))


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.stem)
def test_a_shipped_pack_s_parts_make_one_body_at_a_small_print(path):
    pack = json.loads(path.read_text())
    lat, lon = pack["parts"]["origin"]
    refs = {"latitude": lat, "longitude": lon}
    records, _, openings = landmark_parts.read(pack, refs)
    ground = landmark_parts.plinth(pack, refs)
    tall = max(r["height"]["metres"] for r in records)
    wide = max(abs(v) for r in records for ring in r["footprint"] for point in ring for v in point)
    scale = 150 / max(tall, 2 * wide)
    solid = m3.Manifold.batch_boolean([s for r in records for s in r["_build"](scale, [])], m3.OpType.Add).translate([0, 0, 2])
    base = (solid.project() if ground is None else ground.scale([scale, scale])).extrude(2.02)  # as generate() stacks them
    notes = []
    whole = landmark_parts.cut(solid + base, openings, scale, notes)
    assert sum(d.volume() > 1e-3 for d in whole.decompose()) == 1  # less is a sliver of the join
    assert not [n for n in notes if "covers" in n]
    if any("Omitted" in n for n in notes):  # too narrow to cut here: cut at a print that holds every opening
        scale = 1.01 * landmark_parts.CUT / min(width for _, width, *_ in openings)
        solid = m3.Manifold.batch_boolean([s for r in records for s in r["_build"](scale, [])], m3.OpType.Add).translate([0, 0, 2])
        base = (solid.project() if ground is None else ground.scale([scale, scale])).extrude(2.02)
        notes = []
        landmark_parts.cut(solid + base, openings, scale, notes)
        assert not [n for n in notes if "covers" in n or "Omitted" in n]
    assert all(r["source"].startswith("http") for r in records)


def test_each_opera_house_sail_stands_on_the_deck():
    """Each half sail once fanned from one point 2 m under its lowest row: the sides of it printed in mid air."""
    path = Path(landmark_refs.__file__).with_name("landmarks") / "sydney-opera-house.json"
    pack = json.loads(path.read_text())
    lat, lon = pack["parts"]["origin"]
    sails = [r for r in landmark_parts.read(pack, {"latitude": lat, "longitude": lon})[0] if "-skin-" in r["id"]]
    assert len(sails) == 100
    for r in sails:
        solid = m3.Manifold.batch_boolean(r["_build"](1.04, []), m3.OpType.Add)
        foot, wall = solid.slice(12.2 * 1.04), solid.slice(14 * 1.04)
        assert (foot ^ wall).area() > .9 * wall.area() > 0, r["id"]
