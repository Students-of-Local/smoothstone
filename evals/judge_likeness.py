"""A blind judge of a figure's likeness: is the render the figure was made from the subject asked for?

uv run python evals/judge_likeness.py <run dir or job dir> [--request TEXT]

The tool picks its own photos, so its photos cannot vouch for it: for "DHH" it once styled a
protein, and every check passed a made up man. The reference here comes another way. Opus names
the Wikipedia article the request means (text only), the judge harness fetches that article's
lead image, and a second Opus run compares the render with it, feature by feature (hair, facial
hair, glasses, skin, age, clothes), never naming anyone from a face. Both run as `claude -p` on
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
