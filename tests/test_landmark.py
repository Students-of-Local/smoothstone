"""Reference-backed landmark builds, exercised without network access."""

import copy
import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from smoothstone import landmark_refs, modelprint


FIXTURES = Path(__file__).parent / "fixtures" / "landmark"
CASES = {
    "Cologne Cathedral": ("cologne", "Q4176", "Roman Catholic cathedral"),
    "Taj Mahal": ("taj", "Q9141", "marble mausoleum"),
}


@pytest.fixture
def recorded(monkeypatch, tmp_path):
    """Replay recorded Wikidata and OSM responses through the real parsers."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    def use(name):
        slug, entity_id, description = CASES[name]
        entities = json.loads((FIXTURES / f"{slug}_wikidata.json").read_text())["entities"]
        osm = json.loads((FIXTURES / f"{slug}_overpass.json").read_text())

        def wiki(params):
            if params["action"] == "wbsearchentities":
                return {"search": [{"id": entity_id, "label": name, "description": description}]}
            if params.get("props") == "labels":
                return {"entities": {}}
            return {"entities": entities}

        monkeypatch.setattr(landmark_refs, "_wiki", wiki)
        monkeypatch.setattr(landmark_refs, "_request", lambda *args, **kwargs: {})
        monkeypatch.setattr(landmark_refs, "fetch", lambda refs, root: landmark_refs.parse_osm(osm, refs))
        return osm

    return use


@pytest.mark.parametrize("name", CASES)
def test_real_reference_parsers_find_the_building_and_its_parts(name, recorded, tmp_path):
    recorded(name)
    refs = landmark_refs.resolve(name, tmp_path)
    osm = landmark_refs.fetch(refs, tmp_path)
    assert refs["id"] == CASES[name][1]
    assert refs["sources"]["latitude"].startswith("https://www.wikidata.org/")
    assert refs["sources"]["height"].startswith("https://www.wikidata.org/")
    assert len(osm["outline"][0]) >= 3
    assert len(osm["parts"]) >= 5
    assert all(part["source"].startswith("https://www.openstreetmap.org/") for part in osm["parts"])


def test_reference_pack_layers_custom_facts_over_the_resolved_name(tmp_path):
    private = tmp_path / "extra.json"
    custom = {"west_portals": {"value": 4, "source": "https://example.com/survey"}}
    private.write_text(json.dumps(custom))
    facts = landmark_refs.load_pack("Kölner Dom", private, label="Cologne Cathedral")
    assert facts["west_portals"] == custom["west_portals"]
    assert facts["spire_tracery"]["value"] is True
    private.write_text('{"west_portals": {"value": 4}}')
    with pytest.raises(landmark_refs.LandmarkProblem, match="source URL"):
        landmark_refs.load_pack("Kölner Dom", private, label="Cologne Cathedral")


def test_tower_outline_with_negative_building_part_tag_is_a_reference():
    full = {"type": "way", "id": 1, "tags": {"building": "tower", "building:part": "no"},
            "geometry": [{"lat": y, "lon": x}
                         for x, y in [(-1, -1), (1, -1), (1, 1), (-1, 1), (-1, -1)]]}
    part = {**full, "id": 2, "tags": {"building:part": "yes"}}
    ref = {"latitude": 0, "longitude": 0, "osm_way": 1}
    parsed = landmark_refs.parse_osm({"elements": [full, part]}, ref)
    assert parsed["source"] == "https://www.openstreetmap.org/way/1"
    assert [p["id"] for p in parsed["parts"]] == [2]


def test_exact_landmark_outranks_a_nearby_structural_search_result(tmp_path, monkeypatch):
    requested = {"id": "Q1", "label": "Example Opera House", "description": "performing arts venue"}
    neighbour = {"id": "Q2", "label": "Example Car Park", "description": "building next to the opera house"}
    coordinates = {"claims": {"P625": [{"mainsnak": {"datavalue": {
        "value": {"latitude": 1., "longitude": 2.},
    }}}]}}

    def wiki(params):
        if params["action"] == "wbsearchentities":
            return {"search": [neighbour, requested]}
        return {"entities": {item["id"]: coordinates for item in (neighbour, requested)}}

    monkeypatch.setattr(landmark_refs.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(landmark_refs, "_wiki", wiki)
    assert landmark_refs.resolve(requested["label"], tmp_path)["id"] == requested["id"]


@pytest.mark.parametrize("description", [
    "district of a city", "human settlement in Tower Hamlets, England", "locality in a state", "mountain in the Alps",
    "unincorporated community near Church Hill", "railway stop", ""])
def test_an_exact_place_name_does_not_outrank_the_building(tmp_path, monkeypatch, description):
    place = {"id": "Q1", "label": "St Example's", "description": description}
    building = {"id": "Q2", "label": "St Example's Cathedral", "description": "cathedral in the city of Example"}
    coordinates = {"claims": {"P625": [{"mainsnak": {"datavalue": {"value": {"latitude": 1., "longitude": 2.}}}}]}}

    def wiki(params):
        if params["action"] == "wbsearchentities":
            return {"search": [place, building]}
        return {"entities": {item["id"]: coordinates for item in (place, building)}}

    monkeypatch.setattr(landmark_refs.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(landmark_refs, "_wiki", wiki)
    assert landmark_refs.resolve(place["label"], tmp_path)["id"] == building["id"]
    assert landmark_refs.resolve(building["label"], tmp_path / "again")["id"] == building["id"]


def test_an_exact_name_with_a_building_style_outranks_a_longer_name(tmp_path, monkeypatch):
    ruin = {"id": "Q1", "label": "The Example", "description": "ancient Roman ruin in Example"}
    church = {"id": "Q2", "label": "Church by The Example", "description": "church in Example"}
    claims = {"P625": [{"mainsnak": {"datavalue": {"value": {"latitude": 1., "longitude": 2.}}}}]}
    style = {"P149": [{"mainsnak": {"datavalue": {"value": {"id": "Q9"}}}}]}

    def wiki(params):
        if params["action"] == "wbsearchentities":
            return {"search": [church, ruin]}
        return {"entities": {"Q1": {"claims": {**claims, **style}}, "Q2": {"claims": claims}, "Q9": {}}}

    monkeypatch.setattr(landmark_refs.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(landmark_refs, "_wiki", wiki)
    assert landmark_refs.resolve(ruin["label"], tmp_path)["id"] == "Q1"


def test_separate_bell_tower_requires_a_wikidata_component_link():
    def building(identifier, x, tags):
        points = [(x-1, -1), (x+1, -1), (x+1, 1), (x-1, 1), (x-1, -1)]
        return {"type": "way", "id": identifier, "tags": {"building": "yes", **tags},
                "geometry": [{"lat": y, "lon": x} for x, y in points]}

    body = building(1, 0, {"wikidata": "Q1"})
    bell = building(2, 3, {"wikidata": "Q2", "tower:type": "bell_tower", "height": "80"})
    nearby = building(3, -3, {"wikidata": "Q3", "tower:type": "bell_tower", "height": "70"})
    components = [{"mainsnak": {"datavalue": {"value": {"id": "Q2"}}}}]
    refs = {"latitude": 0, "longitude": 0, "id": "Q1", "wikidata_raw": {"claims": {"P527": components}}}
    data = landmark_refs.parse_osm({"elements": [body, bell, nearby]}, refs)
    assert [part["id"] for part in data["linked_towers"]] == [2]
    assert data["parts"] == []


@pytest.mark.parametrize("shape", ["flat", "gabled", "pyramidal", "skillion", "hipped", "dome",
                                  "onion", "half-hipped", "round", "gambrel", "mansard"])
def test_roof_shapes_form_closed_solids_at_the_given_height(shape):
    import manifold3d as m3
    from smoothstone import landmark

    footprint = m3.CrossSection.square([20, 10], True)
    roof = landmark._roof(footprint, {"roof_shape": shape, "tags": {}}, 10, 8, [])
    mesh = modelprint.to_trimesh(roof)
    assert mesh.is_watertight
    assert mesh.volume > 0
    assert mesh.bounds[1, 2] == pytest.approx(18, abs=.03)


def test_roof_profiles_change_cross_sections():
    import manifold3d as m3
    from smoothstone import landmark

    footprint = m3.CrossSection.square([20, 10], True)
    roofs = {shape: landmark._roof(footprint, {"roof_shape": shape, "tags": {}}, 0, 8, [])
             for shape in ("flat", "gabled", "hipped", "pyramidal", "dome")}
    near_top = {shape: roof.slice(7.5).area() for shape, roof in roofs.items()}
    assert near_top["flat"] == pytest.approx(200, rel=.01)
    assert 0 < near_top["pyramidal"] < near_top["gabled"] < near_top["flat"]
    assert 0 < near_top["hipped"] < near_top["gabled"]
    assert 0 < near_top["dome"] < near_top["flat"]


def test_cologne_geometry_keeps_proportions_spires_and_print_checks(recorded, tmp_path):
    from smoothstone import landmark

    recorded("Cologne Cathedral")
    result = landmark.generate("Cologne Cathedral", tmp_path, (220, 220, 220), 200, "low")
    mesh = trimesh.load(result["stl"], force="mesh", process=True)
    assert mesh.is_watertight
    assert mesh.body_count == 1
    assert max(mesh.extents) == pytest.approx(200, abs=1)
    _, footprint = trimesh.bounds.oriented_bounds_2D(mesh.vertices[:, :2])
    assert mesh.extents[2] / max(footprint) == pytest.approx(157 / 144, rel=0.03)

    # Two spatially distinct towers must remain in the mesh near the top.
    man = modelprint.to_manifold(mesh)
    at_top = man.slice(float(mesh.bounds[0, 2] + mesh.extents[2] * 0.85))
    assert len([piece for piece in at_top.decompose() if piece.area() >= 1.0]) == 2
    crowns = man.slice(float(mesh.bounds[0, 2] + mesh.extents[2] * 0.97))
    crowns = [piece for piece in crowns.decompose() if piece.area() >= 1.0]
    assert len(crowns) == 2
    for crown in crowns:
        x0, y0, x1, y1 = crown.bounds()
        assert max(x1 - x0, y1 - y0) <= 6.0
    checks = modelprint.found_checks(result["stl"], (220, 220, 220), 1)["checks"]
    assert all(check["ok"] for check in checks), [check for check in checks if not check["ok"]]


def test_missing_height_from_levels_is_sourced_and_marked_as_guessed(recorded, tmp_path, monkeypatch):
    from smoothstone import landmark

    recorded("Cologne Cathedral")
    real_fetch = landmark_refs.fetch
    changed = {}

    def with_missing_height(refs, root):
        data = copy.deepcopy(real_fetch(refs, root))
        part = copy.deepcopy(next(p for p in data["parts"] if not p["tags"].get("min_height")))
        part["id"] = 999999999999
        changed["id"] = part["id"]
        part["tags"].pop("height", None)
        part["tags"]["building:levels"] = "3"
        data["parts"].append(part)
        return data

    monkeypatch.setattr(landmark_refs, "fetch", with_missing_height)
    landmark.generate("Cologne Cathedral", tmp_path, (220, 220, 220), 200, "low")
    refs = json.loads((tmp_path / "refs" / "landmark.json").read_text())
    guess = next(part["height"] for part in refs["parts"] if part["id"] == changed["id"])
    assert guess["metres"] == pytest.approx(12)
    assert guess["guessed"] is True
    assert guess["source"].startswith("https://www.openstreetmap.org/")


def test_no_parts_returns_models_fallback(recorded, jobenv, monkeypatch):
    from smoothstone import cli

    recorded("Cologne Cathedral")
    monkeypatch.setattr(landmark_refs, "fetch", lambda refs, root: {"outline": [], "parts": [], "source": ""})
    text, code = cli.run(["landmark", "Cologne Cathedral"])
    assert "FIX" in text
    assert text.splitlines()[-1] == "NEXT: stone models 'Cologne Cathedral'"
    assert not list((jobenv / "stone-job").rglob("*.stl"))


@pytest.mark.parametrize("unit, amount, metres", [
    ("Q11573", "+157", 157.0),        # metre
    ("Q3710", "+515", 156.972),       # foot
    ("Q218593", "+6180", 156.972),    # inch
    ("Q174789", "+157000", 157.0),    # millimetre
    ("Q174728", "+15700", 157.0),     # centimetre
    ("Q99999999", "+157", None),      # a unit we do not know is dropped, not read as metres
])
def test_wikidata_lengths_convert_to_metres(unit, amount, metres):
    value = {"amount": amount, "unit": f"http://www.wikidata.org/entity/{unit}"}
    got = landmark_refs._quantity(value)
    assert got == (None if metres is None else pytest.approx(metres, rel=1e-6))


def test_an_unexpected_build_error_gives_fix_and_next(recorded, jobenv, monkeypatch):
    from smoothstone import cli, landmark

    def broken(*a, **k):
        raise ValueError("need at least one array to concatenate")

    monkeypatch.setattr(landmark, "generate", broken)
    text, code = cli.run(["landmark", "Cologne Cathedral"])
    assert "FIX" in text and "ValueError" in text
    assert text.splitlines()[-1] == "NEXT: stone models 'Cologne Cathedral'"


def test_supplied_facts_do_not_switch_off_the_inferred_massing(recorded, tmp_path, monkeypatch):
    from smoothstone import landmark, landmark_massing

    class Reached(Exception):
        pass

    def infer(*args):
        raise Reached

    recorded("Cologne Cathedral")
    facts = {"expected_height_m": {"value": 157, "source": "https://example.com/survey"}}
    monkeypatch.setattr(landmark_refs, "load_pack", lambda name, path=None, *, label=None: facts if path else {})
    monkeypatch.setattr(landmark_massing, "infer_massing", infer)
    with pytest.raises(Reached):
        landmark.generate("Cologne Cathedral", tmp_path, (220, 220, 220), 200, "low", ref_pack="facts.json")


@pytest.mark.parametrize("direction, down", [("90", (1, 0)), ("ENE", (.92, .38)), ("SSW", (-.38, -.92)), ("n", (0, 1))])
def test_a_shed_roof_descends_the_way_the_map_says(direction, down):
    # the 202 directed skillion parts in five landmarks' maps agree with OSM's sense; a roof built from one was
    # high at the wrong side, and ENE and its kind were not read at all
    import manifold3d as m3
    from smoothstone import landmark

    roof = landmark._roof(m3.CrossSection.circle(6, 32), {"roof_shape": "skillion", "tags": {"roof:direction": direction}},
                          0, 8, [])
    v = np.array(roof.to_mesh().vert_properties)[:, :3]
    top = v[v[:, 2] > 7]
    assert len(top) and (top[:, :2] @ np.array(down)).max() < 0, direction


def _minaret(x, untagged=False):
    def ring(half):
        return [[[x - half, -half], [x + half, -half], [x + half, half], [x - half, half]]]
    tags = [(2.0, "5", "32"), (2.4, "13", "14"), (2.8, "32", "32.3"), (2.2, "36", "41")]
    out = []
    for k, (half, lo, hi) in enumerate(tags):
        t = {"building:part": "yes", "min_height": lo, "height": hi}
        if untagged and k in (1, 2):
            if k == 1:
                out.append({"id": f"{x}-{k}", "footprint": ring(half), "tags": t})
            t = {"building:part": "yes"}
        out.append({"id": f"{x}-{k}{'u' if untagged else ''}", "footprint": ring(half), "tags": t})
    return out


def test_a_part_with_no_height_takes_its_twins_level_not_the_median():
    # the Taj Mahal's south-west minaret: three parts with no height stood as 40 m columns through its rings and kiosk
    from smoothstone import landmark

    parts = [*_minaret(0), *_minaret(50), *_minaret(100), *_minaret(150, untagged=True)]
    records, _ = landmark.resolve_parts(parts, {"geometry_source": "https://www.openstreetmap.org/way/1"})
    odd = {p["id"]: (p["min_height"]["metres"], p["height"]["metres"], p["height"]["guessed"])
           for p in records if str(p["id"]).startswith("150")}
    assert odd["150-2u"] == (32, 32.3, True)
    assert "150-1u" not in odd  # its ring is already drawn with a height
    assert odd["150-1"] == (13, 14, False)


def test_a_part_with_no_height_and_no_twins_still_stands():
    from smoothstone import landmark

    square = [[[0, 0], [9, 0], [9, 9], [0, 9]]]
    parts = [{"id": 1, "footprint": square, "tags": {"height": "20"}},
             {"id": 2, "footprint": [[[30, 0], [39, 0], [39, 9], [30, 9]]], "tags": {}}]
    records, _ = landmark.resolve_parts(parts, {"geometry_source": "x"})
    assert [p["height"]["metres"] for p in records] == [20, 20]


def test_matched_towers_get_the_same_mapped_detail():
    # Cologne's map draws gables, pinnacles and spire bands on the south tower only
    import manifold3d as m3
    from smoothstone import landmark_architecture as la

    fact = lambda v: {"metres": float(v), "source": "x", "guessed": False}
    def part(i, at, size, lo, hi, feature=None):
        cs = m3.CrossSection.square([size, size], True).translate(at)
        return ({"id": i, "height": fact(hi), "min_height": fact(lo), "roof_height": fact(0), "roof_shape": "flat",
                 "spire": False, "feature": feature, "tags": {"roof:direction": "NNE"}, "source": "x",
                 "footprint": []}, cs)
    parts = [part("s", (0, -17), 18, 70, 157, "west_spire"), part("n", (0, 17), 18, 70, 157, "west_spire"),
             *[part(f"p{k}", (dx, -17 + dy), 1, 0, 110) for k, (dx, dy) in enumerate([(8, 8), (-8, 8), (8, -8), (-8, -8)])],
             part("nave", (40, 0), 20, 0, 60)]
    notes = []
    added = la._twin_detail(parts, [np.array([0., -17]), np.array([0., 17])], 18, 70, notes)
    got = sorted(tuple(np.round(la._dimensions(cs)[0], 1)) for _, cs in added)
    assert got == [(-8.0, 9.0), (-8.0, 25.0), (8.0, 9.0), (8.0, 25.0)]
    assert all(p["height"]["guessed"] and float(p["tags"]["roof:direction"]) == pytest.approx(157.5) for p, _ in added)
    assert all(cs.area() == pytest.approx(1) for _, cs in added) and notes
    both = parts + added
    assert la._twin_detail(both, [np.array([0., -17]), np.array([0., 17])], 18, 70, []) == []
