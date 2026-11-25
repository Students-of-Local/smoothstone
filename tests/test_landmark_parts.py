"""Reference parts: the cases in docs/REFERENCE_PARTS.md."""

import json
import math

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


def test_a_taper_is_half_at_the_top_and_a_cone_has_a_cones_volume():
    assert _solid({**BLOCK, "top_scale": .5}).volume() == pytest.approx(10 * (24 + 6 + 12) / 3, rel=.01)
    cone = _solid({"kind": "lathe", "profile": [[0, 5], [10, 0]]}, scale=100)
    assert cone.volume() == pytest.approx(math.pi * 25 * 10 / 3, rel=.02)


def test_a_tapered_roof_sits_on_the_narrowed_top():
    solid = _solid({**BLOCK, "to": 12, "top_scale": .5, "roof": "pyramidal", "roof_rise": 2})
    assert solid.volume() == pytest.approx(10 * (24 + 6 + 12) / 3 + 2 * 6 / 3, rel=.03)
    assert solid.bounding_box()[5] == pytest.approx(12, abs=.02)


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
    assert box[3] - box[0] == pytest.approx(1.2, abs=.02)


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
    ({**BLOCK, "roof": "dome"}, "needs roof_rise"),
    ({**BLOCK, "roof_rise": 2}, "needs roof_rise"),
    ({**BLOCK, "roof": "tent", "roof_rise": 2}, "roof must be"),
    ({**BLOCK, "roof": "dome", "roof_rise": 11}, "roof_rise must be"),
    ({**BLOCK, "top_scale": 0}, "more than 0"),
    ({"kind": "lathe", "profile": [[5, 1], [0, 1]]}, "must rise"),
    ({"kind": "lathe", "profile": [[0, 0], [5, 0]]}, "radius above 0"),
    ({"kind": "lathe"}, "profile must list"),
    ({"kind": "beam", "path": [[0, 0, 0], [0, 0, 0]], "size": [1, 1]}, "repeats a point"),
    ({"kind": "beam", "path": [[0, 0, 0], [0, 0, 1]], "size": [0, 1]}, "more than 0"),
    ({"kind": "opening", "width": 4, "depth": 4, "from": 0, "to": 1, "arch": True}, "half its width"),
    ({**BLOCK, "copies": {"around": [0, 0], "count": 401}}, "1 to 400"),
    ({**BLOCK, "copies": {"mirror": "z"}}, "mirror must be"),
    ({**BLOCK, "copies": 4}, "must be an object"),
    ({**BLOCK, "guess": ""}, "guess must say"),
    ({**BLOCK, "source": "a book"}, "must be a URL"),
    ({**BLOCK, "at": [1]}, "at must be"),
])
def test_a_bad_part_is_refused_by_its_place(part, why):
    with pytest.raises(landmark_refs.LandmarkProblem, match=why) as stop:
        landmark_parts.read(_pack(BLOCK, part), REFS)
    assert "parts[1]" in str(stop.value)


@pytest.mark.parametrize("more", [{"origin": None}, {"origin": [0]}, {"axis": "north"}, {"replace": "some"}, {"value": []}, {"scale": 2}])
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

    def go(pack, parts=()):
        monkeypatch.setattr(landmark_refs, "resolve", lambda name, root: {
            **REFS, "label": "Example", "id": "Q1", "height": None, "style": [], "source": SOURCE, "sources": {}})
        ring = [[[-5, -5], [5, -5], [5, 5], [-5, 5]]]

        def fetch(refs, root):
            asked.append(1)
            return {"outline": ring, "source": SOURCE, "tags": {}, "linked_towers": [], "parts": [
                {"id": i, "type": "way", "footprint": ring if i == 1 else [[[6, -5], [16, -5], [16, 5], [6, 5]]],
                 "tags": {"height": str(h)}, "source": SOURCE} for i, h in parts]}
        monkeypatch.setattr(landmark_refs, "fetch", fetch)
        path = tmp_path / "pack.json"
        path.write_text(json.dumps(pack))
        info = landmark.generate("Example", tmp_path / "job", [200, 200, 200], 100, "low", ref_pack=path)
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


def test_an_opening_lets_light_through_and_cuts_the_maps_walls(build):
    hole = {"kind": "opening", "width": 4, "depth": 12, "from": 0, "to": 6}
    tower = {**BLOCK, "rect": [2, 2], "to": 20}
    whole, _, scale, _ = build(_pack(tower), [(1, 10)])
    man, _, scale, _ = build(_pack(tower, hole), [(1, 10)])
    assert whole.volume() - man.volume() == pytest.approx(4 * 10 * 6 * scale ** 3, rel=.02)
    arched, _, _, _ = build(_pack(tower, {**hole, "arch": True}), [(1, 10)])
    assert whole.volume() - arched.volume() == pytest.approx((4 * 4 + math.pi * 2) * 10 * scale ** 3, rel=.03)


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
