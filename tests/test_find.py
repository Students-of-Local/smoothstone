import json
import urllib.parse

import pytest

from smoothstone import cli, faces, find


def _page(title, lic, idx, w=1200, h=1600, mime="image/jpeg", cats=""):
    meta = {"LicenseShortName": {"value": lic}, "Artist": {"value": "<a>Someone</a>"}}
    if cats:
        meta["Categories"] = {"value": cats}
    return {"title": title, "index": idx, "imageinfo": [{
        "width": w, "height": h, "mime": mime, "thumburl": f"https://x/{idx}.jpg",
        "descriptionurl": f"https://c/{idx}", "extmetadata": meta}]}


def _ent(qid, label, p31, image=None, aliases=(), sites=0, desc="", lang="en"):
    claims = {"P31": [{"mainsnak": {"datavalue": {"value": {"id": c}}}} for c in p31]}
    if image:
        claims["P18"] = [{"mainsnak": {"datavalue": {"value": image}}}]
    return {"id": qid, "labels": {lang: {"value": label}}, "descriptions": {"en": {"value": desc}} if desc else {},
            "aliases": {"en": [{"value": a} for a in aliases]}, "claims": claims,
            "sitelinks": {f"w{i}wiki": {} for i in range(sites)}}


def _fake(pages, lead=None, hits=None, people=(), seen=None, classes=(), depicted=(), lead_cats=""):
    """A fake Wikidata and Commons. hits: entities the name search returns, best first;
    people: humans the full text search returns; classes: P31 classes with their labels;
    seen collects every Commons search; depicted: the files Commons says depict the subject (P180)."""
    if hits is None:
        hits = [_ent("Q1", "Subject", ["Q5"], lead)] if lead else []
    every = {e["id"]: e for e in [*hits, *people, *classes]}

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
            return json.dumps({"query": {"pages": {"9": _page(q["titles"][0], "Public domain", 5, cats=lead_cats)}}}).encode()
        if url.startswith("https://x/"):
            return b"\xff\xd8" + url.encode()  # each photo its own bytes, for a stub face checker
        if seen is not None:
            seen.append(q.get("gsrsearch", [""])[0])
        if q.get("gsrsearch", [""])[0].startswith("haswbstatement:P180"):
            return json.dumps({"query": {"pages": {str(i): p for i, p in enumerate(depicted)}}}).encode()
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
    assert seen and all(q.startswith(("David Heinemeier Hansson", "haswbstatement:P180=Q20")) for q in seen)


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


def test_the_subject_is_what_the_figure_is_of_not_a_part_of_the_base():
    # Review of PR 23: "of" in "the front of the base" and "like his ... uniform" named the wrong subject.
    s = find.subject_from_request
    assert s("Donatello's Saint George as a small statue, 100 mm tall, with GEORGE on the front of the base") \
        == "Donatello's Saint George"
    assert s('Could you make a Lou Gehrig figurine, 110 mm, with "GEHRIG" on the base? '
             "Paint him all white like his Yankees uniform") == "Lou Gehrig"
    assert s("a tall statue, with a name on the side of the base") is None
    assert s("a desk toy that looks like Albert Einstein") == "Albert Einstein"
    assert s("a figure of a cat, painted like my own cat") == "cat"
    assert s("a bust that looks like my grandpa") is None


# Wikidata, 2026-11-19: what a name search returns first is often not what a figure is of.
TOWER = _ent("Q41225", "Big Ben", ["Q3139104"], "Big Ben.jpg", sites=88)
NAMESAKE = _ent("Q2902145", "Big Ben", ["Q5"], sites=1)


def test_a_famous_landmark_wins_over_a_little_known_person_of_its_name(monkeypatch):
    monkeypatch.setattr(find, "_get", _fake([], hits=[TOWER, NAMESAKE]))
    got = find.resolve("Big Ben")
    assert (got["id"], got["kind"]) == ("Q41225", "object")


def test_a_fictional_character_is_found_over_a_genus_or_a_given_name(monkeypatch):
    worm = _ent("Q8054264", "Yoda", ["Q16521"], sites=2)
    yoda = _ent("Q51730", "Yoda", ["Q15773347", "Q33125444"], "Yoda.jpg", sites=68)
    monkeypatch.setattr(find, "_get", _fake([], hits=[worm, yoda]))
    got = find.resolve("Yoda")
    assert (got["id"], got["kind"]) == ("Q51730", "character")
    name = _ent("Q3362622", "Mario", ["Q12308941"], sites=23)
    mario = _ent("Q12379", "Mario", ["Q1569167"], "Mario.png", sites=96)
    monkeypatch.setattr(find, "_get", _fake([], hits=[name, mario]))
    assert find.resolve("Mario")["id"] == "Q12379"


def test_a_character_class_is_known_by_its_label(monkeypatch):
    snoopy = _ent("Q207369", "Snoopy", ["Q88552181"], "Snoopy.png", sites=60)
    dog = _ent("Q88552181", "anthropomorphic dog", [])
    monkeypatch.setattr(find, "_get", _fake([], hits=[snoopy], classes=[dog]))
    assert find.resolve("Snoopy")["kind"] == "character"


def test_a_person_by_initials_wins_over_a_little_known_namesake(monkeypatch):
    genre = _ent("Q5264196", "Desi hip hop", ["Q188451"], aliases=["DHH"], sites=4)
    dhh = _ent("Q20", "David Heinemeier Hansson", ["Q5"], "DHH.jpg", sites=30)
    monkeypatch.setattr(find, "_get", _fake([], hits=[GENE, genre], people=[dhh]))
    assert find.resolve("DHH")["id"] == "Q20"


def test_a_film_a_disease_or_an_agency_of_the_same_name_is_never_the_subject(monkeypatch):
    film = _ent("Q483815", "Shrek", ["Q29168811"], "Shrek poster.jpg", sites=90)
    ogre = _ent("Q52401", "Shrek", ["Q37436391", "Q15773347"], "Shrek.png", sites=30)
    classes = [_ent("Q29168811", "animated feature film", []), _ent("Q37436391", "ogre in a work of fiction", [])]
    monkeypatch.setattr(find, "_get", _fake([], hits=[film, ogre], classes=classes))
    assert find.resolve("Shrek")["id"] == "Q52401"
    als = _ent("Q206901", "amyotrophic lateral sclerosis", ["Q929833"], aliases=["Lou Gehrig's disease"], sites=120)
    lou = _ent("Q357444", "Lou Gehrig", ["Q5"], "Gehrig.jpg", sites=40)
    monkeypatch.setattr(find, "_get", _fake([], hits=[als, lou], classes=[_ent("Q929833", "rare disease", [])]))
    assert find.resolve("Lou Gehrig")["id"] == "Q357444"
    dept = _ent("Q942326", "United States Department of Health and Human Services", ["Q2659904"],
                aliases=["DHH"], sites=70)
    dhh = _ent("Q719413", "David Heinemeier Hansson", ["Q5"], "DHH.jpg", sites=30)
    monkeypatch.setattr(find, "_get", _fake([], hits=[dept], people=[dhh],
                                            classes=[_ent("Q2659904", "government agency", [])]))
    assert find.resolve("DHH")["id"] == "Q719413"


def test_a_name_or_an_animal_just_before_the_figure_word_is_the_subject():
    # Review of PR 23, round 2: "mini" and "print" are no figure, and a lower case animal is a subject too.
    s = find.subject_from_request
    assert s("Make me a mini Grace Hopper figure, 90 mm tall") == "Grace Hopper"
    assert s("Please print a Lou Gehrig figurine") == "Lou Gehrig"
    assert s("I'd like a little koala figure, 70 mm tall") == "koala"
    assert s("a 90 mm tall golden retriever statue") == "golden retriever"
    assert s("Get me a cute bulldog figurine") == "bulldog"


def test_ones_own_named_pet_or_relative_is_never_looked_up():
    s = find.subject_from_request
    assert s("a figure of my dog Max, 80 mm tall") is None
    assert s("a statue of my son Jack") is None
    assert s("a mini figure of our cat Luna") is None
    assert s("make me a little statue of my favorite astronaut Neil Armstrong") == "Neil Armstrong"


def test_nothing_that_can_be_a_subject_resolves_to_nothing(monkeypatch):
    # the DHH protein: a gene alone must not come back as the subject with its picture
    monkeypatch.setattr(find, "_get", _fake([], hits=[GENE]))
    assert find.resolve("DHH") is None


# two people called Michael Jordan: the famous one, and the one a hint can name
ATHLETE = _ent("Q41", "Michael Jordan", ["Q5"], "Jordan.jpg", sites=150, desc="American basketball player")
SCIENTIST = _ent("Q33", "Michael Jordan", ["Q5"], "Jordan Berkeley.jpg", sites=60,
                 desc="American computer scientist, University of California, Berkeley")
ACTOR = _ent("Q34", "Michael Jordan", ["Q5"], sites=8, desc="American actor")


def test_a_name_kept_only_under_mul_still_reads_in_english(monkeypatch):
    """Wikidata now keeps many names under "mul", and the first label was another script."""
    ent = _ent("Q9", "Sam Altman", ["Q5"], sites=40, desc="American entrepreneur", lang="mul")
    ent["labels"] = {"zh": {"value": "山姆"}, **ent["labels"]}
    monkeypatch.setattr(find, "_get", _fake([], hits=[ent]))
    got = find.resolve("Sam Altman")
    assert got["label"] == "Sam Altman" and got["description"] == "American entrepreneur"


def test_a_hint_picks_the_person_it_names_over_the_famous_one(monkeypatch):
    monkeypatch.setattr(find, "_get", _fake([], hits=[ATHLETE, SCIENTIST, ACTOR]))
    got = find.resolve("Michael Jordan, the Berkeley computer scientist")
    assert got["id"] == "Q33" and not got["ambiguous"]
    assert find.resolve("Michael Jordan (computer scientist)")["id"] == "Q33"


def test_two_well_known_people_with_one_name_ask_which_before_any_download(monkeypatch, tmp_path):
    """The wrong person's figure is the worst result: no photo is taken until the person says which."""
    pages = [_page("File:Michael Jordan.jpg", "CC BY 4.0", 1)]
    monkeypatch.setattr(find, "_get", _fake(pages, hits=[ATHLETE, SCIENTIST, ACTOR]))
    got = find.resolve("Michael Jordan")
    assert got["id"] == "Q41" and got["ambiguous"]
    assert [n["id"] for n in got["namesakes"]] == ["Q33", "Q34"]
    try:
        find.fetch("Michael Jordan", tmp_path)
        raise AssertionError("fetch downloaded photos of an ambiguous name")
    except find.WhichOne as e:
        assert e.name == "Michael Jordan" and [p["id"] for p in e.people][:2] == ["Q41", "Q33"]
    assert not list(tmp_path.glob("photo_*"))
    # words in the request that match no one's description do not count as an answer
    assert find.resolve("Michael Jordan, a mini figure 80 mm tall")["ambiguous"]


def test_a_famous_name_with_only_little_known_namesakes_does_not_ask(monkeypatch):
    monkeypatch.setattr(find, "_get", _fake([], hits=[ATHLETE, ACTOR]))
    assert not find.resolve("Michael Jordan")["ambiguous"]


def test_photos_commons_says_show_this_person_alone_come_first(monkeypatch):
    """A text match can be a namesake, a group photo or a thing named after them."""
    solo = {**_page("File:MJ portrait 1997.jpg", "CC BY 4.0", 4), "pageid": 7}
    pages = [_page("File:Michael Jordan Freeway.jpg", "CC BY 4.0", 1),
             _page("File:Michael Jordan and friends.jpg", "CC BY 4.0", 2),
             _page("File:Michael Jordan 2.jpg", "CC BY 4.0", 3)]
    ent = _ent("Q41", "Michael Jordan", ["Q5"], sites=150)
    monkeypatch.setattr(find, "_get", _fake(pages, hits=[ent], depicted=[solo]))
    titles = [c["title"] for c in find.search("Michael Jordan")]
    assert titles[0] == "File:MJ portrait 1997.jpg"
    assert titles.index("File:Michael Jordan 2.jpg") < titles.index("File:Michael Jordan Freeway.jpg")


def test_the_words_after_a_name_say_which_person(monkeypatch):
    """subject_from_request gives "Michael Jordan the Berkeley": the name search finds no one by that."""
    def get(url, timeout=30):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        if "Berkeley" in q.get("search", [""])[0] or "Berkeley" in q.get("srsearch", [""])[0]:
            return json.dumps({"search": [], "query": {"search": []}}).encode()
        return _fake([], hits=[ATHLETE, SCIENTIST, ACTOR])(url, timeout)
    monkeypatch.setattr(find, "_get", get)
    got = find.resolve("Michael Jordan the Berkeley, a mini figure of Michael Jordan the Berkeley computer scientist")
    assert got["id"] == "Q33" and not got["ambiguous"]


def test_a_namesakes_photos_never_stand_in_for_the_person(monkeypatch):
    """Live, 2026-11-20: Michael I. Jordan, the computer scientist, got photos of Michael B. Jordan."""
    pages = [_page("File:Michael B Jordan - Sinners.jpg", "CC BY 4.0", 1),
             _page("File:Steve Lipofsky -- Michael Jordan (1997).jpg", "CC BY 4.0", 2),
             _page("File:Michael I. Jordan at Berkeley.jpg", "CC BY 4.0", 3)]
    scientist = _ent("Q33", "Michael I. Jordan", ["Q5"], sites=60, desc="American computer scientist",
                     aliases=["Michael Jordan"])
    actor = _ent("Q34", "Michael B. Jordan", ["Q5"], sites=90, desc="American actor", aliases=["Michael Jordan"])
    monkeypatch.setattr(find, "_get", _fake(pages, hits=[actor, scientist]))
    ent = find.resolve("Michael Jordan, computer scientist")
    assert ent["id"] == "Q33" and ent["namesakes"]
    assert [c["title"] for c in find.search("Michael Jordan", entity=ent)] == ["File:Michael I. Jordan at Berkeley.jpg"]


def test_a_failed_find_leaves_no_earlier_persons_photos(monkeypatch, tmp_path):
    (tmp_path / "photo_1.jpg").write_bytes(b"someone else")
    (tmp_path / "credits.txt").write_text("photo_1.jpg: someone else")
    monkeypatch.setattr(find, "_get", _fake([]))
    try:
        find.fetch("Nobody Atall", tmp_path)
    except find.FindProblem:
        pass
    assert not list(tmp_path.iterdir())


def test_a_namesake_with_the_very_same_label_never_lends_a_photo(monkeypatch):
    """Review of #46: both are labeled "Michael Jordan", so a title cannot tell them apart."""
    pages = [_page("File:Michael Jordan.jpg", "CC BY 4.0", 1), _page("File:Michael Jordan 1997.jpg", "CC BY 4.0", 2)]
    monkeypatch.setattr(find, "_get", _fake(pages, hits=[ATHLETE, SCIENTIST, ACTOR]))
    ent = find.resolve("Michael Jordan, computer scientist")
    assert ent["id"] == "Q33"
    assert [c["title"] for c in find.search("Michael Jordan", entity=ent)] == ["File:Jordan Berkeley.jpg"]


def test_a_hint_that_fits_several_namesakes_still_asks(monkeypatch):
    a = _ent("Q51", "Chris Evans", ["Q5"], sites=150, desc="actor and film producer")
    b = _ent("Q52", "Chris Evans", ["Q5"], sites=90, desc="television presenter and radio producer")
    monkeypatch.setattr(find, "_get", _fake([], hits=[a, b]))
    assert find.resolve("Chris Evans, the producer")["ambiguous"]
    assert find.resolve("Chris Evans, the radio presenter")["id"] == "Q52"


def test_a_hint_never_lifts_a_thing_over_the_person(monkeypatch):
    lincoln = _ent("Q91", "Abraham Lincoln", ["Q5"], sites=200, desc="president of the United States")
    bust = _ent("Q92", "Abraham Lincoln", ["Q860861"], sites=0, desc="bronze bust by Gutzon Borglum")
    monkeypatch.setattr(find, "_get", _fake([], hits=[bust, lincoln]))
    assert find.resolve("Abraham Lincoln, bronze bust")["id"] == "Q91"


def test_only_the_words_right_after_the_name_say_which_one():
    h = find.hint_after
    assert h("A mini figure of Michael Jordan, 80 mm tall", "Michael Jordan") == ""
    assert h("A figure of Michael Jordan for my son who loves computer games", "Michael Jordan") == ""
    assert h("A figure of Michael Jordan, the basketball player, 90 mm", "Michael Jordan") == "the basketball player"
    assert h("A mini figure of Michael Jordan the Berkeley computer scientist", "Michael Jordan the Berkeley") \
        == "computer scientist"
    assert h("a chibi Chris Evans figure", "Chris Evans") == "figure"


def test_a_generational_suffix_stays_part_of_the_name():
    """Review of #46: "Hank Williams, Jr." is a name, not Hank Williams with the hint "Jr."."""
    assert find.split_hint("Hank Williams, Jr.") == ("Hank Williams, Jr.", "")
    assert find.split_hint("Sammy Davis, Jr., the singer") == ("Sammy Davis, Jr.", "the singer")
    assert find.split_hint("Tim Hardaway Jr.") == ("Tim Hardaway Jr.", "")
    assert find.split_hint("Michael Jordan, computer scientist") == ("Michael Jordan", "computer scientist")
    assert find.split_hint("Michael Jordan (computer scientist)") == ("Michael Jordan", "computer scientist")


def test_a_description_with_a_long_dash_reads_with_a_hyphen(monkeypatch):
    ent = _ent("Q297816", "Sammy Davis Jr.", ["Q5"], sites=60, desc="American entertainer (1925\u20131990)")
    monkeypatch.setattr(find, "_get", _fake([], hits=[ent]))
    assert find.resolve("Sammy Davis, Jr.")["description"] == "American entertainer (1925-1990)"


# the face check: a stub checker stands in for YuNet and SFace, keyed by the photo's url


class _Faces:
    """looks: {page index: faces.Look}; a photo not named shows one face of the person (e0)."""

    def __init__(self, looks):
        self.looks = looks

    def look(self, raw):
        idx = int(raw.decode(errors="ignore").rsplit("/", 1)[-1].split(".")[0])
        return self.looks.get(idx, _one(E0))


E0, E1, E2 = [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]
NEAR0 = [0.9, 0.3, 0.0]  # the same person as E0 in another photo (cosine 0.95)


def _one(e):
    return faces.Look(faces=1, one=True, embedding=e)


SAM = _ent("Q7407093", "Sam Altman", ["Q5"], "Sam Altman TED.jpg", sites=80, desc="American entrepreneur")


def _sam_pages():
    # the lead (Sam Altman TED.jpg) comes back from _fake with index 5
    return [_page("File:Sam Altman 2019.jpg", "CC BY 2.0", 1),
            _page("File:Sam Altman in TAU 2023.jpg", "CC BY 2.0", 2),
            _page("File:Sam Altman 2017.jpg", "CC BY 2.0", 3),
            _page("File:Sam Altman 2022.jpg", "CC BY 2.0", 4)]


def _with_faces(monkeypatch, looks):
    monkeypatch.setattr(faces, "checker", lambda: _Faces(looks))


def test_a_group_shot_is_never_a_persons_photo(monkeypatch, tmp_path):
    """Live, 2026-11-20: Sam Altman's photo 3 was a stage panel of several people."""
    monkeypatch.setattr(find, "_get", _fake(_sam_pages(), hits=[SAM]))
    _with_faces(monkeypatch, {2: faces.Look(faces=3, why="group")})
    got = find.fetch("Sam Altman", tmp_path)
    titles = [g["title"] for g in got]
    assert "File:Sam Altman in TAU 2023.jpg" not in titles and len(titles) == 3
    found = json.loads((tmp_path / "found.json").read_text())
    assert found["faces"] == "checked"
    assert {"title": "File:Sam Altman in TAU 2023.jpg", "why": "group"} in found["left_out"]


def test_one_face_must_lead_the_others_by_twice_the_area_and_be_big_enough():
    assert faces.judge([(300, 380)]) == (True, "")
    assert faces.judge([(300, 380), (60, 70)]) == (True, "")  # diners behind him
    assert faces.judge([(31, 39), (29, 38)])[1] == "group"  # two people on a stage
    assert faces.judge([(200, 250), (160, 200)])[1] == "group"
    assert faces.judge([(40, 50)])[1] == "small"
    assert faces.judge([])[1] == "no face"


def test_a_face_that_is_not_the_persons_is_left_out(monkeypatch, tmp_path):
    """A namesake or a stranger in a photo with the person's name is not them."""
    monkeypatch.setattr(find, "_get", _fake(_sam_pages(), hits=[SAM]))
    _with_faces(monkeypatch, {5: _one(E0), 1: _one(E1), 3: _one(NEAR0), 4: _one(E0)})
    got = find.fetch("Sam Altman", tmp_path)
    assert [g["title"] for g in got][0] == "File:Sam Altman TED.jpg"
    assert "File:Sam Altman 2019.jpg" not in [g["title"] for g in got]
    left = json.loads((tmp_path / "found.json").read_text())["left_out"]
    assert {"title": "File:Sam Altman 2019.jpg", "why": "other"} in left


def test_with_no_lead_face_the_faces_that_agree_win(monkeypatch, tmp_path):
    """Chris Evans the presenter's Wikidata photo shows two people: no anchor, so the faces that
    agree with each other are the person and a lone other face is left out."""
    ent = _ent("Q2964710", "Chris Evans", ["Q5"], "Chris and joss.jpg", sites=40)
    pages = [_page("File:Chris Evans 1.jpg", "CC BY 4.0", 1), _page("File:Chris Evans 2.jpg", "CC BY 4.0", 2),
             _page("File:Chris Evans 3.jpg", "CC BY 4.0", 3), _page("File:Chris Evans 4.jpg", "CC BY 4.0", 4)]
    monkeypatch.setattr(find, "_get", _fake(pages, hits=[ent]))
    _with_faces(monkeypatch, {5: faces.Look(faces=2, why="group"), 1: _one(E1),
                              2: _one(E2), 3: _one([0.1, 0.0, 1.0]), 4: _one([0.0, 0.2, 1.0])})
    got = find.fetch("Chris Evans", tmp_path)
    assert [g["title"] for g in got] == ["File:Chris Evans 2.jpg", "File:Chris Evans 3.jpg", "File:Chris Evans 4.jpg"]
    whys = {x["title"]: x["why"] for x in json.loads((tmp_path / "found.json").read_text())["left_out"]}
    assert whys == {"File:Chris and joss.jpg": "group", "File:Chris Evans 1.jpg": "unlike"}


def test_faces_agree_keeps_the_largest_group_and_breaks_ties_by_rank():
    assert faces.agree([E1, E2, [0.1, 0, 1], [0, 0.2, 1]]) == [1, 2, 3]
    assert faces.agree([E0, E1, E2]) == [0]  # nobody agrees: the best ranked alone
    assert faces.agree([]) == []


def test_an_artwork_of_the_person_is_left_out(monkeypatch, tmp_path):
    """Live, 2026-11-20: Michael Jordan's photo 3 was C215's street art stencil of him."""
    ent = _ent("Q41421", "Michael Jordan", ["Q5"], "Michael Jordan.jpg", sites=150)
    pages = [_page("File:Michael Jordan 1984.jpg", "Public domain", 1),
             _page("File:C215 - Michael Jordan (1).jpg", "CC BY-SA 4.0", 2, cats="C215|Graffiti of Michael Jordan"),
             _page("File:Michael Jordan in 2014.jpg", "CC BY 2.0", 3, cats="Portrait paintings of men"),
             _page("File:Michael Jordan 2006.jpg", "CC BY 2.0", 4)]
    monkeypatch.setattr(find, "_get", _fake(pages, hits=[ent]))
    found = {c["title"]: c["artwork"] for c in find.search("Michael Jordan", entity=find._pack(ent))}
    assert found["File:C215 - Michael Jordan (1).jpg"] and found["File:Michael Jordan in 2014.jpg"]
    assert not found["File:Michael Jordan 1984.jpg"] and not found["File:Michael Jordan.jpg"]
    got = [g["title"] for g in find.fetch("Michael Jordan", tmp_path)]  # faces off: still no artwork
    assert got == ["File:Michael Jordan.jpg", "File:Michael Jordan 1984.jpg", "File:Michael Jordan 2006.jpg"]
    left = json.loads((tmp_path / "found.json").read_text())["left_out"]
    assert {"title": "File:C215 - Michael Jordan (1).jpg", "why": "art"} in left


def test_a_file_commons_calls_an_artwork_is_one(monkeypatch):
    """No word in the title says it, but the file's structured data says it is a sculpture."""
    ent = _ent("Q41421", "Michael Jordan", ["Q5"], sites=150)
    bronze = {**_page("File:MJ 1994.jpg", "CC BY 4.0", 6), "pageid": 9}

    def get(url, timeout=30):
        if "wbgetentities" in url and "M9" in url:
            return json.dumps({"entities": {"M9": {"statements": {
                "P180": [{}], "P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q860861"}}}}]}}}}).encode()
        return _fake([], hits=[ent], depicted=[bronze])(url, timeout)
    monkeypatch.setattr(find, "_get", get)
    got = find.search("Michael Jordan", entity=find._pack(ent))
    assert [(c["title"], c["artwork"]) for c in got] == [("File:MJ 1994.jpg", True)]


def test_without_the_face_models_find_works_as_before_and_says_so(monkeypatch, tmp_path):
    monkeypatch.setattr(find, "_get", _fake(_sam_pages(), hits=[SAM]))

    def gone():
        raise faces.Unavailable("the face model face_detection_yunet_2023mar.onnx: cannot download it (URLError)")
    monkeypatch.setattr(faces, "checker", gone)
    got = find.fetch("Sam Altman", tmp_path)
    assert len(got) == 3  # today's ranking, unchecked, never a failed find
    assert json.loads((tmp_path / "found.json").read_text())["faces"].startswith("not checked: the face model")


def test_the_face_models_are_checked_against_their_sha256(monkeypatch, tmp_path):
    monkeypatch.setenv("STONE_FACE_MODELS", str(tmp_path))
    name = faces.MODELS["detect"][0]

    class Bad:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=-1, _left=[b"not the model"]):
            return _left.pop() if _left else b""
    monkeypatch.setattr(faces.urllib.request, "urlopen", lambda *a, **k: Bad())
    with pytest.raises(faces.Unavailable, match="SHA-256"):
        faces.model("detect")
    assert not (tmp_path / name).exists()


def test_left_out_line_names_each_reason_once():
    left = [{"title": "a", "why": "group"}, {"title": "b", "why": "other"}, {"title": "c", "why": "group"}]
    assert find.left_out_line(left, "Sam Altman") == \
        "Left out 3 photos: 2 group shots, a face that may not be Sam Altman's."
    assert find.left_out_line([{"title": "a", "why": "art"}], "X") == "Left out 1 photo: an artwork."
    assert find.left_out_line([], "X") is None


def test_stone_find_says_what_it_left_out(monkeypatch, jobenv):
    from test_cli import stone
    monkeypatch.setattr(find, "_get", _fake(_sam_pages(), hits=[SAM]))
    _with_faces(monkeypatch, {2: faces.Look(faces=3, why="group"), 1: _one(E1)})
    stone("new", "A mini figure of Sam Altman")
    text, code, nxt = stone("find", "Sam Altman")
    assert "Left out 2 photos: a face that may not be Sam Altman's, a group shot." in text
    assert "Found 3 free-licensed photos" in text


def test_stone_find_says_when_faces_went_unchecked(monkeypatch, jobenv):
    from test_cli import stone
    monkeypatch.setattr(find, "_get", _fake(_sam_pages(), hits=[SAM]))
    stone("new", "A mini figure of Sam Altman")
    text, code, nxt = stone("find", "Sam Altman")
    assert "Faces not checked: STONE_FACES=0 turned it off; look that every photo shows Sam Altman alone." in text


def test_someone_known_only_through_art_keeps_the_paintings(monkeypatch, tmp_path):
    """Review of #48: Mozart's and Napoleon's Wikidata image is a painting; leaving out every artwork
    left nothing, or a monument, where find had returned their portrait. A poster is never one:
    live, 2026-11-20, a 1941 Mozart poster with a swastika was photo 2."""
    ent = _ent("Q254", "Wolfgang Amadeus Mozart", ["Q5"], "Wolfgang-amadeus-mozart 1.jpg", sites=150)
    pages = [_page("File:Mozart Verona 1770.jpg", "Public domain", 1, cats="Portrait paintings of Mozart"),
             _page("File:Mozart-Plakat 1941 Arpke.jpg", "Public domain", 2),
             _page("File:Mozart bust Salzburg.jpg", "CC BY-SA 4.0", 3, cats="Busts of Mozart")]
    # live, 2026-11-20: only Commons' own tags say Krafft's portrait is a painting
    monkeypatch.setattr(find, "_get", _fake(pages, hits=[ent], lead_cats="PD-Art (PD-old-100-expired)|Artworks with Wikidata item"))
    got = [g["title"] for g in find.fetch("Wolfgang Amadeus Mozart", tmp_path)]
    assert got == ["File:Wolfgang-amadeus-mozart 1.jpg", "File:Mozart Verona 1770.jpg", "File:Mozart bust Salzburg.jpg"]
    left = json.loads((tmp_path / "found.json").read_text())["left_out"]
    assert {"title": "File:Mozart-Plakat 1941 Arpke.jpg", "why": "art"} in left


def test_with_only_artworks_of_them_the_artworks_are_their_likeness(monkeypatch, tmp_path):
    ent = _ent("Q9", "Old Painter", ["Q5"], sites=40)
    pages = [_page("File:Old Painter self portrait painting.jpg", "Public domain", 1),
             _page("File:Statue of Old Painter.jpg", "CC BY 4.0", 2)]
    monkeypatch.setattr(find, "_get", _fake(pages, hits=[ent]))
    assert len(find.fetch("Old Painter", tmp_path)) == 2


def test_a_photographers_credit_or_a_loose_category_is_no_artwork(monkeypatch):
    """Review of #48: "portrait by Steve Jurvetson" credits a photographer; "Cartoon Network" is a voice job."""
    ent = _ent("Q317521", "Elon Musk", ["Q5"], sites=150)
    pages = [_page("File:Elon Musk, portrait by Steve Jurvetson.jpg", "CC BY 2.0", 1),
             _page("File:Elon Musk 2015.jpg", "CC BY 2.0", 2, cats="Cartoon Network|People in 2015"),
             _page("File:Elon Musk (1).jpg", "CC BY 2.0", 3, cats="Portrait paintings of men")]
    monkeypatch.setattr(find, "_get", _fake(pages, hits=[ent]))
    art = {c["title"]: c["artwork"] for c in find.search("Elon Musk", entity=find._pack(ent))}
    assert art == {"File:Elon Musk, portrait by Steve Jurvetson.jpg": False, "File:Elon Musk 2015.jpg": False,
                   "File:Elon Musk (1).jpg": True}
