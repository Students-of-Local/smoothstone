"""A blind judge of a stone video: Opus reads the contact sheet and the key frames and names faults.

env -u ANTHROPIC_API_KEY uv run python evals/judge_video.py <video dir> [--control]

<video dir> is what `stone video` wrote (report.json, stills/). The judge gets the request, the
paint the clip claims, and every command the run log holds, and must name any frame where the
figure's colors differ from that paint, a terminal line that is not in the log, text in X's top
200 or bottom 300 px, text cut at a tile border, a missing glyph box, or a spin, zoom or flash.
--control first recolors the jacket in the turntable stills to red (a fault it must catch) and
judges those. Writes judge.json (or judge-control.json) next to report.json. Runs as `claude -p
--model opus` on the owner's sign-in (ANTHROPIC_API_KEY unset: no API billing).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

PROMPT = """You are a strict video editor checking a 15 second vertical clip (1080 x 1920) before it
is posted on X. Read every picture listed below with the Read tool: a contact sheet of one frame a
second, then full-size frames at each card change and at four angles of the turning figure.

The clip claims:
- the request: {request}
- the printed figure is painted exactly: {paint}. Every part not named there is the {main}
  filament. No other color anywhere on the figure.
- every terminal line is one of these commands, sent in this order by the model, or a line stone
  printed back to it (a line may be wrapped, or cut with a closing "…"); lines starting with # are
  captions:
{commands}

Name a fault for any of these, with the picture and where in it:
1. the figure's colors differ from the paint above in any frame (a wrong color, a color on the
   wrong part, a stray patch);
2. a terminal command not in the list, or a typo in one;
3. any text in the top 200 px or the bottom 300 px of a 1080 x 1920 frame (X covers those);
4. text cut off at a tile or window border, or a missing-glyph box (a hollow rectangle);
5. anything that is not a straight cut or a short fade: a spin of the camera, a zoom, a flash.
A turntable that turns the figure itself is expected, not a fault.

Pictures:
{pictures}

Reply with only JSON: {{"score": 0-10, "faults": ["picture: what is wrong"], "notes": ["optional"]}}.
List in faults only what you judge to be wrong."""


def build_prompt(pictures: list[Path], report: dict) -> str:
    """The judge's prompt for this clip. Parts the paint does not name are the job's main filament,
    the one covering the most surface."""
    cmds = [r["text"] for r in report["rows"] if r["kind"] == "cmd"]
    seen = list(dict.fromkeys(cmds))
    req = next((r["text"] for r in report["rows"] if r["kind"] == "req"), "")
    fils = report["paint"]["filaments"]
    paint = ", ".join(f"{n} {int(round(s * 100))}% of the surface" for n, _, s in fils)
    main = max(fils, key=lambda f: f[2])[0] if fils else "main"
    return PROMPT.format(request=req, paint=f"{report.get('paint_words') or ''} ({paint})", main=main,
                         commands="\n".join(f"  {c}" for c in seen),
                         pictures="\n".join(str(p) for p in pictures))


def control_caught(faults: list[str]) -> bool:
    """The control is caught only by a fault that calls the figure red in a turntable still."""
    return any(re.search(r"\bred\b", f, re.I) and "turn_" in f for f in faults)


def run_judge(pictures: list[Path], report: dict, model: str = "opus") -> dict:
    prompt = build_prompt(pictures, report)
    p = subprocess.run(["claude", "-p", "--model", model, "--tools", "Read", "--allowedTools", "Read",
                        "--add-dir", str(pictures[0].parent)], input=prompt, capture_output=True, text=True,
                       timeout=900)
    m = re.search(r"\{.*\}", p.stdout, re.S)
    if p.returncode != 0 or not m:
        raise SystemExit(f"judge gave no verdict ({p.returncode}): {(p.stderr or p.stdout)[-400:]}")
    return json.loads(m.group(0))


def red_jacket(src: Path, dst: Path):
    """The control: the dark jacket pixels of a turntable still turned red."""
    a = np.asarray(Image.open(src).convert("RGB")).astype(int)
    y0, y1 = 470, 1250  # the turntable tile
    sub = a[y0:y1]
    dark = (sub.max(2) < 70) & (sub.max(2) - sub.min(2) < 25) & (sub.sum(2) > 0)
    # the tile's own background is navy (26, 27, 38): keep it, recolor only the near-black fabric
    fabric = dark & ~((np.abs(sub - [26, 27, 38]).sum(2)) < 12)
    sub[fabric] = np.clip(sub[fabric] * [3.2, 0.6, 0.6] + [40, 0, 0], 0, 255)
    a[y0:y1] = sub
    Image.fromarray(a.astype(np.uint8)).save(dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--control", action="store_true")
    ap.add_argument("--model", default="opus")
    a = ap.parse_args()
    d = Path(a.video)
    report = json.loads((d / "report.json").read_text())
    st = d / "stills"
    pics = [st / "sheet.png"] + [st / f"{n}.png" for n in report["stills"]]
    if a.control:
        cd = d / "control"
        if cd.exists():
            shutil.rmtree(cd)
        cd.mkdir()
        out = []
        for p in pics:
            q = cd / p.name
            if p.name.startswith("turn_"):
                red_jacket(p, q)
            else:
                shutil.copy(p, q)
            out.append(q)
        pics = out
    res = run_judge(pics, report, a.model)
    res["control"] = a.control
    res["pictures"] = [str(p) for p in pics]
    (d / ("judge-control.json" if a.control else "judge.json")).write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))
    if a.control:
        caught = control_caught(res.get("faults", []))
        print("control caught" if caught else "CONTROL MISSED: the judge did not name the red jacket")
        sys.exit(0 if caught else 1)
    sys.exit(0 if not res.get("faults") else 1)


if __name__ == "__main__":
    main()
