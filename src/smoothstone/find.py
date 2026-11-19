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


def _wd(**params) -> dict:
    return json.loads(_get(WIKIDATA + "?" + urllib.parse.urlencode({**params, "format": "json"})))


def _entities(ids: list[str]) -> dict:
    if not ids:
        return {}
    return _wd(action="wbgetentities", ids="|".join(ids), props="labels|aliases|claims").get("entities") or {}


def _kind(ent: dict) -> str:
    """person, animal or object, from what Wikidata says the entity is an instance of (P31)."""
    p31 = {((c.get("mainsnak") or {}).get("datavalue") or {}).get("value", {}).get("id")
           for c in (ent.get("claims") or {}).get("P31", [])}
    return "person" if HUMAN in p31 else "animal" if p31 & ANIMAL else "object"


def _label(ent: dict) -> str:
    labels = ent.get("labels") or {}
    return (labels.get("en") or next(iter(labels.values()), {})).get("value", "")


def _pack(ent: dict) -> dict:
    p18 = (ent.get("claims") or {}).get("P18") or []
    image = ((p18[0].get("mainsnak") or {}).get("datavalue") or {}).get("value") if p18 else None
    return {"id": ent.get("id"), "label": _label(ent), "kind": _kind(ent), "image": image}


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

    A figure is of someone or some creature, so the first person or animal among the matches
    wins over a gene or a song with the same name. When none is, a nickname or initials name a
    person only when they are that person's alias or initials ("DHH"), never a loose text match.
    """
    try:
        hits = [h["id"] for h in _wd(action="wbsearchentities", search=query, language="en",
                                     limit="7").get("search") or []]
        ents = _entities(hits)
        for i in hits:
            if i in ents and _kind(ents[i]) != "object":
                return _pack(ents[i])
        found = _wd(action="query", list="search", srsearch=f"{query} haswbstatement:P31={HUMAN}",
                    srlimit="5").get("query", {}).get("search") or []
        people = _entities([h["title"] for h in found])
        for h in found:
            ent = people.get(h["title"])
            if ent and _bare(query) in _names(ent):
                return _pack(ent)
        return _pack(ents[hits[0]]) if hits and hits[0] in ents else None
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


SUBJECT = re.compile(r"\b(?:of|like|looks like|resembling|shaped like)\s+(.+)", re.S)
# where the subject's phrase ends: a comma, a size, "with ...", "in his ...", a quote or a bracket
PHRASE_END = re.compile(r"[,;:(\"\u201c]|\.(?:\s|$)|\d|\s(?:with|in|on|that|who|which|wearing|holding|"
                        r"standing|sitting|for|about|around|at|from|and|to)\s", re.I)
CAPS = re.compile(r"\b[A-Z][\w'.-]*(?:\s+(?:(?:of|the|de|da|di|van|von|der|del|la|le)\s+)?[A-Z][\w'.-]*){0,4}")
OWN = {"my", "our", "his", "her", "their", "your", "me", "us", "him", "them", "myself"}
FILLER = {"a", "an", "the", "one", "some", "little", "small", "tiny", "mini", "cute", "big",
          "favorite", "favourite", "famous"}


def subject_from_request(request: str) -> str | None:
    """'A mini figure of Jensen Huang, 80 mm tall' -> 'Jensen Huang'; 'of a golden retriever' ->
    'golden retriever'. A name in capitals wins ('my favorite astronaut Neil Armstrong'); one's
    own pet or self ('of my dog') is None, since only the owner's photo can show it."""
    m = SUBJECT.search(request)
    if not m:
        return None
    phrase = PHRASE_END.split(m.group(1), maxsplit=1)[0].strip(" .'")
    stop = {"A", "An", "The", "My", "Me", "It", "This", "That", "Our", "Your"}
    for run in CAPS.findall(" " + phrase):
        name = " ".join(w for w in run.split() if w not in stop)
        if name:
            return name
    words = re.findall(r"[a-z][a-z'-]*", phrase.lower())
    if any(w in OWN for w in words):
        return None
    words = [w for w in words if w not in FILLER][:4]
    return " ".join(words) or None
