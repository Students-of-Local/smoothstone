"""Find the best open model of a landmark that was made for printing, and credit it.

stone models "<subject>" searches Printables (no login), Wikimedia Commons' 3D files, and Sketchfab
when the person has set STONE_SKETCHFAB_TOKEN. The subject is looked up on Wikidata first, so a search
also tries its names in other languages ("Kolner Dom" for Cologne Cathedral). Candidates are ranked:
the name must be the subject's, the item must be a model of it (not a cookie cutter, keychain,
lithophane, sign or the like, unless the request asks for one), the license must allow printing it
for oneself, then the most liked, made and downloaded first.

stone models --take <n> downloads the n-th into the job, writes credits.txt, merges and repairs the
mesh, stands it upright, and makes it the job's part. stone build then fits it to the printer
(modelprint.py).

The Printables API is undocumented: every reply is cached in the job, and any error or change fails
softly with a line that says Printables could not be searched and why.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

AGENT = "smoothstone/0.3 (https://github.com/baney75/smoothstone; stone models)"
PRINTABLES = "https://api.printables.com/graphql/"
SKETCHFAB = "https://api.sketchfab.com/v3"
COMMONS = "https://commons.wikimedia.org/w/api.php"
SKETCHFAB_VAR = "STONE_SKETCHFAB_" + "TOKEN"  # the person's own Sketchfab API key; never printed
SEARCH_LIMIT = 20
MAX_TERMS = 4  # names searched on Printables: the subject as typed, its label, and others
MAX_DOWNLOAD = 200 * 1024 * 1024  # bytes, every file of one model together
SHOW = 5  # candidates printed
# Wikidata label languages searched besides English: the languages most landmark models are named in
LANGS = ("en", "de", "fr", "es", "it", "ca", "pt", "nl", "pl", "cs")

SEARCH_Q = ("query S($q: String!, $n: Int) { searchPrints2(query: $q, limit: $n) { items { id name summary "
            "premium price likesCount downloadCount makesCount license { name abbreviation } "
            "user { publicUsername } category { path { name } } } } }")
FILES_Q = ("query P($id: ID!) { print(id: $id) { id name license { name abbreviation } "
           "stls { id name fileSize } user { publicUsername } } }")
LINK_Q = ("mutation L($id: ID!, $pid: ID!) { getDownloadLink(id: $id, printId: $pid, fileType: stl, "
          "source: model_detail) { ok output { link } errors { code } } }")

# what an item is when it is not a model of the landmark: a word in its name (or category) says so
NOT_A_MODEL = [
    ("cookie cutter", r"cookie|cutter"),
    ("keychain", r"key ?chain|key ?ring|key fob"),
    ("lithophane", r"lithophane"),
    ("beer tap", r"\btap\b|tap handle|kolsch|beer"),
    ("stamp", r"\bstamps?\b"),
    ("sign", r"\bsigns?\b|signage|\blogo\b|plaque|badge|emblem|coaster|wall art|wall decoration|wall-mounted|"
             r"hueforge|stained glass|\brelief\b|magnet|2d plates|\bplates? & logos"),
    ("ornament", r"ornament|christmas|bauble"),
    ("remix part", r"\bremix|replacement|\bspare\b|adapter|upgrade|prusa parts|\broof\b|\bdoor\b|rose window|"
                   r"\bwindow\b|\bfacade only\b"),
    ("lamp", r"\blamp\b|\blight(?:ing)?\b|\bled\b|night ?light"),
    ("game piece", r"puzzle|gravitrax|board game|game pieces?|chess|tensegrity|impossible"),
    ("brick set", r"\blego\b|\bduplo\b|kosti\u010dk"),
    ("map", r"\bmap\b|\bcity\b|skyline|1/\d{3,}"),
    ("bust", r"\bbust\b"),
    ("vase", r"\bvase\b|planter|pen holder|\bholder\b|\bbox\b|bookend|egg ?cup|\bmug\b"),
    ("costume", r"carnival|costume|accessory"),
    ("tag", r"\btag\b|etiqueta|label"),
]
# a model said to be for resin printers: stone's printers are FDM, so it ranks lower
RESIN = re.compile(r"\b(?:sla|resin|msla|dlp)\b", re.I)
FDM = re.compile(r"\bfdm\b", re.I)
# licenses that allow printing a copy for oneself
OPEN_LICENSE = re.compile(r"creative commons|\bcc\b|cc-|cc0|public domain|\bgpl|\blgpl|\bbsd\b|\bmit\b|"
                          r"standard digital file|free standard|\bstandard\b", re.I)


class ModelsProblem(Exception):
    pass


def plain(text: str) -> str:
    """stone's lines carry no long dashes and no stray spaces."""
    t = str(text or "").replace("\u2013", "-").replace("\u2014", "-").replace("\u2015", "-")
    return re.sub(r"\s+", " ", t).strip()


def bare(text: str) -> str:
    """Lower case letters and digits only, accents dropped: Kolner Dom and Koelner-Dom compare."""
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", t.lower())


def words(text: str) -> list[str]:
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z0-9]+", t)


# the network: one function, so tests play recorded replies back


def http(url: str, body: dict | None = None, headers: dict | None = None, timeout: float = 60) -> bytes:
    h = {"User-Agent": AGENT, **(headers or {})}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def cached(cache: Path | None, key: str, fetch):
    """fetch() once per key in this job: a reply the person saw is the one --take acts on."""
    f = None
    if cache is not None:
        f = cache / (hashlib.sha256(key.encode()).hexdigest()[:20] + ".json")
        if f.is_file():
            try:
                return json.loads(f.read_text())
            except ValueError:
                pass
    got = fetch()
    if f is not None:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(got))
    return got


def gql(query: str, variables: dict, cache: Path | None = None) -> dict:
    def fetch():
        d = json.loads(http(PRINTABLES, {"query": query, "variables": variables}))
        if d.get("errors") and not d.get("data"):
            raise ModelsProblem("the Printables API answered with an error: "
                                + plain(str(d["errors"][0].get("message", "")))[:120])
        return d.get("data") or {}
    return cached(cache, "printables " + query + json.dumps(variables, sort_keys=True), fetch)


# the subject's names


def names(subject: str) -> dict:
    """{label, wikidata, kind, description, names: every Latin name and alias}, from Wikidata.
    Offline or not found: the subject's own words."""
    from . import find

    out = {"label": subject, "wikidata": None, "kind": None, "description": "", "names": [subject]}
    try:
        ent = find.resolve(subject)
        if not ent or not ent.get("id"):
            return out
        full = find._entities([ent["id"]]).get(ent["id"]) or {}
    except Exception:  # offline or an odd reply: search by the words alone
        return out
    got = [subject, ent.get("label") or subject]
    labels = full.get("labels") or {}
    for lang in LANGS:
        v = (labels.get(lang) or {}).get("value")
        if v:
            got.append(v)
    for lang in ("en", "mul"):
        got += [a.get("value", "") for a in (full.get("aliases") or {}).get(lang, [])]
    seen, keep = set(), []
    for n in got:
        n = plain(n)
        if not n or not bare(n) or bare(n) in seen:
            continue  # a name in another script has no Latin letters and searches nothing
        seen.add(bare(n))
        keep.append(n)
    out.update({"label": plain(ent.get("label") or subject), "wikidata": ent["id"], "kind": ent.get("kind"),
                "description": plain(ent.get("description") or ""), "names": keep})
    return out


def search_terms(nm: dict) -> list[str]:
    """The names to search: the subject, its label, then the other languages' names, one each."""
    out, seen = [], set()
    for n in nm["names"]:
        k = " ".join(words(n))
        if k and k not in seen:
            seen.add(k)
            out.append(n)
    return out[:MAX_TERMS]


# the sources


def printables_search(terms: list[str], cache: Path | None) -> tuple[list[dict], str | None]:
    """Candidates from Printables for every term, and None or why it could not be searched."""
    items, why = {}, None
    for t in terms:
        try:
            got = (gql(SEARCH_Q, {"q": t, "n": SEARCH_LIMIT}, cache).get("searchPrints2") or {}).get("items")
            if not isinstance(got, list):
                raise ModelsProblem("the search reply has no items (the API may have changed)")
        except Exception as e:  # the API is undocumented: any change fails softly
            why = why or _why(e)
            continue
        for it in got:
            if isinstance(it, dict) and it.get("id") and str(it["id"]) not in items:
                items[str(it["id"])] = it
    if items:
        why = None  # one term answered: Printables was searched
    out = []
    for it in items.values():
        lic = it.get("license") or {}
        out.append({
            "source": "printables", "id": str(it["id"]), "name": plain(it.get("name")),
            "summary": plain(it.get("summary"))[:200], "author": plain((it.get("user") or {}).get("publicUsername")),
            "license": plain(lic.get("name")), "license_code": plain(lic.get("abbreviation")),
            "likes": int(it.get("likesCount") or 0), "makes": int(it.get("makesCount") or 0),
            "downloads": int(it.get("downloadCount") or 0),
            "category": "/".join(plain(c.get("name")) for c in ((it.get("category") or {}).get("path") or [])),
            "paid": bool(it.get("premium")) or bool(it.get("price")),
            "url": f"https://www.printables.com/model/{it['id']}",
            "made_for_printing": True,
        })
    return out, why


def _why(e: Exception) -> str:
    if isinstance(e, ModelsProblem):
        return str(e)
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    if isinstance(e, (urllib.error.URLError, OSError)):
        return f"no connection ({type(e).__name__})"
    if isinstance(e, (ValueError, KeyError, TypeError, AttributeError)):
        return f"an unexpected reply ({type(e).__name__})"
    return type(e).__name__


def commons_search(terms: list[str], cache: Path | None) -> tuple[list[dict], str | None]:
    """STL files on Wikimedia Commons named for the subject."""
    from . import find

    out, why = {}, None
    for t in terms[:2]:
        q = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": "6",
             "gsrsearch": f'"{t}" filetype:3d', "gsrlimit": "10", "prop": "imageinfo",
             "iiprop": "url|size|mime|extmetadata"}
        url = COMMONS + "?" + urllib.parse.urlencode(q)
        try:
            d = cached(cache, url, lambda: json.loads(http(url)))
        except Exception as e:
            why = why or _why(e)
            continue
        for p in ((d.get("query") or {}).get("pages") or {}).values():
            info = (p.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata") or {}
            title = plain(p.get("title", ""))
            if title in out or not info.get("url"):
                continue
            out[title] = {
                "source": "commons", "id": title, "name": re.sub(r"^File:|\.stl$", "", title, flags=re.I),
                "summary": "", "author": plain(find._clean((meta.get("Artist") or {}).get("value", "")))[:80],
                "license": plain(find._clean((meta.get("LicenseShortName") or {}).get("value", ""))),
                "license_code": "", "likes": 0, "makes": 0, "downloads": 0, "category": "",
                "paid": False, "url": info.get("descriptionurl", ""), "made_for_printing": True,
                "files": [{"id": info["url"], "name": title[5:], "size": int(info.get("size") or 0)}],
            }
    return list(out.values()), (None if out else why)


def sketchfab_search(terms: list[str], cache: Path | None) -> tuple[list[dict], str | None]:
    """Downloadable Sketchfab models; searched only with the person's own key, which download needs."""
    if not os.environ.get(SKETCHFAB_VAR):
        return [], None
    out, why = {}, None
    for t in terms[:2]:
        url = SKETCHFAB + "/search?" + urllib.parse.urlencode({"type": "models", "q": t, "downloadable": "true",
                                                               "count": "12"})
        try:
            d = cached(cache, url, lambda: json.loads(http(url)))
        except Exception as e:
            why = why or _why(e)
            continue
        for r in d.get("results") or []:
            if not r.get("uid") or r["uid"] in out:
                continue
            out[r["uid"]] = {
                "source": "sketchfab", "id": r["uid"], "name": plain(r.get("name")), "summary": "",
                "author": plain((r.get("user") or {}).get("username")),
                "license": plain((r.get("license") or {}).get("label")), "license_code": "",
                "likes": int(r.get("likeCount") or 0), "makes": 0, "downloads": int(r.get("viewCount") or 0) // 20,
                "category": "", "paid": bool(r.get("price")), "faces": int(r.get("faceCount") or 0),
                "url": f"https://sketchfab.com/3d-models/{r['uid']}", "made_for_printing": False,
            }
    return list(out.values()), (None if out else why)


# ranking


def name_match(c: dict, nm: dict) -> int:
    """2: one of the subject's names is in the item's name; 1: all its words are; 0: neither."""
    item = bare(c["name"])
    iw = set(words(c["name"]))
    best = 0
    for n in nm["names"]:
        b = bare(n)
        if len(b) >= 4 and b in item:
            return 2
        w = [x for x in words(n) if x not in ("the", "of", "de", "la", "le", "st", "saint")]
        if w and all(x in iw for x in w):
            best = 1
    return best


def not_a_model(c: dict, request: str) -> str | None:
    """The kind of thing the item is when it is not a model of the landmark, else None."""
    text = (c["name"] + " | " + c.get("category", "")).lower()
    asked = request.lower()
    for kind, pat in NOT_A_MODEL:
        if re.search(pat, text) and not re.search(pat, asked):
            return kind
    return None


def license_ok(c: dict) -> bool:
    return bool(c.get("license")) and bool(OPEN_LICENSE.search(c["license"] + " " + c.get("license_code", "")))


def license_short(c: dict) -> str:
    code = c.get("license_code") or ""
    lic = c.get("license") or ""
    if code:
        return "CC0 (public domain)" if code == "CC0" else code.replace("CC-BY", "CC BY")
    m = re.sub(r"creative commons\s*-?\s*", "CC ", lic, flags=re.I)
    for a, b in (("Attribution", "BY"), ("NonCommercial", "NC"), ("Noncommercial", "NC"), ("ShareAlike", "SA"),
                 ("Share Alike", "SA"), ("NoDerivatives", "ND"), ("No Derivatives", "ND")):
        m = m.replace(a, b)
    return re.sub(r"\s*-\s*", "-", re.sub(r"\s+", " ", m)).replace("CC-", "CC ").strip()


def license_note(c: dict) -> str | None:
    """A plain note when the license limits what the person may do with the print or the files."""
    t = (c.get("license", "") + " " + c.get("license_code", "")).lower()
    nc = "noncommercial" in t or "non-commercial" in t or "-nc" in t
    nd = "noderiv" in t or "no deriv" in t or "-nd" in t
    std = "standard" in t and not nc
    if nc and nd:
        return ("noncommercial, no derivatives: scaling and splitting it for your own print is fine; "
                "you may not sell the print, or share or sell the changed files")
    if nc:
        return "noncommercial: print it for yourself; you may not sell the print or the files"
    if nd:
        return "no derivatives: scaling and splitting it for your own print is fine; do not share the changed files"
    if std:
        return "standard license: print it for yourself; do not share or sell the files"
    return None


def popularity(c: dict) -> float:
    p = c["likes"] + 5 * c["makes"] + c["downloads"] / 50
    text = c["name"] + " " + c.get("summary", "")
    if RESIN.search(text) and not FDM.search(text):
        p *= 0.5  # made for resin printers: thin rods an FDM nozzle cannot draw
    return p


SOURCE_ORDER = {"printables": 0, "commons": 1, "sketchfab": 2}


def rank(cands: list[dict], nm: dict, request: str) -> tuple[list[dict], list[dict]]:
    """(kept best first, left out with "why")."""
    kept, out = [], []
    for c in cands:
        m = name_match(c, nm)
        why = None
        if m == 0:
            why = "another subject"
        elif (k := not_a_model(c, request)):
            why = k
        elif c.get("paid"):
            why = "a paid model"
        elif not license_ok(c):
            why = f"license {c.get('license') or 'unknown'}"
        c = {**c, "match": m}
        if why:
            out.append({**c, "why": why})
        else:
            kept.append(c)
    kept.sort(key=lambda c: (SOURCE_ORDER.get(c["source"], 9), -popularity(c), -c["match"]))
    return kept, out


def clear_lead(kept: list[dict]) -> bool:
    """The first model is the plain pick: named for the subject, licensed for a personal print, and
    ahead of every other on both makes and likes (a model many people printed). Then stone models
    takes it itself, and the list stays for a person who wants another."""
    if not kept:
        return False
    top = kept[0]
    rest = kept[1:]
    return (top.get("match") == 2 and license_ok(top) and top["source"] == "printables"
            and all(top["makes"] > c["makes"] and top["likes"] > c["likes"] for c in rest))


def search(subject: str, request: str, cache: Path | None) -> dict:
    """Everything stone models prints and --take reads: names, ranked candidates, what each source said."""
    nm = names(subject)
    terms = search_terms(nm)
    p, pwhy = printables_search(terms, cache)
    c, cwhy = commons_search(terms[:2], cache)
    s, swhy = sketchfab_search(terms[:2], cache)
    kept, out = rank(p + c + s, nm, request)
    for k in kept[:SHOW]:  # the file count and size the person sees in the list
        if k["source"] == "printables" and k.get("files") is None:
            try:
                k["files"] = printables_files(k, cache)
            except Exception:  # listed without it; --take asks again
                k["files"] = None
    return {"subject": subject, "names": nm, "terms": terms, "kept": kept, "left_out": out,
            "sources": {"printables": {"found": len(p), "why": pwhy},
                        "commons": {"found": len(c), "why": cwhy},
                        "sketchfab": {"found": len(s), "why": swhy,
                                      "searched": bool(os.environ.get(SKETCHFAB_VAR))}}}


def size_text(n: int) -> str:
    return f"{n / 1e6:.1f} MB" if n >= 1e5 else f"{n / 1e3:.0f} KB"


def candidate_line(i: int, c: dict) -> str:
    files = c.get("files")
    nfiles = f"{len(files)} file{'s' if len(files) != 1 else ''} {size_text(sum(f['size'] for f in files))}, " \
        if files else ""
    pop = (f"{c['likes']} likes, {c['makes']} makes, {c['downloads']} downloads"
           if c["source"] != "commons" else "Wikimedia Commons")
    return (f"{i}. {c['name']} by {c['author'] or 'unknown'}, {license_short(c)}, {nfiles}{pop} "
            f"({c['url']})")


# files


def printables_files(c: dict, cache: Path | None) -> list[dict]:
    d = gql(FILES_Q, {"id": c["id"]}, cache).get("print") or {}
    stls = d.get("stls")
    if not isinstance(stls, list):
        raise ModelsProblem("the model's file list has no STL files (the API may have changed)")
    return [{"id": str(s["id"]), "name": plain(s.get("name")), "size": int(s.get("fileSize") or 0)}
            for s in stls if s.get("id")]


def printables_link(c: dict, f: dict) -> str:
    d = json.loads(http(PRINTABLES, {"query": LINK_Q, "variables": {"id": f["id"], "pid": c["id"]}}))
    g = (d.get("data") or {}).get("getDownloadLink") or {}
    link = (g.get("output") or {}).get("link")
    if not g.get("ok") or not link:
        codes = ", ".join(str(e.get("code")) for e in g.get("errors") or []) or "no link"
        raise ModelsProblem(f"Printables gave no download link for {f['name']} ({codes})")
    return link


# a file that is not the model itself: a crane, a pin, a support, a test print
ACCESSORY = re.compile(r"crane|\bpins?\b|\bpegs?\b|support|\btest\b|calibrat|keychain|stand ?only|logo|sign|"
                       r"\bbrim\b|\braft\b|gcode", re.I)
WHOLE = re.compile(r"complete|full|whole|assembled|entire|all[-_ ]?in[-_ ]?one|one[-_ ]?piece|single", re.I)


YEAR = re.compile(r"(?:19|20)\d\d")


def _year_twin(f: dict, files: list[dict]) -> dict | None:
    """The newest other file that differs from f only by a year (2014-eiffel and 2022-eiffel are
    two versions of one model, not two parts of it), when f is not the newest."""
    if not YEAR.search(f["name"]):
        return None
    key = bare(YEAR.sub("", f["name"]))
    same = [g for g in files if YEAR.search(g["name"]) and bare(YEAR.sub("", g["name"])) == key]
    if len(same) < 2:
        return None
    newest = max(same, key=lambda g: (max(int(y) for y in YEAR.findall(g["name"])), g["size"]))
    return None if newest is f else newest


def choose_files(files: list[dict]) -> tuple[list[dict], list[tuple[dict, str]]]:
    """(files to merge, [(file, why left out)]). A file named complete or whole is the model on its
    own; accessories (a crane, pins, supports) are left out; a fixed or repaired copy wins over the
    original of the same name."""
    stl = [f for f in files if f["name"].lower().endswith((".stl", ".obj", ".3mf", ".glb", ".gltf", ".zip"))]
    left: list[tuple[dict, str]] = [(f, "not a mesh file") for f in files if f not in stl]
    whole = [f for f in stl if WHOLE.search(f["name"])]
    if whole:
        pick = max(whole, key=lambda f: f["size"])
        return [pick], left + [(f, f"{pick['name']} is the whole model") for f in stl if f is not pick]
    keep = []
    for f in stl:
        if ACCESSORY.search(f["name"]) and len(stl) > 1:
            left.append((f, "an accessory, not the model"))
        elif (twin := _year_twin(f, stl)) is not None:
            left.append((f, f"{twin['name']} is the same model in another year's version"))
        else:
            keep.append(f)
    fixed = [f for f in keep if re.search(r"repair|fixed", f["name"], re.I)]
    if fixed:
        base = {bare(re.sub(r"repaired|fixed", "", f["name"], flags=re.I)) for f in fixed}
        for f in list(keep):
            if f not in fixed and bare(f["name"]) in base:
                keep.remove(f)
                left.append((f, "a repaired copy is kept instead"))
    return keep, left


def download(c: dict, files: list[dict], dest: Path) -> list[Path]:
    dest.mkdir(parents=True, exist_ok=True)
    total = sum(f["size"] for f in files)
    if total > MAX_DOWNLOAD:
        raise ModelsProblem(f"the files are {size_text(total)}, more than stone downloads "
                            f"({size_text(MAX_DOWNLOAD)})")
    out = []
    for f in files:
        name = re.sub(r"[^\w.+-]+", "_", f["name"]) or "model.stl"
        if c["source"] == "sketchfab":
            name = "model.zip"
        p = dest / name
        if not p.is_file() or (f["size"] and c["source"] != "sketchfab" and p.stat().st_size != f["size"]):
            if c["source"] == "printables":
                url = printables_link(c, f)
            elif c["source"] == "sketchfab":
                url = sketchfab_link(c)
            else:
                url = f["id"]
            p.write_bytes(http(url, timeout=600))
        out.append(p)
    return out


def sketchfab_link(c: dict) -> str:
    key = os.environ.get(SKETCHFAB_VAR)
    if not key:
        raise ModelsProblem(f"Sketchfab downloads need your own API key in {SKETCHFAB_VAR}")
    d = json.loads(http(f"{SKETCHFAB}/models/{c['id']}/download", headers={"Authorization": "Token " + key}))
    url = (d.get("gltf") or d.get("glb") or {}).get("url")
    if not url:
        raise ModelsProblem("Sketchfab gave no download link for this model")
    return url


def _3mf_matrix(text: str | None) -> np.ndarray:
    """A 3MF transform ("m00 m01 m02 m10 ... m32", rows of a 4x3) as a 4x4 for column vectors."""
    M = np.eye(4)
    if text:
        v = [float(x) for x in text.split()]
        M[:3, :4] = np.array(v, float).reshape(4, 3).T
    return M


def read_3mf(path: Path):
    """The build items of a 3MF file as one mesh, read with the standard library (trimesh's own
    reader needs lxml, which stone does not ship): each object's triangles, its components and
    the build's transforms."""
    import xml.etree.ElementTree as ET

    import trimesh

    with zipfile.ZipFile(path) as z:
        models = {n: ET.fromstring(z.read(n)) for n in z.namelist() if n.lower().endswith(".model")}
    if not models:
        raise ModelsProblem(f"{path.name} holds no 3D model")
    objects: dict[tuple[str, str], object] = {}
    for name, root in models.items():
        ns = root.tag[:root.tag.index("}") + 1] if root.tag.startswith("{") else ""
        for ob in root.iter(ns + "object"):
            objects[("/" + name.lstrip("/"), ob.get("id"))] = (ob, ns)
    main = next((n for n in models if n.lower().endswith("3dmodel.model") and "/3d/" in "/" + n.lower()),
                next(iter(models)))

    def mesh_of(key, depth=0):
        if depth > 8 or key not in objects:
            return []
        ob, ns = objects[key]
        out = []
        mesh = ob.find(ns + "mesh")
        if mesh is not None:
            v = np.array([[float(e.get(a)) for a in "xyz"] for e in mesh.find(ns + "vertices")], float)
            f = np.array([[int(e.get(a)) for a in ("v1", "v2", "v3")] for e in mesh.find(ns + "triangles")], np.int64)
            if len(v) and len(f):
                out.append((v, f))
        comps = ob.find(ns + "components")
        for c in (comps if comps is not None else []):
            ref = c.get("{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}path") or key[0]
            M = _3mf_matrix(c.get("transform"))
            for v, f in mesh_of(("/" + ref.lstrip("/"), c.get("objectid")), depth + 1):
                out.append((v @ M[:3, :3].T + M[:3, 3], f))
        return out

    root = models[main]
    ns = root.tag[:root.tag.index("}") + 1] if root.tag.startswith("{") else ""
    parts = []
    for item in root.iter(ns + "item"):
        M = _3mf_matrix(item.get("transform"))
        for v, f in mesh_of(("/" + main.lstrip("/"), item.get("objectid"))):
            parts.append(trimesh.Trimesh(v @ M[:3, :3].T + M[:3, 3], f, process=False))
    if not parts:
        raise ModelsProblem(f"{path.name} has no triangles in its build")
    return trimesh.util.concatenate(parts)


def load_mesh(paths: list[Path]):
    """Every file's triangles in one mesh. A glTF zip (Sketchfab) is opened in memory."""
    import trimesh

    parts = []
    for p in paths:
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as z:
                gl = next((n for n in z.namelist() if n.lower().endswith((".gltf", ".glb"))), None)
                if gl is None:
                    raise ModelsProblem(f"{p.name} holds no glTF model")
                raw = z.read(gl)
            scene = trimesh.load(io.BytesIO(raw), file_type=gl.rsplit(".", 1)[1],
                                 resolver=trimesh.resolvers.ZipResolver(io.BytesIO(p.read_bytes())))
            m = scene.dump(concatenate=True) if hasattr(scene, "dump") else scene
        elif p.suffix.lower() == ".3mf":
            m = read_3mf(p)
        else:
            m = trimesh.load(str(p), force="mesh")
        if isinstance(m, trimesh.Trimesh) and len(m.faces):
            parts.append(trimesh.Trimesh(m.vertices, m.faces, process=False))
    if not parts:
        raise ModelsProblem("no triangles in the model's files")
    return trimesh.util.concatenate(parts)


# repair


def _manifold(v, f):
    import manifold3d as m3

    g = m3.Mesh(vert_properties=np.asarray(v, np.float32), tri_verts=np.asarray(f, np.uint32))
    g.merge()
    man = m3.Manifold(g)
    if man.status() != m3.Error.NoError or man.volume() <= 0:
        return None
    return man


def voxel_body(b, pitch: float):
    """A closed copy of a body whose surface has holes or torn edges: filled where rays along two of
    the three axes agree it is inside, then its surface traced (marching cubes). Detail finer than
    pitch is smoothed."""
    from skimage import measure

    lo, hi = b.bounds
    lo = lo - 2 * pitch
    n = np.maximum(np.ceil((hi + 2 * pitch - lo) / pitch).astype(int), 3)
    votes = np.zeros(tuple(int(x) for x in n), np.uint8)
    for ax in range(3):
        u, v = [a for a in range(3) if a != ax]
        cu = lo[u] + (np.arange(n[u]) + 0.5) * pitch
        cv = lo[v] + (np.arange(n[v]) + 0.5) * pitch
        U, V = np.meshgrid(cu, cv, indexing="ij")
        org = np.zeros((U.size, 3))
        org[:, u], org[:, v], org[:, ax] = U.ravel(), V.ravel(), lo[ax] - 1
        d = np.zeros_like(org)
        d[:, ax] = 1
        try:
            loc, ri, _ = b.ray.intersects_location(org, d, multiple_hits=True)
        except Exception:
            continue
        if not len(ri):
            continue
        order = np.lexsort((loc[:, ax], ri))
        loc, ri = loc[order], ri[order]
        cells = lo[ax] + (np.arange(n[ax]) + 0.5) * pitch
        starts = np.r_[0, np.flatnonzero(np.diff(ri)) + 1, len(ri)]
        for a, e in zip(starts[:-1], starts[1:]):
            z = loc[a:e, ax]
            z = z[np.r_[True, np.diff(z) > 1e-9]]
            if len(z) % 2:
                z = z[:-1]
            i, j = divmod(int(ri[a]), int(n[v]))
            for z0, z1 in zip(z[0::2], z[1::2]):
                k0, k1 = np.searchsorted(cells, [z0, z1])
                sl = [0, 0, 0]
                sl[u], sl[v], sl[ax] = i, j, slice(int(k0), int(k1))
                votes[tuple(sl)] += 1
    solid = votes >= 2
    if solid.sum() < 8:
        return None
    vol = np.pad(solid, 1).astype(np.float32)
    verts, faces, _, _ = measure.marching_cubes(vol, 0.5)
    verts = (verts - 1) * pitch + lo + pitch / 2
    man = _manifold(verts, faces[:, ::-1]) or _manifold(verts, faces)
    return man.simplify(pitch / 4) if man is not None else None  # marching cubes' flat runs of tiny faces


def repair(mesh, log: list[str]):
    """One closed 2-manifold from a downloaded mesh: each body is closed (holes filled, torn ones
    rebuilt from voxels), loose faces dropped, and every body united. Each change is a line in log."""
    import manifold3d as m3
    import trimesh

    m = trimesh.Trimesh(mesh.vertices, mesh.faces, process=True)
    diag = float(np.linalg.norm(m.extents)) or 1.0
    bodies = m.split(only_watertight=False)
    total_area = float(m.area) or 1.0
    good, filled, voxeled, dropped = [], 0, 0, 0
    for b in bodies:
        man = _manifold(b.vertices, b.faces)
        if man is None:
            c = b.copy()
            c.merge_vertices()
            c.update_faces(c.nondegenerate_faces())
            c.update_faces(c.unique_faces())
            c.remove_unreferenced_vertices()
            if len(c.faces) >= 4:
                trimesh.repair.fix_normals(c)
                trimesh.repair.fill_holes(c)
                man = _manifold(c.vertices, c.faces)
                if man is not None:
                    filled += 1
            if man is None and len(c.faces) >= 4 and c.area / total_area > 1e-4:
                man = voxel_body(c, diag / 900)
                if man is not None:
                    voxeled += 1
        if man is None or man.volume() < (diag / 2000) ** 3:
            dropped += 1
            continue
        good.append(man)
    if not good:
        raise ModelsProblem("no closed body could be made from the model's surface")
    whole = m3.Manifold.batch_boolean(good, m3.OpType.Add) if len(good) > 1 else good[0]
    pieces = whole.decompose()
    if len(pieces) > 1:
        # crumbs the union left (or tiny loose bits of the model) cannot print on their own
        big = max(p.volume() for p in pieces)
        keep = [p for p in pieces if p.volume() >= big * 1e-4]
        if len(keep) < len(pieces):
            log.append(f"Left out {len(pieces) - len(keep)} loose crumbs too small to print.")
        whole = m3.Manifold.compose(keep)
    if len(bodies) > 1:
        n = len(whole.decompose())
        log.append(f"Joined {len(bodies)} bodies into {n}." if n > 1 else f"Joined {len(bodies)} bodies into one.")
    if filled:
        log.append(f"Closed the holes in {filled} bodies.")
    if voxeled:
        log.append(f"Rebuilt {voxeled} torn bodies as closed solids (detail under {diag / 900:.2g} model units "
                   "is smoothed).")
    if dropped:
        log.append(f"Dropped {dropped} loose faces or slivers with no volume.")
    o = whole.to_mesh()
    return trimesh.Trimesh(np.asarray(o.vert_properties[:, :3], float), np.asarray(o.tri_verts, np.int64),
                           process=False)


def upright(mesh, log: list[str]):
    """Stand the model on its base: the side with the most flat area at its extreme goes down.
    The file's own up stays unless another side is clearly the base (an export with y up)."""
    import trimesh

    flat = {}
    normals, areas, tris = mesh.face_normals, mesh.area_faces, mesh.triangles
    for ax in range(3):
        for sgn in (-1, 1):
            d = np.zeros(3)
            d[ax] = sgn
            proj = tris[:, :, ax] * sgn
            ext = proj.max()
            tol = 0.004 * float(np.ptp(mesh.vertices[:, ax]) or 1)
            on = (normals @ d > 0.99) & (proj.min(axis=1) >= ext - tol)
            flat[(ax, sgn)] = float(areas[on].sum())
    down = (2, -1)
    best = max(flat, key=flat.get)
    mesh = mesh.copy()
    if best != down and flat[best] > 2.0 * flat[down] and flat[best] > 0:
        ax, sgn = best
        d = np.zeros(3)
        d[ax] = sgn
        mesh.apply_transform(trimesh.geometry.align_vectors(d, [0, 0, -1]))
        name = "xyz"[ax]
        log.append(f"Stood it on its base: the file's {'-' if sgn < 0 else '+'}{name} side is its flat bottom.")
    mesh.apply_translation(-mesh.bounds[0])
    return mesh


def credits_text(c: dict, files: list[dict]) -> str:
    lines = [f"{c['name']} by {c['author'] or 'unknown'}",
             f"License: {license_short(c)} ({c['license']})",
             f"Source: {c['url']}",
             "Files: " + ", ".join(f["name"] for f in files)]
    note = license_note(c)
    if note:
        lines.append("License note: " + note + ".")
    lines.append("Changed by smoothstone for one person's own print: repaired, scaled, and split into parts "
                 "with pin holes when it does not fit the bed.")
    return "\n".join(lines) + "\n"


# where the job keeps it


def found_file(job_root: Path) -> Path:
    return Path(job_root) / "models" / "found.json"


def model_file(job_root: Path) -> Path:
    return Path(job_root) / "model" / "model.json"


def taken(job_root: Path) -> dict | None:
    from .job import read_json

    m = read_json(model_file(job_root))
    return m if isinstance(m, dict) and m.get("stl") else None


# what a request asks for


BUILDING = re.compile(r"\b(?:cathedral|basilica|church|chapel|abbey|minster|duomo|dom|mosque|temple|shrine|"
                      r"pagoda|tower|castle|palace|fortress|fort|citadel|bridge|colosseum|coliseum|amphitheat\w*|"
                      r"pyramids?|monument|memorial|lighthouse|skyscraper|building|landmark|arch|gate|"
                      r"stadium|opera house|capitol|parliament|mausoleum|tomb|kremlin|cathedrale|kathedrale|"
                      r"catedral|sagrada|mahal|notre)\b", re.I)
# "find me a model of", "download a model", "an open model", "on Printables": the person wants a made model
FILE_WORD = r"(?:models?|stls?|3mfs?|files?|meshe?s?)"
FIND_MODEL = re.compile(r"\b(?:find|download|get|grab)(?:\s+me)?\s+(?:an?\s+|the\s+)?(?:(?!my\b|your\b|our\b|his\b|her\b|their\b)[\w-]+\s+){0,2}" + FILE_WORD + r"\b|"
                        r"\b(?:existing|open|someone['’]s)\s+" + FILE_WORD + r"\b|"
                        r"\b(?:on|from)\s+(?:printables|thingiverse|myminifactory|cults3?d?)\b", re.I)
PRINT_WORDS = {"A", "An", "The", "Make", "Print", "Build", "I", "My", "Please", "Model", "Replica",
               "Find", "Download", "Get", "Grab", "STL", "Printables", "Thingiverse"}


# "St. Basil's Cathedral": the period is an abbreviation's, not the end of the subject
ABBREV = re.compile(r"\b(St|Ste|Mt|Ft)\.\s+(?=[A-Z])")
ABBREVS = {"st": "Saint", "ste": "Sainte", "mt": "Mount", "ft": "Fort"}


def subject_of(request: str) -> str | None:
    """The landmark a request names, or None: 'a model of Cologne Cathedral that fits my 220 mm bed'
    gives 'Cologne Cathedral', 'a 300 mm tall Sagrada Familia' gives 'Sagrada Familia'."""
    from . import find

    req = ABBREV.sub(lambda m: ABBREVS[m.group(1).lower()] + " ", request.replace("’", "'"))
    req = re.sub(r"^\s*(?:can|could|would) you\s+(?:please\s+)?", "", req, flags=re.I)
    m = re.search(r"\b(?:model|replica|miniature|version|print|stl|3mf|file|mesh)(?:e?s)?\s+of\s+(?:the\s+)?(.+)", req, re.I)
    if m:
        s = find._phrase(m.group(1))
        if s:
            return s.strip(" ,.")
    caps = find._capitals(req)
    if caps:
        caps = " ".join(w for w in caps.split() if w not in PRINT_WORDS)
        caps = re.sub(r"^(?:the|a|an)\s+", "", caps.strip(" ,."), flags=re.I)
        if caps:
            return caps
    m = re.search(r"\b((?:\w+\s+){0,2}(?:cathedral|basilica|tower|castle|palace|temple|bridge|mosque))\b", req, re.I)
    if m:
        w = [x for x in m.group(1).split() if x.lower() not in ("a", "an", "the", "my", "of", "tall", "mm")]
        return " ".join(w) or None
    return None


def names_landmark(request: str) -> str | None:
    """The subject when a request plainly asks for a model of a named landmark (offline: words only).
    The subject must name a building or structure: a capitalised product ("a stand for my Kindle
    Paperwhite") or the word "model" alone is no landmark, and keeps the ask-the-person path."""
    s = subject_of(request)
    if not s:
        return None
    # Someone asking for an existing file of a named thing wants that search, building word or not.
    return s if BUILDING.search(s) or asks_found_model(request) else None


# What may come before the name of the thing asked for, a size and a "model of" last, and what may come after it.
LEAD = re.compile(r"""(?:(?:please|hi|hello|hey|can|could|would|will|you|i|i'd|we|we'd|let's|want|need|like|love|to|me|us|give|get|have
    |make|print|model|build|create|recreate|design|generate|produce|render|sculpt|do|3d[ -]?print|3d[ -]?model)\b[\s,]+)*""", re.I | re.X)
SIZE = r"[\d.]+[\s-]*(?:mm|cm|m|in|inch(?:es)?)\b[\s-]*(?:tall|high|long|wide|across)?"
SIZED = re.compile(rf"(?:(?:an?\s+)?{SIZE}\s+)?", re.I)
MODEL_OF = re.compile(r"""(?:(?:an?|the)\s+)?(?:(?!(?:for|with|of|on|to|under|hold\w*|that)\b)[\w.:/'-]+\s+){0,5}?
    (?:models?|replicas?|miniatures?|versions?|prints?|copy|copies|stls?|3mfs?|files?|mesh(?:es)?)\s+of\s+""", re.I | re.X)
NAME_ENDS = re.compile(r"""\s*(?:[,.;:!?()]|$)|\s+(?:[-\u2013\u2014]\s|\d|(?:for|that|which|please|about|with|so|using|from|scaled?|sized)\b
    |(?:in|at)\s+(?:\d|an?\b|one\b|two\b|pla|petg|abs|asa|tpu|resin|plastic|wood|stone|colou?r|white|black|gr[ae]y|red|green|blue
    |gold|silver|bronze|full|true|high|low|small|large|scale|about|around)
    |as\s+(?:an?\s+)?(?:3d\s+)?(?:model|replica|miniature|print)\b|to\s+(?:be\s+)?(?:3-?d[\s-]?)?(?:print|fit|display)\w*\b|i\s+(?:can|could|want)\b)""", re.I | re.X)


def known_landmark(request: str) -> str | None:
    """The thing a request asks for when a pack or Wikidata knows it as a structure: "a 3D print of the Arc de
    Triomphe" has no building word in it. Only the thing itself, by name: not "a clip for the Arc", "a small Parthenon
    on it" or "a white house". One lookup, and only for a request no recipe fits."""
    from . import landmark_refs

    req = ABBREV.sub(lambda m: ABBREVS[m.group(1).lower()] + " ", request.replace("\u2019", "'")).strip()
    for lead in (LEAD, SIZED, MODEL_OF, SIZED):
        m = lead.match(req)
        req = req[m.end():] if m else req
    req = re.sub(r"^the\s+", "", req, flags=re.I)
    name = re.sub(r"\s+(?:3d\s+)?(?:models?|replicas?|miniatures?|prints?|stls?)$", "", req[:NAME_ENDS.search(req).start()], flags=re.I)
    words = name.casefold().split()
    if not 1 <= len(words) <= 7 or words[0] in ("a", "an", "some", "any") or {"my", "our", "your", "his", "her", "their"} & {*words}:
        return None
    return name if landmark_refs.is_structure(name) else None


def asks_found_model(request: str) -> bool:
    """True when a request asks to find, download or get an existing or open model, not to build one."""
    return bool(FIND_MODEL.search(request))


UNITS = {"mm": 1.0, "cm": 10.0, "in": 25.4, "inch": 25.4, "inches": 25.4, "\"": 25.4}
NUM = r"(\d+(?:\.\d+)?)"
UNIT = r"\s*(mm|cm|inches|inch|in\b|\")"


def target(request: str, bed) -> dict:
    """What size the request asks for: {"mode": "z" | "long" | "max" | "fit", "mm", "bed", "said"}.
    "300 mm tall" is the height, "150 mm long" or "wide" the longest side across, a bare "200 mm" the
    longest side; with no size, the largest that fits the bed. "my 220 mm bed" or "a 220 x 220 x 250
    bed" is the bed (a single number is a cube)."""
    text = request.replace("×", "x")
    b = [float(x) for x in bed]
    said_bed = None
    mb = re.search(NUM + r"(?:\s*(?:mm)?\s*x\s*" + NUM + r"(?:\s*(?:mm)?\s*x\s*" + NUM + r")?)?" + r"\s*(mm|cm)?"
                   r"\s*(?:square\s+)?(?:print\s*)?(?:bed|build plate|build volume)", text, re.I)
    if mb:
        unit = UNITS.get((mb.group(4) or "mm").lower(), 1.0)
        x = float(mb.group(1)) * unit
        y = float(mb.group(2)) * unit if mb.group(2) else x
        z = float(mb.group(3)) * unit if mb.group(3) else x
        b = [x, y, z]
        said_bed = mb.group(0).strip()
        text = text[:mb.start()] + " " + text[mb.end():]
    for m in re.finditer(NUM + UNIT + r"\s*(tall|high|in height|height|long|in length|length|wide|across|"
                         r"width|in diameter)?", text, re.I):
        v = float(m.group(1)) * UNITS.get(m.group(2).lower(), 1.0)
        word = (m.group(3) or "").lower()
        before = text[max(0, m.start() - 12):m.start()].lower()
        if not word and re.search(r"(tall|high|height)\W*$", before):
            word = "tall"
        mode = "z" if word in ("tall", "high", "in height", "height") else "long" if word else "max"
        return {"mode": mode, "mm": round(v, 2), "bed": b, "said": m.group(0).strip(), "bed_said": said_bed}
    return {"mode": "fit", "mm": None, "bed": b, "said": f"fits the {said_bed}" if said_bed else "fits the bed",
            "bed_said": said_bed}


def fmt3(v) -> str:
    return " x ".join(f"{float(x):.0f}" for x in v) + " mm"


def asked_size_line(t: dict) -> str:
    what = {"z": "tall", "long": "long (its longest side across)", "max": "on its longest side"}
    if t["mode"] == "fit":
        return f"Size: the largest that fits the {fmt3(t['bed'])} bed"
    return f"Size: {t['mm']:g} mm {what[t['mode']]}, on a {fmt3(t['bed'])} bed"


def slug(text: str) -> str:
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", t)).strip("_")[:40] or "model"


def mesh_line(mesh) -> str:
    e = mesh.extents
    return (f"{len(mesh.faces)} faces, {e[0]:.3g} x {e[1]:.3g} x {e[2]:.3g} in the file's units, "
            f"{'watertight' if mesh.is_watertight else 'not watertight'}")
