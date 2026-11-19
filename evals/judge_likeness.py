"""A blind judge of a figure's likeness: is the render the figure was made from the subject asked for?

uv run python evals/judge_likeness.py <run dir or job dir> [--request TEXT]

The tool picks its own photos, so its photos cannot vouch for it: for "DHH" it once styled a
protein, and every check passed a made up man. The reference here comes another way. Opus names
the Wikipedia article the request means (text only), the judge harness fetches that article's
lead image, and a second Opus run compares the render with it, feature by feature (hair, facial
hair, glasses, skin, age, clothes), never naming anyone from a face. When the lead image is a photo
the tool styled from (image/found/found.json), another photo of the subject from the article is the
reference, and with none there is no verdict: a render compared with its own source measures
copying, not likeness. Both run as `claude -p` on
Donovan's sign-in (ANTHROPIC_API_KEY unset). The verdict is {"score": 1-10, "conflicts": [...],
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

Read both pictures with the Read tool:
  {reference}: a reference photo of the request's subject, the lead image of the Wikipedia
    article "{title}" ({caption}).
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
conflicts with feature "reference" and judge from the request's subject as best you can.

Reply with one JSON object and nothing else:
{{"score": <1-10>, "conflicts": [{{"feature": "...", "what": "..."}}]}}"""


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


def other_reference(ref: dict, avoid: set[str]) -> dict | None:
    """A photo from the same article that the tool did not use, named for the subject (a file
    whose name has a word of the title), or None."""
    q = urllib.parse.urlencode({"action": "query", "titles": ref["title"], "prop": "images", "imlimit": "50",
                                "format": "json"})
    pages = (json.loads(_get(WIKI + "?" + q)).get("query") or {}).get("pages") or {}
    files = [i["title"] for pg in pages.values() for i in pg.get("images") or []]
    words = {w.lower() for w in re.findall(r"[A-Za-z]{3,}", ref["title"])}
    for f in files:
        key = _file_key(f)
        if key in avoid or not key.endswith((".jpg", ".jpeg")) or not words & set(re.findall(r"[a-z]{3,}", key)):
            continue
        q = urllib.parse.urlencode({"action": "query", "titles": f, "prop": "imageinfo", "iiprop": "url",
                                    "format": "json"})
        info = [ii for pg in ((json.loads(_get(WIKI + "?" + q)).get("query") or {}).get("pages") or {}).values()
                for ii in pg.get("imageinfo") or []]
        if info and info[0].get("url"):
            lead = urllib.parse.unquote(urllib.parse.urlparse(ref["url"]).path.rsplit("/", 1)[-1])
            return {**ref, "url": info[0]["url"], "instead_of": lead.replace("_", " ")}
    return None


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
    return {"score": score, "conflicts": [{"feature": str(c.get("feature", "")), "what": str(c.get("what", ""))}
                                          for c in conflicts if isinstance(c, dict)]}


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
    if _file_key(ref["url"]) in avoid:  # the article leads with the photo the render was styled from
        ref = other_reference(ref, avoid)
        if ref is None:
            raise JudgeProblem(f"the article {title!r} shows only photos the tool styled from; "
                               "no reference apart from them")
    with tempfile.TemporaryDirectory(prefix="likeness-") as tmp:
        t = Path(tmp)
        ext = Path(urllib.parse.urlparse(ref["url"]).path).suffix.lower() or ".jpg"
        (t / f"reference{ext}").write_bytes(_get(ref["url"]))
        shutil.copy(render, t / "render.png")
        reply = claude(RUBRIC.format(request=request, reference=t / f"reference{ext}", title=ref["title"],
                                     caption=ref["caption"] or "no caption", render=t / "render.png"),
                       folder=t, model=model)
    res = parse(reply)
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
