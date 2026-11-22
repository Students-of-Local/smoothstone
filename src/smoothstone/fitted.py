"""After a fitted part builds: build/engineering.json, where the product sits in the part and what holds it.

The recipe's OpenSCAD echoes what it built (recipes/fitted_case/recipe.scad):
  echo(stone_fit = [frame x, y, z, clearance per side, gap under, wall, floor, retention]);
  echo(stone_snap = [root x, y, z, t_dir x, y, z, w, y, t, L]);   (snap retention only)
so the file says what the mesh has, in the part's STL coordinates. The sources are the URLs the
catalog cites for each number (evals/README.md, "Engineering specs").
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import catalog
from . import recipes as rc

FIT_ECHO = re.compile(r"ECHO: stone_fit = (\[.*\])")
SNAP_ECHO = re.compile(r"ECHO: stone_snap = (\[.*\])")
SIDES = ("+x", "-x", "+y", "-y")


def _echo(rx: re.Pattern, log: str) -> list | None:
    m = rx.findall(log or "")
    if not m:
        return None
    try:
        return json.loads(m[-1])
    except ValueError:
        return None


def engineering(r: rc.Recipe, params: dict, log: str) -> dict | None:
    """engineering.json's content for a build of a recipe with a catalog product, or None when the
    recipe has none or the build log does not say where the product sits."""
    cp = rc.catalog_param(r)
    if cp is None:
        return None
    p = catalog.get(str(params.get(cp.name)))
    fit = _echo(FIT_ECHO, log)
    if p is None or not fit or len(fit) < 8:
        return None
    ox, oy, oz, c, under, _wall, _floor, ret = fit[:8]
    open_faces = set(p.get("open_faces", [])) | ({"+y"} if params.get("style") == "sleeve" else set())
    clearance = {f: round(float(c), 4) for f in SIDES if f not in open_faces}
    if not p.get("board"):
        clearance["-z"] = round(float(under), 4)
    if ret == "snap":
        s = _echo(SNAP_ECHO, log)
        if not s or len(s) < 10:
            return None
        retention = {"type": "snap", "at": [round(float(v), 4) for v in s[0:3]],
                     "t_dir": [round(float(v), 4) for v in s[3:6]], "L_dir": [0, 0, 1],
                     "w": float(s[6]), "y": float(s[7]), "t": float(s[8]), "L": round(float(s[9]), 4)}
    elif ret == "friction":
        retention = {"type": "friction", "gap": round(float(c), 4)}
    else:
        retention = {"type": "none"}
    return {
        "product": p["slug"],
        "frame": [[1, 0, 0, round(float(ox), 4)], [0, 1, 0, round(float(oy), 4)],
                  [0, 0, 1, round(float(oz), 4)], [0, 0, 0, 1]],
        "material": str(params.get("material", "PLA")),
        "clearance": clearance,
        "retention": retention,
        "sources": catalog.sources(p),
    }


def write(build_dir: Path, r: rc.Recipe, params: dict, log: str) -> Path | None:
    """Write build_dir/engineering.json for a fitted part; None when the recipe is not one."""
    eng = engineering(r, params, log)
    if eng is None:
        return None
    out = Path(build_dir) / "engineering.json"
    out.write_text(json.dumps(eng, indent=1) + "\n")
    return out
