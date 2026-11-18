"""A painted multi-color 3MF from a passing build.

regions(): the part's faces split into colored regions, from the figure's style picture (paint.py)
or one region for a part without a picture. write_3mf(): the STL's own float32 mesh in the
Bambu/Orca 3MF layout with `paint_color` on each painted triangle, which Orca, Bambu Studio,
Creality Print and PrusaSlicer read as filament paint. check_3mf(): read that file back the way a
slicer does.
"""
from __future__ import annotations

import heapq
import re
import uuid
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from . import clean

MIN_SHARE = 0.015  # a region under this share of the surface joins its neighbor...
SPECK = 0.003  # ...unless it is at least this big and stands out from that neighbor (hands beside a jacket)
CONTRAST = 50.0  # delta E (Lab) that counts as standing out; shading on one cloth stays well under it
LIST_MAX = 8
LAYER = 0.2  # mm
PURGE_G = 0.65  # grams of purge per filament change, about what Orca's default flush uses
MANY_LAYERS = 10  # a warning from this many mixed layers
MAX_FILAMENTS = 16
EDGE_RADIUS = 1.5  # mm: color boundaries are smoothed over about this distance before the cut
EDGE_WINDOW = 2.0  # mm of arc length: the moving average a boundary is compared with
JAGGED = 1.08  # a boundary this much longer than its smoothed self zigzags
EDGE_SPAN = 5.0  # mm: the stretch the wobble check looks at
WOBBLE = 0.15  # mm: over any EDGE_SPAN stretch a crisp edge stays this close to one plane
LEDGE_MM = 2.0  # mm from a part's color edge where an up-facing face of the upper color is a ledge
LEDGE_NZ = 0.5  # a face whose normal points up at least this much faces up (within 60 degrees)
LEDGE_AREA = 0.2  # mm2 of such faces seen (parts.visible_faces) in any 30 degree sector fails the check
EDGE_MIN = 4.0  # mm: shorter boundary pieces (ends at a three-color corner) are too short to judge
VOLUME_TOL = 0.0005  # the painted mesh keeps the STL's volume within 0.05%

# plain color names and a typical filament of each
NAMES = {
    "white": (240, 240, 240), "black": (25, 25, 28), "gray": (128, 128, 128),
    "brown": (110, 70, 40), "tan": (205, 175, 125), "skin": (232, 188, 152),
    "red": (200, 30, 35), "orange": (240, 130, 30), "yellow": (240, 210, 40),
    "green": (50, 150, 60), "blue": (40, 80, 200), "purple": (120, 60, 160),
    "pink": (240, 150, 185),
}
ALIASES = {"grey": "gray", "beige": "tan", "gold": "yellow", "silver": "gray", "violet": "purple"}
# words in a request that ask for color
WORDS = set(NAMES) | {"grey", "color", "colour", "colors", "colours", "colored", "coloured",
                      "two-color", "two-colour", "multicolor", "multicolour", "multi-color", "multi-colour"}

NS_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"


# filament paint codes


def paint_code(n: int) -> str:
    """Orca's triangle paint code for filament n: 1 "4", 2 "8", n >= 3 is hex nibble (n - 3) then "C"."""
    if not 1 <= n <= MAX_FILAMENTS:
        raise ValueError(f"filament {n} is outside 1..{MAX_FILAMENTS}")
    if n == 1:
        return "4"
    if n == 2:
        return "8"
    return f"{n - 3:X}C"


def decode_paint(code: str) -> int:
    """The filament a whole-triangle paint code stands for; ValueError for anything else."""
    c = code.strip().upper()
    if c == "4":
        return 1
    if c == "8":
        return 2
    if len(c) == 2 and c[1] == "C" and c[0] in "0123456789ABCDEF":
        n = int(c[0], 16) + 3
        if n <= MAX_FILAMENTS:
            return n
    raise ValueError(f"not a filament paint code: {code!r}")


# colors


def _lab(rgb) -> np.ndarray:
    from .paint import _to_lab

    return _to_lab(np.asarray(rgb, dtype=float).reshape(-1, 3))


def color_name(rgb) -> str:
    """The nearest plain color name."""
    names = list(NAMES)
    d = ((_lab(list(NAMES.values())) - _lab(rgb)) ** 2).sum(1)
    return names[int(d.argmin())]


def word_color(word: str) -> str | None:
    """The plain color a word names: "grey" -> "gray", "dark-red" -> "red", "sky-blue" -> "blue"."""
    w = word.strip().lower()
    w = ALIASES.get(w, w)
    if w in NAMES:
        return w
    if "-" in w:  # a shade: the last word that is a color names it
        for p in reversed(w.split("-")):
            p = ALIASES.get(p, p)
            if p in NAMES:
                return p
    return None


def filament_rgb(name: str):
    """A display color for a filament name ("white", "matte black", "#FF0000"), or None."""
    s = name.strip().lower()
    if re.fullmatch(r"#[0-9a-f]{6}", s):
        return tuple(int(s[i:i + 2], 16) for i in (1, 3, 5))
    for w in re.findall(r"[a-z]+", s):
        c = word_color(w)
        if c:
            return NAMES[c]
    return None


def subject_names(request: str, also=()) -> list[str]:
    """The names of people (or pets) in a request: runs of two or more capitalized words
    ("Jack Black", "Betty White"), and any name given in `also` (the name stone find searched)."""
    out = [n for n in also if n]
    for m in re.finditer(r"\b[A-Z][a-z'.]+(?:[ -][A-Z][a-z'.]+)+\b", request):
        if m.group(0) not in out:
            out.append(m.group(0))
    return out


def without_names(request: str, names=()) -> str:
    """The request with the subject's name taken out, so "Jack Black" is not a color."""
    for n in sorted(names, key=len, reverse=True):
        request = re.sub(re.escape(n), " ", request, flags=re.I)
    return request


def request_colors(request: str, names=()) -> list[str]:
    """Plain color names a request mentions, in order, leaving out the subject's name."""
    out = []
    for w in re.findall(r"[a-z]+(?:-[a-z]+)?", without_names(request, names).lower()):
        c = word_color(w)
        if c and c not in out:
            out.append(c)
    return out


def asks_for_color(request: str, names=()) -> bool:
    words = re.findall(r"[a-z]+(?:-[a-z]+)?", without_names(request, names).lower())
    return any(w in WORDS or word_color(w) for w in words)


STOP = {"but", "except", "with", "and", "or", "while", "which", "that", "is", "are", "in", "on",
        "everywhere", "everything", "else", "rest", "all", "other", "others"}


def part_colors(request: str, names=()) -> dict[str, str]:
    """The colors a request gives to parts of a figure: {"top": "black"} for "a black jacket",
    "the jacket in black" or "the jacket, which is black"; "picture" for a part after "all
    <color> but" with no color of its own (it keeps its color from the picture). Keys are parts
    (parts.part_of), the word the request used under "word:<part>"."""
    from .parts import part_of

    words = re.findall(r"[a-z]+(?:-[a-z]+)?|[,.;]", without_names(request, names).lower())
    out: dict[str, str] = {}
    used: dict[str, str] = {}

    def give(i, c):
        p = part_of(words[i])
        if p and p not in out:
            out[p] = c
            used[p] = words[i]

    for i, w in enumerate(words):
        p = part_of(w)
        if p is None:
            continue
        # <color> <up to two words> <part>: "a black leather jacket"
        for j in range(i - 1, max(-1, i - 4), -1):
            if words[j] in STOP or words[j] in ",.;":
                break
            c = word_color(words[j])
            if c:
                give(i, c)
                break
        if p in out:
            continue
        # <part> in <color>, <part> is <color>, <part>, which is <color>
        k = i + 1
        if k < len(words) and words[k] == ",":
            k += 1
        if k < len(words) and words[k] in ("which", "that"):
            k += 1
        if k < len(words) and words[k] in ("in", "is", "are"):
            for j in range(k + 1, min(len(words), k + 4)):
                if words[j] in ",.;":
                    break
                c = word_color(words[j])
                if c:
                    give(i, c)
                    break
    # all <color> but / except (for) the <part> (and the <part>): those keep the picture's color
    for i, w in enumerate(words):
        if w in ("but", "except") and i >= 1 and any(word_color(x) for x in words[max(0, i - 3):i]):
            for j in range(i + 1, min(len(words), i + 8)):
                if words[j] in ".;":
                    break
                p = part_of(words[j])
                if p and p not in out:
                    out[p] = "picture"
                    used[p] = words[j]
    out.update({f"word:{p}": w for p, w in used.items()})
    return out


def nearest_filament(rgb, filaments: list[str]) -> int:
    """1-based number of the loaded filament closest in color; filament 1 when none has a color."""
    best, bd = 1, np.inf
    for i, f in enumerate(filaments, 1):
        c = filament_rgb(f)
        if c is None:
            continue
        d = float(((_lab(c) - _lab(rgb)) ** 2).sum())
        if d < bd:
            best, bd = i, d
    return best


# the mesh


def shared(vertices, faces):
    """Vertices merged by exact float32 position (as a slicer reads them), faces in the same order."""
    v32 = np.asarray(vertices, dtype=np.float32)
    uniq, inv = np.unique(v32, axis=0, return_inverse=True)
    return uniq, inv.reshape(-1)[np.asarray(faces, dtype=np.int64)]


def load_stl_mesh(vertices, faces):
    """A trimesh of the mesh as a slicer reads it: float32 corners shared by exact position."""
    import trimesh

    v, f = shared(vertices, faces)
    return trimesh.Trimesh(v.astype(np.float64), f, process=False)


def load_stl(path: Path):
    import trimesh

    m = trimesh.load(str(path), force="mesh", process=False)
    return load_stl_mesh(m.vertices, m.faces)


def base_top(recipe: str, params: dict) -> float:
    """Height of the plinth's top for a recipe with one, else 0."""
    if recipe != "figure" or params.get("base", "round") == "none":
        return 0.0
    try:
        bh = float(params.get("base_h") or 0)
    except (TypeError, ValueError):
        bh = 0.0
    return bh if bh > 0 else (8.0 if not params.get("name") else 12.0)


def smooth_labels(mesh, labels: np.ndarray, rounds: int = 3, keep=None, never: int | None = None) -> np.ndarray:
    """Majority vote over each face's edge neighbors; removes specks a picture leaves. Faces in
    `keep` hold their label, and no other face can take label `never` (the plinth's)."""
    adj = mesh.face_adjacency
    k = int(labels.max()) + 1
    for _ in range(rounds):
        votes = np.zeros((len(labels), k))
        votes[np.arange(len(labels)), labels] += 1.5
        np.add.at(votes, (adj[:, 0], labels[adj[:, 1]]), 1)
        np.add.at(votes, (adj[:, 1], labels[adj[:, 0]]), 1)
        if never is not None and never < k:
            votes[:, never] = -1
        new = votes.argmax(1)
        if keep is not None:
            new[keep] = labels[keep]
        labels = new
    return labels


def regions(mesh, labels: np.ndarray, base=None, min_share: float = MIN_SHARE, lab=None, zone=None) -> np.ndarray:
    """Connected regions of equal label over face adjacency, numbered from 0. Regions under
    `min_share` of the surface join the neighbor they share the longest edge with, except that with
    `lab` (a Lab color per label) a region of at least SPECK that differs from that neighbor by more
    than CONTRAST stays its own: white hands on a black jacket are small but not noise. Faces in the
    `base` mask are one region of their own that never merges. With `zone` (a part of the body
    per face), a region never spans two zones and joins only a neighbor in its own zone."""
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components

    n = len(mesh.faces)
    labels = np.asarray(labels).copy()
    base = np.zeros(n, bool) if base is None else np.asarray(base, bool)
    if base.any():
        labels[base] = labels.max() + 1  # its own label, so it is its own component
    zone = np.zeros(n, int) if zone is None else np.asarray(zone, int)
    adj = mesh.face_adjacency
    same = (labels[adj[:, 0]] == labels[adj[:, 1]]) & (zone[adj[:, 0]] == zone[adj[:, 1]])
    a, b = adj[same, 0], adj[same, 1]
    G = sp.coo_matrix((np.ones(len(a)), (a, b)), shape=(n, n))
    nc, comp = connected_components(G, directed=False)
    comp_label = np.zeros(nc, int)
    comp_label[comp] = labels
    comp_zone = np.zeros(nc, int)
    comp_zone[comp] = zone
    if base.any():  # the plinth and the name letters are one region even where they do not touch
        bid = comp[base][0]
        comp[base] = bid
    area = np.bincount(comp, weights=mesh.area_faces, minlength=nc)
    is_base = np.zeros(nc, bool)
    if base.any():
        is_base[comp[base][0]] = True
    # shared edge length between neighboring components
    ev = mesh.face_adjacency_edges
    elen = np.linalg.norm(mesh.vertices[ev[:, 0]] - mesh.vertices[ev[:, 1]], axis=1)
    ca, cb = comp[adj[:, 0]], comp[adj[:, 1]]
    diff = ca != cb
    nb: list[dict[int, float]] = [dict() for _ in range(nc)]
    for x, y, L in zip(ca[diff], cb[diff], elen[diff]):
        nb[x][y] = nb[x].get(y, 0.0) + L
        nb[y][x] = nb[y].get(x, 0.0) + L
    parent = np.arange(nc)
    thresh = min_share * area.sum()
    heap = [(area[i], i) for i in range(nc) if not is_base[i] and area[i] < thresh]
    heapq.heapify(heap)
    alive = np.ones(nc, bool)
    while heap:
        ar, i = heapq.heappop(heap)
        if not alive[i] or ar != area[i] or area[i] >= thresh:
            continue
        cands = {j: L for j, L in nb[i].items() if alive[j] and (comp_zone[j] == comp_zone[i] or is_base[j])}
        if not cands:
            continue  # an island on its own (a loose piece): it stays
        plain = {j: L for j, L in cands.items() if not is_base[j]}
        pick = plain or cands
        j = max(pick, key=pick.get)
        if is_base[j]:
            continue  # only the plinth touches it: leave it, the base never grows
        if (lab is not None and area[i] >= SPECK * area.sum() and comp_label[i] < len(lab)
                and comp_label[j] < len(lab)
                and np.linalg.norm(lab[comp_label[i]] - lab[comp_label[j]]) > CONTRAST):
            continue  # small but plainly a different color from what it touches: keep it
        # i joins j
        alive[i] = False
        parent[i] = j
        area[j] += area[i]
        for k, L in nb[i].items():
            if k == j:
                continue
            nb[j][k] = nb[j].get(k, 0.0) + L
            nb[k][j] = nb[k].get(j, 0.0) + L
            nb[k].pop(i, None)
        nb[j].pop(i, None)
        nb[i] = {}
        if area[j] < thresh:
            heapq.heappush(heap, (area[j], j))
    root = parent.copy()
    for i in range(nc):  # follow merges to the live region
        r = i
        while parent[r] != r:
            r = parent[r]
        root[i] = r
    out = root[comp]
    _, out = np.unique(out, return_inverse=True)
    return out.reshape(-1)


def describe(mesh, region: np.ndarray, rgb: np.ndarray, base_region: int | None) -> list[dict]:
    """One entry per region, largest first: share of surface, z span, position word, color."""
    z = mesh.triangles_center[:, 2]
    lo, hi = mesh.bounds[0, 2], mesh.bounds[1, 2]
    H = max(hi - lo, 1e-9)
    area = mesh.area_faces
    total = area.sum()
    out = []
    for r in range(int(region.max()) + 1):
        sel = region == r
        if not sel.any():
            continue
        a = area[sel]
        zc = float((z[sel] * a).sum() / a.sum())
        f = (zc - lo) / H
        if r == base_region:
            pos = "base"
        else:
            pos = "base" if f < 0.12 else "bottom" if f < 0.4 else "middle" if f < 0.7 else "top"
        col = rgb[r]
        out.append({
            "region": r, "share": float(a.sum() / total), "z0": float(mesh.vertices[mesh.faces[sel]][:, :, 2].min()),
            "z1": float(mesh.vertices[mesh.faces[sel]][:, :, 2].max()), "pos": pos, "base": r == base_region,
            "rgb": None if col is None else [float(c) for c in col],
            "color": None if col is None else color_name(col),
        })
    out.sort(key=lambda d: -d["share"])
    for i, d in enumerate(out, 1):
        d["n"] = i
    return out


def figure_labels(mesh, fig_labels: np.ndarray, base: np.ndarray, npal: int) -> np.ndarray:
    """Palette label per face, smoothed. The plinth has a label of its own (npal) that votes for
    nothing, so feet beside it keep their color instead of taking palette color 0."""
    labels = np.full(len(mesh.faces), npal, int)
    labels[~base] = fig_labels
    return smooth_labels(mesh, labels, keep=base, never=npal)


def find_regions(mesh, recipe: str, params: dict, front: Path | None, back: Path | None, atlas: Path,
                 look: str = "") -> dict:
    """The color regions of a part: {"mesh" (the mesh they are on: a figure's is cut along the
    lines of its shape), "num" (region number 1..R per face), "regions" (the list, largest first,
    with a part name each on a figure), "fixed" (faces whose color edge is already a line of the
    shape, kept through the edge smoothing) and "anatomy" (a figure's hem, neck and wrists)}."""
    from . import parts

    n = len(mesh.faces)
    if front is None or not Path(front).is_file():
        region = np.zeros(n, int)
        info = describe(mesh, region, [None], None)
        info[0]["pos"] = "whole part"
        return {"mesh": mesh, "num": region + 1, "regions": info, "fixed": None, "anatomy": None}
    import trimesh

    from . import paint

    top = base_top(recipe, params)
    anat = None
    if recipe == "figure" and top > 0:
        anat = parts.anatomy(mesh, top)
        if parts.all_lines(anat):
            V, F = parts.cut(mesh.vertices, mesh.faces, anat)
            mesh = load_stl_mesh(V, F)
            n = len(mesh.faces)
    zc = mesh.triangles_center[:, 2]
    ztop = mesh.vertices[mesh.faces][:, :, 2].max(1)
    # the plinth's top face lies at exactly `top`: a face is base when its center is below the top
    # or it lies flat on it
    base = (zc < top) | (ztop <= top + 0.01) if top > 0 else np.zeros(n, bool)
    fig = ~base
    # project the pictures on the figure alone, scaled to unit height as paint.py expects
    sub = trimesh.Trimesh(mesh.vertices, mesh.faces[fig], process=False)
    sub.remove_unreferenced_vertices()
    lo = sub.bounds[0]
    sub.vertices = (sub.vertices - lo) / max(sub.extents[2], 1e-9)
    rgb_f = paint.face_colors(sub, Path(front), Path(back) if back else None, atlas)
    pal, lab_f = paint.palette(rgb_f, most=6)
    labels = figure_labels(mesh, lab_f, base, len(pal))
    zone = None
    fixed = base.copy()
    if anat is not None:
        zone, hand = parts.zones(mesh, anat, base)
        labels, band = parts.snap(mesh, labels, zone, hand, anat)
        fixed |= band
    reg = regions(mesh, labels, base=base if base.any() else None, lab=_lab(pal), zone=zone)

    def listing(reg):
        R = int(reg.max()) + 1
        rgb: list = [None] * R
        base_region = int(reg[base][0]) if base.any() else None
        area = mesh.area_faces
        for r in range(R):
            if r == base_region:
                continue
            sel = reg == r
            votes = np.bincount(labels[sel], weights=area[sel], minlength=len(pal) + 1)[:len(pal)]
            rgb[r] = pal[int(votes.argmax())]
        info = describe(mesh, reg, rgb, base_region)
        if anat is not None:
            parts.name_parts(mesh, reg, info, zone, anat, look)
        return info

    info = listing(reg)
    merged = []
    if anat is not None:
        keep = {d["region"] for d in info if d["part"] != "other"}
        reg, merged = parts.merge_odd(mesh, reg, labels, zone, keep, anat["center"])
        if merged:
            _, reg = np.unique(reg, return_inverse=True)
            reg = reg.reshape(-1)
            info = listing(reg)
    num = np.zeros(int(reg.max()) + 1, int)
    for d in info:
        num[d["region"]] = d["n"]
    if anat is not None:
        anat = {**anat, "merged": [why for _, _, why in merged]}
    return {"mesh": mesh, "num": num[reg], "regions": info, "fixed": fixed if anat is not None else (base if base.any() else None),
            "anatomy": anat}


# 3MF


NS = ('xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
      'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
      'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p"')
CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
    ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
    ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n</Types>\n')


def _rels(target: str) -> str:
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
            f' <Relationship Target="{target}" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n'
            '</Relationships>\n')


def write_3mf(path: Path, vertices, faces, filament: np.ndarray, name: str, bed=(256.0, 256.0, 256.0)) -> int:
    """Write a Bambu/Orca project 3MF of one object. `filament` gives each face's filament (1-based).
    The object takes the most used filament and its triangles stay unpainted; the rest carry
    `paint_color`. Vertices are shared by exact float32 position. Returns the object filament."""
    v, f = shared(vertices, faces)
    filament = np.asarray(filament, dtype=int)
    p = np.asarray(v, dtype=np.float64)[f]
    area = np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1) / 2
    main = int(np.bincount(filament, weights=area).argmax())
    codes = {n: f' paint_color="{paint_code(n)}"' for n in np.unique(filament) if n != main}
    codes[main] = ""
    lo, hi = v.min(0).astype(float), v.max(0).astype(float)
    X, Y, Z = bed[0] / 2 - (lo[0] + hi[0]) / 2, bed[1] / 2 - (lo[1] + hi[1]) / 2, -lo[2]
    verts = "\n".join(f'<vertex x="{x:.9g}" y="{y:.9g}" z="{z:.9g}"/>' for x, y, z in v.astype(np.float64))
    tris = "\n".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"{codes[k]}/>' for (a, b, c), k in zip(f, filament))
    obj = (f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" {NS}>\n'
           '<metadata name="BambuStudio:3mfVersion">1</metadata>\n<resources>\n'
           f'<object id="1" p:UUID="{uuid.uuid4()}" type="model"><mesh><vertices>\n{verts}\n</vertices><triangles>\n{tris}\n'
           '</triangles></mesh></object>\n</resources>\n<build/>\n</model>\n')
    tf = f"1 0 0 0 1 0 0 0 1 {X:.4f} {Y:.4f} {Z:.4f}"
    root = (f'<?xml version="1.0" encoding="UTF-8"?>\n<model unit="millimeter" xml:lang="en-US" {NS}>\n'
            '<metadata name="Application">smoothstone</metadata>\n'
            '<metadata name="BambuStudio:3mfVersion">1</metadata>\n<resources>\n'
            f'<object id="2" p:UUID="{uuid.uuid4()}" type="model"><components>'
            f'<component p:path="/3D/Objects/object_1.model" objectid="1" p:UUID="{uuid.uuid4()}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>'
            '</components></object>\n</resources>\n'
            f'<build p:UUID="{uuid.uuid4()}"><item objectid="2" p:UUID="{uuid.uuid4()}" transform="{tf}" printable="1"/></build>\n'
            '</model>\n')
    settings = ('<?xml version="1.0" encoding="UTF-8"?>\n<config>\n  <object id="2">\n'
                f'    <metadata key="name" value="{name}"/>\n    <metadata key="extruder" value="{main}"/>\n'
                f'    <part id="1" subtype="normal_part">\n      <metadata key="name" value="{name}"/>\n'
                '      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n'
                f'      <metadata key="extruder" value="{main}"/>\n'
                '    </part>\n  </object>\n  <plate>\n    <metadata key="plater_id" value="1"/>\n'
                '    <metadata key="plater_name" value=""/>\n    <metadata key="locked" value="false"/>\n'
                '    <model_instance>\n      <metadata key="object_id" value="2"/>\n'
                '      <metadata key="instance_id" value="0"/>\n      <metadata key="identify_id" value="101"/>\n'
                '    </model_instance>\n  </plate>\n  <assemble>\n'
                f'   <assemble_item object_id="2" instance_id="0" transform="{tf}" offset="0 0 0" />\n'
                '  </assemble>\n</config>\n')
    layers = ('<?xml version="1.0" encoding="utf-8"?>\n<custom_gcodes_per_layer>\n<plate>\n<plate_info id="1"/>\n'
              '<mode value="MultiExtruder"/>\n</plate>\n</custom_gcodes_per_layer>\n')
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", _rels("/3D/3dmodel.model"))
        z.writestr("3D/3dmodel.model", root)
        z.writestr("3D/_rels/3dmodel.model.rels", _rels("/3D/Objects/object_1.model"))
        z.writestr("3D/Objects/object_1.model", obj)
        z.writestr("Metadata/model_settings.config", settings)
        z.writestr("Metadata/custom_gcode_per_layer.xml", layers)
    tmp.replace(path)
    return main


def read_3mf(path: Path) -> tuple[np.ndarray, np.ndarray, list[str], int]:
    """(vertices, faces, paint code per face or "", object filament) from a 3MF write_3mf made."""
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("3D/Objects/object_1.model"))
        settings = z.read("Metadata/model_settings.config").decode()
    ns = {"m": NS_CORE}
    vs = root.findall(".//m:vertices/m:vertex", ns)
    ts = root.findall(".//m:triangles/m:triangle", ns)
    v = np.array([[float(e.get("x")), float(e.get("y")), float(e.get("z"))] for e in vs], dtype=np.float64)
    f = np.array([[int(e.get("v1")), int(e.get("v2")), int(e.get("v3"))] for e in ts], dtype=np.int64)
    codes = [e.get("paint_color") or "" for e in ts]
    m = re.search(r'key="extruder" value="(\d+)"', settings)
    return v.reshape(-1, 3), f.reshape(-1, 3), codes, int(m.group(1)) if m else 1


def check_3mf(path: Path, faces: int, filaments: int, volume: float | None = None) -> list[str]:
    """Problems with a written 3MF, read back as a slicer would: [] when it is good. `faces` is the
    mesh that was written (the cut mesh); `volume`, when given, is the STL's, which the 3MF must keep
    within VOLUME_TOL."""
    import trimesh

    try:
        v, f, codes, main = read_3mf(path)
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, ET.ParseError) as e:
        return [f"the 3MF does not read back ({type(e).__name__})"]
    bad = []
    view = clean.slicer_view(v, f)
    if any(view.values()):
        bad.append("the 3MF mesh is not clean for a slicer: " + ", ".join(clean.problems(view)))
    tm = trimesh.Trimesh(v, f, process=False)
    if not tm.is_watertight:
        bad.append("the 3MF mesh is not watertight")
    elif volume and abs(tm.volume - volume) > VOLUME_TOL * abs(volume):
        bad.append(f"the 3MF volume {tm.volume:.1f} mm3 is not the STL's {volume:.1f} mm3")
    if len(f) != faces:
        bad.append(f"the 3MF has {len(f)} faces and the STL {faces}")
    if not 1 <= main <= filaments:
        bad.append(f"the object filament {main} is not one of the {filaments} filaments")
    wrong = 0
    for c in set(codes) - {""}:
        try:
            if not 1 <= decode_paint(c) <= filaments:
                wrong += 1
        except ValueError:
            wrong += 1
    if wrong:
        bad.append(f"{wrong} paint codes are not one of the {filaments} filaments")
    return bad


def layer_changes(mesh, filament: np.ndarray, layer: float = LAYER) -> tuple[int, int]:
    """(layers whose section holds faces of more than one filament, estimated filament changes)."""
    z = mesh.vertices[mesh.faces][:, :, 2]
    z0 = mesh.bounds[0, 2]
    zmin, zmax = z.min(1) - z0, z.max(1) - z0
    nl = int(np.ceil(mesh.extents[2] / layer)) + 1
    lo = np.clip(np.ceil(zmin / layer - 0.5), 0, nl - 1).astype(int)
    hi = np.clip(np.floor(zmax / layer - 0.5), -1, nl - 1).astype(int)
    ok = hi >= lo
    fils = np.unique(filament)
    has = np.zeros((len(fils), nl + 1), int)
    for i, n in enumerate(fils):
        sel = ok & (filament == n)
        np.add.at(has[i], lo[sel], 1)
        np.add.at(has[i], hi[sel] + 1, -1)
    present = np.cumsum(has, 1)[:, :nl] > 0
    mixed = int((present.sum(0) > 1).sum())
    changes, cur = 0, None
    for k in range(nl):  # one layer at a time, starting with the filament already loaded
        here = [int(fils[i]) for i in np.where(present[:, k])[0]]
        if not here:
            continue
        if cur in here:  # print the loaded one first
            here.remove(cur)
            here = [cur] + here
            changes += len(here) - 1
        else:
            changes += len(here) - (1 if cur is None else 0)
        cur = here[-1]
    return mixed, changes


# color boundaries


def _diffuse(V, F, X, radius: float):
    """Columns of X (one value per vertex) blurred over about `radius` mm along the surface: one
    implicit heat step (M + tK) x = M x0 with the cotangent Laplacian K (negative weights clamped)
    and vertex areas M. The surface metric, not the triangle count, sets how far a value spreads,
    so a finely meshed foot does not bleed onto a coarse plinth beside it."""
    import scipy.sparse as sp
    from scipy.sparse.linalg import splu

    n = len(V)
    p = V[F]
    rows, cols, vals = [], [], []
    for k in range(3):  # the corner k is opposite the edge (k+1, k+2)
        i, j = F[:, (k + 1) % 3], F[:, (k + 2) % 3]
        u, w = p[:, (k + 1) % 3] - p[:, k], p[:, (k + 2) % 3] - p[:, k]
        cot = (u * w).sum(1) / np.maximum(np.linalg.norm(np.cross(u, w), axis=1), 1e-12)
        c = np.maximum(cot, 0) / 2
        rows += [i, j]
        cols += [j, i]
        vals += [c, c]
    A = sp.coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n)).tocsr()
    K = sp.diags(np.asarray(A.sum(1)).ravel()) - A
    area = np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1) / 2
    M = np.bincount(F.ravel(), weights=np.repeat(area / 3, 3), minlength=n)
    t = radius ** 2 / 2  # heat flow for time t spreads a point by sqrt(2t) in each direction
    lu = splu((sp.diags(M) + t * K).tocsc())
    return np.column_stack([lu.solve(np.ascontiguousarray(M * X[:, k])) for k in range(X.shape[1])])


def smooth_cut(V, F, face_fil, radius: float = EDGE_RADIUS, fixed=None):
    """Cut the mesh along smooth color boundaries. Each filament's indicator per vertex (the
    area-weighted share of its faces) is diffused over about `radius` mm, the mesh is cut along its
    0.5 level (clean.cut_iso), and every face takes the filament whose smoothed indicator is largest
    at its centroid. A boundary then runs as a smooth curve through the triangles instead of along
    their edges. Faces in `fixed` (a plinth: its edge with the figure is a seam in the shape, already
    a clean line) keep their filament and take no part in the smoothing, so the figure's color runs
    right down to that seam. Returns (V, F, face_fil, parent) of the cut mesh, parent being the input
    face each face came from; one filament comes back unchanged."""
    import scipy.sparse as sp

    V = np.asarray(V, float)
    F = np.asarray(F, np.int64)
    face_fil = np.asarray(face_fil, int)
    fils = np.unique(face_fil)
    if len(fils) < 2:
        return V, F, face_fil, np.arange(len(F))
    p = V[F]
    area = np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1) / 2
    rows = F.ravel()
    cols = np.repeat(np.arange(len(F)), 3)
    M = sp.coo_matrix((np.repeat(area, 3), (rows, cols)), shape=(len(V), len(F))).tocsr()
    onehot = (face_fil[:, None] == fils[None, :]).astype(float)
    ind = (M @ onehot) / np.maximum(np.asarray(M.sum(1)), 1e-30)
    fixed = np.zeros(len(F), bool) if fixed is None else np.asarray(fixed, bool)
    free = ~fixed
    if free.any():
        # the free faces alone set the values on their vertices, the seam included
        Mf = M[:, free]
        on = np.asarray(Mf.sum(1)).ravel() > 0
        sub = (Mf @ onehot[free]) / np.maximum(np.asarray(Mf.sum(1)), 1e-30)
        idx = np.where(on)[0]
        remap = np.full(len(V), -1)
        remap[idx] = np.arange(len(idx))
        ind[idx] = _diffuse(V[idx], remap[F[free]], sub[idx], radius)
    parent = np.arange(len(F))
    for i in range(len(fils) if len(fils) > 2 else 1):  # with two filaments both levels are one curve
        V, F, ind, par = clean.cut_iso(V, F, ind[:, i], 0.5, fields=ind, parents=True)
        parent = parent[par]
    out = fils[ind[F].mean(1).argmax(1)]
    keep = fixed[parent]
    out[keep] = face_fil[parent[keep]]
    return V, F, out, parent


def boundary_lines(V, F, face_fil) -> list[dict]:
    """Every boundary between two filaments, chained into polylines: dicts with the filament pair,
    the points, closed or not, and the length in mm."""
    import trimesh

    tm = trimesh.Trimesh(V, F, process=False)
    adj = tm.face_adjacency
    ev = tm.face_adjacency_edges
    fa, fb = face_fil[adj[:, 0]], face_fil[adj[:, 1]]
    diff = fa != fb
    pairs = np.sort(np.stack([fa[diff], fb[diff]], 1), 1)
    edges = ev[diff]
    out = []
    for pr in np.unique(pairs, axis=0):
        es = edges[(pairs == pr).all(1)]
        nb: dict[int, list[int]] = {}
        for a, b in es:
            nb.setdefault(int(a), []).append(int(b))
            nb.setdefault(int(b), []).append(int(a))
        used = set()

        def walk(start, nxt):
            path = [start]
            prev, cur = start, nxt
            while True:
                used.add((min(prev, cur), max(prev, cur)))
                path.append(cur)
                if len(nb[cur]) != 2 or cur == start:
                    return path
                a, b = nb[cur]
                n2 = b if a == prev else a
                if (min(cur, n2), max(cur, n2)) in used:
                    return path
                prev, cur = cur, n2

        ends = [v for v, ns in nb.items() if len(ns) != 2]
        for v in ends + list(nb):
            for w in nb[v]:
                if (min(v, w), max(v, w)) not in used:
                    path = walk(v, w)
                    pts = V[path]
                    closed = path[0] == path[-1] and len(path) > 3
                    out.append({"pair": (int(pr[0]), int(pr[1])), "pts": pts, "verts": np.array(path), "closed": closed,
                                "length": float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())})
    return out


def _moving_average(r: np.ndarray, k: int, closed: bool) -> np.ndarray:
    if closed:
        pad = np.concatenate([r[-(k // 2):], r, r[: k // 2]])
    else:
        h = k // 2  # mirror through each end point, so a straight line stays straight to its ends
        pad = np.concatenate([2 * r[:1] - r[h:0:-1], r, 2 * r[-1:] - r[-2:-h - 2:-1]])
    c = np.cumsum(np.vstack([np.zeros((1, 3)), pad]), 0)
    return (c[k:] - c[:-k]) / k


def _length(r: np.ndarray, closed: bool) -> float:
    if closed:
        r = np.vstack([r, r[:1]])
    return float(np.linalg.norm(np.diff(r, axis=0), axis=1).sum())


def _resample(pts: np.ndarray, closed: bool):
    """(points every ds mm along a polyline, its length, ds)."""
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    L = float(seg.sum())
    s = np.r_[0, np.cumsum(seg)]
    ds = min(0.05, max(L, 1e-9) / 400)
    q = np.arange(0, L, ds) if closed else np.linspace(0, L, max(int(L / ds), 2) + 1)
    return np.stack([np.interp(q, s, pts[:, k]) for k in range(3)], 1), L, ds


def wobble(pts: np.ndarray, closed: bool, span: float = EDGE_SPAN) -> float:
    """The farthest any point of a line strays from the best-fit plane of the `span` mm stretch
    around it, in mm. A cuff or a hem cut along a plane scores 0; an edge that wanders up and
    down across the surface, which reads as wavy from the side, scores its wander. The length
    ratio (jaggedness) cannot see this: a smoothed edge can wander and still be short, and a
    plane cut through folds is long but straight from every side."""
    if len(pts) < 3:
        return 0.0
    r, L, ds = _resample(pts, closed)
    n = max(4, int(round(span / ds)))
    if len(r) <= n:
        idx = [np.arange(len(r))]
    else:
        stride = max(1, int(round(0.25 / ds)))
        idx = [np.arange(i, i + n) % len(r) for i in range(0, len(r) if closed else len(r) - n + 1, stride)]
    worst = 0.0
    for ii in idx:
        p = r[ii] - r[ii].mean(0)
        normal = np.linalg.svd(p, full_matrices=False)[2][2]
        worst = max(worst, float(np.abs(p @ normal).max()))
    return worst


def jaggedness(pts: np.ndarray, closed: bool, window: float = EDGE_WINDOW) -> float:
    """Length of a polyline over the length of the same line smoothed by a moving average over
    `window` mm of arc length. 1.0 is perfectly smooth; a sawtooth along triangle edges is well over.

    A moving average also shrinks any curve (a 8 mm loop by 11%), which would fail small round
    loops that are perfectly smooth. So the ratio is divided by the shrink a second pass of the same
    average gives: on a smooth curve the two passes shrink it alike, while a zigzag loses its
    length in the first pass only."""
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    L = float(seg.sum())
    if L <= 0:
        return 1.0
    s = np.r_[0, np.cumsum(seg)]
    ds = min(0.05, L / 400)
    q = np.arange(0, L, ds) if closed else np.linspace(0, L, max(int(L / ds), 2) + 1)
    r = np.stack([np.interp(q, s, pts[:, k]) for k in range(3)], 1)
    k = max(3, int(round(window / ds)) | 1)
    k = min(k, max(3, (len(r) - 3) | 1))  # a line shorter than the window: average over most of it
    m1 = _moving_average(r, k, closed)
    m2 = _moving_average(m1, k, closed)
    L1, L2 = _length(m1, closed), _length(m2, closed)
    return (L / max(L1, 1e-9)) / max(L1 / max(L2, 1e-9), 1.0)


def color_edges(V, F, face_fil) -> tuple[float, list[dict]]:
    """(worst jaggedness over the color boundaries long enough to judge, the boundary lines with a
    "ratio" and a "wobble" each). 1.0 with no boundaries."""
    lines = boundary_lines(V, F, np.asarray(face_fil))
    worst = 1.0
    for ln in lines:
        judge = ln["length"] >= EDGE_MIN
        ln["ratio"] = jaggedness(ln["pts"], ln["closed"]) if judge else None
        ln["wobble"] = wobble(ln["pts"], ln["closed"]) if judge else None
        if ln["ratio"] is not None:
            worst = max(worst, ln["ratio"])
    return worst, lines


ON_GROOVE = 0.1  # mm: a color edge this close to a groove line (most of its length) runs in the groove


def mark_grooves(lines: list[dict], anatomy: list[dict]) -> None:
    """Set ln["groove"] to the anatomy line's name on each color edge that runs in a sculpted groove
    (parts.find_groove): 80% of its points within ON_GROOVE mm of the groove line. Such an edge
    follows the shape, so it is not flat like a plane and the wobble limit does not apply to it."""
    from . import parts

    grooves = [g for g in anatomy or [] if (g.get("groove") or {}).get("used")]
    for ln in lines:
        p = ln["pts"]
        for g in grooves:
            cx, cy = g["center"]
            near = np.hypot(p[:, 0] - cx, p[:, 1] - cy) < g["rmax"] + 1.0
            on = near & (np.abs(parts.field(g, p)) < ON_GROOVE)
            if on.mean() >= 0.8:
                ln["groove"] = g["name"]
                break


def edge_faults(lines: list[dict]) -> list[dict]:
    """The lines that fail: zigzag (ratio over JAGGED) or wavy (wobble over WOBBLE, unless the edge
    runs in a groove: mark_grooves), worst first."""
    bad = [ln for ln in lines if (ln.get("ratio") or 0) > JAGGED
           or ((ln.get("wobble") or 0) > WOBBLE and not ln.get("groove"))]
    return sorted(bad, key=lambda ln: -max((ln.get("ratio") or 1) - 1,
                                           0 if ln.get("groove") else (ln.get("wobble") or 0) / WOBBLE * (JAGGED - 1)))


def ledges(V, F, face_fil, lines: list[dict]) -> list[dict]:
    """Up-facing faces of the wrong color next to a part boundary, per anatomy line (parts.py):
    where the color above the line has climbed onto a ledge of the part below it, like the top of
    a standing collar painted the head's color by a plane cut through the collar. For each color
    edge near the line, the color of its upper face is the upper color; the faces of that color
    within LEDGE_MM of the edge that face up (normal z over LEDGE_NZ) and that a person sees are
    the fault (a strip tucked under a cuff's rim is hidden and counts as seen only where it is).
    Returns one entry per line: {"name", "side", "area" (seen mm2, worst 30 degree sector), "angle" (that sector's
    middle, degrees around the line's center, 0 = +x), "fil" (the upper color), "faces"}."""
    from scipy.spatial import cKDTree

    from . import parts

    V = np.asarray(V, float)
    F = np.asarray(F)
    face_fil = np.asarray(face_fil)
    mesh = load_stl_mesh(V, F)
    c = mesh.triangles_center
    nz = mesh.face_normals[:, 2]
    area = mesh.area_faces
    adj = mesh.face_adjacency
    ev = mesh.face_adjacency_edges
    diff = face_fil[adj[:, 0]] != face_fil[adj[:, 1]]
    out = []
    for ln in lines:
        if not ln.get("rmax"):
            continue
        cx, cy = ln["center"]
        d = parts.field(ln, c)
        r = np.hypot(c[:, 0] - cx, c[:, 1] - cy)
        near = (np.abs(d) < parts.SNAP + LEDGE_MM) & (r < ln["rmax"] + LEDGE_MM)
        res = {"name": ln["name"], "side": ln.get("side"), "area": 0.0, "angle": None, "fil": None, "faces": 0}
        above = near & (d > 0.5) & (d < parts.SNAP)
        below = near & (d < -0.5) & (d > -parts.SNAP)
        if not above.any() or not below.any():
            out.append(res)
            continue
        U = int(np.bincount(face_fil[above], weights=area[above]).argmax())
        L = int(np.bincount(face_fil[below], weights=area[below]).argmax())
        e = diff & near[adj[:, 0]] & near[adj[:, 1]]
        e &= np.isin(face_fil[adj[:, 0]], (U, L)) & np.isin(face_fil[adj[:, 1]], (U, L))
        if U != L and e.any():
            mid = V[ev[e]].mean(1)
            cand = np.where(near & (nz > LEDGE_NZ) & (face_fil == U))[0]
            if len(cand):
                dist, _ = cKDTree(mid).query(c[cand], distance_upper_bound=LEDGE_MM)
                bad = cand[np.isfinite(dist)]
                if len(bad):
                    th = np.degrees(np.arctan2(c[bad, 1] - cy, c[bad, 0] - cx)) % 360
                    sec = (th // 30).astype(int)
                    sel = np.zeros(len(F), bool)
                    sel[bad] = True
                    seen = np.zeros(len(F))
                    seen[sel] = parts.visible_faces(mesh, sel)
                    per = np.bincount(sec, weights=seen[bad], minlength=12)
                    k = int(per.argmax())
                    res.update(area=float(per[k]), angle=float(k * 30 + 15), fil=U, faces=int(len(bad)))
        out.append(res)
    return out


def ledge_faults(found: list[dict]) -> list[dict]:
    """The lines whose worst sector has more than LEDGE_AREA mm2 of up-facing upper color."""
    return sorted([x for x in found if x["area"] > LEDGE_AREA], key=lambda x: -x["area"])


def worst_wobble(lines: list[dict]) -> float:
    """The largest wobble of the edges the limit applies to (not those in a groove)."""
    return max([ln["wobble"] for ln in lines if ln.get("wobble") is not None and not ln.get("groove")], default=0.0)


# pictures

VIEW_PX = 360
# every part from 8 sides at 20 degrees up, then straight down and straight up
VIEWS = [(f"{a} deg", np.radians(a), np.radians(20)) for a in range(0, 360, 45)] + [
    ("top", 0.0, np.radians(90)), ("bottom", 0.0, np.radians(-90))]


def _rot(az: float, elev: float) -> np.ndarray:
    """Turn the world so a camera on -Y, raised by `elev` and walked round by `az`, looks along +Y."""
    c, s = np.cos(az), np.sin(az)
    Rz = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])
    ce, se = np.cos(elev), np.sin(elev)
    Rx = np.array([[1, 0, 0], [0, ce, -se], [0, se, ce]])
    return Rx @ Rz


SUPERSAMPLE = 3  # panels are drawn 3x and averaged down: antialiased edges


def _panel(v, f, face_rgb, az, elev, center, half, px, title="", numbers=None, show=None, clip=False, font=None,
           ss: int = SUPERSAMPLE):
    """One flat-shaded orthographic view as a PIL image, `half` mm from the center to each edge.
    Drawn at `ss` times the size and box-filtered down, so a smooth edge does not show as pixel
    stairs that a reader (or the blind judge) takes for a stepped paint line."""
    from PIL import Image, ImageDraw
    from scipy import ndimage

    t = ((v - center) @ _rot(az, elev).T)[f]
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    n /= np.linalg.norm(n, axis=1)[:, None] + 1e-12
    cen = t.mean(1)
    vis = n[:, 1] < 0
    if clip:  # a close-up: only the faces around the spot
        vis &= (np.abs(cen[:, 0]) < half * 1.5) & (np.abs(cen[:, 2]) < half * 1.5)
    order = np.where(vis)[0]
    order = order[np.argsort(-cen[order, 1])]  # far first
    P = px * ss
    scale = P / (2 * half)
    sx = t[:, :, 0] * scale + P / 2
    sy = P / 2 - t[:, :, 2] * scale
    ids = Image.new("I", (P, P), -1)
    d = ImageDraw.Draw(ids)
    for i in order:
        d.polygon([(sx[i, 0], sy[i, 0]), (sx[i, 1], sy[i, 1]), (sx[i, 2], sy[i, 2])], fill=int(i))
    idbuf = np.asarray(ids, dtype=np.int64)
    shade = 0.35 + 0.65 * np.clip(-n[:, 1] * 0.7 + n[:, 2] * 0.3, 0, 1)
    img = np.full((P, P, 3), 136, np.float64)
    hit = idbuf >= 0
    img[hit] = face_rgb[idbuf[hit]] * shade[idbuf[hit], None]
    if ss > 1:
        img = img.reshape(px, ss, px, ss, 3).mean((1, 3))
        idbuf = idbuf[ss // 2::ss, ss // 2::ss]
        hit = idbuf >= 0
    im = Image.fromarray(img.round().clip(0, 255).astype(np.uint8))
    dd = ImageDraw.Draw(im)
    if numbers is not None:
        nb = np.where(hit, numbers[np.clip(idbuf, 0, None)], 0)
        for r in sorted(show or set(np.unique(numbers))):
            mask = nb == r
            if mask.sum() < 40:
                continue
            dist = ndimage.distance_transform_edt(mask)
            y, x = np.unravel_index(int(dist.argmax()), dist.shape)
            dd.text((x, y), str(r), fill=(0, 0, 0), font=font, anchor="mm", stroke_width=3, stroke_fill=(255, 255, 255))
    if title:
        dd.text((px / 2, 12), title, fill=(255, 255, 255), font=font, anchor="mm", stroke_width=2, stroke_fill=(60, 60, 60))
    return im


def _sheet(panels, cols: int, out_png: Path) -> None:
    from PIL import Image

    rows = -(-len(panels) // cols)
    w, h = panels[0].size
    out = Image.new("RGB", (cols * w, rows * h), (136, 136, 136))
    for i, p in enumerate(panels):
        out.paste(p, ((i % cols) * w, (i // cols) * h))
    out.save(out_png)


def render(mesh, face_rgb: np.ndarray, out_png: Path, views=(("front", 0.0, 0.0), ("back", np.pi, 0.0)),
           numbers: np.ndarray | None = None, show: set | None = None, px: int = VIEW_PX * 2,
           cols: int | None = None) -> int:
    """Flat-shaded views of the whole mesh with per-face colors (and each region's number when
    given), one square panel per (name, azimuth, elevation). Returns the number of panels."""
    from PIL import ImageFont

    v = np.asarray(mesh.vertices, float)
    f = np.asarray(mesh.faces)
    center = (v.min(0) + v.max(0)) / 2
    half = float(np.linalg.norm(v - center, axis=1).max()) * 1.04
    font = ImageFont.load_default(size=max(12, px // 26))
    panels = [_panel(v, f, np.asarray(face_rgb, float), az, el, center, half, px, title=name,
                     numbers=numbers, show=show, font=font) for name, az, el in views]
    _sheet(panels, cols or len(panels), out_png)
    return len(panels)


def render_views(mesh, face_rgb, out_png: Path) -> int:
    """build/views.png: 8 sides at 20 degrees up, top and bottom, 5 panels a row."""
    return render(mesh, face_rgb, out_png, views=VIEWS, px=VIEW_PX, cols=5)


def render_boundaries(V, F, face_rgb, lines: list[dict], out_png: Path, most: int = 6, px: int = 300,
                      anatomy: list[dict] | None = None) -> int:
    """build/boundaries.png: each jagged color boundary, then the longest, close up from 8 sides, one
    row per boundary, so the edge can be seen as it will print; then, on a figure, the collar (the
    neck line) from 8 sides level and from 30 degrees up. Returns the number of rows."""
    from PIL import ImageFont

    font = ImageFont.load_default(size=13)
    # the jagged ones first, so a failing check shows its edge, then the longest
    pick = sorted([ln for ln in lines if ln["length"] >= EDGE_MIN],
                  key=lambda ln: (-((ln.get("ratio") or 0) > JAGGED), -ln["length"]))[:most]
    panels = []
    for k, ln in enumerate(pick, 1):
        lo, hi = ln["pts"].min(0), ln["pts"].max(0)
        center = (lo + hi) / 2
        half = float(np.clip(np.linalg.norm(hi - lo) / 2 + 2, 4, 20))
        r = f"{ln['ratio']:.3f}" if ln.get("ratio") else "-"
        for a in range(0, 360, 45):
            name = f"{k}: {ln['pair'][0]}/{ln['pair'][1]} z{center[2]:.0f} {a}d r{r}"
            panels.append(_panel(V, F, face_rgb, np.radians(a), np.radians(10), center, half, px,
                                 title=name, clip=True, font=font))
    rows = len(pick)
    neck = next((ln for ln in anatomy or [] if ln["name"] == "neck" and ln.get("rmax")), None)
    if neck is not None:
        zc = float(np.mean(neck["curve"])) if neck.get("curve") is not None else float(neck["z"])
        center = np.array([neck["center"][0], neck["center"][1], zc])
        half = float(np.clip(neck["rmax"] + 2, 6, 20))
        how = "groove" if (neck.get("groove") or {}).get("used") else "level"
        for el in (0, 30):
            at = center - [0, 0, 3.0 if el else 0.0]  # from above, the head fills the top of the panel
            for a in range(0, 360, 45):
                panels.append(_panel(V, F, face_rgb, np.radians(a), np.radians(el), at, half, px,
                                     title=f"collar ({how}) {a}d up {el}d", clip=False, font=font))
            rows += 1
    if panels:
        _sheet(panels, 8, out_png)
    return rows


TINTS = [(230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200), (245, 130, 48), (145, 30, 180),
         (70, 240, 240), (240, 50, 230), (210, 245, 60), (250, 190, 212), (0, 128, 128), (170, 110, 40)]


def region_tints(numbers: np.ndarray, info: list[dict]) -> np.ndarray:
    """Per-face display color: each listed region a distinct tint over its own color."""
    out = np.full((len(numbers), 3), 200.0)
    for d in info:
        sel = numbers == d["n"]
        own = np.array(d["rgb"] if d["rgb"] is not None else (200, 200, 200), float)
        tint = np.array(TINTS[(d["n"] - 1) % len(TINTS)], float)
        out[sel] = 0.45 * own + 0.55 * tint if d["n"] <= LIST_MAX else own
    return out
