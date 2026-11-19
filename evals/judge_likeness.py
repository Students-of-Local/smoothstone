"""A blind judge of a figure's likeness: is the render the figure was made from the subject asked for?

uv run python evals/judge_likeness.py <run dir or job dir> [--request TEXT]

The tool picks its own photos, so its photos cannot vouch for it: for "DHH" it once styled a
protein, and every check passed a made up man. The reference here comes another way. Opus names
the Wikipedia article the request means (text only), the judge harness fetches that article's
lead image, and a second Opus run compares the render with it, feature by feature (hair, facial
hair, glasses, skin, age, clothes), never naming anyone from a face. When the lead image is a photo
the tool styled from (image/found/found.json), another photo of the subject from the article is the
reference, and with none there is no verdict: a render compared with its own source measures
copying, not likeness. A lead image can also be old or miss the subject (DHH's is him in a racing
suit), so up to two more photos named for the subject, from the article and a Commons search,
newest first by the year in the file name, go with it; the judge leaves out any that do not show
the subject, goes by the newest where they differ, and with none usable there is no verdict. For a
subject whose free photos the tool used up (DHH's portraits on Commons are all its own), photos
picked by hand outside the tool go first (likeness_refs.json).
Both run as `claude -p` on Donovan's sign-in (ANTHROPIC_API_KEY unset). The verdict is {"score": 1-10, "conflicts": [...],
"reference": {...}}, saved as likeness.json next to the run; a score under PASS fails it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import time
import urllib.request
from pathlib import Path

PASS = 6
WIKI = "https://en.wikipedia.org/w/api.php"
AGENT = "smoothstone-evals/0.1 (https://github.com/baney75/smoothstone; likeness judge)"

TITLE = """A person asked a tool for a collectible figure with this request:
{request}

Which English Wikipedia article is about the subject of the figure (the person, animal, statue
or thing it shows)? Reply with the exact article title and nothing else."""

RUBRIC = """A tool made a 3D printable collectible figure from this request:
{request}

Read the pictures with the Read tool:
{references}
  {render}: the colored render the tool sculpted the figure from. It is stylized (for a chibi
    figure a big head and a small body are the style, not a fault).

Judge whether the figure is recognizably meant to be the request's subject, by comparing the
features a sculptor controls between the two pictures. Do not identify anyone from a face; compare
features only. For a person: hair color, length and style, hairline or baldness, facial hair,
glasses (there or not, frame shape), skin tone, apparent age, and the kind of clothes. For an
animal: species or breed, coat colors and markings, ears, tail. For a statue or thing: its shape
and defining details. A different outfit than the reference is fine when the request or the
subject's usual look explains it; a feature the subject does not have is not.
- 9 to 10: every feature matches.
- 6 to 8: recognizably the subject, with one small difference (a shade of hair, a slightly
  different cut).
- 3 to 5: a feature that is clearly wrong (glasses the subject does not wear, a full beard on a
  clean shaven face, the wrong hair color), so people would not know who it is meant to be.
- 1 to 2: a different subject (another person, an animal or a thing instead of a person).
If the reference photo does not show the subject (a logo, a building for a person), say so in
conflicts with feature "reference" and judge from the request's subject as best you can.{several}

Reply with one JSON object and nothing else:
{{"score": <1-10>, "conflicts": [{{"feature": "...", "what": "..."}}]}}"""

SEVERAL = """
The reference photos were found by the subject's name, so some may not show the subject (a car the
subject drives, a relative, a crowd, a logo): leave those out. A photo marked picked by hand shows
the subject as they look now; where it differs from the others, go by it. Otherwise hair, weight
and age change over the years, so where the photos differ, go by the most recent one that shows
the subject (the file names give years). If none of them shows the subject, add "usable": false to
your reply."""


class JudgeProblem(Exception):
    pass


def _get(url: str, timeout: float = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def claude(prompt: str, folder: Path | None = None, model: str = "opus") -> str:
    """One `claude -p` reply; Read only when folder is given (the pictures are in it)."""
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    cmd = ["claude", "-p", "--model", model, "--strict-mcp-config", "--no-session-persistence",
           "--output-format", "json"]
    cmd += ["--tools", "Read", "--allowedTools", "Read", "--add-dir", str(folder)] if folder else ["--tools", ""]
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, env=env,  # --tools takes a
                           cwd=folder or None, timeout=900)  # list, so a prompt after it is a tool name
    except (OSError, subprocess.TimeoutExpired) as e:
        raise JudgeProblem(f"claude did not answer: {type(e).__name__}") from e
    if p.returncode != 0:
        raise JudgeProblem(f"claude exited {p.returncode}: {(p.stderr or p.stdout)[-300:]}")
    return str(json.loads(p.stdout).get("result", "")).strip()


def reference(title: str) -> dict:
    """The lead image of an English Wikipedia article: {title, url, caption}."""
    q = urllib.parse.urlencode({"action": "query", "titles": title, "redirects": "1", "format": "json",
                                "prop": "pageimages|description", "piprop": "original"})
    pages = list((json.loads(_get(WIKI + "?" + q)).get("query") or {}).get("pages", {}).values())
    if not pages or "missing" in pages[0] or not (pages[0].get("original") or {}).get("source"):
        raise JudgeProblem(f"no lead image for the Wikipedia article {title!r}")
    p = pages[0]
    return {"title": p["title"], "url": p["original"]["source"], "caption": p.get("description", "")}


def _file_key(name: str) -> str:
    """A Commons file name as one compares it: no File: prefix, no query, spaces, lower case."""
    name = urllib.parse.unquote(urllib.parse.urlparse(name).path.rsplit("/", 1)[-1] if "/" in name else name)
    return re.sub(r"^file:", "", name.replace("_", " ").strip().lower())


def tool_photos(job: Path) -> set[str]:
    """The Commons files the tool found and styled from (image/found/found.json), as _file_key."""
    try:
        found = json.loads((job / "image" / "found" / "found.json").read_text())
    except (OSError, ValueError):
        return set()
    return {_file_key(p.get("title", "")) for p in found.get("photos") or [] if p.get("title")}


READABLE = {".jpg", ".jpeg", ".png", ".webp", ".gif"}  # what the judge can open; an SVG or TIFF it cannot


def _hash(data: bytes) -> int | None:
    """A 16 x 16 average hash: the same picture re-encoded, resized or in another format keeps it."""
    import io
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(data)).convert("L").resize((16, 16))
    except Exception:  # not a picture PIL reads: it matches nothing
        return None
    px = list(im.tobytes())
    mean = sum(px) / len(px)
    return sum(1 << k for k, v in enumerate(px) if v > mean)


def _same_picture(data: bytes, owners: list[int]) -> bool:
    h = _hash(data)
    return h is not None and any(bin(h ^ o).count("1") <= 20 for o in owners)  # 20 of 256 bits


def owner_photos(job: Path) -> list[int]:
    """Hashes of the photos the owner gave the tool (image/source.*): the tool styled from them,
    so a reference that is one of them, under any name, measures copying, not likeness."""
    return [h for f in sorted((job / "image").glob("source.*")) if (h := _hash(f.read_bytes())) is not None]


COMMONS = "https://commons.wikimedia.org/w/api.php"
REFERENCES = 3
REFS_FILE = Path(__file__).with_name("likeness_refs.json")


def picked_by_hand(title: str) -> list[dict]:
    """Photos of a subject picked outside the tool, for one whose free photos the tool used up
    (likeness_refs.json: {article title: [{"url", "source"}]}), as [{"file", "url", "source"}]."""
    try:
        refs = json.loads(REFS_FILE.read_text())
    except (OSError, ValueError):
        return []
    return [{"file": _file_key(r["url"]), "url": r["url"], "source": r.get("source", "")}
            for r in refs.get(title) or [] if r.get("url")]


NOISE = {"cropped", "crop", "jpg", "jpeg", "png", "file", "image", "photo", "the", "and", "with", "from"}


def _year(key: str) -> int:
    """The latest year in a file name, as 2023, 20231003 or 2023-10-03 (0 with none); never one
    still to come, nor digits run on from a word (IMG_2099)."""
    now = time.gmtime().tm_year
    ys = [int(y) for y in re.findall(r"(?<![\dA-Za-z_])((?:19|20)\d\d)(?:[-_ ]?[01]\d[-_ ]?[0-3]\d)?(?!\d)", key)]
    return max([y for y in ys if y <= now], default=0)


def _stem(key: str) -> str:
    """A file name with its crops taken off: "Elon Musk 2019 (cropped).jpg" and "Elon Musk
    2019.jpg" are one picture, so a crop of a photo the tool used is the tool's photo too."""
    k = re.sub(r"\.[a-z0-9]+$", "", key)
    k = re.sub(r"\([^)]*crop[^)]*\)", " ", k)
    k = re.sub(r"\bcrop(?:ped)?\d*\b", " ", k)
    return " ".join(re.findall(r"[a-z0-9]+", k))


def _title_words(title: str) -> set[str]:
    """The words a file must have to be of the subject: the whole title, without a disambiguator
    in brackets ("Elon Musk", never "Musk" alone, which a relative's photo has too)."""
    return {w.lower() for w in re.findall(r"[A-Za-z]{3,}", re.sub(r"\([^)]*\)", " ", title))}


def _named_for(key: str, words: set[str]) -> float:
    """How much of a file name is the subject's name: "Elon Musk 2025 (cropped)" 1.0, a race car
    "Oreca 07 - David Heinemeier-Hansson, Fabio Scherer & ..." far less."""
    ws = [w for w in re.findall(r"[a-z]{3,}", key) if w not in NOISE]
    return sum(w in words for w in ws) / len(ws) if ws else 0.0


def other_references(ref: dict, avoid: set[str], n: int = REFERENCES) -> list[dict]:
    """Up to n photos of the subject the tool did not use, from the article's own photos and a
    Commons search for its title. Files named mostly for the subject come first (a portrait, not a
    race car the subject drove among others), newest first by the year in the name.
    [{"file", "url"}], url a 1600 px rendition."""
    words = _title_words(ref["title"])
    avoid = {_stem(a) for a in avoid}
    q = urllib.parse.urlencode({"action": "query", "titles": ref["title"], "prop": "images", "imlimit": "50",
                                "redirects": "1", "format": "json"})
    pages = (json.loads(_get(WIKI + "?" + q)).get("query") or {}).get("pages") or {}
    files = [i["title"] for pg in pages.values() for i in pg.get("images") or []]
    q = urllib.parse.urlencode({"action": "query", "list": "search", "srnamespace": "6", "srlimit": "20",
                                "srsearch": f"{ref['title']} filetype:bitmap", "format": "json"})
    files += [h["title"] for h in (json.loads(_get(COMMONS + "?" + q)).get("query") or {}).get("search") or []]
    seen, keep = set(), []
    for f in files:
        key = _file_key(f)
        if _stem(key) in avoid or key in seen or not key.endswith((".jpg", ".jpeg")):
            continue
        if words <= set(re.findall(r"[a-z]{3,}", key)):
            seen.add(key)
            keep.append(f)
    keep = sorted(keep, key=lambda f: (_named_for(_file_key(f), words) < 0.6, -_year(_file_key(f))))[:n]
    if not keep:
        return []
    q = urllib.parse.urlencode({"action": "query", "titles": "|".join(keep), "prop": "imageinfo",
                                "iiprop": "url", "iiurlwidth": "1600", "format": "json"})
    info = {pg.get("title"): (pg.get("imageinfo") or [{}])[0]
            for pg in ((json.loads(_get(COMMONS + "?" + q)).get("query") or {}).get("pages") or {}).values()}
    out = []
    for f in keep:
        ii = info.get(f) or {}
        url = ii.get("thumburl") or ii.get("url")
        if url:
            out.append({"file": f[5:] if f.startswith("File:") else f, "url": url})
    return out


def parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise JudgeProblem("no JSON in the judge's reply")
    out = json.loads(m.group(0))
    score = int(out["score"])
    if not 1 <= score <= 10:
        raise JudgeProblem(f"score {score} outside 1..10")
    conflicts = out.get("conflicts", [])
    if not isinstance(conflicts, list):
        raise JudgeProblem("conflicts is not a list")
    res = {"score": score, "conflicts": [{"feature": str(c.get("feature", "")), "what": str(c.get("what", ""))}
                                         for c in conflicts if isinstance(c, dict)]}
    if out.get("usable") is False:
        res["usable"] = False
    return res


def render_of(job: Path) -> Path | None:
    """The style render the job's figure was made from (image/figure/<key>/style.png)."""
    latest = job / "image" / "figure" / "latest.txt"
    if latest.exists():
        r = Path(latest.read_text().strip()).with_name("style.png")
        if r.exists():
            return r
    found = sorted((job / "image" / "figure").glob("*/style.png"), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def judge(job: Path, request: str, model: str = "opus") -> dict:
    render = render_of(job)
    if render is None:
        raise JudgeProblem(f"no style.png under {job / 'image' / 'figure'}")
    title = claude(TITLE.format(request=request), model=model).strip().strip('"').splitlines()[0]
    ref = reference(title)
    avoid = tool_photos(job)
    lead = urllib.parse.unquote(urllib.parse.urlparse(ref["url"]).path.rsplit("/", 1)[-1]).replace("_", " ")
    lead_is_tools = _stem(_file_key(ref["url"])) in {_stem(a) for a in avoid}  # Wikidata's photo, which the tool put first
    hand = [h for h in picked_by_hand(ref["title"]) if _stem(h["file"]) not in {_stem(a) for a in avoid}]
    room = REFERENCES - len(hand) - (0 if lead_is_tools else 1)
    others = other_references(ref, avoid | {_file_key(ref["url"])}, room) if room > 0 else []
    photos = hand + ([] if lead_is_tools else [{"file": lead, "url": ref["url"]}]) + others
    if not photos:
        raise JudgeProblem(f"no photo of {title!r} apart from the ones the tool styled from")
    if lead_is_tools:
        ref = {**ref, "instead_of": lead, "url": photos[0]["url"]}
    if lead_is_tools or len(photos) > 1:
        ref = {**ref, "photos": photos}
    owners = owner_photos(job)

    def fetch(url: str, stem: str) -> Path | None:
        """The photo saved under its own format, or None: a format the judge cannot read, a link
        that moved, or a photo the owner gave the tool."""
        ext = Path(urllib.parse.urlparse(url).path).suffix.lower() or ".jpg"
        if ext not in READABLE:
            return None
        try:
            data = _get(url)
        except OSError:
            return None
        if _same_picture(data, owners):
            return None
        (t / f"{stem}{ext}").write_bytes(data)
        return t / f"{stem}{ext}"

    with tempfile.TemporaryDirectory(prefix="likeness-") as tmp:
        t = Path(tmp)
        if ref.get("photos"):
            lines = []
            for ph in ref["photos"]:
                name = fetch(ph["url"], f"reference_{len(lines) + 1}")
                if name is None:  # the others still judge
                    continue
                where = f"picked by hand, from {ph['source']}" if ph.get("source") else \
                    "found by searching Wikimedia Commons for the subject's name"
                lines.append(f"  {name}: a photo {where}, file \"{ph['file']}\".")
            if not lines:
                raise JudgeProblem(f"no reference photo of {title!r} could be downloaded")
            refs, several = "\n".join(lines), SEVERAL
        else:
            name = fetch(ref["url"], "reference")
            if name is None:
                raise JudgeProblem(f"the photo of {title!r} could not be used (format, link, or the owner's own)")
            refs = (f"  {name}: a reference photo of the request's subject, the lead image of "
                    f"the Wikipedia\n    article \"{ref['title']}\" ({ref['caption'] or 'no caption'}).")
            several = ""
        shutil.copy(render, t / "render.png")
        reply = claude(RUBRIC.format(request=request, references=refs, several=several, render=t / "render.png"),
                       folder=t, model=model)
    res = parse(reply)
    if res.get("usable") is False:
        raise JudgeProblem(f"none of the reference photos of {title!r} shows the subject")
    return {**res, "pass": res["score"] >= PASS, "reference": ref, "render": str(render),
            "model": model, "request": request}


def main() -> None:
    sys.path.insert(0, str(Path(__file__).parent))
    from judge_views import find_request

    ap = argparse.ArgumentParser()
    ap.add_argument("run", help="a run folder (with job/) or a job folder")
    ap.add_argument("--request")
    ap.add_argument("--model", default="opus")
    a = ap.parse_args()
    d = Path(a.run).resolve()
    job = d / "job" if (d / "job").is_dir() else d
    res = judge(job, a.request or find_request(d), a.model)
    (d / "likeness.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    sys.exit(main())
