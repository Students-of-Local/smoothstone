"""A blind judge of a painted part: Opus reads views.png and boundaries.png and scores them.

uv run python evals/judge_views.py <run dir or job dir> [--request TEXT]

The judge sees the request text and the two pictures, nothing else: no spec, no log, no grade.
It runs as `claude -p --model opus` on Donovan's sign-in (ANTHROPIC_API_KEY unset, so no API
billing), with the Read tool only, in a folder that holds copies of the two pictures. It returns
{"score": 1-10, "faults": [{"panel", "what"}]}, written to judge.json next to the run.
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
from pathlib import Path

RUBRIC = """You judge a 3D printed part painted in a few filament colors, from two rendered pictures.

The request the part was made for:
{request}

Read both pictures with the Read tool:
  {views}: the whole part from several sides.
  {boundaries}: close-ups of each color edge, and of the collar from level and from 30 degrees up.

Score how well the paint does what the request asks, as a careful owner would before printing:
- 10: every part has the color asked for, every color edge is a clean line where the shape changes
  (collar, cuffs, hem), and nothing needs fixing by hand.
- 7 to 9: right colors; small flaws a person might not notice in the print (a thin rim, a slight
  wave in an edge).
- 4 to 6: right colors but a flaw anyone would see: a jagged or sawtooth edge, a strip of the wrong
  color on a ledge or under a collar, a stray patch.
- 1 to 3: a part has the wrong color, a part asked for is missing, or the paint is a mess.
A part the request does not name takes the rest color, so the neck, the underside of the hair at the
nape and the wrist below a cuff are correct in the rest color even where they show between painted
parts; a light line there is that part catching the light. A fault is paint on the wrong side of
where the shape changes: a strip of one color on the other part's surface, a step in the edge, a
stray patch. List in faults only what you judge to be wrong. Something you looked at and judge
correct (such as the neck showing as a light line above the collar) is not a fault: leave it out of
faults, or put it in an optional "notes" list of strings.
Judge only what you see in the pictures. Name each fault with the picture and the panel it is in,
starting with the picture's name (such as "boundaries row 2, column 3" or "views front"), and what
is wrong in a few words.

Reply with one JSON object and nothing else:
{{"score": <1-10>, "faults": [{{"panel": "...", "what": "..."}}]}}"""


SHAPE = """You judge a one-color 3D printable figure from a rendered picture, as a careful owner would
before printing it.

The request the part was made for:
{request}

Read the pictures with the Read tool:
  {views}: the whole part from several sides.{closeup}

Score the shape as a finished print:
- 10: a clean, well-formed figure of what the request asks; the surface is smooth where it should be
  and detailed where it should be (face, hair, hands, clothes); the name on the base is complete and
  legible; nothing would need fixing by hand.
- 7 to 9: good; small flaws a person might not notice in the print (a faint ridge, a slightly soft
  detail).
- 4 to 6: a flaw anyone would see: lumps, holes, melted or noisy patches, a missing or fused hand or
  foot, a broken or cut-off letter, a part floating off the body, a strut through the face.
- 1 to 3: not a figure of a person, badly broken, or would not print.
Thin rods drawn in blue, from a hand, hem, chin or hair down to the body or the base, are built-in
supports that snap off after printing; they are not a fault unless one crosses the face or the name. A plinth with the name on its
front is the design. List in faults only what you judge to be wrong. Name each fault with the panel
it is in (such as "views front") and what is wrong in a few words.

Reply with one JSON object and nothing else:
{{"score": <1-10>, "faults": [{{"panel": "...", "what": "..."}}]}}"""


def find_request(d: Path) -> str:
    for p in (d / "log.json", d.parent / "log.json"):
        if p.exists():
            log = json.loads(p.read_text())
            for m in log.get("messages", []):
                if m.get("role") == "user":
                    return m["content"].split("\n")[0]
    for p in (d / "job" / "brief.md", d / "brief.md"):
        if p.exists():
            return p.read_text().strip().splitlines()[0]
    raise SystemExit("no request found: pass --request")


def parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON in the judge's reply")
    out = json.loads(m.group(0))
    score = int(out["score"])
    if not 1 <= score <= 10:
        raise ValueError(f"score {score} outside 1..10")
    faults = [{"panel": str(f.get("panel", "")), "what": str(f.get("what", ""))} for f in out.get("faults", [])]
    return {"score": score, "faults": faults}


def judge(build: Path, request: str, model: str = "opus") -> dict:
    with tempfile.TemporaryDirectory(prefix="judge-") as tmp:
        t = Path(tmp)
        painted = (build / "boundaries.png").exists()  # a one-color part has no color edges to judge
        for name in ("views.png", "boundaries.png") if painted else ("views.png",):
            src = build / name
            if not src.exists():
                raise SystemExit(f"missing {src}")
            shutil.copy(src, t / name)
        close = ""
        if (build / "closeup.png").exists():  # a figure's face and name, big and lit from the side
            shutil.copy(build / "closeup.png", t / "closeup.png")
            close = (f"\n  {t / 'closeup.png'}: the face from the front and both sides, and the name on the "
                     "plinth, close up and lit from the side. Judge the face and the name here.")
        prompt = (RUBRIC.format(request=request, views=t / "views.png", boundaries=t / "boundaries.png") if painted
                  else SHAPE.format(request=request, views=t / "views.png", closeup=close))
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        p = subprocess.run(["claude", "-p", "--model", model, "--tools", "Read", "--allowedTools", "Read",
                            "--strict-mcp-config", "--no-session-persistence", "--add-dir", str(t),
                            "--output-format", "json", prompt],
                           capture_output=True, text=True, env=env, cwd=t, timeout=900)
        if p.returncode != 0:
            raise SystemExit(f"claude exited {p.returncode}: {(p.stderr or p.stdout)[-500:]}")
        reply = json.loads(p.stdout).get("result", "")
    return {**parse(reply), "model": model, "request": request}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", help="a run folder (with job/) or a job folder")
    ap.add_argument("--request")
    ap.add_argument("--model", default="opus")
    a = ap.parse_args()
    d = Path(a.run).resolve()
    job = d / "job" if (d / "job" / "build").exists() else d
    res = judge(job / "build", a.request or find_request(d), a.model)
    (d / "judge.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    sys.exit(main())
