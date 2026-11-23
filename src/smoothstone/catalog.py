"""The product catalog: real products a part is made to fit, with every size sourced.

Each product is one file in src/smoothstone/products/<slug>.json: the maker's published sizes
(body, body_sources, features, sources, in the product frame of evals/README.md "Engineering
specs"), the names and model numbers people type (aliases), and how a case holds it (fitted_case,
open_faces, board, shaft). A product's numbers are copied from documents the maker publishes, with the URL
next to each; a product whose numbers are not published is left out, never estimated.

The ten products here are the tuning set (from evals/engineering). Products for a held-out set come
later and must not be tuned on.

A product the catalog does not have comes from the person: `stone product add` writes it to the job
(job/products/<slug>.json, the same schema, "set": "job") with the size they gave and where it came
from, and while that job is the current one (use_job) every function here sees it like a shipped one.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).resolve().parent / "products"
FACES = ("+x", "-x", "+y", "-y", "+z", "-z")


@lru_cache(maxsize=1)
def _shipped() -> dict[str, dict]:
    out = {}
    for f in sorted(DIR.glob("*.json")):
        p = json.loads(f.read_text())
        out[p["slug"]] = p
    return out


# The job whose own products (job/products/<slug>.json, written by stone product add) count as part
# of the catalog while it is the current one. stone sets it for every command (cli.run).
JOB: Path | None = None


def use_job(root: Path | None) -> None:
    """Make root the current job, so its products are in the catalog; None leaves only the shipped ones."""
    global JOB
    JOB = Path(root) if root is not None else None


def job_products(root: Path | None = None) -> dict[str, dict]:
    """slug -> product record, the products the person gave this job (none for no job)."""
    root = root if root is not None else JOB
    out = {}
    if root is None:
        return out
    for f in sorted((Path(root) / "products").glob("*.json")):
        try:
            p = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(p, dict) and p.get("slug") and p["slug"] not in _shipped():
            out[p["slug"]] = p
    return out


def _all() -> dict[str, dict]:
    return {**_shipped(), **job_products()}


def all_products() -> dict[str, dict]:
    """slug -> product record, every product in the catalog, the current job's included."""
    return dict(_all())


def shipped() -> dict[str, dict]:
    """slug -> product record, the products that ship with stone (src/smoothstone/products)."""
    return dict(_shipped())


def get(slug: str) -> dict | None:
    return _all().get(slug)


def case_slugs() -> list[str]:
    """The products a fitted case can hold (fitted_case true), sorted."""
    return sorted(s for s, p in _all().items() if p.get("fitted_case"))


def is_round(p: dict) -> bool:
    """A round body: a revolved profile, or a disc (w = d and corner_r half of it)."""
    b = p["body"]
    return bool(b.get("profile")) or (abs(float(b["w"]) - float(b["d"])) < 1e-6
                                      and float(b.get("corner_r") or 0) >= float(b["w"]) / 2 - 1e-6)


def bottom_holes(p: dict) -> list[dict]:
    """The mounting holes on the product's -z face (a board's)."""
    return [f for f in p.get("features", []) if f["kind"] == "hole" and f["face"] == "-z"]


# Which products each kind of part can be made for, from the shape of the product alone (no product
# is named here): a recipe's catalog parameter ("catalog": "<kind>") offers these.
KINDS = {
    "fitted_case": lambda p: bool(p.get("fitted_case")),
    "round_case": lambda p: is_round(p) and not p.get("shaft"),
    "product_holder": lambda p: not is_round(p) and not p.get("shaft"),
    "product_mount": lambda p: not is_round(p) and not p.get("shaft"),
    "board_plate": lambda p: len(bottom_holes(p)) >= 2 and not p.get("shaft"),
    "knob": lambda p: bool(p.get("shaft")),
}


def slugs_for(kind: str) -> list[str]:
    """The catalog products a part of this kind can be made for, sorted."""
    ok = KINDS.get(kind)
    if ok is None:
        raise KeyError(f"no catalog kind {kind!r}")
    return sorted(s for s, p in _all().items() if ok(p))


def kinds_for(slug: str) -> list[str]:
    """The kinds of part the catalog can make for a product."""
    p = get(slug)
    return [k for k, ok in KINDS.items() if p is not None and ok(p)]


def slug_of(name: str) -> str:
    """A product name as a slug: "Mac Studio (2025)" is mac_studio_2025."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def model_numbers(name: str) -> list[str]:
    """The model numbers in a product's name: words of 4 or more characters with letters and digits
    both ("A1388", "ABX00080"); a year or a chip name such as M4 is not one."""
    return [w for w in re.findall(r"[A-Za-z0-9-]+", name)
            if len(w) >= 4 and re.search(r"[A-Za-z]", w) and re.search(r"\d", w)]


def make_product(name: str, w: float, d: float, h: float, source: str, corner_r: float | None = None,
                 round_: bool = False, open_faces: list[str] | None = None) -> dict:
    """A product record from the size the person gave and where it comes from (a URL, or "measured by
    the person"), in the catalog's schema. A round one is a disc: w is its diameter, d = w and the
    corner radius half of it. A box is one a fitted case can hold. Nothing here is estimated: a corner
    radius not given is 0, the enclosing box."""
    w, d, h = float(w), float(d), float(h)
    url = first_url(source)
    if round_:
        d, r = w, w / 2
        r_src = f"{source} (half the {w:g} mm diameter: a round body)"
    elif corner_r:
        r = float(corner_r)
        r_src = f"{source} (corner radius {r:g} mm, as the person gave it)"
    else:
        r = 0.0
        r_src = f"no radius given with {source}; 0 is the enclosing box"
    aliases = [name] + [m for m in model_numbers(name) if m != name]
    return {
        "slug": slug_of(name),
        "name": name,
        "aliases": aliases,
        "set": "job",
        "frame": ("x width, y depth (front at -y), z height, as the person gave them; no feature is located, "
                  "so the faces named in open_faces stay clear"),
        "fitted_case": not round_,
        "open_faces": [f for f in FACES if f in (open_faces or [])],
        "body": {"w": w, "d": d, "h": h, "corner_r": round(r, 4)},
        "body_sources": {
            "w": f"{source} ({'diameter' if round_ else 'width'} {w:g} mm, as the person gave it)",
            "d": f"{source} ({'the same diameter: the body is round' if round_ else f'depth {d:g} mm, as the person gave it'})",
            "h": f"{source} (height {h:g} mm, as the person gave it)",
            "corner_r": r_src,
        },
        "features": [],
        "sources": [url] if url else [],
    }


def _plain(text: str) -> str:
    # a dot stays only inside a number (22.5W); a sentence's last dot is not part of a model number
    text = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", text.lower())
    return " " + re.sub(r"[^a-z0-9.]+", " ", text).strip() + " "


# A word right after a product's name that makes it another model: "iPhone 17 Pro Max" is not
# the "iPhone 17 Pro", "Mac mini Pro" not the "Mac mini".
VARIANT = {"max", "plus", "mini", "ultra", "pro", "air", "lite", "se", "xl", "xs", "fe", "neo"}


def _named(alias: str, low: str) -> bool:
    """The plain alias is in the plain text and no variant word follows it there."""
    at = low.find(alias)
    while at >= 0:
        nxt = low[at + len(alias):].split(" ", 1)[0]
        if nxt not in VARIANT:
            return True
        at = low.find(alias, at + 1)
    return False


def find(text: str, only: list[str] | None = None) -> str | None:
    """The slug of the catalog product the text names, by its longest alias (case does not matter,
    model numbers included), or None. `only` limits the search to those slugs. An alias followed by
    a variant word (VARIANT) names another model, so it does not count."""
    low = _plain(text)
    best, size = None, 0
    for slug, p in _all().items():
        if only is not None and slug not in only:
            continue
        for a in p.get("aliases", []):
            pa = _plain(a)
            if len(pa) > size and _named(pa, low):
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


PIN_PLAY = 0.3  # mm a locating pin is under its hole's diameter: YAPP_Box's standoffPinDiameter 2.4 in a 2.7 hole


def standoffs(p: dict) -> list[list[float]]:
    """[x, y, diameter, hole, pin] in the product frame for each mounting hole on -z: a standoff that
    bears on the hole's pad (1 mm inside it), or on a ring 1.2 mm wide around the hole when no pad is
    published, with a locating pin PIN_PLAY under the hole's diameter (YAPP_Box's idea) so the board
    cannot slide farther than half that play."""
    out = []
    w = float(p["body"]["w"])
    for f in p.get("features", []):
        if f["kind"] != "hole" or f["face"] != "-z":
            continue
        hole = float(f["size"][0])
        pad = (f.get("pad") or [hole + 2.4])[0]
        out.append([round(w - float(f["c"][0]), 4), float(f["c"][1]), round(float(pad) - 1.0, 4), hole,
                    round(hole - PIN_PLAY, 4)])
    return out


def pin_travel(p: dict) -> float | None:
    """How far a board on its locating pins can slide, mm: half the largest pin play; None when the
    product has no pins (nothing in the catalog bounds how far it slides)."""
    s = standoffs(p) if p.get("board") else []
    return round(max((h - pin) / 2 for *_, h, pin in s), 4) if s else None


def _free(face: str, p: dict, u: float) -> float:
    """How far an arm centered at u on a face is from the nearest window or corner, mm (below 0: it hits one)."""
    need = ARM_W / 2 + ARM_SLOT + 1.0
    L = face_len(face, p["body"])
    room = min(u - need - ARM_EDGE, L - ARM_EDGE - u - need)
    for f, wu, _, hw, _, _ in windows(p):
        if f == face:
            room = min(room, abs(u - wu) - hw - need)
    return room


CATCH_GAP = 0.3  # mm from the product's top (the envelope's) up to a catch's underside; recipe.scad uses the same
CATCH_BELOW = 0.5  # mm: a catch bears on a surface whose top is at most this far below its underside
CATCH_MARGIN = 0.5  # mm a catch's footprint keeps inside its surface along the wall
MAX_REACH_GAP = 2.5  # mm from a catch surface's edge to the wall the arm stands in, at most


def _feature(p: dict, name: str) -> dict:
    return next(f for f in p.get("features", []) if f["name"] == name)


def catch_surfaces(p: dict) -> list[list]:
    """Where a snap catch can bear on the product: [feature, x0, x1, y0, y1, top z] in the product frame,
    one per snap_catch entry. A side feature locates its span along its face (c and size) and its top
    (c v + size h / 2); the entry adds its sourced span along the face's normal (x for a +x or -x
    feature, y for a +y or -y one). A product with no snap_catch has nothing a catch can bear on."""
    b = p["body"]
    w, d = float(b["w"]), float(b["d"])
    out = []
    for e in p.get("snap_catch", []):
        f = _feature(p, e["feature"])
        u, v = float(f["c"][0]), float(f["c"][1])
        sw, sh = float(f["size"][0]), float(f["size"][1])
        top = v + sh / 2
        if f["face"] in ("+x", "-x"):
            y_mid = u if f["face"] == "+x" else d - u
            x0, x1 = (float(t) for t in e["x"])
            y0, y1 = y_mid - sw / 2, y_mid + sw / 2
        else:
            x_mid = u if f["face"] == "-y" else w - u
            x0, x1 = x_mid - sw / 2, x_mid + sw / 2
            y0, y1 = (float(t) for t in e["y"])
        out.append([f["name"], round(x0, 4), round(x1, 4), round(y0, 4), round(y1, 4), round(top, 4)])
    return out


def snap_arms(p: dict) -> list[list]:
    """For a snap case: [face, u, gap, top] per arm, one arm per catch surface, in the closed side wall
    nearest the surface (not the surface's own face, where its port is): u is the arm's center along
    the wall, gap how far the surface's edge is from the product's face there, top the surface's top z.
    The arm's catch spans the arm's width, at least CATCH_MARGIN inside the surface and clear of every
    window and corner, placed where the less of those two room figures is greatest. A surface whose top is too far below the catch, or too far from a wall, gets none."""
    b = p["body"]
    w, d, h = float(b["w"]), float(b["d"]), float(b["h"])
    open_faces = set(p.get("open_faces", []))
    out = []
    for name, x0, x1, y0, y1, top in catch_surfaces(p):
        if h + CATCH_GAP - top > CATCH_BELOW:
            continue
        own = _feature(p, name)["face"]
        best = None
        for face, gap in (("+y", d - y1), ("-y", y0), ("+x", w - x1), ("-x", x0)):
            if face == own or face in open_faces or gap > MAX_REACH_GAP:
                continue
            lo, hi = (x0, x1) if face in ("+y", "-y") else (y0, y1)
            lo, hi = lo + ARM_W / 2 + CATCH_MARGIN, hi - ARM_W / 2 - CATCH_MARGIN
            L = face_len(face, b)
            n = max(1, int((hi - lo) * 4))
            for i in range(n + 1):
                t = lo + (hi - lo) * i / n  # x along a y wall, y along an x wall
                u = {"-y": t, "+y": w - t, "+x": t, "-x": d - t}[face]
                if 0 <= u <= L:
                    room = _free(face, p, u)
                    inside = min(t - lo, hi - t) + CATCH_MARGIN  # how far the catch keeps inside the surface
                    score = min(room, inside)
                    if room >= 0 and (best is None or score > best[0] + 1e-9):
                        best = (score, [face, round(u, 2), round(gap, 4), top])
        if best:
            out.append(best[1])
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


def _case_rows(products: dict[str, dict]) -> list[str]:
    rows = []
    for slug in sorted(s for s, p in products.items() if p.get("fitted_case")):
        p = products[slug]
        b = p["body"]
        board = p.get("board")
        pcb = float(board["pcb_underside_z"]) if board else -1.0
        arms = snap_arms(p)
        rows.append(_scad([slug, [float(b["w"]), float(b["d"]), float(b["h"])], list(p.get("open_faces", [])),
                           pcb, standoffs(p), windows(p), arms]))
    return rows


def products_value() -> str:
    """The fitted case's PRODUCTS table as one OpenSCAD value, the current job's products included:
    a build for a job product passes it with -D, so the shipped products.scad stays as generated."""
    return "[" + ", ".join(_case_rows(_all())) + "]"


def scad_table() -> str:
    """recipes/fitted_case/products.scad: one row per shipped product a fitted case can hold."""
    lines = ["// GENERATED by tools/products_scad.py from src/smoothstone/products/*.json. Do not edit by hand.",
             "// Row: [slug, [w, d, h], open faces, PCB underside z (-1: not a board), standoffs [[x, y, d, hole, pin]],",
             "//       windows [[face, u, v, half w, half h, round]],",
             "//       snap arms [[face, u, gap from the catch surface to the product's face, the surface's top z]]]",
             "// Product frame (evals/README.md): x width, y depth, z height, origin at the body's min corner.",
             "PRODUCTS = ["]
    lines.append(",\n".join("  " + r for r in _case_rows(_shipped())))
    lines.append("];")
    return "\n".join(lines) + "\n"


# --- every product as one OpenSCAD table (recipes/lib/catalog.scad) ----------------------------
# The product recipes (round_case, product_holder, product_mount, board_plate, knob) read a product
# from this table by its slug and build to its sizes; fitted_case keeps its own layout table above.
FEATURE_ROW = "[name, kind, face, u, v, size w, size h, plug w, plug h, round, depth]"


def _feature_row(f: dict) -> list:
    sw, sh = f["size"]
    pw, ph = f.get("plug") or f["size"]
    return [f["name"], f["kind"], f["face"], float(f["c"][0]), float(f["c"][1]), float(sw), float(sh),
            float(pw), float(ph), f.get("shape") == "circle", float(f.get("depth") or 0)]


def _catalog_rows(products: dict[str, dict]) -> list[str]:
    rows = []
    for slug, p in sorted(products.items()):
        b = p["body"]
        board = p.get("board")
        sh = p.get("shaft")
        rows.append(_scad([slug, [float(b["w"]), float(b["d"]), float(b["h"])], float(b.get("corner_r") or 0),
                           [[float(r), float(z)] for r, z in b.get("profile", [])], list(p.get("open_faces", [])),
                           float(board["pcb_underside_z"]) if board else -1.0,
                           [_feature_row(f) for f in p.get("features", [])],
                           [sh["type"], float(sh.get("flat") or 0)] if sh else []]))
    return rows


def catalog_value() -> str:
    """The CATALOG table as one OpenSCAD value, the current job's products included: a build for a
    job product passes it with -D, so catalog_row(slug) finds it and lib/catalog.scad stays as generated."""
    return "[" + ", ".join(_catalog_rows(_all())) + "]"


def catalog_table() -> str:
    """recipes/lib/catalog.scad: one row per shipped product."""
    lines = ["// GENERATED by tools/products_scad.py from src/smoothstone/products/*.json. Do not edit by hand.",
             "// Row: [slug, [w, d, h], corner_r, profile [[r, z]] ([] for a box), open faces,",
             "//       PCB underside z (-1: not a board), features " + FEATURE_ROW + ",",
             "//       shaft [type, across flats] ([] for no shaft)]",
             "// Product frame (evals/README.md): x width, y depth, z height, origin at the body's min corner.",
             "CATALOG = ["]
    lines.append(",\n".join("  " + r for r in _catalog_rows(_shipped())))
    lines.append("];")
    lines.append("function catalog_row(slug) = let(m = [for (r = CATALOG) if (r[0] == slug) r]) len(m) == 1 ? m[0] : [];")
    return "\n".join(lines) + "\n"
