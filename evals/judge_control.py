"""A control for the blind judge: seed a paint fault the judge must catch, drawn by the same renderer.

uv run python evals/judge_control.py <job dir> <out dir> [--line N] [--depth MM] [--length MM]

Reads the job's painted figure.3mf (or <recipe>.3mf) and build/regions.json, flips the faces on one
side of a color boundary into the other color (a tab `depth` mm deep and `length` mm along the
line, centered on the line's point that a viewer sees most from the side), and writes
<out>/build/views.png and boundaries.png with colors.render_views and render_boundaries, as stone
colors draws them. Then judge it: judge_views.py <out> --request '...'. A judge that misses the
tab is too lenient for its pass to mean anything. --depth 0 writes the same pictures with no fault.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from smoothstone import colors as C  # noqa: E402


def seed_tab(V, F, face_fil, line: dict, depth: float, length: float) -> np.ndarray:
    """face_fil with a tab across the line: the faces within `depth` of the line, within `length`/2
    of its middle point, that have the color most common there take the line's other color."""
    pts = np.asarray(line["pts"], float)
    a, b = line["pair"]
    mid = pts[len(pts) // 2]
    near = pts[np.linalg.norm(pts - mid, axis=1) <= length / 2]
    cen = V[F].mean(1)
    # distance from each face center to the nearest line point of the stretch
    d = np.min(np.linalg.norm(cen[:, None, :] - near[None, :, :], axis=2), axis=1)
    out = face_fil.copy()
    # the majority color near the stretch gives up the tab
    sel = d <= depth
    side = a if (face_fil[sel] == a).sum() >= (face_fil[sel] == b).sum() else b
    other = b if side == a else a
    out[sel & (face_fil == side)] = other
    return out


def painted_3mf(job: Path) -> Path:
    """The job's painted 3MF: figure.3mf, else <recipe>.3mf. Never another .3mf that sits in the
    job, such as a reference print file."""
    names = ["figure.3mf"]
    try:
        recipe = json.loads((job / "plan.json").read_text()).get("recipe")
        if recipe:
            names.append(f"{recipe}.3mf")
    except (OSError, ValueError):
        pass
    for n in names:
        if (job / n).exists():
            return job / n
    raise SystemExit(f"no painted 3MF in {job}: looked for {', '.join(names)}; run stone colors first")


def pick_line(pick: list, n: int, most: int = 6) -> dict:
    """Line n (1-based) of the boundaries.png rows: render_boundaries draws only the first `most`."""
    top = min(len(pick), most)
    if not 1 <= n <= top:
        raise SystemExit(f"--line {n}: boundaries.png shows lines 1 to {top}")
    return pick[n - 1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("job")
    ap.add_argument("out")
    ap.add_argument("--line", type=int, default=3, help="the boundaries.png row to seed (1-based)")
    ap.add_argument("--depth", type=float, default=0.6)
    ap.add_argument("--length", type=float, default=2.5)
    a = ap.parse_args()
    job = Path(a.job)
    f3 = painted_3mf(job)
    V, F, codes, main = C.read_3mf(f3)
    st = json.loads((job / "status.json").read_text())["colors"]
    fil = [str(x) for x in st["filaments"]]
    face_fil = np.array([C.decode_paint(c) if c else main for c in codes])
    anat = (json.loads((job / "build" / "regions.json").read_text()).get("anatomy") or {}).get("lines") or []
    worst, lines = C.color_edges(V, F, face_fil)
    C.mark_grooves(lines, anat)
    pick = sorted([ln for ln in lines if ln["length"] >= C.EDGE_MIN],
                  key=lambda ln: (-((ln.get("ratio") or 0) > C.JAGGED), -ln["length"]))
    target = pick_line(pick, a.line)
    seeded = seed_tab(V, F, face_fil, target, a.depth, a.length) if a.depth > 0 else face_fil
    flipped = int((seeded != face_fil).sum())
    fil_rgb = np.array([C.filament_rgb(f) or (150, 150, 150) for f in fil], float)
    rgb = fil_rgb[seeded - 1]
    bd = Path(a.out) / "build"
    bd.mkdir(parents=True, exist_ok=True)
    mesh = C.load_stl_mesh(V, F)
    C.render_views(mesh, rgb, bd / "views.png")
    # the boundaries are the real ones: the judge must find the tab by looking, not by a new row
    C.render_boundaries(V, F, rgb, lines, bd / "boundaries.png", anatomy=anat)
    info = {"job": str(job), "line": a.line, "pair": list(target["pair"]), "depth": a.depth,
            "length": a.length, "faces_flipped": flipped,
            "at": np.asarray(target["pts"])[len(target["pts"]) // 2].round(2).tolist()}
    (Path(a.out) / "control.json").write_text(json.dumps(info, indent=1))
    print(json.dumps(info))


if __name__ == "__main__":
    main()
