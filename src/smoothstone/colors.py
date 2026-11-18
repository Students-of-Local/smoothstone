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
    w = word.strip().lower()
    w = ALIASES.get(w, w)
    return w if w in NAMES else None


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


def request_colors(request: str) -> list[str]:
    """Plain color names a request mentions, in order."""
    out = []
    for w in re.findall(r"[a-z]+(?:-[a-z]+)?", request.lower()):
        c = word_color(w)
        if c and c not in out:
            out.append(c)
    return out


def asks_for_color(request: str) -> bool:
    words = set(re.findall(r"[a-z]+(?:-[a-z]+)?", request.lower()))
    return bool(words & WORDS)


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


def smooth_labels(mesh, labels: np.ndarray, rounds: int = 3, keep=None) -> np.ndarray:
    """Majority vote over each face's edge neighbors; removes specks a picture leaves."""
    adj = mesh.face_adjacency
    k = int(labels.max()) + 1
    for _ in range(rounds):
        votes = np.zeros((len(labels), k))
        votes[np.arange(len(labels)), labels] += 1.5
        np.add.at(votes, (adj[:, 0], labels[adj[:, 1]]), 1)
        np.add.at(votes, (adj[:, 1], labels[adj[:, 0]]), 1)
        new = votes.argmax(1)
        if keep is not None:
            new[keep] = labels[keep]
        labels = new
    return labels


def regions(mesh, labels: np.ndarray, base=None, min_share: float = MIN_SHARE, lab=None) -> np.ndarray:
    """Connected regions of equal label over face adjacency, numbered from 0. Regions under
    `min_share` of the surface join the neighbor they share the longest edge with, except that with
    `lab` (a Lab color per label) a region of at least SPECK that differs from that neighbor by more
    than CONTRAST stays its own: white hands on a black jacket are small but not noise. Faces in the
    `base` mask are one region of their own that never merges."""
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components

    n = len(mesh.faces)
    labels = np.asarray(labels).copy()
    base = np.zeros(n, bool) if base is None else np.asarray(base, bool)
    if base.any():
        labels[base] = labels.max() + 1  # its own label, so it is its own component
    adj = mesh.face_adjacency
    same = labels[adj[:, 0]] == labels[adj[:, 1]]
    a, b = adj[same, 0], adj[same, 1]
    G = sp.coo_matrix((np.ones(len(a)), (a, b)), shape=(n, n))
    nc, comp = connected_components(G, directed=False)
    comp_label = np.zeros(nc, int)
    comp_label[comp] = labels
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
        cands = {j: L for j, L in nb[i].items() if alive[j]}
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


def find_regions(mesh, recipe: str, params: dict, front: Path | None, back: Path | None, atlas: Path):
    """(face region numbers 1..R in face order, region list) for a part."""
    n = len(mesh.faces)
    if front is None or not Path(front).is_file():
        region = np.zeros(n, int)
        info = describe(mesh, region, [None], None)
        info[0]["pos"] = "whole part"
        return region + 1, info
    import trimesh

    from . import paint

    top = base_top(recipe, params)
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
    labels = np.zeros(n, int)
    labels[fig] = lab_f
    labels = smooth_labels(mesh, labels, keep=base)
    reg = regions(mesh, labels, base=base if base.any() else None, lab=_lab(pal))
    R = int(reg.max()) + 1
    rgb: list = [None] * R
    base_region = int(reg[base][0]) if base.any() else None
    area = mesh.area_faces
    for r in range(R):
        if r == base_region:
            continue
        sel = reg == r
        votes = np.bincount(labels[sel], weights=area[sel], minlength=len(pal))
        rgb[r] = pal[int(votes.argmax())]
    info = describe(mesh, reg, rgb, base_region)
    num = np.zeros(R, int)
    for d in info:
        num[d["region"]] = d["n"]
    return num[reg], info


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


def check_3mf(path: Path, faces: int, filaments: int) -> list[str]:
    """Problems with a written 3MF, read back as a slicer would: [] when it is good."""
    import trimesh

    try:
        v, f, codes, main = read_3mf(path)
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, ET.ParseError) as e:
        return [f"the 3MF does not read back ({type(e).__name__})"]
    bad = []
    view = clean.slicer_view(v, f)
    if any(view.values()):
        bad.append("the 3MF mesh is not clean for a slicer: " + ", ".join(clean.problems(view)))
    if not trimesh.Trimesh(v, f, process=False).is_watertight:
        bad.append("the 3MF mesh is not watertight")
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


# pictures


def _project(v, f, angle):
    """Screen x, screen y (up), depth and a facing mask for a camera on -Y turned by `angle`."""
    c, s = np.cos(angle), np.sin(angle)
    R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])
    w = v @ R.T
    t = w[f]
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    n /= np.linalg.norm(n, axis=1)[:, None] + 1e-12
    return t, n


def render(mesh, face_rgb: np.ndarray, out_png: Path, views=(("front", 0.0), ("back", np.pi)),
           numbers: np.ndarray | None = None, show: set | None = None, px: int = 640) -> None:
    """Shaded views of the mesh with per-face colors, and each region's number when given."""
    from PIL import Image, ImageDraw, ImageFont
    from scipy import ndimage

    v = mesh.vertices - mesh.bounds.mean(0)
    f = mesh.faces
    ext = mesh.extents
    span = max(ext[2], np.hypot(ext[0], ext[1])) * 1.06
    scale = px / span
    W = int(np.hypot(ext[0], ext[1]) * scale * 1.06) + 20
    panels = []
    font = ImageFont.load_default(size=max(14, px // 22))
    for name, ang in views:
        t, n = _project(v, f, ang)
        vis = np.where(n[:, 1] < 0)[0]
        order = vis[np.argsort(-t[vis, :, 1].mean(1))]  # far first
        sx = (t[:, :, 0] * scale + W / 2)
        sy = (px / 2 - t[:, :, 2] * scale)
        ids = Image.new("I", (W, px), -1)
        d = ImageDraw.Draw(ids)
        for i in order:
            d.polygon([(sx[i, 0], sy[i, 0]), (sx[i, 1], sy[i, 1]), (sx[i, 2], sy[i, 2])], fill=int(i))
        idbuf = np.asarray(ids, dtype=np.int64)
        shade = 0.35 + 0.65 * np.clip(-n[:, 1] * 0.7 + n[:, 2] * 0.3, 0, 1)
        img = np.full((px, W, 3), 136, np.float64)
        hit = idbuf >= 0
        img[hit] = face_rgb[idbuf[hit]] * shade[idbuf[hit], None]
        im = Image.fromarray(img.clip(0, 255).astype(np.uint8))
        dd = ImageDraw.Draw(im)
        if numbers is not None:
            nb = np.where(hit, numbers[np.clip(idbuf, 0, None)], 0)
            for r in sorted(show or set(np.unique(numbers))):
                mask = nb == r
                if mask.sum() < 40:
                    continue
                dist = ndimage.distance_transform_edt(mask)
                y, x = np.unravel_index(int(dist.argmax()), dist.shape)
                dd.text((x, y), str(r), fill=(0, 0, 0), font=font, anchor="mm", stroke_width=3,
                        stroke_fill=(255, 255, 255))
        dd.text((W / 2, 14), name, fill=(255, 255, 255), font=font, anchor="mm")
        panels.append(im)
    out = Image.new("RGB", (sum(p.width for p in panels), px), (136, 136, 136))
    x = 0
    for p in panels:
        out.paste(p, (x, 0))
        x += p.width
    out.save(out_png)


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
