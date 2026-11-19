import json
import urllib.parse

from smoothstone import find


def _page(title, lic, idx, w=1200, h=1600, mime="image/jpeg"):
    return {"title": title, "index": idx, "imageinfo": [{
        "width": w, "height": h, "mime": mime, "thumburl": f"https://x/{idx}.jpg",
        "descriptionurl": f"https://c/{idx}", "extmetadata": {
            "LicenseShortName": {"value": lic}, "Artist": {"value": "<a>Someone</a>"}}}]}


def _ent(qid, label, p31, image=None, aliases=()):
    claims = {"P31": [{"mainsnak": {"datavalue": {"value": {"id": c}}}} for c in p31]}
    if image:
        claims["P18"] = [{"mainsnak": {"datavalue": {"value": image}}}]
    return {"id": qid, "labels": {"en": {"value": label}},
            "aliases": {"en": [{"value": a} for a in aliases]}, "claims": claims}


def _fake(pages, lead=None, hits=None, people=(), seen=None):
    """A fake Wikidata and Commons. hits: entities the name search returns, best first;
    people: humans the full text search returns; seen collects every Commons search."""
    if hits is None:
        hits = [_ent("Q1", "Subject", ["Q5"], lead)] if lead else []
    every = {e["id"]: e for e in [*hits, *people]}

    def get(url, timeout=30):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        if "wbsearchentities" in url:
            return json.dumps({"search": [{"id": e["id"]} for e in hits]}).encode()
        if "wbgetentities" in url:
            ids = q["ids"][0].split("|")
            return json.dumps({"entities": {i: every[i] for i in ids if i in every}}).encode()
        if "wikidata" in url and "list=search" in url:
            return json.dumps({"query": {"search": [{"title": e["id"]} for e in people]}}).encode()
        if "titles=" in url:
            return json.dumps({"query": {"pages": {"9": _page(q["titles"][0], "Public domain", 5)}}}).encode()
        if url.startswith("https://x/"):
            return b"\xff\xd8jpeg"
        if seen is not None:
            seen.append(q.get("gsrsearch", [""])[0])
        return json.dumps({"query": {"pages": {str(i): p for i, p in enumerate(pages)}}}).encode()
    return get


def test_license_and_size_filter(monkeypatch):
    pages = [_page("File:Ada Lovelace.jpg", "CC BY-SA 4.0", 1),
             _page("File:Ada Lovelace 2.jpg", "All rights reserved", 2),
             _page("File:Ada Lovelace tiny.jpg", "CC0", 3, w=200, h=200),
             _page("File:Ada Lovelace.svg", "CC0", 4, mime="image/svg+xml")]
    monkeypatch.setattr(find, "_get", _fake(pages))
    got = find.search("Ada Lovelace")
    assert [c["title"] for c in got] == ["File:Ada Lovelace.jpg"]
    assert got[0]["author"] == "Someone"


def test_wikidata_main_image_leads(monkeypatch):
    pages = [_page("File:USS Abraham Lincoln at sea.jpg", "Public domain", 1),
             _page("File:Abraham Lincoln statue.jpg", "CC BY 4.0", 2)]
    monkeypatch.setattr(find, "_get", _fake(pages, lead="Abraham Lincoln portrait.jpg"))
    assert find.search("Abraham Lincoln")[0]["title"] == "File:Abraham Lincoln portrait.jpg"


def test_fetch_writes_credits(monkeypatch, tmp_path):
    pages = [_page("File:Grace Hopper.jpg", "Public domain", 1), _page("File:Grace Hopper 2.jpg", "CC BY 4.0", 2)]
    monkeypatch.setattr(find, "_get", _fake(pages))
    got = find.fetch("Grace Hopper", tmp_path, n=2)
    assert len(got) == 2 and (tmp_path / "photo_1.jpg").exists()
    credits = (tmp_path / "credits.txt").read_text()
    assert "Grace Hopper.jpg by Someone, Public domain" in credits


def test_subject_from_request():
    assert find.subject_from_request("A mini figure of Jensen Huang, 80 mm tall") == "Jensen Huang"
    assert find.subject_from_request("make a small statue of Abraham Lincoln.") == "Abraham Lincoln"
    assert find.subject_from_request("a figure of my dog") is None


def test_a_subject_in_lower_case_or_after_my_favorite_is_still_found():
    s = find.subject_from_request
    assert s("a mini figure of a golden retriever, 80 mm tall") == "golden retriever"
    assert s("figurine of an african elephant") == "african elephant"
    assert s("make me a little statue of my favorite astronaut Neil Armstrong") == "Neil Armstrong"
    assert s("A mini figure of DHH, 90 mm tall.") == "DHH"
    assert s("A mini figure of DHH (David Heinemeier Hansson), 90 mm tall") == "DHH"
    assert s("a figure of the Statue of Liberty 120 mm tall") == "Statue of Liberty"
    assert s('A figure of Vincent van Gogh with "VINCENT" on the base') == "Vincent van Gogh"
    assert s("a statue of me") is None


GENE = _ent("Q10", "DHH", ["Q7187"], "DHH protein.png")
DHH = _ent("Q20", "David Heinemeier Hansson", ["Q5"], "David Heinemeier Hansson.jpg")


def test_a_nickname_finds_the_person_not_the_gene_with_that_name(monkeypatch):
    seen = []
    pages = [_page("File:David Heinemeier Hansson 2.jpg", "CC BY 4.0", 1)]
    monkeypatch.setattr(find, "_get", _fake(pages, hits=[GENE], people=[DHH], seen=seen))
    got = find.resolve("DHH")
    assert (got["label"], got["kind"]) == ("David Heinemeier Hansson", "person")
    titles = [c["title"] for c in find.search("DHH")]
    assert titles[0] == "File:David Heinemeier Hansson.jpg"
    assert seen and all(q.startswith("David Heinemeier Hansson") for q in seen)


def test_a_loose_text_match_on_a_person_is_not_the_subject(monkeypatch):
    tower = _ent("Q243", "Eiffel Tower", ["Q1440476"], "Tour Eiffel.jpg")
    giant = _ent("Q44368", "Andre the Giant", ["Q5"], aliases=["Andre Roussimoff"])
    monkeypatch.setattr(find, "_get", _fake([], hits=[tower], people=[giant]))
    got = find.resolve("Eiffel Tower")
    assert (got["label"], got["kind"]) == ("Eiffel Tower", "object")


def test_the_first_person_or_animal_wins_over_a_namesake(monkeypatch):
    game = _ent("Q1", "Golden Retriever", ["Q7889"])
    breed = _ent("Q38686", "Golden Retriever", ["Q39367"], "Golden.jpg")
    monkeypatch.setattr(find, "_get", _fake([], hits=[game, breed]))
    got = find.resolve("golden retriever")
    assert (got["id"], got["kind"]) == ("Q38686", "animal")


def test_fetch_records_who_the_photos_are_of(monkeypatch, tmp_path):
    pages = [_page("File:David Heinemeier Hansson 2.jpg", "CC BY 4.0", 1)]
    monkeypatch.setattr(find, "_get", _fake(pages, hits=[GENE], people=[DHH]))
    find.fetch("DHH", tmp_path, n=2)
    found = json.loads((tmp_path / "found.json").read_text())
    assert (found["subject"], found["kind"], found["wikidata"]) == ("David Heinemeier Hansson", "person", "Q20")


def test_lead_is_not_downloaded_twice(monkeypatch):
    pages = [_page("File:Grace Hopper portrait.jpg", "Public domain", 1), _page("File:Grace Hopper 2.jpg", "CC BY 4.0", 2)]
    monkeypatch.setattr(find, "_get", _fake(pages, lead="Grace Hopper portrait.jpg"))
    titles = [c["title"] for c in find.search("Grace Hopper")]
    assert titles == ["File:Grace Hopper portrait.jpg", "File:Grace Hopper 2.jpg"]
