"""Reference-backed landmark builds, exercised without network access."""

import copy
import http.client
import json
import time
import os
import shlex
import urllib.parse
from pathlib import Path

import numpy as np
import pytest
import trimesh

from smoothstone import landmark_refs, modelprint


FIXTURES = Path(__file__).parent / "fixtures" / "landmark"
IS_STRUCTURE = landmark_refs.is_structure  # conftest keeps the tests off the network
CASES = {
    "Cologne Cathedral": ("cologne", "Q4176", "Roman Catholic cathedral"),
    "Taj Mahal": ("taj", "Q9141", "marble mausoleum"),
}


@pytest.fixture(autouse=True)
def no_wikipedia(monkeypatch):
    monkeypatch.setattr(landmark_refs, "_wikipedia", lambda params: {})


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
    "unincorporated community near Church Hill", "railway stop", "cathedral city in a county",
    "census-designated place in a county", "tidal island off the northeast coast of England",
    "village located in Kent", "railway station"])
@pytest.mark.parametrize("claims", [{}, {"P149": [{"mainsnak": {"datavalue": {"value": {"id": "Q9"}}}}]}])
def test_an_exact_place_name_does_not_outrank_the_building(tmp_path, monkeypatch, description, claims):
    if claims and description.startswith("railway st"):
        pytest.skip("a station with an architectural style is a building")
    place = {"id": "Q1", "label": "St Example's", "description": description}
    building = {"id": "Q2", "label": "St Example's Cathedral", "description": "cathedral in the city of Example"}
    coordinates = {"claims": {"P625": [{"mainsnak": {"datavalue": {"value": {"latitude": 1., "longitude": 2.}}}}]}}

    def wiki(params):
        if params["action"] == "wbsearchentities":
            return {"search": [place, building]}
        return {"entities": {"Q1": {"claims": {**coordinates["claims"], **claims}}, "Q2": coordinates, "Q9": {}}}

    monkeypatch.setattr(landmark_refs.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(landmark_refs, "_wiki", wiki)
    assert landmark_refs.resolve(place["label"], tmp_path)["id"] == building["id"]
    assert landmark_refs.resolve(building["label"], tmp_path / "again")["id"] == building["id"]


@pytest.mark.parametrize("kind", ["fort in Kent", "parish church in Kent", "windmill in Kent", "pumping works in Kent",
                                  "(ruined) castle", "state capitol in Kent", "*railway station in Kent", "*"])
@pytest.mark.parametrize("other", [("Fort Example Museum", "museum in Kent"), ("Fort Example Road", "street near Tower Bridge")])
def test_an_exact_building_of_any_kind_outranks_a_longer_name(tmp_path, monkeypatch, kind, other):
    # A star marks a hit with an architect: a station, and one nobody described.
    architect = {"P84": [{"mainsnak": {"datavalue": {"value": {"id": "Q9"}}}}]} if kind.startswith("*") else {}
    exact = {"id": "Q1", "label": "Fort Example", "description": kind.lstrip("*")}
    longer = {"id": "Q2", "label": other[0], "description": other[1]}
    coordinates = {"claims": {"P625": [{"mainsnak": {"datavalue": {"value": {"latitude": 1., "longitude": 2.}}}}]}}

    def wiki(params):
        if params["action"] == "wbsearchentities":
            return {"search": [longer, exact]}
        return {"entities": {"Q1": {"claims": {**coordinates["claims"], **architect}}, "Q2": coordinates}}

    monkeypatch.setattr(landmark_refs.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(landmark_refs, "_wiki", wiki)
    assert landmark_refs.resolve("Fort Example", tmp_path)["id"] == "Q1"


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


def test_the_better_known_of_two_buildings_with_one_name_comes_first(tmp_path, monkeypatch):
    local = {"id": "Q1", "label": "Example Temple", "description": "building in a town"}
    famous = {"id": "Q2", "label": "Example Temple", "description": "ancient temple in a capital"}
    claims = {"P625": [{"mainsnak": {"datavalue": {"value": {"latitude": 1., "longitude": 2.}}}}]}

    def wiki(params):
        if params["action"] == "wbsearchentities":
            return {"search": [local, famous]}
        sites = {f"{code}wiki": {"title": ""} for code in ("de", "fr", "it")}
        return {"entities": {"Q1": {"claims": claims}, "Q2": {"claims": claims, "sitelinks": sites}}}

    monkeypatch.setattr(landmark_refs.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(landmark_refs, "_wiki", wiki)
    assert landmark_refs.resolve("Example Temple", tmp_path)["id"] == "Q2"


def _claims(words):
    present = [{"mainsnak": {"datavalue": {"value": {"id": "Q839954"}}}}]
    return {"P625": present, "P31": present if "dug" in words else [], **{w: present for w in words if w[0] == "P"}}


@pytest.mark.parametrize("name, wanted, candidates", json.loads((FIXTURES / "names.json").read_text()),
                         ids=lambda value: value if isinstance(value, str) else "")
def test_a_famous_name_gives_the_landmark_a_person_means(name, wanted, candidates):
    """Wikidata's and Wikipedia's answers of 2026-11-24, with each name's nearest rivals, worst first."""
    hits, entities = [], {}
    for identifier, label, description, aliases, links, words in reversed(candidates):
        hits.append({"id": identifier, "label": label, "description": description, "article": "article" in words})
        entities[identifier] = {"aliases": {"en": [{"value": alias} for alias in aliases]},
                                "sitelinks": dict.fromkeys(range(links)), "claims": _claims(words.split())}
    assert landmark_refs._choose(name, hits, entities)[0]["id"] == wanted


def _hit(identifier, label, description, links=0, article=False, aliases=(), **claims):
    point = [{"mainsnak": {"datavalue": {"value": {"latitude": 1., "longitude": 2.}}}}]
    return ({"id": identifier, "label": label, "description": description, "article": article},
            {"claims": {"P625": point, **claims}, "sitelinks": dict.fromkeys(range(links)),
             "aliases": {"en": [{"value": a} for a in aliases]}})


def _chosen(name, *found):
    return landmark_refs._choose(name, [hit for hit, _ in found], {hit["id"]: entity for hit, entity in found})[0]["id"]


@pytest.mark.parametrize("description", ["memorial to the Battle of Example", "monument commemorating the siege",
                                         "church rebuilt after the 1755 earthquake", "abbey in Battle, East Sussex", "siege castle in Germany",
                                         "earthquake memorial museum in Kobe", "fire lookout tower in Kent"])
def test_a_building_that_recalls_an_event_is_still_a_building(description):
    assert _chosen("Example Memorial", _hit("Q1", "Example Memorial", description, 20),
                   _hit("Q2", "Example Memorial Hall", "hall in Kent", 3)) == "Q1"


def test_the_event_itself_is_not():
    assert _chosen("Example", _hit("Q1", "Siege of Example", "1836 major battle in Texas", 50, article=True, aliases=["Example"]),
                   _hit("Q2", "Example Mission", "historic place in Texas", 20, aliases=["Example"])) == "Q2"


def test_a_fire_in_a_cathedral_is_not_the_cathedral():
    assert _chosen("Notre Example", _hit("Q1", "Notre Example fire", "2019 church fire in Paris", 63, article=True),
                   _hit("Q2", "Notre Example de Paris", "cathedral in Paris", 8)) == "Q2"


def test_a_fire_station_is_not_a_fire():
    assert _chosen("Example Works", _hit("Q1", "Example Works", "fire station in Kent", 2)) == "Q1"


def test_wikipedia_is_asked_for_the_items_of_its_pages(monkeypatch):
    asked = []
    monkeypatch.undo()
    monkeypatch.setattr(landmark_refs, "_request", lambda url: asked.append(url) or {"query": {}})
    assert landmark_refs._wikipedia({"titles": "Example", "redirects": 1}) == {"query": {}}
    query = urllib.parse.parse_qs(urllib.parse.urlparse(asked[0]).query)
    assert asked[0].startswith(landmark_refs.WIKIPEDIA + "?")
    assert query == {"action": ["query"], "format": ["json"], "prop": ["pageprops"], "ppprop": ["wikibase_item"],
                     "titles": ["Example"], "redirects": ["1"]}


def test_a_name_may_say_the_place():
    hits = (_hit("Q1", "Example Tower", "tower in Paris, France", 60), _hit("Q2", "Example Tower (Paris, Texas)", "tower in Texas", 9))
    assert _chosen("Example Tower Paris", *hits) == "Q1"
    assert _chosen("Example Tower Paris Texas", *hits) == "Q2"
    with pytest.raises(landmark_refs.LandmarkProblem):
        _chosen("Example Tower Rome", hits[0])


def test_the_start_of_a_name_is_kept_and_loses_to_a_name():
    started, entity = _hit("Q1", "Example Palace", "palace in Kent", 90)
    started = {**started, "match": {"text": "Example Palace"}}
    assert _chosen("Example Pal", (started, entity)) == "Q1"
    assert _chosen("Example Pal", (started, entity), _hit("Q2", "Example Pal", "house in Kent", 2)) == "Q2"


def test_a_page_that_is_only_related_is_no_answer():
    famous = _hit("Q9", "Tower of London", "castle in central London", 140)
    assert _chosen("Example Works", _hit("Q1", "Example Works", ""), famous) == "Q1"
    with pytest.raises(landmark_refs.LandmarkProblem, match="No building with coordinates"):
        _chosen("Example Works", famous)


def test_the_thing_with_the_name_comes_before_the_building_its_name_redirects_to():
    assert _chosen("Tomb of Example", _hit("Q1", "Tomb of Example", "tomb in Seville", 8),
                   _hit("Q2", "Seville Cathedral", "cathedral in Seville", 12, article=True)) == "Q1"


@pytest.mark.parametrize("people, when, winner", [("+82000", None, "Q2"), ("+0", None, "Q1"), (None, None, "Q1"),
                                                  ("+125000", "+0500-00-00T00:00:00Z", "Q1"), ("+900", "-0500-00-00T00:00:00Z", "Q1"),
                                                  ("+82000", "+2017-00-00T00:00:00Z", "Q2")])
def test_a_town_dug_by_archaeologists_is_a_town_while_people_live_there(people, when, winner):
    claims = {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q839954"}}}}]}
    if people:
        claims["P1082"] = [{"mainsnak": {"datavalue": {"value": {"amount": people}}},
                            "qualifiers": {"P585": [{"datavalue": {"value": {"time": when}}}]} if when else {}}]
    assert _chosen("Example", _hit("Q1", "Example", "city in Lebanon", 80, article=True, **claims),
                   _hit("Q2", "Temple of Example", "temple in Example", 15)) == winner


@pytest.mark.parametrize("trouble", [OSError("rate limited"), http.client.IncompleteRead(b""), {"error": {"code": "busy"}}],
                         ids=["refused", "cut off", "error page"])
@pytest.mark.parametrize("down, winner, kept", [((), "Q2", True), (("titles",), "Q3", False), (("generator",), "Q2", False),
                                                (("titles", "generator"), "Q1", False)])
def test_wikipedia_joins_the_search_and_an_answer_without_it_is_not_kept(tmp_path, monkeypatch, down, winner, kept, trouble):
    """The article of that name, then a page the search found, then Wikidata's own hit."""
    point = [{"mainsnak": {"datavalue": {"value": {"latitude": 1., "longitude": 2.}}}}]
    entities = {key: {"claims": {"P625": point}, "sitelinks": dict.fromkeys(range(links)),
                      "labels": {"en": {"value": label}}, "descriptions": {"en": {"value": kind}}}
                for key, label, kind, links in (("Q1", "Little White Example", "house in Kent", 1),
                                                ("Q2", "White Example", "residence of the president", 5),
                                                ("Q3", "White Example Palace", "palace in Kent", 30))}

    def wiki(params):
        if params["action"] == "wbsearchentities":
            return {"search": [{"id": "Q1", "label": "Little White Example", "description": "house in Kent"}]}
        return {"entities": {key: value for key, value in entities.items() if key in params["ids"].split("|")}}

    def wikipedia(params):
        if any(key in params for key in down):
            if isinstance(trouble, dict):
                return trouble
            raise trouble
        item, title = ("Q2", "White Example (Kent)") if "titles" in params else ("Q3", "White Example Palace")
        return {"query": {"pages": {"7": {"title": title, "pageprops": {"wikibase_item": item}}}}}

    monkeypatch.setattr(landmark_refs.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(landmark_refs, "_wiki", wiki)
    monkeypatch.setattr(landmark_refs, "_wikipedia", wikipedia)
    ref = landmark_refs.resolve("white example", tmp_path)
    assert (ref["id"], ref["label"]) == (winner, entities[winner]["labels"]["en"]["value"])
    assert any((tmp_path / "home").rglob("*.json")) == kept
    hits, _, answered = landmark_refs._matches("white example")
    assert {hit["id"]: hit.get("article", False) for hit in hits if hit["id"] == "Q3"} in ({}, {"Q3": False})
    assert answered == kept


@pytest.mark.parametrize("name, label, description, claims, wikis, built", [
    ("Arc de Exemple", "Arc de Exemple", "triumphal arch in Paris", {}, 5, True),
    ("arc de exemple", "Arc de Exemple", "triumphal arch in Paris", {}, 5, True),
    ("Arc de Exemple", "Arc de Exemple", "triumphal arch in Paris", {}, 4, False),  # too little known
    ("Arc de", "Arc de Exemple", "triumphal arch in Paris", {}, 90, False),  # not its name
    ("Exemple", "Exemple", "town in Kent", {}, 90, False),
    ("Exemple", "Exemple", "summit in Nepal", {}, 90, False),  # nothing says it is built
    ("Mount Exemple", "Mount Exemple", "mountain in South Dakota", {}, 40, True),  # a part's word, and a famous place
    ("Mount Exemple", "Mount Exemple", "mountain in South Dakota", {}, 39, False),
    ("Mount Exemple", "Mount", "mountain in South Dakota", {}, 90, False),
    ("Exemple", "Exemple", "summit in Nepal", {"P84": [{"mainsnak": {"datavalue": {"value": {"id": "Q9"}}}}]}, 5, True),
    ("Exemple", "Exemple", "ancient city in Jordan",
     {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q839954"}}}}]}, 5, True),
])
def test_a_name_that_is_a_known_structure(monkeypatch, tmp_path, name, label, description, claims, wikis, built):
    monkeypatch.setattr(landmark_refs.Path, "home", lambda: tmp_path)
    here = {"P625": [{"mainsnak": {"datavalue": {"value": {"latitude": 1, "longitude": 1}}}}]}
    hit = {"id": "Q1", "label": label, "description": description}
    entity = {"labels": {"en": {"value": label}}, "claims": here | claims, "sitelinks": {str(n): {} for n in range(wikis)}}
    monkeypatch.setattr(landmark_refs, "_matches", lambda wanted: ([hit], {"Q1": entity}, True))
    assert IS_STRUCTURE(name) is built


def _entity(wikis, description="triumphal arch in Paris", place=True, **claims):
    at = {"P625": [{"mainsnak": {"datavalue": {"value": {"latitude": 1, "longitude": 1}}}}]} if place else {}
    return {"labels": {"en": {"value": "Exemple"}}, "descriptions": {"en": {"value": description}},
            "claims": at | claims, "sitelinks": {str(n): {} for n in range(wikis)}}


ENDED = {"mainsnak": {"datavalue": {"value": {"time": "+1790-00-00T00:00:00Z"}}}}


@pytest.mark.parametrize("found, answered, built", [
    ([_entity(9)], True, True),
    ([_entity(9)], False, False),  # Wikipedia did not answer
    ([_entity(9), _entity(200, "god of examples", place=False)], True, False),  # the god is meant
    ([_entity(9), _entity(3, "film", place=False)], True, True),
    ([_entity(9, P576=[ENDED])], True, False),  # it no longer stands
    ([_entity(9, P576=[ENDED], P1435=[{}])], True, True),  # a ruin that does
    ([_entity(9, P576=[ENDED], P1435=[{"qualifiers": {"P582": []}}])], True, False),  # and was taken off the list
    ([_entity(9, P576=[ENDED | {"rank": "deprecated"}])], True, True),
    ([_entity(9), _entity(99, "Wikimedia disambiguation page", place=False,
                          P31=[{"mainsnak": {"datavalue": {"value": {"id": "Q4167410"}}}}])], True, True),
    ([_entity(9, "natural limestone arch on a coast")], True, False),
    ([_entity(9, "natural history museum in Chicago")], True, True),
    ([_entity(9, "museum ship in London")], True, False),
])
def test_the_best_known_thing_of_the_name_must_stand(monkeypatch, tmp_path, found, answered, built):
    monkeypatch.setattr(landmark_refs.Path, "home", lambda: tmp_path)
    asked = []
    hits = [{"id": f"Q{i}", "label": "Exemple"} for i in range(len(found))]
    monkeypatch.setattr(landmark_refs, "_matches", lambda name: asked.append(name) or (
        hits, {h["id"]: e for h, e in zip(hits, found)}, answered))
    assert IS_STRUCTURE("Exemple") is built and IS_STRUCTURE("exemple") is built
    assert len(asked) == 1  # a definite answer is kept a week
    old = time.time() - 700
    for path in (tmp_path / ".cache/smoothstone/structure").iterdir():
        os.utime(path, (old, old))
    IS_STRUCTURE("Exemple")
    assert len(asked) == (1 if answered else 2)  # and a weak one ten minutes


def test_a_busy_wikidata_is_not_a_no(monkeypatch, tmp_path):
    monkeypatch.setattr(landmark_refs.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(landmark_refs, "_wikipedia", lambda params: {})
    monkeypatch.setattr(landmark_refs, "_wiki", lambda params: (
        {"search": [{"id": "Q1", "label": "Exemple"}]} if "search" in params else {"error": {"code": "maxlag"}}))
    with pytest.raises(ValueError, match="maxlag"):
        landmark_refs._matches("Exemple")
    assert not IS_STRUCTURE("Exemple")
    assert [p.read_text() for p in (tmp_path / ".cache/smoothstone/structure").iterdir()] == ["null"]


def test_a_statue_on_a_building_is_refused_for_what_wikidata_calls_it():
    refs = {"latitude": 0, "longitude": 0, "wikidata_raw": _entity(9, "colossal sculpture on an island")}
    with pytest.raises(landmark_refs.LandmarkProblem, match="A statue is a sculpture"):
        landmark_refs.parse_osm({"elements": []}, refs)


def test_a_shipped_pack_is_a_known_structure_and_offline_nothing_else_is(monkeypatch):
    def offline(name):
        raise OSError("no network")

    monkeypatch.setattr(landmark_refs, "_matches", offline)
    assert IS_STRUCTURE("Taj Mahal")
    assert not IS_STRUCTURE("Arc de Exemple")


@pytest.mark.parametrize("a, b", [("Sacr\u00e9-C\u0153ur", "Sacre Coeur"), ("Saint Paul's", "St. Pauls"), ("The Alamo", "Alamo")])
def test_one_name_written_two_ways(a, b):
    assert landmark_refs._words(a) == landmark_refs._words(b)


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


def test_the_base_follows_the_plan_and_joins_what_stands_apart(recorded, monkeypatch, tmp_path):
    # Speyer, Lincoln and Buckingham Palace stood on boat-shaped plates, the convex hull of their plans
    from smoothstone import landmark

    recorded("Taj Mahal")
    monkeypatch.setattr(landmark, "SPLIT_SHARE", 0)
    monkeypatch.setattr(landmark, "LEAST_HEIGHT", 0)

    def way(i, ring, tags):
        ring = [*ring, ring[0]]
        return {"type": "way", "id": i, "tags": tags, "geometry": [
            {"lat": 27.175 + y / 111320, "lon": 78.042 + x / 99000} for x, y in ring]}

    def box(x0, y0, x1, y1):
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

    part = {"building:part": "yes", "height": "20"}

    def fetch(refs, root):
        here = {**refs, "latitude": 27.175, "longitude": 78.042, "osm_way": 1, "osm_relation": None}
        return landmark_refs.parse_osm({"elements": [
            way(1, box(-60, -60, 60, 60), {"building": "yes"}),
            way(2, box(-50, -10, 50, 10), part), way(3, box(-10, 10, 10, 50), part),  # a T
            way(4, box(40, 40, 50, 50), part)]}, here)  # a pavilion that stands apart
    monkeypatch.setattr(landmark_refs, "fetch", fetch)
    result = landmark.generate("Taj Mahal", tmp_path, (220, 220, 220), 100, "low")
    mesh = trimesh.load(result["stl"])
    k = result["scale"]
    plan = (100 * 20 + 20 * 40 + 10 * 10) * k * k
    base = modelprint.to_manifold(mesh).slice(1.).area()
    assert plan <= base < plan * 1.05
    assert len(mesh.split()) == 1
    notes = json.loads(Path(result["refs"]).read_text())["modeling_additions"]
    assert any("following the mapped plan" in n for n in notes) and not any("convex" in n for n in notes)


@pytest.mark.parametrize("width, height, widened", [(18, 180, True), (60, 180, False), (40, 60, False)])
def test_a_slender_tower_gets_a_wider_base(width, height, widened):
    # the Washington Monument, 18 by 180 mm, leaned 7 degrees before it tipped and was refused
    import manifold3d as m3
    from smoothstone import landmark, printable

    tower, notes = m3.Manifold.cube([width, width, height]).translate([5, 9, 0]), []
    out = landmark._footing(tower, notes)
    assert bool(notes) == widened
    if not widened:
        assert out.volume() == tower.volume()
    mesh = modelprint.to_trimesh(out)
    assert printable.tip_angle(mesh, printable.occupancy(mesh)) >= printable.TIP_MIN
    assert out.slice(3).area() == pytest.approx(width * width)


def _map(monkeypatch, *boxes, outline=(-60, -60, 60, 60)):
    """The Taj's map, answering with these boxes of building: (x0, y0, x1, y1, height) in metres."""
    def way(i, box, tags):
        x0, y0, x1, y1 = box
        return {"type": "way", "id": i, "tags": tags, "geometry": [
            {"lat": 27.175 + y / 111320, "lon": 78.042 + x / 99000}
            for x, y in [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]]}

    def fetch(refs, root):
        here = {**refs, "latitude": 27.175, "longitude": 78.042, "osm_way": 1, "osm_relation": None}
        return landmark_refs.parse_osm({"elements": [way(1, outline, {"building": "yes"}), *(
            way(i + 2, b[:4], {"building:part": "yes", "height": str(b[4])}) for i, b in enumerate(boxes))]}, here)
    monkeypatch.setattr(landmark_refs, "fetch", fetch)


def test_bodies_that_meet_at_a_corner_get_a_real_join(recorded, monkeypatch, tmp_path):
    from smoothstone import landmark

    recorded("Taj Mahal")
    monkeypatch.setattr(landmark, "LEAST_SHARE", 0)
    monkeypatch.setattr(landmark, "LEAST_HEIGHT", 0)
    _map(monkeypatch, (-50, -50, 0, 0, 20), (0, 0, 50, 50, 20))
    result = landmark.generate("Taj Mahal", tmp_path, (220, 220, 220), 100, "low")
    base = modelprint.to_manifold(trimesh.load(result["stl"])).slice(1.)
    assert len(base.offset(-.2).decompose()) == 1


def test_the_base_is_widened_for_what_the_style_adds_too(recorded, monkeypatch, tmp_path):
    import manifold3d as m3
    from smoothstone import landmark, landmark_style, printable

    recorded("Taj Mahal")
    _map(monkeypatch, (-8, -8, 8, 8, 90), outline=(-8, -8, 8, 8))

    def decorate(man, *args, **kw):  # a heavy head
        box = man.bounding_box()
        head = m3.Manifold.cube([60, 60, 60], True).translate([(box[0] + box[3]) / 2, (box[1] + box[4]) / 2, box[5] + 29])
        return man + head, ["a heavy head"]
    monkeypatch.setattr(landmark_style, "decorate", decorate)
    result = landmark.generate("Taj Mahal", tmp_path, (220, 220, 220), 100, "high", plain=True)
    mesh = trimesh.load(result["stl"])
    assert printable.tip_angle(mesh, printable.occupancy(mesh)) >= printable.TIP_MIN


def test_two_walls_that_meet_along_a_line_are_welded():
    # Westminster Abbey: two buttress corners meet along a 24 mm line, "still 1 non-manifold edges"
    import manifold3d as m3
    from smoothstone import clean, landmark

    base = m3.Manifold.cube([40, 40, 2])
    man = base + m3.Manifold.cube([10, 10, 20]).translate([10, 10, 0]) + m3.Manifold.cube([10, 10, 30]).translate([20, 20, 0])
    raw, notes = modelprint.to_trimesh(man), []
    view = clean.slicer_view(np.asarray(raw.vertices), np.asarray(raw.faces))
    assert view["bad_edges"]
    welded = modelprint.to_trimesh(landmark._weld(man, raw, notes))
    out = clean.for_slicer(welded)
    assert not clean.problems(clean.slicer_view(out.vertices, out.faces)) and len(out.split()) == 1
    assert out.volume == pytest.approx(man.volume(), rel=1e-4) and "Welded 1 edge" in notes[0]


def test_a_weld_stays_above_the_bed_and_leaves_a_collapsed_sliver_alone():
    import manifold3d as m3
    import trimesh
    from smoothstone import landmark

    man = m3.Manifold.cube([10, 10, 20]) + m3.Manifold.cube([10, 10, 20]).translate([10, 10, 0])  # a line from the bed up
    welded = landmark._weld(man, modelprint.to_trimesh(man), [])
    assert welded.bounding_box()[2] == 0 and welded.volume() > man.volume()
    box = modelprint.to_trimesh(m3.Manifold.cube([10, 10, 10]))
    a, b = np.asarray(box.edges[0])
    sliver = [[a, b, len(box.vertices)]] * 2  # a third corner at a's own place: flat, and gone at float32
    flat = trimesh.Trimesh(np.vstack([box.vertices, box.vertices[a]]), np.vstack([box.faces, sliver]), process=False)
    notes = []
    assert landmark._weld(man, flat, notes) is man and notes == []


@pytest.mark.parametrize("fails, note", [(0, None), (1, "Snapped"), (2, "Welded"), (3, "Collapsed"), (4, None)])
def test_a_mesh_is_closed_by_the_lightest_repair_that_works(fails, note, monkeypatch):
    import manifold3d as m3
    from smoothstone import clean, landmark

    calls, real = [], clean.for_slicer

    def stubborn(mesh, tolerance=.01):
        calls.append(tolerance)
        if len(calls) <= fails:
            raise ValueError("still 1 zero-area faces after three repair passes")
        return real(mesh, tolerance)
    monkeypatch.setattr(clean, "for_slicer", stubborn)
    man, notes = m3.Manifold.cube([40, 40, 2]) + m3.Manifold.cube([10, 10, 20]).translate([10, 10, 0]), []
    if fails > 1:
        man += m3.Manifold.cube([10, 10, 30]).translate([20, 20, 0])  # they meet along a line
    raw = modelprint.to_trimesh(man)
    if fails == 4:
        with pytest.raises(ValueError, match="zero-area"):
            landmark._closed(man, raw, notes)
        return
    assert landmark._closed(man, raw, notes).volume == pytest.approx(man.volume(), rel=1e-4)
    assert calls == [.01, .01, .01, .03][:fails + 1]
    assert (notes[-1].startswith(note) if note else notes == [])


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


def _of(records, start):
    return {p["id"]: (p["min_height"]["metres"], p["height"]["metres"]) for p in records if str(p["id"]).startswith(start)}


def test_two_parts_with_no_height_share_two_missing_levels():
    from smoothstone import landmark

    odd = _minaret(150)
    for k in (1, 2):
        odd[k] = {"id": f"150-{k}u", "footprint": odd[1]["footprint"], "tags": {"building:part": "yes"}}
    twins = [*_minaret(0), *_minaret(50), *_minaret(100)]
    for k in range(0, 12, 4):  # the same plan at both levels
        twins[k + 2]["footprint"] = twins[k + 1]["footprint"]
    records, _ = landmark.resolve_parts([*twins, *odd], {"geometry_source": "x"})
    assert {_of(records, "150")[f"150-{k}u"] for k in (1, 2)} == {(13, 14), (32, 32.3)}


def test_a_part_mapped_from_the_ground_keeps_it():
    from smoothstone import landmark

    parts = [*_minaret(0), *_minaret(50), *_minaret(100), *_minaret(150, untagged=True)]
    for part in parts:
        if part["id"] == "150-2u":
            part["tags"]["min_height"] = "0"
    records, _ = landmark.resolve_parts(parts, {"geometry_source": "x"})
    assert _of(records, "150")["150-2u"][0] == 0


def test_a_pinnacle_on_another_tower_gives_no_level():
    from smoothstone import landmark

    def part(i, x, half, lo=None, hi=None):
        ring = [[[x - half, -half], [x + half, -half], [x + half, half], [x - half, half]]]
        tags = {"building:part": "yes", **({"min_height": lo, "height": hi} if hi else {})}
        return {"id": i, "footprint": ring, "tags": tags}
    parts = [part("a", 0, .75, "60", "64"), part("b", 10, .75, "60", "64"), part("tower", 5, 9, "0", "60"),
             part("low", 50, 2, "10", "25"), part("high", 50, 1.9, "25", "40"), part("odd", 50, .75)]
    records, _ = landmark.resolve_parts(parts, {"geometry_source": "x"})
    assert _of(records, "odd")["odd"][0] == 0


def test_a_part_with_no_height_and_no_twins_still_stands():
    from smoothstone import landmark

    square = [[[0, 0], [9, 0], [9, 9], [0, 9]]]
    parts = [{"id": 1, "footprint": square, "tags": {"height": "20"}},
             {"id": 2, "footprint": [[[30, 0], [39, 0], [39, 9], [30, 9]]], "tags": {}}]
    records, _ = landmark.resolve_parts(parts, {"geometry_source": "x"})
    assert [p["height"]["metres"] for p in records] == [20, 20]


def _way(i, x0, y0, x1, y1, **tags):
    """A rectangle in metres about latitude and longitude zero."""
    ring = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    return {"type": "way", "id": i, "tags": {k.replace("__", ":"): v for k, v in tags.items()},
            "geometry": [{"lat": y / 111320, "lon": x / 111320} for x, y in ring]}


CASTLE = [_way(1, -100, -60, 100, 60, historic="castle", wikidata="Q1", name="Example Castle"),
          _way(2, -10, -10, 10, 10, building="yes", name="Round Tower", height="30"),
          _way(3, 40, 0, 70, 20, building="yes", height="12"), _way(4, 40, 0, 55, 20, building__part="yes", height="12"),
          _way(5, -70, 0, -40, 20, building="yes"), _way(6, 200, 0, 230, 20, building="yes", height="9")]


def _site_refs(**more):
    return {"latitude": 0, "longitude": 0, "id": "Q1", "label": "Example Castle", **more}


@pytest.mark.parametrize("change, parts, source", [
    ({}, [4, 2, 5], "way/1"),  # Windsor Castle was built as its Round Tower
    ({"refs": {"id": "Q2", "osm_way": "1"}}, [4, 2, 5], "way/1"),  # Wikidata's OSM way, no wikidata tag on the map
    ({"tags": {"historic": "monument"}}, [2], "way/2"),  # grounds are not a site
    ({"refs": {"id": "Q2"}}, [2], "way/2"),  # a castle the landmark happens to stand in
    ({"tower": {"name": "The Example Castle Keep"}}, [2], "way/2"),  # the building has the landmark's name
])
def test_a_castle_is_every_building_on_its_site(change, parts, source):
    elements = copy.deepcopy(CASTLE)
    elements[0]["tags"].update(change.get("tags", {}))
    elements[1]["tags"].update({"roof:shape": "pyramidal", **change.get("tower", {})})
    parsed = landmark_refs.parse_osm({"elements": elements}, _site_refs(**change.get("refs", {})))
    assert parsed["source"].endswith(source)
    assert [p["id"] for p in parsed["parts"]] == parts
    assert bool(parsed.get("site")) == (source == "way/1")


def _map_answer(monkeypatch, tmp_path, drawn):
    """Overpass is down and the OSM map answers with these ways. Returns its nodes and what was asked."""
    monkeypatch.setenv("HOME", str(tmp_path))
    nodes, ways, asked = [], [], []
    for way in drawn:
        ids = [way["id"] * 100 + k for k in range(4)]
        nodes += [{"type": "node", "id": n, **g} for n, g in zip(ids, way["geometry"])]
        ways.append({"type": "way", "id": way["id"], "tags": way["tags"], "nodes": [*ids, ids[0]]})

    def request(url, data=None):
        if data is not None:
            raise OSError("Overpass is down")
        asked.append(url)
        return {"elements": nodes + ways}
    monkeypatch.setattr(landmark_refs, "_request", request)
    return nodes, asked


BRIDGE = _way(1, -700, -60, 400, 60, man_made="bridge", wikidata="Q1")
DECK = _way(7, -700, -40, 400, 40, building__part="yes", min_height="8", height="10")


def test_the_map_answer_keeps_a_site_and_a_far_site_is_searched_again(monkeypatch, tmp_path):
    nodes, asked = _map_answer(monkeypatch, tmp_path, [
        BRIDGE, DECK, CASTLE[1], _way(9, 0, 0, 5, 5, man_made="bridge", wikidata="Q8")])
    parsed = landmark_refs.fetch(_site_refs(label="Example Bridge"), tmp_path)
    assert parsed["site"] and [p["id"] for p in parsed["parts"]] == [7, 2]
    assert len(asked) == 2  # 220 m, then the 703 m the bridge reaches
    nodes[0]["lon"] *= 2
    with pytest.raises(landmark_refs.LandmarkProblem, match="1 km"):
        landmark_refs.fetch(_site_refs(label="Example Bridge", osm_way="1"), tmp_path)


def test_overpass_is_asked_for_the_landmarks_own_area(monkeypatch, tmp_path):
    """A castle's area has no building tag, so the search for buildings alone never returned it."""
    monkeypatch.setenv("HOME", str(tmp_path))
    asked = []

    def request(url, data=None):
        asked.append(urllib.parse.parse_qs(data.decode())["data"][0])
        wanted = '"wikidata"="Q1"' in asked[-1]
        return {"elements": CASTLE if wanted else CASTLE[1:]}
    monkeypatch.setattr(landmark_refs, "_request", request)
    assert [p["id"] for p in landmark_refs.fetch(_site_refs(), tmp_path)["parts"]] == [4, 2, 5]
    assert 'way["wikidata"="Q1"](around:1000,' in asked[0] and 'relation["wikidata"="Q1"]' in asked[0]


def test_a_statue_the_map_answer_has_is_refused_and_a_dome_on_a_site_keeps_its_walls(monkeypatch, tmp_path):
    _map_answer(monkeypatch, tmp_path, [_way(1, -3, -3, 3, 3, artwork_type="statue", wikidata="Q1"),
                                        _way(2, -8, -8, 8, 8, building="yes", height="12")])
    with pytest.raises(landmark_refs.LandmarkProblem, match="statue"):
        landmark_refs.fetch(_site_refs(), tmp_path)
    domed = [CASTLE[0], _way(2, -25, -25, 25, 25, building="yes", height="17"),
             _way(3, -10, -10, 10, 10, building__part="yes", height="34", roof__shape="dome")]
    assert [p["id"] for p in landmark_refs.parse_osm({"elements": domed}, _site_refs())["parts"]] == [3, 2]


def test_a_bridge_with_no_mapped_deck_is_refused_after_the_far_search(monkeypatch, tmp_path):
    """The Golden Gate Bridge was built as two towers and no bridge."""
    _, asked = _map_answer(monkeypatch, tmp_path, [BRIDGE, *CASTLE[1:3]])
    with pytest.raises(landmark_refs.LandmarkProblem, match="deck"):
        landmark_refs.fetch(_site_refs(label="Example Bridge"), tmp_path)
    assert len(asked) == 2


@pytest.mark.parametrize("walls, dome, drum, parts", [
    ("17", "34", 20, [2, 1]),  # the Dome of the Rock was built as its dome, with no octagon
    ("34", "34", 20, [2]),  # the height of the whole, not of the walls
    (None, "34", 20, [2]),
    ("17", "34", 44, [2]),  # the parts are the building
    ("17", "34", -44, [2, 1]),  # Angkor Wat's galleries stood in the air over its 23 m platform
])
def test_the_walls_around_a_mapped_dome_are_a_part(walls, dome, drum, parts):
    r = abs(drum) / 2
    raised = {"min_height": "17"} if drum < 0 else {}
    whole = _way(1, -25, -25, 25, 25, building="mosque", wikidata="Q1", **({"height": walls} if walls else {}))
    elements = [whole, _way(2, -r, -r, r, r, building__part="yes", height=dome, roof__shape="dome", **raised)]
    assert [p["id"] for p in landmark_refs.parse_osm({"elements": elements}, _site_refs())["parts"]] == parts


def test_a_building_mapped_off_the_ground_is_not_filled_in_under_its_antenna():
    """The Atomium's nine balls were built as one block, its plan 102 m tall, because its antenna is taller."""
    whole = _way(1, -25, -25, 25, 25, building="yes", wikidata="Q1", height="102")
    ball = _way(2, -24, -24, 24, 24, building__part="yes", height="76", min_height="58")
    antenna = _way(3, -1, -1, 1, 1, building__part="yes", height="110", min_height="102")
    assert [p["id"] for p in landmark_refs.parse_osm({"elements": [whole, ball, antenna]}, _site_refs())["parts"]] == [2, 3]


@pytest.mark.parametrize("tags, parts", [
    ({"height": "169.3", "roof:shape": "pyramidal", "roof:height": "16.8"}, [1]),  # the Washington Monument
    ({"height": "60", "man_made": "lighthouse"}, [1]),
    ({"height": "60", "building": "tower"}, [1]),
    ({"height": "20"}, []),  # a box says nothing of a palace
    ({"height": "20", "roof:shape": "flat"}, []),
    ({"height": "96", "roof:shape": "gabled"}, []),  # 96 m is the cathedral's spire
    ({"roof:shape": "pyramidal"}, []),
])
def test_a_tower_with_its_own_height_is_its_own_part(tags, parts):
    way = _way(1, -8, -8, 8, 8, **{"building": "yes", **tags})
    assert [p["id"] for p in landmark_refs.parse_osm({"elements": [way]}, _site_refs())["parts"]] == parts


@pytest.mark.parametrize("tags", [{"artwork_type": "statue"}, {"monument": "statue"}])
def test_a_statue_is_refused_for_what_it_is(tags):
    way = _way(1, -8, -8, 8, 8, building="yes", building__part="yes", height="10", **tags)
    with pytest.raises(landmark_refs.LandmarkProblem, match="statue"):
        landmark_refs.parse_osm({"elements": [way]}, _site_refs(osm_way="1"))
    # A statue that only stands near the landmark refuses nothing.
    near = _way(2, 20, 20, 22, 22, building__part="yes", height="4", **tags)
    house = _way(3, -8, -8, 8, 8, building="yes")
    assert landmark_refs.parse_osm({"elements": [house, near]}, _site_refs())["parts"] == []


def test_an_obelisk_tapers(recorded, monkeypatch, tmp_path):
    from smoothstone import landmark

    recorded("Taj Mahal")
    way = _way(1, -8.4, -8.4, 8.4, 8.4, building="yes", man_made="obelisk", height="169.3", roof__shape="pyramidal",
               roof__height="16.8")
    monkeypatch.setattr(landmark_refs, "fetch", lambda refs, root: landmark_refs.parse_osm(
        {"elements": [way]}, _site_refs()))
    result = landmark.generate("Taj Mahal", tmp_path, (220, 220, 220), 172, "low")
    solid = modelprint.to_manifold(trimesh.load(result["stl"]))
    k = result["scale"]
    widths = [np.ptp([solid.slice(2 + z * k).bounds()[i] for i in (0, 2)]) / k for z in (1, 152, 160)]
    assert widths[0] == pytest.approx(16.8, abs=.2) and widths[1] == pytest.approx(16.8 * .63, abs=.2)
    assert widths[2] < widths[1] * .7 and len(solid.decompose()) == 1


def test_a_guessed_height_follows_the_ground_the_building_covers_not_the_count_of_its_parts():
    # York Minster: eight small pinnacles at 54 to 63 m and three small 54 m towers stood six chapels up as 54 m blocks
    from smoothstone import landmark

    def part(i, x, side, **tags):
        ring = [[x, 0], [x + side, 0], [x + side, side], [x, side]]
        return {"id": i, "footprint": [ring], "tags": {k.replace("__", ":"): v for k, v in tags.items()}}
    built = [part(1, 0, 75, height="22"), part(2, 80, 54, height="35"), part(3, 140, 21, height="54"),
             part(4, 165, 12, height="54"),
             *[part(10 + k, 200 + 3 * k, 1.6, min_height="54", height="63") for k in range(8)]]
    records, _ = landmark.resolve_parts([*built, part(30, 300, 9, roof__shape="gabled")], {"geometry_source": "x"})
    guessed, = [p for p in records if p["id"] == 30]
    assert guessed["height"]["metres"] == 22 and guessed["height"]["guessed"]
    # A raised part never ends below its own foot, and with nothing known on the ground the raised parts decide.
    records, _ = landmark.resolve_parts([*built, part(31, 300, 9, min_height="40")], {"geometry_source": "x"})
    assert [p["height"]["metres"] for p in records if p["id"] == 31] == [44]
    records, _ = landmark.resolve_parts([*built[4:], part(32, 300, 9)], {"geometry_source": "x"})
    assert [p["height"]["metres"] for p in records if p["id"] == 32] == [63]


@pytest.mark.parametrize("tags, kept", [
    ({"indoor": "room", "room": "toilets", "amenity": "toilets", "level": "0"}, False),  # the White House's toilets
    ({"indoor": "yes"}, False),
    ({"room": "office"}, False),
    ({"location": "underground"}, False),
    ({"indoor": "no"}, True),
    ({"level": "0"}, True),
    ({}, True),
])
def test_a_room_inside_the_building_is_no_part_of_its_outside(tags, kept):
    def way(i, half, tags):
        return {"type": "way", "id": i, "tags": tags,
                "geometry": [{"lat": y * 1e-4, "lon": x * 1e-4} for x, y in
                             [(-half, -half), (half, -half), (half, half), (-half, half), (-half, -half)]]}
    data = {"elements": [way(1, 4, {"building": "yes"}), way(2, 3, {"building:part": "yes", "height": "18"}),
                         way(3, 1, {"building:part": "yes", **tags})]}
    parsed = landmark_refs.parse_osm(data, {"latitude": 0, "longitude": 0, "osm_way": 1})
    assert [p["id"] for p in parsed["parts"]] == ([2, 3] if kept else [2])


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
    for p, _ in added:  # raised by a sourced amount, it is still a guess
        p.update(spire=True, roof_shape="pyramidal")
    facts = {"spire_rise_m": {"value": 12, "source": "https://example.org"}}
    tops = [(p["height"]["metres"], p["height"]["guessed"]) for p in la.reconcile(
        [p for p, _ in both], [cs for _, cs in both], {}, facts, ["gothic"])[0] if str(p["id"]).endswith("-twin")]
    assert tops == [(122, True)] * 4
    assert la._twin_detail(both, [np.array([0., -17]), np.array([0., 17])], 18, 70, []) == []


def _drawn(monkeypatch, recorded, *ways, **refs):
    """The Taj Mahal's recorded facts over a map that draws only these ways."""
    recorded("Taj Mahal")
    monkeypatch.setattr(landmark_refs, "fetch", lambda r, root: landmark_refs.parse_osm({"elements": list(ways)}, _site_refs()))
    real = landmark_refs.resolve
    monkeypatch.setattr(landmark_refs, "resolve", lambda name, root: {**real(name, root), "height": 73.0, **refs})
    monkeypatch.setattr(landmark_refs, "load_pack", lambda *args, **kwargs: {})


OUTLINE = _way(1, -40, -10, 40, 10, building="yes", wikidata="Q1")


@pytest.mark.parametrize("top, refused", [("54", True), ("55", False)])
def test_a_map_that_stops_far_under_the_sourced_height_is_refused(recorded, monkeypatch, tmp_path, top, refused):
    """Tokyo Tower came out as a 150 m stub of a 332.6 m tower and was called ready."""
    from smoothstone import landmark

    _drawn(monkeypatch, recorded, OUTLINE, _way(2, -40, -10, 0, 10, building__part="yes", height=top),
           _way(3, 0, -10, 40, 10, building__part="yes", height="20"))
    if refused:
        with pytest.raises(landmark_refs.LandmarkProblem, match="tallest part of Taj Mahal is 54 m, and the whole stands 73 m"):
            landmark.generate("Taj Mahal", tmp_path, (220, 220, 220), 172, "low")
        assert not list(tmp_path.rglob("*.stl"))
    else:
        assert landmark.generate("Taj Mahal", tmp_path, (220, 220, 220), 172, "low")["stl"]


@pytest.mark.parametrize("inner, refused", [(17, True), (15, False), (0, False)])
def test_a_map_of_two_ends_and_no_middle_is_refused(recorded, monkeypatch, tmp_path, inner, refused):
    """The Porta Nigra came out as two blocks joined by a thin strip and was called ready."""
    from smoothstone import landmark

    _drawn(monkeypatch, recorded, OUTLINE, _way(2, -40, -10, -inner, 10, building__part="yes", height="73"),
           _way(3, inner, -10, 40, 10, building__part="yes", height="70"))
    if refused:
        with pytest.raises(landmark_refs.LandmarkProblem, match="separate pieces covering 5[78]% of its plan"):
            landmark.generate("Taj Mahal", tmp_path, (220, 220, 220), 172, "low")
    else:
        assert landmark.generate("Taj Mahal", tmp_path, (220, 220, 220), 172, "low")["stl"]


@pytest.mark.parametrize("joint, refused", [(.5, True), (3, False)])
def test_a_thin_strip_does_not_make_two_ends_one_building(recorded, monkeypatch, tmp_path, joint, refused):
    """A screen wall or walkway between the two ends took the middle's place."""
    from smoothstone import landmark

    _drawn(monkeypatch, recorded, OUTLINE, _way(2, -40, -10, -19, 10, building__part="yes", height="73"),
           _way(3, 19, -10, 40, 10, building__part="yes", height="70"),
           _way(4, -19, -joint, 19, joint, building__part="yes", height="20"))
    if refused:
        with pytest.raises(landmark_refs.LandmarkProblem, match="separate pieces covering 55% of its plan"):
            landmark.generate("Taj Mahal", tmp_path, (220, 220, 220), 172, "low")
    else:
        assert landmark.generate("Taj Mahal", tmp_path, (220, 220, 220), 172, "low")["stl"]


def test_a_shed_beside_the_body_does_not_make_it_two_pieces(recorded, monkeypatch, tmp_path):
    from smoothstone import landmark

    _drawn(monkeypatch, recorded, OUTLINE, _way(2, -40, -10, 4, 10, building__part="yes", height="73"),
           _way(3, 30, -1, 33, 2, building__part="yes", height="5"))
    assert landmark.generate("Taj Mahal", tmp_path, (220, 220, 220), 172, "low")["stl"]


def _no_models(monkeypatch):
    from smoothstone import models

    none = {"subject": "Taj Mahal", "kept": [], "left_out": [], "terms": [], "names": {"label": "Taj Mahal"},
            "sources": {k: {"found": 0, "searched": True, "why": ""} for k in ("printables", "commons", "sketchfab")}}
    monkeypatch.setattr(models, "search", lambda *args: none)


PLAIN = _way(1, -20, -20, 20, 20, building="tower", height="73", wikidata="Q1")


def test_one_plain_shape_is_built_only_after_the_open_models_are_out(recorded, monkeypatch, jobenv):
    """The Temple of Heaven came out as one drum and cone, and was called ready with no search for a better model."""
    from smoothstone import cli

    def run(*args):
        text, _ = cli.run(list(args))
        return text, text.splitlines()[-1]

    _drawn(monkeypatch, recorded, PLAIN)
    _no_models(monkeypatch)
    for size in ([], ["--size", "120"]):  # asking again is no permission
        text, last = run("landmark", "Taj Mahal", *size)
        assert "one plain shape" in text and last == "NEXT: stone models 'Taj Mahal'"
    plain = run("models", "Taj Mahal")[1]
    assert plain == "NEXT: stone landmark 'Taj Mahal' --size 120.0 --plain"
    text, last = run(*shlex.split(plain)[2:])
    assert "NOTE, tell the person: the map has Taj Mahal as one plain shape" in text and "Part ready" in text
    assert "Size: 120 mm" in text
    assert run("models", "Taj Mahal")[1].startswith("NEXT: ask the person")


def test_a_plain_shape_after_the_models_is_not_sent_back_to_them(recorded, monkeypatch, jobenv):
    from smoothstone import cli

    _drawn(monkeypatch, recorded, PLAIN)
    _no_models(monkeypatch)
    cli.run(["new", "Find me an open model of the Taj Mahal, 12 cm tall"])
    assert cli.run(["models", "Taj Mahal"])[0].splitlines()[-1] == "NEXT: stone landmark 'Taj Mahal'"
    assert cli.run(["landmark", "Taj Mahal"])[0].splitlines()[-1] == "NEXT: stone landmark 'Taj Mahal' --plain"


def test_one_tower_on_a_wide_plan_is_not_the_building(recorded, monkeypatch, tmp_path):
    from smoothstone import landmark

    _drawn(monkeypatch, recorded, OUTLINE, _way(2, -40, -10, -25, 10, building__part="yes", height="73"))
    with pytest.raises(landmark_refs.LandmarkProblem, match="a piece covering 19% of its plan"):
        landmark.generate("Taj Mahal", tmp_path, (220, 220, 220), 172, "low", plain=True)


def test_a_tall_bell_tower_does_not_hide_a_church_without_its_dome(recorded, monkeypatch, tmp_path):
    from smoothstone import landmark

    tower = _way(5, 60, 0, 70, 10, building="bell_tower", wikidata="Q5", height="73")
    item = [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}]
    site = _site_refs(wikidata_raw={"claims": {"P527": item}})
    _drawn(monkeypatch, recorded, OUTLINE)
    monkeypatch.setattr(landmark_refs, "fetch", lambda r, root: landmark_refs.parse_osm({"elements": [
        OUTLINE, tower, _way(2, -40, -10, 0, 10, building__part="yes", height="20"),
        _way(3, 0, -10, 40, 10, building__part="yes", height="21")]}, site))
    with pytest.raises(landmark_refs.LandmarkProblem, match="tallest part of Taj Mahal is 21 m"):
        landmark.generate("Taj Mahal", tmp_path, (220, 220, 220), 172, "low")


def test_a_whole_pyramid_is_no_plain_shape(recorded, monkeypatch, tmp_path):
    from smoothstone import landmark

    _drawn(monkeypatch, recorded, _way(1, -40, -40, 40, 40, building="yes", height="73", roof__shape="pyramidal",
                                       roof__height="73", wikidata="Q1"))
    assert landmark.generate("Taj Mahal", tmp_path, (220, 220, 220), 172, "low")["stl"]


def test_a_crowded_map_is_asked_again_for_a_smaller_area(monkeypatch, tmp_path):
    """The Brooklyn Bridge stopped at "HTTP Error 400: Bad Request": the map API refuses over 50,000 nodes."""
    import urllib.error

    house = _way(3, -8, -8, 8, 8, building="yes", height="12", wikidata="Q1")
    wide = _way(4, -900, -9, 900, 9, building="yes", height="12", wikidata="Q1")
    cut = {"type": "relation", "id": 8, "tags": {"building": "yes", "type": "multipolygon", "wikidata": "Q1"},
           "members": [{"type": "way", "ref": 404, "role": "outer"}]}
    for i, (drawn, found, more) in enumerate((
            (house, True, []), (wide, False, []), (house, False, [cut]),
            (_way(3, -8, -8, 8, 8, building="yes", height="12"), False, []))):  # and its own outline is not in the answer
        home = tmp_path / str(i)
        nodes, asked = _map_answer(monkeypatch, home, [drawn])
        nodes += more
        answer = landmark_refs._request

        def request(url, data=None, answer=answer):
            got = answer(url, data)
            if len(asked) < 3:
                raise urllib.error.HTTPError(url, 400, "Bad Request", {}, None)
            return got
        monkeypatch.setattr(landmark_refs, "_request", request)
        if found:
            assert landmark_refs.fetch(_site_refs(length=1825), home)["outline"]
        else:
            with pytest.raises(landmark_refs.LandmarkProblem, match="too crowded"):
                landmark_refs.fetch(_site_refs(length=1825), home)
        boxes = [[float(v) for v in urllib.parse.parse_qs(url.split("?")[1])["bbox"][0].split(",")] for url in asked]
        assert [round((b[3] - b[1]) * 111320 / 2) for b in boxes] == [1000, 500, 250]
        assert not list((home / ".cache/smoothstone/osm").glob("*.json"))

    def crowded(url, data=None):
        raise urllib.error.HTTPError(url, 400, "Bad Request", {}, None)
    monkeypatch.setattr(landmark_refs, "_request", crowded)
    with pytest.raises(landmark_refs.LandmarkProblem, match="too crowded"):  # the smallest area is still too large
        landmark_refs.fetch(_site_refs(), tmp_path / "small")
