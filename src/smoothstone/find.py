"""Find free-licensed photos of a person, animal or thing on Wikimedia Commons.

Only files under licenses that allow reuse with credit are kept (public domain, CC0, CC BY,
CC BY-SA, GODL). Every download is written to credits.txt with its author and license, so a
render or a post can name the source.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://commons.wikimedia.org/w/api.php"
AGENT = "smoothstone/0.3 (https://github.com/baney75/smoothstone; stone find)"
OK_LICENSE = re.compile(r"^(public domain|pd|cc0|cc by(-sa)? [1-4]\.0|cc by(-sa)?$|godl)", re.I)
THUMB_PX = 1280


class FindProblem(Exception):
    pass


def _get(url: str, timeout: float = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _clean(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html or "")).strip()


WIKIDATA = "https://www.wikidata.org/w/api.php"
HUMAN = "Q5"
# taxon, breed, dog breed, cat breed, horse breed, animal known by a common name, individual animal
ANIMAL = {"Q16521", "Q38829", "Q39367", "Q43577", "Q1160573", "Q55983715", "Q26401003"}
# fictional human, character, comics, film, television, animated, video game and literary character,
# mascot character
CHARACTER = {"Q15632617", "Q95074", "Q1114461", "Q15773347", "Q15773317", "Q15711870", "Q1569167",
             "Q3658341", "Q386208"}
# never what a figure is of: given and family names, disambiguation pages, genes, proteins, works
# (video game, film, television series, song, album, single, literary work) and Wikimedia lists
NOT_A_SUBJECT = {"Q12308941", "Q11879590", "Q202444", "Q101352", "Q4167410", "Q7187", "Q8054", "Q7889",
                 "Q11424", "Q5398426", "Q7366", "Q482994", "Q134556", "Q7725634", "Q13406463", "Q4167836"}
SEARCH_HITS = 15  # Batman the character is 8th or later after a city and a province
SUBJECT_WEIGHT = 1.5  # a person, animal or character is what a figure is usually of


def _wd(**params) -> dict:
    return json.loads(_get(WIKIDATA + "?" + urllib.parse.urlencode({**params, "format": "json"})))


def _entities(ids: list[str]) -> dict:
    if not ids:
        return {}
    return _wd(action="wbgetentities", ids="|".join(ids),
               props="labels|aliases|claims|sitelinks").get("entities") or {}


def _p31(ent: dict) -> set[str]:
    return {((c.get("mainsnak") or {}).get("datavalue") or {}).get("value", {}).get("id")
            for c in (ent.get("claims") or {}).get("P31", [])} - {None}


def _kind(ent: dict, character_classes: set[str] = frozenset()) -> str:
    """person, animal, character or object, from what Wikidata says the entity is an instance of
    (P31). character_classes adds classes known as characters by their label (anthropomorphic dog)."""
    p31 = _p31(ent)
    if HUMAN in p31:
        return "person"
    if p31 & (CHARACTER | set(character_classes)):
        return "character"
    return "animal" if p31 & ANIMAL else "object"


# what a class's English label says: a character, or never a figure's subject (a work, a name,
# a disease, a band, a company); a character's label wins ("film character" is a character)
CLASS_WORDS = {
    "character": re.compile(r"\b(?:character|fictional|anthropomorphic|superhero|mascot|pok\u00e9mon)\b", re.I),
    "not": re.compile(r"\b(?:film|movie|series|episode|video game|album|song|single|novel|book|franchise|"
                      r"name|surname|disambiguation|gene|protein|disease|disorder|syndrome|musical group|band|"
                      r"company|business|software|website|television program|agency|organi[sz]ation|department|"
                      r"ministry|government|institution|university|school|political party)s?\b", re.I),
}


def _classes(ents: list[dict]) -> dict[str, set[str]]:
    """{"character": classes, "not": classes} of ents, read from the classes' English labels in one
    lookup (a class already known either way is not looked up)."""
    ids = sorted(set().union(set(), *(_p31(e) for e in ents)) - CHARACTER - ANIMAL - NOT_A_SUBJECT - {HUMAN})
    out = {"character": set(), "not": set()}
    if not ids:
        return out
    got = _wd(action="wbgetentities", ids="|".join(ids[:50]), props="labels", languages="en").get("entities") or {}
    for i, e in got.items():
        label = ((e.get("labels") or {}).get("en") or {}).get("value", "")
        if CLASS_WORDS["character"].search(label):
            out["character"].add(i)
        elif CLASS_WORDS["not"].search(label):
            out["not"].add(i)
    return out


def _label(ent: dict) -> str:
    labels = ent.get("labels") or {}
    return (labels.get("en") or next(iter(labels.values()), {})).get("value", "")


def _pack(ent: dict, character_classes: set[str] = frozenset()) -> dict:
    p18 = (ent.get("claims") or {}).get("P18") or []
    image = ((p18[0].get("mainsnak") or {}).get("datavalue") or {}).get("value") if p18 else None
    return {"id": ent.get("id"), "label": _label(ent), "kind": _kind(ent, character_classes), "image": image}


def _bare(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _names(ent: dict) -> set[str]:
    """Every label and alias in every language, and the label's initials (DHH, JFK)."""
    names = {_bare(v.get("value", "")) for v in (ent.get("labels") or {}).values()}
    names |= {_bare(a.get("value", "")) for v in (ent.get("aliases") or {}).values() for a in v}
    names.add("".join(w[0] for w in re.findall(r"[A-Za-z]+", _label(ent))).lower())
    return names - {""}


def resolve(query: str) -> dict | None:
    """The Wikidata entity a figure of query means: {id, label, kind, image}, or None.

    The candidates are the name search's matches that can be a figure's subject (never a given
    name, a gene or a video game), and the people whose alias or initials are the query ("DHH"),
    never a loose text match. The best known wins, by Wikipedia sitelinks, with a person, animal or
    character weighted over a thing: "Big Ben" is the tower, not a little known man of that name,
    and "Yoda" the character, not a worm genus. Ties keep the search's order.
    """
    try:
        hits = [h["id"] for h in _wd(action="wbsearchentities", search=query, language="en",
                                     limit=str(SEARCH_HITS)).get("search") or []]
        ents = _entities(hits)
        found = _wd(action="query", list="search", srsearch=f"{query} haswbstatement:P31={HUMAN}",
                    srlimit="5").get("query", {}).get("search") or []
        people = _entities([h["title"] for h in found])
        cands = [ents[i] for i in hits if i in ents]
        have = {e.get("id") for e in cands}
        cands += [people[h["title"]] for h in found if h["title"] in people and h["title"] not in have
                  and _bare(query) in _names(people[h["title"]])]
        cls = _classes(cands)
        chars, never = cls["character"], NOT_A_SUBJECT | cls["not"]
        cands = [e for e in cands if HUMAN in _p31(e) or not (_p31(e) & never) or _p31(e) & (CHARACTER | chars)]
        if not cands:  # a gene or a given name is no subject: search by the words alone
            return None

        def score(rank_ent):
            rank, ent = rank_ent
            weight = SUBJECT_WEIGHT if _kind(ent, chars) != "object" else 1.0
            return (len(ent.get("sitelinks") or {}) * weight, -rank)
        return _pack(max(enumerate(cands), key=score)[1], chars)
    except Exception:  # offline or an odd reply: search Commons by the words alone
        return None


def main_image(query: str) -> str | None:
    """The Commons file Wikidata names as the subject's main image (P18), if any."""
    ent = resolve(query)
    return "File:" + ent["image"] if ent and ent.get("image") else None


def search(query: str, limit: int = 20, entity: dict | None | bool = True) -> list[dict]:
    """Candidate photos for query, best first. Wikidata's main image leads when there is one.

    entity is what resolve(query) gave (True: look it up here). Commons is searched by the
    entity's own name, so a nickname finds the person's photos.
    """
    ent = resolve(query) if entity is True else entity or None
    if ent and ent.get("label"):
        query = ent["label"]
    common = {"format": "json", "prop": "imageinfo",
              "iiprop": "url|size|mime|extmetadata", "iiurlwidth": str(THUMB_PX)}
    params = {"action": "query", "generator": "search", "gsrnamespace": "6",
              "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": str(limit), **common}
    try:
        data = json.loads(_get(API + "?" + urllib.parse.urlencode(params)))
        lead = "File:" + ent["image"] if ent and ent.get("image") else None
        if lead:
            one = json.loads(_get(API + "?" + urllib.parse.urlencode(
                {"action": "query", "titles": lead, **common})))
            for p in (one.get("query") or {}).get("pages", {}).values():
                if p.get("imageinfo"):
                    p["index"], p["lead"] = -100, True
                    data.setdefault("query", {}).setdefault("pages", {})["lead"] = p
    except Exception as e:  # network, http and json errors all mean the same thing here
        raise FindProblem(f"cannot reach Wikimedia Commons ({type(e).__name__})") from e
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", query)]
    out = []
    for p in (data.get("query") or {}).get("pages", {}).values():
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        lic = _clean((meta.get("LicenseShortName") or {}).get("value", ""))
        if not OK_LICENSE.match(lic) or info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        w, h = int(info.get("width", 0)), int(info.get("height", 0))
        if min(w, h) < 500:
            continue
        title = p.get("title", "")
        t = title.lower()
        score = 10 * sum(w_ in t for w_ in words) - int(p.get("index", 0))
        if all(w_ in t for w_ in words):
            score += 20
        if p.get("lead"):
            score += 100
        if any(k in t for k in ("logo", "signature", "map", "diagram", "chart")):
            score -= 50
        out.append({
            "title": title, "url": info.get("thumburl") or info.get("url"),
            "page": info.get("descriptionurl", ""), "width": w, "height": h,
            "license": lic, "author": _clean((meta.get("Artist") or {}).get("value", ""))[:120],
            "score": score,
        })
    out.sort(key=lambda c: -c["score"])
    seen, uniq = set(), []
    for c in out:  # the lead image can also come back from the search
        if c["title"] not in seen:
            seen.add(c["title"])
            uniq.append(c)
    return uniq


def fetch(query: str, dest: Path, n: int = 3) -> list[dict]:
    """Download the n best photos into dest (photo_1.jpg ...) and write credits.txt."""
    ent = resolve(query)
    found = search(query, entity=ent)
    if not found:
        raise FindProblem(f"no free-licensed photos of {query} on Wikimedia Commons")
    dest.mkdir(parents=True, exist_ok=True)
    for old in dest.glob("photo_*"):
        old.unlink()
    got = []
    for c in found:
        if len(got) >= n:
            break
        try:
            raw = _get(c["url"], timeout=60)
        except Exception:
            continue
        ext = ".png" if c["url"].lower().split("?")[0].endswith(".png") else ".jpg"
        f = dest / f"photo_{len(got) + 1}{ext}"
        f.write_bytes(raw)
        got.append({**c, "file": str(f)})
    if not got:
        raise FindProblem(f"could not download photos of {query}")
    lines = [f"{Path(g['file']).name}: {g['title'][5:]} by {g['author'] or 'unknown'}, "
             f"{g['license']}, {g['page']}" for g in got]
    (dest / "credits.txt").write_text("\n".join(lines) + "\n")
    (dest / "found.json").write_text(json.dumps({"query": query, "subject": (ent or {}).get("label") or query,
                    "kind": (ent or {}).get("kind"), "wikidata": (ent or {}).get("id"),
                    "photos": got}, indent=1))
    return got


NOUN = (r"(?:figure|figurine|statue|statuette|bust|sculpture|model|miniature|mini|replica|toy|doll|print|"
        r"keychain|ornament|chibi|version)s?")
FIGURE_OF = re.compile(rf"\b{NOUN}\s+of\s+(.+)", re.S)  # lower case: "Statue of Liberty" is a name
# the figure word a name or an animal stands just before ("a Babe Ruth figurine"); not "mini" or
# "print", which are as often a size or a verb ("a mini Elon Musk figure", "print a ... figurine")
FIGURE_AT = re.compile(r"\b(?:figure|figurine|statue|statuette|bust|sculpture|miniature|replica|toy|doll|"
                       r"keychain|ornament|chibi)s?\b")
# a pet or a relative after "my": "my dog Max" is the owner's own, only their photo shows it
KIN = {"dog", "puppy", "cat", "kitten", "pet", "horse", "pony", "bird", "parrot", "hamster", "rabbit", "bunny",
       "fish", "son", "daughter", "kid", "kids", "child", "baby", "boy", "girl", "wife", "husband", "mom", "mum",
       "mother", "dad", "father", "brother", "sister", "grandma", "grandpa", "grandmother", "grandfather",
       "uncle", "aunt", "cousin", "nephew", "niece", "friend", "boyfriend", "girlfriend", "partner", "fiance",
       "fiancee", "family"}
# words that end a lower case subject read backwards from the figure word
NOT_SUBJECT_WORDS = {"make", "print", "build", "create", "get", "give", "want", "need", "like", "love",
                                 "please", "tall", "high", "wide", "long", "mm", "cm", "inch", "inches", "in",
                                 "of", "for", "with", "and", "or", "as", "into", "i", "i'd", "i'm", "i'll", "i've",
                                 "you", "can", "could", "would", "will", "do", "send", "style", "styled"}
LIKE = re.compile(r"\b(?:looks like|look like|resembling|shaped like|like)\s+(.+?)(?=\blike\b|$)", re.S)
CAPITAL_OF = re.compile(r"\bof\s+((?:the\s+)?[A-Z].*)", re.S)
# where the subject's phrase ends: a comma, a size, "with ...", "in his ...", a quote or a bracket
PHRASE_END = re.compile(r"[,;:(\"\u201c]|\.(?:\s|$)|\d|\s(?:with|in|on|that|who|which|wearing|holding|"
                        r"standing|sitting|for|about|around|at|from|and|to)\s", re.I)
CAPS = re.compile(r"\b[A-Z][\w'.-]*(?:\s+(?:(?:of|the|de|da|di|van|von|der|del|la|le)\s+)?[A-Z][\w'.-]*){0,4}")
OWN = {"my", "our", "his", "her", "their", "your", "me", "us", "him", "them", "myself"}
FILLER = {"a", "an", "the", "one", "some", "little", "small", "tiny", "mini", "cute", "big",
          "favorite", "favourite", "famous"}


STOP = {"A", "An", "The", "My", "Me", "It", "This", "That", "Our", "Your", "Could", "Can", "Would", "Will",
        "Please", "Make", "Print", "Build", "Create", "I", "We", "Get", "Give", "Send", "Do", "Hi", "Hey",
        "Hello", "Want", "Need", "Let's", "Mini", "Little", "Small", "Tiny", "Cute"}


def _capitals(text: str, last: bool = False) -> str | None:
    """The first (or last) run of capitalized words in text, without sentence words like "A"."""
    names = [" ".join(w for w in run.split() if w not in STOP and not re.match(r"I'\w+$", w))
             for run in CAPS.findall(" " + text)]
    names = [n for n in names if n]
    return (names[-1] if last else names[0]) if names else None


def _phrase(text: str) -> str | None:
    """A subject phrase: the name in capitals in it, or its words; None for one's own (my dog)."""
    phrase = PHRASE_END.split(text, maxsplit=1)[0].strip(" .'")
    words = re.findall(r"[a-z][a-z'-]*", phrase.lower())
    own = next((i for i, w in enumerate(words) if w in OWN), None)
    if own is not None and any(w in KIN for w in words[own + 1:]):
        return None  # "my dog Max", "my son Jack"; "my favorite astronaut Neil Armstrong" is not one's own
    name = _capitals(phrase)
    if name:
        return name
    if any(w in OWN for w in words):
        return None
    words = [w for w in words if w not in FILLER][:4]
    return " ".join(words) or None


def subject_from_request(request: str) -> str | None:
    """What a figure request is of: 'A mini figure of Jensen Huang, 80 mm tall' -> 'Jensen Huang';
    'of a golden retriever' -> 'golden retriever'; 'a Babe Ruth figurine' -> 'Babe Ruth'; 'a toy that
    looks like Albert Einstein' -> 'Albert Einstein'. A name in capitals wins ('my favorite astronaut
    Neil Armstrong'); one's own pet or self ('of my dog') is None, since only the owner's photo can
    show it. An "of" that is not the figure's ('the front of the base') names nothing."""
    m = FIGURE_OF.search(request)
    if m:
        return _phrase(m.group(1))
    clauses = [re.split(r"[.?!;,:\"\u201c]", request[:m.start()])[-1] for m in FIGURE_AT.finditer(request)]
    for clause in clauses:  # a name just before the figure word, in its clause: "Michelangelo's David as a statue"
        name = _capitals(clause, last=True)
        if name:
            return name
    for m in LIKE.finditer(request):  # "looks like Albert Einstein"; a bare "like" is often a verb (I'd like)
        first = re.findall(r"[A-Za-z']+", m.group(1))[:1]
        bare = m.group(0).lower().startswith("like")
        if first and first[0].lower() not in OWN and (not bare or _capitals(PHRASE_END.split(m.group(1), 1)[0])):
            return _phrase(m.group(1))
    for clause in clauses:  # a creature just before the figure word: "a little koala figure"
        back = []
        for w in reversed(re.findall(r"[a-z0-9][a-z0-9'-]*", clause.lower())):
            if w in FILLER or w in OWN or w in NOT_SUBJECT_WORDS or w[0].isdigit() or len(back) == 3:
                break
            back.insert(0, w)
        if back:
            return " ".join(back)
    m = CAPITAL_OF.search(request)
    return _phrase(m.group(1)) if m else None
