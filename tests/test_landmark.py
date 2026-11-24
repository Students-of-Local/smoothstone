"""Reference-backed landmark builds, exercised without network access."""

import copy
import json
from pathlib import Path

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
