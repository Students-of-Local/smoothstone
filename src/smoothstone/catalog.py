"""The product catalog: real products a part is made to fit, with every size sourced.

Each product is one file in src/smoothstone/products/<slug>.json: the maker's published sizes
(body, body_sources, features, sources, in the product frame of evals/README.md "Engineering
specs"), the names and model numbers people type (aliases), and how a case holds it (fitted_case,
open_faces, board). A product's numbers are copied from documents the maker publishes, with the URL
next to each; a product whose numbers are not published is left out, never estimated.

The ten products here are the tuning set (from evals/engineering). Products for a held-out set come
later and must not be tuned on.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).resolve().parent / "products"
FACES = ("+x", "-x", "+y", "-y", "+z", "-z")


@lru_cache(maxsize=1)
def _all() -> dict[str, dict]:
    out = {}
    for f in sorted(DIR.glob("*.json")):
        p = json.loads(f.read_text())
        out[p["slug"]] = p
    return out


def all_products() -> dict[str, dict]:
    """slug -> product record, every product in the catalog."""
    return dict(_all())


def get(slug: str) -> dict | None:
    return _all().get(slug)


def case_slugs() -> list[str]:
    """The products a fitted case can hold (fitted_case true), sorted."""
    return sorted(s for s, p in _all().items() if p.get("fitted_case"))


def _plain(text: str) -> str:
    # a dot stays only inside a number (22.5W); a sentence's last dot is not part of a model number
    text = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", text.lower())
    return " " + re.sub(r"[^a-z0-9.]+", " ", text).strip() + " "


def find(text: str, only: list[str] | None = None) -> str | None:
    """The slug of the catalog product the text names, by its longest alias (case does not matter,
    model numbers included), or None. `only` limits the search to those slugs."""
    low = _plain(text)
    best, size = None, 0
    for slug, p in _all().items():
        if only is not None and slug not in only:
            continue
        for a in p.get("aliases", []):
            pa = _plain(a)
            if len(pa) > size and pa in low:
                best, size = slug, len(pa)
    return best


def first_url(text: str) -> str | None:
    """The first http(s) URL in a source text, without trailing punctuation."""
    m = re.search(r"https?://\S+", str(text or ""))
    return m.group(0).rstrip(".,;:)'\"") if m else None


def sources(p: dict) -> dict[str, str]:
    """For w, d, h, corner_r, a profile and every feature: the URL the record cites for that number."""
    out = {}
    for k, v in (p.get("body_sources") or {}).items():
        u = first_url(v)
        if u:
            out[k] = u
    for f in p.get("features", []):
        u = first_url(f.get("source", ""))
        if u:
            out[f["name"]] = u
    return out


# --- the fitted case's layout (recipes/fitted_case reads it as products.scad) --------------------
# Cutouts follow YAPP_Box's per-face idea (https://github.com/mrWheel/YAPP_Box, MIT, by Willem
# Aandewiel): each opening is a center and a size on one face of the product, cut through that wall.
# No YAPP code is copied.
WINDOW_MARGIN = 0.5  # mm around a feature's plug (or opening) left open; the grader leaves this much out too
ARM_W = 6.0  # mm, a snap arm's width
ARM_SLOT = 1.0  # mm, the slot on each side that frees the arm from the wall
ARM_EDGE = 3.0  # mm an arm keeps from the product's corners
SIDE = ("+x", "-x", "+y", "-y")


def face_len(face: str, body: dict) -> float:
    """A side face's length along its u axis (README table: -y and +y run along x, the others y)."""
    return float(body["w"] if face in ("-y", "+y", "+z", "-z") else body["d"])


def windows(p: dict) -> list[list]:
    """[face, u, v, half width, half height, round] for every feature a part must leave open (all but
    mounting holes): its plug, or its opening when no plug is published, plus WINDOW_MARGIN."""
    out = []
    for f in p.get("features", []):
        if f["kind"] == "hole":
            continue
        pw, ph = f.get("plug") or f["size"]
        sw, sh = f["size"]
        hw, hh = max(pw, sw) / 2 + WINDOW_MARGIN, max(ph, sh) / 2 + WINDOW_MARGIN
        rnd = f.get("shape") == "circle"
        if rnd:
            hh = hw
        out.append([f["face"], float(f["c"][0]), float(f["c"][1]), round(hw, 4), round(hh, 4), rnd])
    return out


def standoffs(p: dict) -> list[list[float]]:
    """[x, y, diameter] in the product frame for each mounting hole on -z: a standoff that bears on the
    hole's pad (1 mm inside it), or on a ring 1.2 mm wide around the hole when no pad is published."""
    out = []
    w = float(p["body"]["w"])
    for f in p.get("features", []):
        if f["kind"] != "hole" or f["face"] != "-z":
            continue
        pad = (f.get("pad") or [f["size"][0] + 2.4])[0]
        out.append([round(w - float(f["c"][0]), 4), float(f["c"][1]), round(float(pad) - 1.0, 4)])
    return out


def _free(face: str, p: dict, u: float) -> float:
    """How far an arm centered at u on a face is from the nearest window or corner, mm (below 0: it hits one)."""
    need = ARM_W / 2 + ARM_SLOT + 1.0
    L = face_len(face, p["body"])
    room = min(u - need - ARM_EDGE, L - ARM_EDGE - u - need)
    for f, wu, _, hw, _, _ in windows(p):
        if f == face:
            room = min(room, abs(u - wu) - hw - need)
    return room


def arm_spots(p: dict) -> dict[str, list[float]]:
    """For a snap case: per pair of opposite faces ("y": -y and +y, "x": -x and +x), the arm centers
    [u on the minus face, u on the plus face] at one place along the product, the one farthest from
    every window and corner; no entry when the pair has no room."""
    b = p["body"]
    out = {}
    for key, (lo, hi), span in (("y", ("-y", "+y"), float(b["w"])), ("x", ("-x", "+x"), float(b["d"]))):
        best, at = 0.0, None
        n = int(span * 4)
        for i in range(n + 1):
            t = span * i / n  # x (or y) along the product; -y has u = x, +y has u = w - x; +x u = y, -x u = d - y
            a = t if lo == "-y" else span - t
            c = span - t if hi == "+y" else t
            room = min(_free(lo, p, a), _free(hi, p, c))
            if room > best + 1e-9:
                best, at = room, (round(a, 2), round(c, 2))
        if at is not None:
            out[key] = list(at)
    return out


def _scad(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_scad(x) for x in v) + "]"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(round(v, 4) if isinstance(v, float) else v)


def scad_table() -> str:
    """recipes/fitted_case/products.scad: one row per product a fitted case can hold."""
    lines = ["// GENERATED by tools/products_scad.py from src/smoothstone/products/*.json. Do not edit by hand.",
             "// Row: [slug, [w, d, h], open faces, PCB underside z (-1: not a board), standoffs [[x, y, d]],",
             "//       windows [[face, u, v, half w, half h, round]], arm spots [[\"y\", [u -y, u +y]], [\"x\", [u -x, u +x]]]]",
             "// Product frame (evals/README.md): x width, y depth, z height, origin at the body's min corner.",
             "PRODUCTS = ["]
    rows = []
    for slug in case_slugs():
        p = get(slug)
        b = p["body"]
        board = p.get("board")
        pcb = float(board["pcb_underside_z"]) if board else -1.0
        arms = [[k, v] for k, v in sorted(arm_spots(p).items(), key=lambda kv: kv[0] != "y")]
        rows.append("  " + _scad([slug, [float(b["w"]), float(b["d"]), float(b["h"])], list(p.get("open_faces", [])),
                                  pcb, standoffs(p), windows(p), arms]))
    lines.append(",\n".join(rows))
    lines.append("];")
    return "\n".join(lines) + "\n"
