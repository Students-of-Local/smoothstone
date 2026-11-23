"""Grade a part made from a recipe the model wrote (an off-catalog spec, tier L): its size and its
named openings, measured in the mesh, and the new recipe's own sheet.

expect: {"new_recipe": true,
         "dims": [[lo, hi], [lo, hi], [lo, hi]],
         "features": [{"name": "m4_holes", "kind": "hole", "d": [4.3, 4.8], "count": 2},
                      {"name": "usb_window", "kind": "cutout", "w": [12, 13], "h": [7, 8], "count": 1}]}

- dims: the part's bounding box extents, largest first, so the part may lie any way on the bed.
- A hole is a round opening (through or blind) in a cut through the part square to x, y or z; its
  diameter is the circle of the same area. A cutout is a rectangular one; w and h are its sides,
  larger first. The part is cut every 0.5 mm along each axis, and the same opening seen in several
  cuts counts once, sized by the median of its cuts. `count` is exact: the part has that many
  openings of that kind and size.
- The new recipe passes tools/sheet.py: its defaults and every example build and pass the print checks.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
STEP = 0.5  # mm between cuts
ROUND = 0.85  # 4 pi A / P^2 at or above: a round opening (a 6 sided one is 0.91)
RECT = 0.8  # area over its bounding box at or above: a rectangular opening (a rounded corner keeps it)
SAME = 1.0  # mm: openings on one axis with centers this close are the same opening

# each axis turned onto z, so manifold3d's slice cuts square to it
TURN = {"z": [0, 0, 0], "x": [0, -90, 0], "y": [90, 0, 0]}


def _manifold(mesh):
    import manifold3d as m3

    return m3.Manifold(m3.Mesh(vert_properties=np.asarray(mesh.vertices, np.float32),
                               tri_verts=np.asarray(mesh.faces, np.uint32)))


def _ring(p: np.ndarray) -> tuple[float, float, np.ndarray]:
    """(signed area, perimeter, centroid) of a closed ring of 2D points."""
    x, y = p[:, 0], p[:, 1]
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    cross = x * y1 - x1 * y
    a = cross.sum() / 2
    c = np.array([((x + x1) * cross).sum(), ((y + y1) * cross).sum()]) / (6 * a) if a else p.mean(axis=0)
    return float(a), float(np.hypot(x1 - x, y1 - y).sum()), c


def openings(mesh) -> list[dict]:
    """Every opening in the part: {"axis", "c" (its center in the cut), "kind" (hole, cutout or
    other), "d" (equal area diameter), "w", "h" (its sides, larger first), "cuts"}, each counted
    once. Its size is the median of its cuts, so a chamfered mouth, a countersink or a drill point
    does not stand in for the bore."""
    part = _manifold(mesh)
    found: list[dict] = []
    for axis, turn in TURN.items():
        m = part.rotate(turn)
        lo, hi = m.bounding_box()[2], m.bounding_box()[5]
        for z in np.arange(lo + STEP / 2, hi, STEP):
            for p in m.slice(float(z)).to_polygons():
                p = np.asarray(p, float)
                a, per, c = _ring(p) if len(p) >= 3 else (0.0, 0.0, None)
                if a >= 0:  # an outline; openings wind the other way
                    continue
                a = -a
                ext = p.max(axis=0) - p.min(axis=0)
                w, h = float(max(ext)), float(min(ext))
                kind = "hole" if 4 * np.pi * a / per ** 2 >= ROUND else "cutout" if a / (w * h) >= RECT else "other"
                cut = {"kind": kind, "d": 2 * np.sqrt(a / np.pi), "w": w, "h": h}
                same = next((o for o in found if o["axis"] == axis and np.hypot(*(o["c"] - c)) <= SAME), None)
                if same is None:
                    found.append({"axis": axis, "c": c, "cuts": [cut]})
                else:
                    same["cuts"].append(cut)
    out = []
    for o in found:
        kinds = [c["kind"] for c in o["cuts"]]
        out.append({"axis": o["axis"], "c": o["c"], "cuts": len(kinds), "kind": max(set(kinds), key=kinds.count),
                    **{k: float(np.median([c[k] for c in o["cuts"]])) for k in ("d", "w", "h")}})
    return out


def _in(v: float, r: list) -> bool:
    return r[0] <= v <= r[1]


def check(stl: Path, expect: dict) -> tuple[list[str], dict]:
    """(why it fails, what was measured) for the part's size and features."""
    import trimesh

    mesh = trimesh.load(stl, force="mesh")
    why: list[str] = []
    ext = sorted((float(e) for e in mesh.extents), reverse=True)
    measured = {"dims": [round(e, 2) for e in ext], "features": {}}
    for e, want, n in zip(ext, expect.get("dims") or [], ("largest", "middle", "smallest")):
        if not _in(e, want):
            why.append(f"{n} size {e:.1f} mm (want {want[0]} to {want[1]})")
    found = openings(mesh) if expect.get("features") else []
    for f in expect.get("features") or []:
        if f["kind"] == "hole":
            hit = [o for o in found if o["kind"] == "hole" and _in(o["d"], f["d"])]
            want = f"Ø{f['d'][0]} to {f['d'][1]} mm"
        else:
            hit = [o for o in found if o["kind"] == "cutout" and _in(o["w"], f["w"]) and _in(o["h"], f["h"])]
            want = f"{f['w'][0]} to {f['w'][1]} by {f['h'][0]} to {f['h'][1]} mm"
        measured["features"][f["name"]] = len(hit)
        if len(hit) != f.get("count", 1):
            near = sorted({round(o["d"] if f["kind"] == "hole" else o["w"], 1) for o in found if o["kind"] == f["kind"]})
            why.append(f"{f['name']}: {len(hit)} {f['kind']}s of {want} (want {f.get('count', 1)})"
                       + (f"; {f['kind']}s found: {near}" if near else f"; no {f['kind']} found"))
    return why, measured


def sheet(recipe: str, recipes: Path, out: Path, stone_bin: Path) -> list[str]:
    """tools/sheet.py on the new recipe, from the run's recipes: each line that is not PASS."""
    env = {**os.environ, "STONE_RECIPES": str(recipes), "PATH": str(stone_bin) + os.pathsep + os.environ.get("PATH", "")}
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "sheet.py"), recipe, "--out", str(out)],
                       capture_output=True, text=True, env=env, cwd=ROOT)
    lines = [l for l in p.stdout.splitlines() if l.startswith(recipe)]
    bad = [" ".join(l.split()) for l in lines if " PASS " not in f" {l} "]
    if p.returncode and not bad:
        bad.append(f"tools/sheet.py exit {p.returncode}: " + (p.stderr.strip().splitlines() or [""])[-1][:200])
    if not lines and not bad:
        bad.append("tools/sheet.py built nothing")
    return [f"sheet: {l[:200]}" for l in bad]
