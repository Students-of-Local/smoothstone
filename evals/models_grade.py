"""The grade of a found model run (evals/models, evals/models_heldout), outside the model's reach.

A run passes when:
- credits.txt names the model's author, an open or printable license, and the page it came from;
- every part file fits the spec's bed and passes stone's print checks, run again here on the files
  that ship (the pins too);
- put back together from parts.json's to_print transforms, the model is within 3% of the size the
  person asked for (a model with no size asked fills the bed in its tightest direction, 97% or more);
- a spec that must split has that many parts, and a spec whose model has thin features gets the
  thin features report;
- a blind Opus judge, shown the clay views and the Wikipedia lead photo of the landmark, says it is
  that landmark (judge_likeness.claude and judge_likeness.reference, on Donovan's sign-in).
"""

from __future__ import annotations

import json
import multiprocessing as mp
import re
import shutil
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

SIZE_TOL = 0.03
PASS = 6

RUBRIC = """A tool prepared a printable model of a landmark for this request:
{request}

Read the pictures with the Read tool:
  {reference}: a photo of {title}, the lead image of its English Wikipedia article.
  {views}: the printable model from several sides, in plain clay with no color.

Is the model recognizably {title}? Compare what a model maker controls: the overall shape and
proportions, the number and placement of towers, spires, domes or minarets, the roof line, and
defining details. A model is smaller and plainer than the building, and missing color or fine
ornament is not a fault; a different building, a generic one, or a part of it (one tower, a
facade, a souvenir sign or a map) is.
- 9 to 10: clearly this landmark, every main feature in place.
- 6 to 8: recognizably this landmark, with a small difference.
- 3 to 5: a building like it, but people would not know it is this one.
- 1 to 2: a different building or not a building.

Reply with one JSON object and nothing else:
{{"score": <1-10>, "conflicts": [{{"feature": "...", "what": "..."}}]}}"""

LICENSE = re.compile(r"^License: .*(CC|public domain|GPL|BSD|MIT|standard)", re.I | re.M)


def credits_why(job: Path) -> list[str]:
    f = job / "credits.txt"
    if not f.is_file():
        return ["no credits.txt"]
    text = f.read_text()
    why = []
    first = text.splitlines()[0] if text.strip() else ""
    if " by " not in first or first.rstrip().endswith("by unknown"):
        why.append("credits.txt names no author")
    if not LICENSE.search(text):
        why.append("credits.txt names no open or printable license")
    if not re.search(r"^Source: https?://", text, re.M):
        why.append("credits.txt gives no source page")
    return why


def assembled_vertices(parts: list[dict]):
    """Each part's STL vertices mapped back into the assembled model."""
    import trimesh

    for p in parts:
        m = trimesh.load(p["file"], force="mesh", process=False)
        back = np.linalg.inv(np.asarray(p["to_print"], float))
        yield m.vertices @ back[:3, :3].T + back[:3, 3]


def assembled_size(parts: list[dict]) -> np.ndarray:
    """The model's size put back together from the printed part files."""
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for v in assembled_vertices(parts):
        lo, hi = np.minimum(lo, v.min(0)), np.maximum(hi, v.max(0))
    return hi - lo


def size_why(size: np.ndarray, want: dict, bed) -> list[str]:
    mode = want["mode"]
    if mode == "fit":
        r = max(size[i] / bed[i] for i in range(3))
        if r < 1 - SIZE_TOL:
            return [f"fills {r:.0%} of the bed in its tightest direction (want {1 - SIZE_TOL:.0%} or more)"]
        return []
    got = {"z": size[2], "long": max(size[0], size[1]), "max": max(size)}[mode]
    if abs(got / want["mm"] - 1) > SIZE_TOL:
        name = {"z": "tall", "long": "long", "max": "on its longest side"}[mode]
        return [f"{got:.1f} mm {name} (want {want['mm']:g} mm within {SIZE_TOL:.0%})"]
    return []


def _check(path: str, bed, bodies: int) -> list[dict]:
    from smoothstone import modelprint

    return modelprint.check_part(path, bed, bodies)


def fit_why(f: Path, bed) -> list[str]:
    import trimesh

    e = trimesh.load(str(f), force="mesh", process=False).extents
    if any(e[i] > bed[i] + 1e-6 for i in range(3)):
        return [f"{f.name} is {e[0]:.1f} x {e[1]:.1f} x {e[2]:.1f} mm, larger than the bed"]
    return []


def checks_why(data: dict, bed, *, recorded: bool = False) -> tuple[list[str], list[dict]]:
    """Check file fit, then collect the results of stone's checks on every part and pin."""
    parts = list(data["parts"])
    if data.get("pins"):
        parts.append(data["pins"])
    jobs = [(p["file"], bed, p.get("bodies", p.get("count", 1))) for p in parts]
    why = []
    for f, *_ in jobs:
        if not Path(f).is_file():
            why.append(f"{Path(f).name} is missing")
    if why:
        return why, []
    for f, *_ in jobs:
        why += fit_why(Path(f), bed)
    if recorded:
        res = [p.get("checks") or [] for p in parts]
    else:
        with ProcessPoolExecutor(max_workers=max(1, min(len(jobs), 8)), mp_context=mp.get_context("spawn")) as pool:
            res = list(pool.map(_check, *zip(*jobs)))
    out = []
    for (f, *_), r in zip(jobs, res):
        bad = [x["name"] for x in r if not x["ok"]] if r else ["no check results"]
        if bad:
            why.append(f"{Path(f).name}: print checks fail: " + ", ".join(bad))
        out.append({"file": f, "fails": bad})
    return why, out


def grade(job: Path, spec: dict, checks: bool = True) -> dict:
    """Everything but the judge: {"pass", "why", "size_mm", "parts", "checks"}."""
    want = spec["expect"]["models"]
    bed = [float(x) for x in want["bed"]]
    why = credits_why(job)
    try:
        data = json.loads((job / "build" / "model" / "parts.json").read_text())
    except (OSError, ValueError):
        return {"pass": False, "why": why + ["no fitted model (build/model/parts.json)"], "parts": 0}
    out = {"parts": len(data["parts"]), "thin": len(data.get("thin") or [])}
    if not all(Path(p["file"]).is_file() for p in data["parts"]):
        return {**out, "pass": False, "why": why + ["a part file is missing"]}
    size = assembled_size(data["parts"])
    out["size_mm"] = [round(float(x), 2) for x in size]
    why += size_why(size, want["size"], bed)
    if want.get("parts_min") and len(data["parts"]) < want["parts_min"]:
        why.append(f"{len(data['parts'])} part(s) (want {want['parts_min']} or more: it is larger than the bed)")
    if want.get("thin") and not data.get("thin"):
        why.append("the thin features report is empty")
    if checks:
        w, res = checks_why(data, bed)
        why += w
        out["checks"] = res
    return {**out, "pass": not why, "why": why or ["all checks pass"]}


def judge(job: Path, request: str, title: str | None = None, model: str = "opus", *,
          reference_out: Path | None = None, minimum: int = PASS) -> dict:
    """The blind landmark judge on build/views.png: {"score", "conflicts", "pass", "reference"}."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import judge_likeness as jl

    views = job / "build" / "views.png"
    if not views.is_file():
        raise jl.JudgeProblem(f"no views at {views}")
    if not title:
        title = jl.claude(jl.TITLE.format(request=request), model=model).strip().strip('"').splitlines()[0]
    try:
        ref = jl.reference(title)
    except jl.JudgeProblem:  # an article Wikipedia has chosen no lead image for (Chrysler Building)
        ref = {"title": title, "url": jl.first_photo(title), "caption": ""}
    if ".svg" in ref["url"].lower():  # a logo is no photo of it
        ref["url"] = jl.first_photo(ref["title"])
    data = jl._get(ref["url"])
    ext = jl._suffix(data)
    if not ext:
        raise jl.JudgeProblem(f"the lead image of {title!r} is in a format the judge cannot read")
    if reference_out is not None:
        (reference_out / f"reference{ext}").write_bytes(data)
        ref["file"] = f"reference{ext}"
    with tempfile.TemporaryDirectory(prefix="landmark-", dir=reference_out) as tmp:
        t = Path(tmp)
        (t / f"reference{ext}").write_bytes(data)
        shutil.copy(views, t / "views.png")
        reply = jl.claude(RUBRIC.format(request=request, title=ref["title"], reference=t / f"reference{ext}",
                                        views=t / "views.png"), folder=t, model=model)
    res = jl.parse(reply)
    return {**res, "pass": res["score"] >= minimum, "reference": ref, "model": model, "request": request}


def judged(rdir: Path, job: Path, spec: dict, g: dict, *, suite: str = "models",
           save_reference: bool = False, minimum: int = PASS) -> dict:
    """The grade with the judge's verdict, saved as landmark.json; a judge that cannot answer fails it."""
    try:
        res = judge(job, spec["request"], spec["expect"][suite].get("wikipedia"),
                    reference_out=rdir if save_reference else None, minimum=minimum)
    except Exception as e:  # never passed unjudged
        res = {"score": None, "pass": False, "conflicts": [], "error": f"{type(e).__name__}: {e}"}
    (rdir / "landmark.json").write_text(json.dumps(res, indent=1))
    if res["pass"]:
        return {**g, "likeness": res["score"]}
    why = [w for w in g["why"] if w != "all checks pass"]
    if res.get("error"):
        why.append(f"landmark judge could not answer ({res['error'][:120]})")
    else:
        why.append(f"landmark judge {res['score']}/10: " + "; ".join(f"{c['feature']}: {c['what']}"
                                                                  for c in res["conflicts"])[:240])
    return {**g, "pass": False, "why": why, "likeness": res["score"]}
