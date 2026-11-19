"""A blind judge of a description's traits: is each trait it names visible on the figure?

uv run python evals/judge_traits.py <run dir or job dir> --trait "a gray beard" [--trait ...]

The judge sees views.png and the list of traits, nothing else: no request, no spec, no file name
that tells it which case it is. It runs as `claude -p` on Donovan's sign-in (judge_likeness.claude,
ANTHROPIC_API_KEY unset), with the Read tool only, in a folder that holds a copy of views.png. It
returns {"traits": [{"trait", "visible", "why"}], "pass"}: pass means every trait is visible, and a
trait the reply leaves out is not.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import judge_likeness  # noqa: E402

PROMPT = """Read the picture with the Read tool:
  {views}: a painted 3D printable figure of a person, from several sides.

For each trait below, say whether it is visible on the figure. A trait is visible when someone
looking at the picture would see it without being told: a color must be the color named, and a
garment, hair style or feature must be there in its shape. A stylized figure (a big head, a small
body) is the style, not a missing trait. Judge only what you see in the picture.

Traits:
{traits}

Reply with one JSON object and nothing else:
{{"traits": [{{"n": <the trait's number>, "visible": true or false, "why": "<a few words>"}}]}}"""


def parse(text: str, traits: list[str]) -> list[dict]:
    """The reply as one entry per trait, in order; a trait the reply leaves out is not visible."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise judge_likeness.JudgeProblem("no JSON in the judge's reply")
    out = json.loads(m.group(0)).get("traits")
    if not isinstance(out, list):
        raise judge_likeness.JudgeProblem("traits is not a list")
    by_n = {}
    for t in out:
        if isinstance(t, dict) and str(t.get("n", "")).isdigit():
            by_n.setdefault(int(t["n"]), t)
    res = []
    for k, trait in enumerate(traits, 1):
        t = by_n.get(k)
        res.append({"trait": trait, "visible": bool(t) and t.get("visible") is True,
                    "why": str(t.get("why", "")) if t else "the judge did not answer"})
    return res


def judge(build: Path, traits: list[str], model: str = "opus") -> dict:
    if not traits:
        raise judge_likeness.JudgeProblem("the spec names no traits")
    src = build / "views.png"
    if not src.exists():
        raise judge_likeness.JudgeProblem(f"missing {src}")
    with tempfile.TemporaryDirectory(prefix="traits-") as tmp:
        t = Path(tmp)
        shutil.copy(src, t / "views.png")
        listed = "\n".join(f"{k}. {x}" for k, x in enumerate(traits, 1))
        reply = judge_likeness.claude(PROMPT.format(views=t / "views.png", traits=listed), folder=t, model=model)
    res = parse(reply, traits)
    return {"traits": res, "pass": all(t["visible"] for t in res), "model": model}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run", help="a run folder (with job/) or a job folder")
    ap.add_argument("--trait", action="append", required=True)
    ap.add_argument("--model", default="opus")
    a = ap.parse_args()
    d = Path(a.run).resolve()
    job = d / "job" if (d / "job" / "build").exists() else d
    res = judge(job / "build", a.trait, a.model)
    (d / "traits.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    sys.exit(main())
