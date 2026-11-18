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


def main_image(query: str) -> str | None:
    """The Commons file Wikidata names as the subject's main image (P18), if any."""
    try:
        q = urllib.parse.urlencode({"action": "wbsearchentities", "search": query,
                                    "language": "en", "format": "json", "limit": "1"})
        hits = json.loads(_get(WIKIDATA + "?" + q)).get("search") or []
        if not hits:
            return None
        q = urllib.parse.urlencode({"action": "wbgetclaims", "entity": hits[0]["id"],
                                    "property": "P18", "format": "json"})
        claims = json.loads(_get(WIKIDATA + "?" + q)).get("claims", {}).get("P18") or []
        return "File:" + claims[0]["mainsnak"]["datavalue"]["value"] if claims else None
    except Exception:
        return None


def search(query: str, limit: int = 20) -> list[dict]:
    """Candidate photos for query, best first. Wikidata's main image leads when there is one."""
    common = {"format": "json", "prop": "imageinfo",
              "iiprop": "url|size|mime|extmetadata", "iiurlwidth": str(THUMB_PX)}
    params = {"action": "query", "generator": "search", "gsrnamespace": "6",
              "gsrsearch": f"{query} filetype:bitmap", "gsrlimit": str(limit), **common}
    try:
        data = json.loads(_get(API + "?" + urllib.parse.urlencode(params)))
        lead = main_image(query)
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
    found = search(query)
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
    (dest / "found.json").write_text(json.dumps({"query": query, "photos": got}, indent=1))
    return got


SUBJECT = re.compile(
    r"\b(?:of|like|looks like|resembling|shaped like)\s+((?:[A-Z][\w'.-]*\s?){1,4})")


def subject_from_request(request: str) -> str | None:
    """'A mini figure of Jensen Huang, 80 mm tall' -> 'Jensen Huang'."""
    m = SUBJECT.search(request)
    if m:
        name = m.group(1).strip(" .,'")
        stop = {"A", "An", "The", "My", "Me", "It", "This", "That"}
        parts = [w for w in name.split() if w not in stop]
        if parts:
            return " ".join(parts)
    return None
