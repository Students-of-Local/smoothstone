import json
import urllib.parse

from smoothstone import find


def _page(title, lic, idx, w=1200, h=1600, mime="image/jpeg"):
    return {"title": title, "index": idx, "imageinfo": [{
        "width": w, "height": h, "mime": mime, "thumburl": f"https://x/{idx}.jpg",
        "descriptionurl": f"https://c/{idx}", "extmetadata": {
            "LicenseShortName": {"value": lic}, "Artist": {"value": "<a>Someone</a>"}}}]}


def _ent(qid, label, p31, image=None, aliases=(), sites=0, desc="", lang="en"):
    claims = {"P31": [{"mainsnak": {"datavalue": {"value": {"id": c}}}} for c in p31]}
    if image:
        claims["P18"] = [{"mainsnak": {"datavalue": {"value": image}}}]
    return {"id": qid, "labels": {lang: {"value": label}}, "descriptions": {"en": {"value": desc}} if desc else {},
            "aliases": {"en": [{"value": a} for a in aliases]}, "claims": claims,
            "sitelinks": {f"w{i}wiki": {} for i in range(sites)}}


def _fake(pages, lead=None, hits=None, people=(), seen=None, classes=(), depicted=()):
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
            return json.dumps({"query": {"pages": {"9": _page(q["titles"][0], "Public domain", 5)}}}).encode()
        if url.startswith("https://x/"):
            return b"\xff\xd8jpeg"
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
