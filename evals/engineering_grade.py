"""The engineering grade: does a part made for a real product fit it, leave its ports open, hold it,
carry its load, print, and name a source for every size it was built to?

evals/run.py calls grade() from grade_job when a spec has "product" (evals/engineering/). The spec
holds the product's published sizes (the truth); the part only says where the product sits in it,
in build/engineering.json (schema in evals/README.md):

  {"frame": 4x4 rigid matrix, product frame to part coordinates (row major),
   "material": "PLA" | "PETG" | "TPU",
   "clearance": mm per side, a number or {"+x": mm, ...},
   "retention": {"type": "snap", "y": undercut mm, "t": arm thickness at the root mm, "L": arm length mm,
                 "w": arm width mm, "at": root point, "t_dir": thickness axis, "L_dir": along the arm}
              | {"type": "friction", "gap": mm (negative is interference)}
              | {"type": "screw", "size": "M2" | "M2.5" | "M3", "method": "self_tap" | "insert" | "through",
                 "hole_d": mm, "holes": [{"at": the hole's mouth, "axis": into the part}, ...]}
              | {"type": "none"},
   "load": {"n": N, "dir": "-z", "arm": mm, "b": mm, "h": mm, "across_layers": bool,
            "section": {"at": a point in the critical section, "b_dir": axis of b, "h_dir": axis of h}}
           (when the spec has load_n),
   "part_holes": {"<name>": {"c": the pattern's center on the part's face, "u": the pattern's first axis}}
                 (when the spec has part_holes),
   "attach": {"holes": [{"at": the hole's mouth on the face that goes against the desk or wall}, ...]}
             (when the spec has attach),
   "sources": {"w": url, "d": ..., "h": ..., "corner_r": ..., "profile": ... (a profiled body),
               "<feature name>": ...}}

Points and directions are in the part's STL coordinates. The snap arm (its root, length, sides and
catch), the screw and attachment holes, and the critical section (its size, its arm from where the
product bears, its direction against the load and the layers) are measured in the mesh, and the
load path is cut along the beam for its weakest section, so engineering.json cannot claim a part it
does not have.

Each check that fails adds one line that names it and gives the measured number.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

NO_FILE = "the part does not say where the product sits (no engineering.json)"

# --- fit ------------------------------------------------------------------------------------------
# Gap ranges per side, mm, as (least, most); a negative gap is interference. PLA and PETG slip 0.15
# to 0.45 and snug 0.05 to 0.25, TPU 0.3 interference to 0.1 gap: the owner's ranges (smoothstone
# engineering program, 2026-11-22). No maker publishes a printed-fit table that covers these, so
# they stand as given. Press in a rigid plastic: no published range found either; we take the narrow
# conservative band of 0.1 mm interference to 0.05 mm gap (a quarter of a 0.4 mm line or less).
FIT = {
    ("PLA", "slip"): (0.15, 0.45), ("PETG", "slip"): (0.15, 0.45),
    ("PLA", "snug"): (0.05, 0.25), ("PETG", "snug"): (0.05, 0.25),
    ("PLA", "press"): (-0.10, 0.05), ("PETG", "press"): (-0.10, 0.05),
    ("TPU", "slip"): (-0.30, 0.10), ("TPU", "snug"): (-0.30, 0.10), ("TPU", "press"): (-0.30, 0.10),
}
STEP = 0.7  # mm between samples: 1 / 0.7^2 = 2.04 samples per mm2, at least the 2 asked for
TOUCH = 0.02  # mm: a sample this far into the part is a facet of a curve, not a tight fit
REACH = 1.0  # mm past the most gap: farther than this, that spot of the face is not covered
COVERED_MIN = 0.80  # share of a covered face (ports left out) the part must reach
OPEN_REACH = 20.0  # mm: material this close past an open face blocks it
OPEN_MAX = 0.10  # share of an open face that may be blocked (a rim, a lip)
FEATURE_MARGIN = 0.5  # mm around a feature's rectangle or disc left out of the fit numbers
# support (a spec with load_dir or support): the part must bear on that face of the product in at
# least SUPPORT_QUARTERS of its four quarters, each with SUPPORT_MM2 of it within the most gap plus
# REACH, so the product cannot drop or tip out. Our numbers: no published rule covers this.
SUPPORT_QUARTERS = 3
SUPPORT_MM2 = 4.0  # mm2 per quarter: about a 2.3 mm disc, a standoff's top

# --- access ---------------------------------------------------------------------------------------
PAST_WALL = 3.0  # mm past the wall the plug's path must be clear
BLOCKED_MM3 = 0.5  # mm3 of material in a plug's path that blocks it (below: boolean slivers)
# holes (a "hole" feature of the product, a screw hole, a spec's part_holes): the bore, the hole's
# size less HOLE_TOL a side, is clear, and at least SEAT_MIN of a ring MIN_WALL wide around it is the
# part, so the hole is in the part and lines up with the product's. Our numbers.
SEAT_MIN = 0.5
SCREW_DEPTH_K = 2.0  # a screw hole is probed 2 x the screw's diameter deep (our number)
SECTION_TOL = 0.2  # mm: a declared arm or section may differ from the mesh by this much (our number)
# ISO 273 clearance holes for bolts and screws, mm, (fine, medium, coarse). ISO 273:1979 is sold
# (https://www.iso.org/standard/4183.html); the values as charted by
# https://mechcodex.com/reference/metric-clearance-hole-sizes (a third party). A through hole passes
# from the fine size less HOLE_TOL to the coarse size plus HOLE_TOL.
CLEARANCE = {"M2": (2.2, 2.4, 2.6), "M2.5": (2.7, 2.9, 3.1), "M3": (3.2, 3.4, 3.6), "M4": (4.3, 4.5, 4.8),
             "M5": (5.3, 5.5, 5.8), "M6": (6.4, 6.6, 7.0)}
# An attach screw's head, mm, (head diameter dk, head height k), each the larger maximum of the pan
# head tapping screw DIN 7981 ST4.2 (dk 8.2, k 3.05,
# https://fullerfasteners.com/tech/din-7981-specifications-pan-head-tapping-screws/) and the pan head
# machine screw ISO 7045 M4 (dk 8, k 3.1,
# https://fullerfasteners.com/tech/iso-7045-specifications-pan-head-screws-with-cross-recess/); and
# the countersunk head ISO 7046 M4 (actual dk 8.4, k 2.7,
# https://fullerfasteners.com/tech/iso-7046-1-specifications-countersunk-flat-head-screws/), a 90
# degree cone. A third party charts all three, since the standards are sold.
PAN_HEAD = {"M4": (8.2, 3.1)}
FLAT_HEAD = {"M4": (8.4, 2.7)}
# The attach holes that count must spread at least this share of the part's largest extent across
# the attach face, so the part cannot turn about them (our number).
ATTACH_SPREAD = 0.25

# --- retention ------------------------------------------------------------------------------------
# Cantilever snap fit of constant rectangular section: y = 0.67 * eps * L^2 / t, so
# eps = 1.5 * y * t / L^2 (Bayer MaterialScience, "Snap-Fit Joints for Plastics, A Design Guide",
# Table 1, shape A, https://fab.cba.mit.edu/classes/S62.12/people/vernelle.noel/Plastic_Snap_fit_design.pdf).
# Permissible strain: the owner's 2% PLA, 3% PETG, 20% TPU. Each sits under the printed elongation at
# yield on the maker's data sheet: Prusament PLA 2.9% (ISO 527-1, horizontal), Prusament PETG 5.1%,
# Prusament TPU 95A 563% maximum elongation (ISO 37); so the owner's values are the conservative ones.
#   https://prusament.com/wp-content/uploads/2022/10/PLA_Prusament_TDS_2021_10_EN.pdf
#   https://storage.googleapis.com/prusa3d-content-prod-14e8-wordpress-prusament-prod/2023/10/9f8d2165-tds_prusament-petg_n_en.pdf
#   https://storage.googleapis.com/prusa3d-content-prod-14e8-wordpress-prusament-prod/2025/05/80316f6d-tds-prusament_tpu_95a_en-1.pdf
SNAP_STRAIN = {"PLA": 0.02, "PETG": 0.03, "TPU": 0.20}
# Where the arm is found in the mesh: its sides are probed from SNAP_FIRST of its length every
# SNAP_PITCH mm to SNAP_LAST mm short of its tip, its root ROOT_BEHIND mm behind `at` must be wider
# than the arm (there it joins the part), and its catch is how far the arm stands out past its root
# face toward the product in its outer half. Our numbers.
SNAP_FIRST = 0.05
SNAP_PITCH = 0.5
SNAP_LAST = 0.25
ROOT_BEHIND = 0.5
HOOK_STEP = 0.2
SCREW_D = {"M2": 2.0, "M2.5": 2.5, "M3": 3.0}
# Thread-forming screw straight into plastic: hole = k x nominal diameter (EJOT PT boss design table,
# https://apexfasteners.com/fasteners/images/Brochure_EJOT_PT_02.11_en.pdf). PLA is not in the table;
# it is stiff and brittle like the PS and ABS rows (0.80 x d). PETG takes the PET row (0.75 x d).
# TPU does not hold a thread-forming screw: no row, so a screw in TPU fails.
PILOT_K = {"PLA": 0.80, "PETG": 0.75}
# Heat-set insert holes, mm. M2 3.2 and M3 4.0: ruthex's drill set for its inserts ("3.2 + 4 + 5.6 +
# 6.4 + 8mm" for M2 to M6, https://www.ruthex.de/en/products/ruthex-hss-bohrer-set-5-tlg-fur-gewindeeinsatze-m2-m2-5-m3-m4-m5-m6-din-338-bohrer-3-2-4-0-5-6-6-4-8-0-mm-fur-kunststoff-stahl-alu-kupfer-messing-uvm).
# M2.5: ruthex gives it no drill of its own and we found no first-party number; 3.6 mm is the CNC
# Kitchen M2.5 standard insert hole as charted by https://tools.creative3dp.com/blog/heat-set-insert-hole-size-chart/
# (a third party), used until a maker's table is found.
INSERT_HOLE = {"M2": 3.2, "M2.5": 3.6, "M3": 4.0}
HOLE_TOL = 0.15  # mm either way: a printed hole comes out up to a line width off (our tolerance)

# --- strength -------------------------------------------------------------------------------------
# Printed tensile yield strength, MPa, in the layers (ISO 527-1, horizontal): Prusament PLA 51 +/- 3,
# Prusament PETG 47 +/- 2 (data sheets above). The owner set 50 for both; we take the lower of his
# and the sheet's: PLA 50, PETG 47. Across the layers the bond is weaker: the owner's 0.5 factor.
STRENGTH = {"PLA": 50.0, "PETG": 47.0}
ACROSS_LAYERS = 0.5
# The bending stress runs along the beam's axis (b_dir x h_dir). Within 15 degrees of the layers
# (the STL's xy plane, the bed) it counts as in the layers; steeper, across them. Our number.
IN_LAYERS_TILT = math.sin(math.radians(15.0))
# The load path is swept: the part is cut square to the beam's axis every SWEEP_PITCH mm from the
# declared section out to where the load enters and on to the screws it goes to, at most SWEEP_MAX
# cuts (a longer path spreads them out), and each piece's cut face is graded. Our numbers.
SWEEP_PITCH = 0.5
SWEEP_MAX = 160
SWEEP_SHIFT = 0.0137  # mm: the cuts are moved off round numbers so no cut lies on a face of the part

# --- walls ----------------------------------------------------------------------------------------
MIN_WALL = 1.2  # mm, the owner's floor for a part that carries a product (stone's own check is 0.8)

CUBE_DIRS = np.array([(i, j, k) for i in (-1, 0, 1) for j in (-1, 0, 1) for k in (-1, 0, 1) if (i, j, k) != (0, 0, 0)], float)
CUBE_DIRS /= np.linalg.norm(CUBE_DIRS, axis=1)[:, None]
FACES = ("+x", "-x", "+y", "-y", "+z", "-z")
NORMAL = {"+x": (1, 0, 0), "-x": (-1, 0, 0), "+y": (0, 1, 0), "-y": (0, -1, 0), "+z": (0, 0, 1), "-z": (0, 0, -1)}


def face_uv(face: str, p: np.ndarray, body: dict) -> np.ndarray:
    """(u, v) on a face as seen from outside the product, from its lower-left corner (README table)."""
    w, d = body["w"], body["d"]
    x, y, z = p[:, 0], p[:, 1], p[:, 2]
    u, v = {"-y": (x, z), "+y": (w - x, z), "+x": (y, z), "-x": (d - y, z),
            "+z": (x, y), "-z": (w - x, y)}[face]
    return np.stack([u, v], axis=1)


def uv_point(face: str, u: float, v: float, body: dict) -> np.ndarray:
    """The product-frame point at (u, v) on a face: face_uv's inverse."""
    w, d, h = body["w"], body["d"], body["h"]
    return np.array({"-y": (u, 0, v), "+y": (w - u, d, v), "+x": (w, u, v), "-x": (0, d - u, v),
                     "+z": (u, v, h), "-z": (w - u, v, 0)}[face], float)


def face_axes(face: str) -> tuple[np.ndarray, np.ndarray]:
    """Product-frame unit vectors along u and along v on a face."""
    return {"-y": ((1, 0, 0), (0, 0, 1)), "+y": ((-1, 0, 0), (0, 0, 1)), "+x": ((0, 1, 0), (0, 0, 1)),
            "-x": ((0, -1, 0), (0, 0, 1)), "+z": ((1, 0, 0), (0, 1, 0)), "-z": ((-1, 0, 0), (0, 1, 0))}[face]


def _grid(a: float, b: float, step: float) -> np.ndarray:
    n = max(1, int(math.ceil((b - a) / step - 1e-9)))
    return a + (np.arange(n) + 0.5) * (b - a) / n


def _label(N: np.ndarray) -> np.ndarray:
    dirs = np.array([NORMAL[f] for f in FACES], float)
    return np.array(FACES)[np.argmax(N @ dirs.T, axis=1)]


def sample_profile(body: dict, step: float = STEP) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """sample_box for a round body given as a profile: [[r, z], ...] from the axis at the bottom,
    out and up the side, back to the axis at the top, revolved about the vertical line through the
    middle of the w x d box. Each sample counts for the face its normal is nearest."""
    prof = np.asarray(body["profile"], float)
    cx, cy = float(body["w"]) / 2, float(body["d"]) / 2
    pts, nrm = [], []
    for (r0, z0), (r1, z1) in zip(prof[:-1], prof[1:]):
        L = math.hypot(r1 - r0, z1 - z0)
        if L < 1e-9:
            continue
        nr, nz = (z1 - z0) / L, -(r1 - r0) / L  # outward: the profile turns counterclockwise
        n = max(1, int(math.ceil(L / step - 1e-9)))
        for t in (np.arange(n) + 0.5) / n:
            r, z = r0 + t * (r1 - r0), z0 + t * (z1 - z0)
            k = max(1, int(math.ceil(2 * math.pi * r / step - 1e-9)))
            a = 2 * math.pi * (np.arange(k) + 0.5) / k
            pts.append(np.stack([cx + r * np.cos(a), cy + r * np.sin(a), np.full(k, z)], 1))
            nrm.append(np.stack([nr * np.cos(a), nr * np.sin(a), np.full(k, nz)], 1))
    P, N = np.concatenate(pts), np.concatenate(nrm)
    return P, N, _label(N)


def top_sag(body: dict, radius: float) -> float:
    """How far a profiled body's top dips below h within `radius` of its axis (0 for a box)."""
    if not body.get("profile"):
        return 0.0
    prof = np.asarray(body["profile"], float)
    low = float(body["h"])
    for r in np.linspace(0.0, radius, 65):
        top = -np.inf
        for (r0, z0), (r1, z1) in zip(prof[:-1], prof[1:]):
            if min(r0, r1) - 1e-9 <= r <= max(r0, r1) + 1e-9:
                z = max(z0, z1) if abs(r1 - r0) < 1e-9 else z0 + (r - r0) / (r1 - r0) * (z1 - z0)
                top = max(top, z)
        low = min(low, top)
    return float(body["h"]) - low


def sample_box(body: dict, step: float = STEP) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Points on the product's surface, at least 1 / step^2 per mm2, with their outward normals and
    the face each counts for. The four vertical edges are rounded by corner_r; a point on a rounded
    corner counts for the side its normal is nearest, so a round shaft still has four sides. A body
    with a "profile" is sampled as that shape of revolution instead (sample_profile)."""
    if body.get("profile"):
        return sample_profile(body, step)
    w, d, h = float(body["w"]), float(body["d"]), float(body["h"])
    r = min(float(body.get("corner_r") or 0.0), w / 2, d / 2)
    pts, nrm = [], []
    zs = _grid(0, h, step)
    for face, (a0, a1), fixed in (("-y", (r, w - r), 0.0), ("+y", (r, w - r), d),
                                  ("-x", (r, d - r), 0.0), ("+x", (r, d - r), w)):
        if a1 - a0 < 1e-9:
            continue
        A, Z = np.meshgrid(_grid(a0, a1, step), zs, indexing="ij")
        A, Z = A.ravel(), Z.ravel()
        F = np.full_like(A, fixed)
        p = np.stack([A, F, Z], 1) if face in ("-y", "+y") else np.stack([F, A, Z], 1)
        pts.append(p)
        nrm.append(np.tile(NORMAL[face], (len(p), 1)))
    if r > 0:
        k = max(1, int(math.ceil((math.pi / 2) * r / step)))
        for cx, cy, t0 in ((w - r, d - r, 0.0), (r, d - r, 90.0), (r, r, 180.0), (w - r, r, 270.0)):
            t = np.radians(t0 + (np.arange(k) + 0.5) * 90.0 / k)
            T, Z = np.meshgrid(t, zs, indexing="ij")
            T, Z = T.ravel(), Z.ravel()
            n = np.stack([np.cos(T), np.sin(T), np.zeros_like(T)], 1)
            pts.append(np.stack([cx + r * n[:, 0], cy + r * n[:, 1], Z], 1))
            nrm.append(n)
    X, Y = np.meshgrid(_grid(0, w, step), _grid(0, d, step), indexing="ij")
    X, Y = X.ravel(), Y.ravel()
    if r > 0:  # inside the rounded rectangle only
        qx = np.clip(X, r, w - r)
        qy = np.clip(Y, r, d - r)
        keep = (X - qx) ** 2 + (Y - qy) ** 2 <= r * r
        X, Y = X[keep], Y[keep]
    for z, face in ((h, "+z"), (0.0, "-z")):
        pts.append(np.stack([X, Y, np.full_like(X, z)], 1))
        nrm.append(np.tile(NORMAL[face], (len(X), 1)))
    P, N = np.concatenate(pts), np.concatenate(nrm).astype(float)
    return P, N, _label(N)


def read_frame(m) -> tuple[np.ndarray | None, str]:
    """(4x4 matrix, "") for a rigid frame, else (None, why): a scaled frame would fake a fit."""
    try:
        M = np.asarray(m, float).reshape(4, 4)
    except (TypeError, ValueError):
        return None, "frame is not a 4x4 matrix"
    R = M[:3, :3]
    if not np.allclose(R @ R.T, np.eye(3), atol=1e-4) or abs(np.linalg.det(R) - 1) > 1e-4 or \
            not np.allclose(M[3], [0, 0, 0, 1], atol=1e-9):
        return None, "frame is not a rotation plus a move (no scale, no mirror)"
    return M, ""


def _first_hit(mesh, origins: np.ndarray, dirs: np.ndarray) -> np.ndarray:
    """Distance along each ray to the first surface of the part, inf where it hits nothing."""
    out = np.full(len(origins), np.inf)
    if len(origins) == 0:
        return out
    loc, idx, _ = mesh.ray.intersects_location(origins, dirs, multiple_hits=False)
    if len(idx):
        out[idx] = np.einsum("ij,ij->i", loc - origins[idx], dirs[idx])
    return out


def gaps(mesh, P: np.ndarray, N: np.ndarray) -> np.ndarray:
    """Per sample (part coordinates), its gap to the part along its outward normal, mm; negative
    when the sample is inside the material (interference), by how deep.

    Method: inside or not is trimesh's ray parity test (Trimesh.contains, the sign that
    trimesh.proximity.signed_distance uses); the distance is a ray cast (trimesh with embree) along
    the face's normal, out to the part's inner surface for a sample in the air. Along the normal
    rather than to the nearest point, so a sample near an edge reads its own face's wall, not the
    next face's. A sample in the material is as deep as the nearest way out of it: the shortest ray
    of its inward normal and the 26 directions to a cube's faces, edges and corners (trimesh's
    nearest-point query needs rtree, which this install does not have), so a side sample that dips
    into the floor reads the floor's depth, not the floor's width; the ray set reads at most about
    1.1 times the true depth."""
    eps = 1e-3
    inside = mesh.contains(P)
    g = np.empty(len(P))
    out = ~inside
    g[out] = _first_hit(mesh, P[out] - N[out] * eps, N[out]) - eps
    if inside.any():
        Pi, Ni = P[inside], N[inside]
        dirs = [-Ni] + [np.tile(a, (len(Pi), 1)) for a in CUBE_DIRS]
        depth = np.min([_first_hit(mesh, Pi, d) for d in dirs], axis=0)
        g[inside] = -depth
    return g


def wall_beyond(mesh, P: np.ndarray, N: np.ndarray, g: np.ndarray) -> np.ndarray:
    """Thickness of the part's wall just past each sample's gap, along the normal (inf: no wall)."""
    t = np.full(len(P), np.inf)
    ok = np.isfinite(g) & (g >= 0)
    if ok.any():
        entry = P[ok] + N[ok] * (g[ok][:, None] + 1e-3)
        t[ok] = _first_hit(mesh, entry, N[ok]) + 1e-3
    return t


def is_circle(f: dict) -> bool:
    """A round feature: "shape": "circle", its size and plug a diameter (the first number)."""
    return f.get("shape") == "circle"


def feature_mask(P: np.ndarray, label: np.ndarray, body: dict, features: list[dict]) -> np.ndarray:
    """True for samples on a feature's rectangle or disc (size, plug or pad, the largest) plus
    FEATURE_MARGIN."""
    m = np.zeros(len(P), bool)
    for f in features:
        on = label == f["face"]
        if not on.any():
            continue
        uv = face_uv(f["face"], P[on], body)
        sw = max(f["size"][0], (f.get("plug") or f["size"])[0], (f.get("pad") or f["size"])[0]) / 2 + FEATURE_MARGIN
        sh = max(f["size"][1], (f.get("plug") or f["size"])[1], (f.get("pad") or f["size"])[1]) / 2 + FEATURE_MARGIN
        du, dv = uv[:, 0] - f["c"][0], uv[:, 1] - f["c"][1]
        if is_circle(f):
            hit = du * du + dv * dv <= sw * sw
        else:
            hit = (np.abs(du) <= sw) & (np.abs(dv) <= sh)
        idx = np.flatnonzero(on)
        m[idx[hit]] = True
    return m


def _to_manifold(mesh):
    import manifold3d as m3

    return m3.Manifold(m3.Mesh(vert_properties=np.asarray(mesh.vertices, np.float32),
                               tri_verts=np.asarray(mesh.faces, np.uint32)))


def closed_part(mesh):
    """(the part as a manifold, "") or (None, why): manifold3d makes an open mesh an empty solid,
    and an empty solid would read every path as clear."""
    import manifold3d as m3

    part = _to_manifold(mesh)
    if part.status() != m3.Error.NoError or part.is_empty():
        return None, (f"access: the part is not a closed solid ({part.status().name}), so no path or hole "
                      f"in it can be measured")
    return part, ""


def _cylinder(p0: np.ndarray, axis: np.ndarray, length: float, radius: float, radius_end: float | None = None):
    """A manifold cylinder from p0 along the unit vector axis, `length` long (a cone to radius_end)."""
    import manifold3d as m3

    a = np.asarray(axis, float) / np.linalg.norm(axis)
    helper = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(a, helper)
    u /= np.linalg.norm(u)
    v = np.cross(a, u)
    A = np.eye(4)
    A[:3, 0], A[:3, 1], A[:3, 2], A[:3, 3] = u, v, a, p0
    end = radius if radius_end is None else radius_end
    return m3.Manifold.cylinder(length, radius, end, 64).transform(A[:3, :].tolist())


def _trimesh(m):
    """A manifold as a trimesh."""
    import trimesh

    g = m.to_mesh()
    return trimesh.Trimesh(np.asarray(g.vert_properties)[:, :3], np.asarray(g.tri_verts), process=True)


def product_box(spec: dict, M: np.ndarray):
    """The product's enclosing box (w x d x h) in part coordinates, as a manifold."""
    import manifold3d as m3

    b = spec["product"]["body"]
    return m3.Manifold.cube([float(b["w"]), float(b["d"]), float(b["h"])]).transform(M[:3, :].tolist())


def probe_hole(part, p0: np.ndarray, axis: np.ndarray, bore_d: float, depth: float, ring_in: float,
               seat_depth: float, lead: float = 0.0) -> tuple[float, float]:
    """(mm3 of the part in the bore, share of the seat ring that is the part). The bore runs from
    `lead` mm before p0, along axis (into the part), to `depth` mm past it; the ring, from radius
    ring_in out MIN_WALL more, runs `seat_depth` mm from p0."""
    a = np.asarray(axis, float) / np.linalg.norm(axis)
    bore = _cylinder(np.asarray(p0, float) - a * lead, a, depth + lead, bore_d / 2)
    ring = _cylinder(np.asarray(p0, float), a, seat_depth, ring_in + MIN_WALL) - \
        _cylinder(np.asarray(p0, float) - a * 0.01, a, seat_depth + 0.02, ring_in)
    return float((part ^ bore).volume()), float((part ^ ring).volume() / max(ring.volume(), 1e-9))


def plug_path(f: dict, body: dict, M: np.ndarray, length: float):
    """The plug (or the feature's own size) as a box, or a cylinder for a round feature, from the
    product's face outward `length` mm, in part coordinates, as a manifold. On a profiled body's top
    the path starts where the top dips lowest under the feature, not at h."""
    import manifold3d as m3

    pw, ph = f.get("plug") or f["size"]
    eu, ev = (np.array(a, float) for a in face_axes(f["face"]))
    n = np.array(NORMAL[f["face"]], float)
    c = uv_point(f["face"], f["c"][0], f["c"][1], body)
    start = 0.05  # mm off the face: the product's own surface touching the part is not a block
    if f["face"] == "+z":
        reach = pw / 2 if is_circle(f) else math.hypot(pw, ph) / 2
        start -= top_sag(body, math.hypot(c[0] - body["w"] / 2, c[1] - body["d"] / 2) + reach)
    if is_circle(f):
        return _cylinder((M[:3, :3] @ (c + n * start)) + M[:3, 3], M[:3, :3] @ n, length - start, pw / 2)
    corner = c - eu * pw / 2 - ev * ph / 2 + n * start
    # a unit cube [0,1]^3 mapped so x runs along u, y along v and z along the normal
    A = np.eye(4)
    A[:3, 0], A[:3, 1], A[:3, 2], A[:3, 3] = eu * pw, ev * ph, n * (length - start), corner
    T = M @ A
    return m3.Manifold.cube([1, 1, 1]).transform(T[:3, :].tolist())




def face_range(exp: dict, face: str, lo: float, hi: float) -> tuple[float, float]:
    """A face's gap range: the fit band, or the spec's own face_gap for a face that carries no fit
    (a shaft's end under a knob's bore floor)."""
    r = (exp.get("face_gap") or {}).get(face)
    return (float(r[0]), float(r[1])) if r else (lo, hi)


def check_fit(mesh, spec: dict, M: np.ndarray, material: str) -> tuple[list[str], dict]:
    prod, exp = spec["product"], spec["expect"]
    body = prod["body"]
    lo, hi = FIT[(material, exp["fit"])]
    P, N, label = sample_box(body)
    Pp = (M[:3, :3] @ P.T).T + M[:3, 3]
    Np = (M[:3, :3] @ N.T).T
    g = gaps(mesh, Pp, Np)
    feat = feature_mask(P, label, body, prod.get("features", []))
    why, out = [], {"samples": int(len(P)), "per_mm2": round(1 / STEP ** 2, 2), "range": [lo, hi], "faces": {}}
    floor = {f: min(face_range(exp, f, lo, hi)[0], 0.0) for f in FACES}
    tight = g < np.array([floor[f] for f in label]) - TOUCH
    if tight.any():
        worst = float(g[tight].min())
        faces = sorted(set(label[tight]))
        typ = float(np.median(g[tight]))
        why.append(f"fit: {int(tight.sum())} spots of the product are inside the part, {-typ:.2f} mm deep "
                   f"(up to {-worst:.2f}), "
                   f"on {', '.join(faces)} (want a gap of {lo:.2f} to {hi:.2f} mm)")
    for face in exp.get("covered", []):
        flo, fhi = face_range(exp, face, lo, hi)
        sel = (label == face) & ~feat
        if not sel.any():
            why.append(f"covered: {face} has no surface outside its features to cover")
            continue
        gf = g[sel]
        reach = float(np.mean(gf <= fhi + REACH))
        med = float(np.median(gf))
        out["faces"][face] = {"median_gap": round(med, 3) if math.isfinite(med) else None,
                              "covered": round(reach, 3)}
        if reach < COVERED_MIN:
            why.append(f"covered: {face} is {reach:.0%} covered (the part within {fhi + REACH:.2f} mm; need "
                       f"{COVERED_MIN:.0%})")
        elif not flo - 1e-9 <= med <= fhi + 1e-9:
            what = f"{material} {exp['fit']}" if (flo, fhi) == (lo, hi) else "the spec's face_gap"
            why.append(f"fit: {face} gap {med:.2f} mm (want {flo:.2f} to {fhi:.2f} mm for {what})")
    for face, mg in (exp.get("min_gap") or {}).items():
        sel = (label == face) & ~feat & np.isfinite(g)
        near = sel & (g < float(mg) - 1e-9)
        if near.any():
            why.append(f"clear: {int(near.sum())} spots of {face} have the part {float(g[near].min()):.2f} mm away "
                       f"(the spec wants {float(mg):g} mm clear there, outside its features)")
    for face in exp.get("open", []):
        sel = (label == face) & ~feat
        if not sel.any():
            continue
        blocked = float(np.mean(g[sel] <= OPEN_REACH))
        out["faces"].setdefault(face, {})["blocked"] = round(blocked, 3)
        if blocked > OPEN_MAX:
            why.append(f"open: {face} is {blocked:.0%} blocked by the part within {OPEN_REACH:.0f} mm "
                       f"(at most {OPEN_MAX:.0%})")
    out["_g"], out["_P"], out["_N"], out["_label"], out["_feat"], out["_P0"] = g, Pp, Np, label, feat, P
    # a hole's pad is where a standoff bears: left out of the fit numbers, kept for bearing
    out["_feat_bear"] = feature_mask(P, label, body, [f for f in prod.get("features", []) if f["kind"] != "hole"])
    return why, out


def bearing(spec: dict, fit: dict) -> np.ndarray | None:
    """Which samples of the support face (support or load_dir) the part bears on: within the face's
    most gap plus REACH, features left out but for a hole's pad, where a standoff bears. None when
    the spec has no support face."""
    exp = spec["expect"]
    face = exp.get("support") or exp.get("load_dir")
    if not face:
        return None
    lo, hi = face_range(exp, face, *fit["range"])
    g, label, feat = fit["_g"], fit["_label"], fit.get("_feat_bear", fit["_feat"])
    return (label == face) & ~feat & np.isfinite(g) & (g >= min(lo, 0.0) - TOUCH) & (g <= hi + REACH)


def check_support(spec: dict, fit: dict) -> tuple[list[str], dict]:
    """With load_dir (or support): the face the product bears on has the part under it in at least
    SUPPORT_QUARTERS of its quarters, SUPPORT_MM2 each, within the face's most gap plus REACH."""
    exp, body = spec["expect"], spec["product"]["body"]
    face = exp.get("support") or exp.get("load_dir")
    if not face:
        return [], {}
    lo, hi = face_range(exp, face, *fit["range"])
    label, P0 = fit["_label"], fit["_P0"]
    bear = bearing(spec, fit)
    w, d, h = float(body["w"]), float(body["d"]), float(body["h"])
    cu, cv = {"-y": (w, h), "+y": (w, h), "+x": (d, h), "-x": (d, h), "+z": (w, d), "-z": (w, d)}[face]
    uv = face_uv(face, P0, body)
    quarters = []
    for su in (False, True):
        for sv in (False, True):
            q = bear & ((uv[:, 0] >= cu / 2) == su) & ((uv[:, 1] >= cv / 2) == sv)
            quarters.append(round(float(q.sum()) * STEP * STEP, 1))
    held = sum(a >= SUPPORT_MM2 for a in quarters)
    out = {"face": face, "quarters_mm2": quarters}
    if held < SUPPORT_QUARTERS:
        return [f"support: the part bears on {face} in {held} of its 4 quarters (need {SUPPORT_QUARTERS}, each "
                f"with {SUPPORT_MM2:g} mm2 of the part within {hi + REACH:.2f} mm), so the product can drop or "
                f"tip out"], out
    return [], out


def check_access(mesh, spec: dict, M: np.ndarray, fit: dict, part=None) -> tuple[list[str], dict]:
    """Every feature (but a mounting hole) on every face: its plug's path through the wall plus
    PAST_WALL, out to the feature's own depth, or OPEN_REACH on an open face, is empty."""
    prod, exp = spec["product"], spec["expect"]
    body = prod["body"]
    feats = [f for f in prod.get("features", []) if f["kind"] != "hole"]
    if not feats:
        return [], {}
    if part is None:
        part, bad = closed_part(mesh)
        if part is None:
            return [bad], {}
    g, Pp, Np, label, feat = fit["_g"], fit["_P"], fit["_N"], fit["_label"], fit["_feat"]
    opened = set(exp.get("open", []))
    why, out = [], {}
    for f in feats:
        _, hi = face_range(exp, f["face"], *fit["range"])
        sel = (label == f["face"]) & ~feat & np.isfinite(g) & (g >= 0) & (g <= hi + REACH)
        t = wall_beyond(mesh, Pp[sel], Np[sel], g[sel]) if sel.any() else np.array([])
        t = t[np.isfinite(t)]
        wall = float(np.median(t)) if len(t) else MIN_WALL
        length = max(hi + wall + PAST_WALL, float(f.get("depth") or 0.0),
                     OPEN_REACH if f["face"] in opened else 0.0)
        vol = float((part ^ plug_path(f, body, M, length)).volume())
        out[f["name"]] = {"blocked_mm3": round(vol, 2), "path_mm": round(length, 2)}
        if vol > BLOCKED_MM3:
            what = "plug" if f.get("plug") else "opening"
            why.append(f"access: {f['name']} ({f['kind']} on {f['face']}) is blocked: {vol:.1f} mm3 of the part "
                       f"in its {what} path ({length:.1f} mm out from the product)")
    return why, out


def _unit(v) -> np.ndarray | None:
    try:
        a = np.asarray(v, float).reshape(3)
    except (TypeError, ValueError):
        return None
    n = float(np.linalg.norm(a))
    return a / n if np.isfinite(n) and n > 1e-9 else None


def _point(v) -> np.ndarray | None:
    try:
        a = np.asarray(v, float).reshape(3)
    except (TypeError, ValueError):
        return None
    return a if np.all(np.isfinite(a)) else None


def _screw_hole(ret: dict) -> float | None:
    try:
        d = float(ret.get("hole_d"))
    except (TypeError, ValueError):
        return None
    return d if math.isfinite(d) and d > 0 else None


def check_holes(mesh, spec: dict, eng: dict, M: np.ndarray, fit: dict, part=None) -> tuple[list[str], dict]:
    """The product's mounting holes (features of kind "hole") when the part screws to them, and the
    spec's part_holes (a pattern the part itself must carry, such as VESA 75): each is a clear bore
    with the part around it. A self-tapping screw or an insert needs the part within the face's most
    gap plus REACH of the product (a standoff up to the board). A through hole (a bolt and nut, or a
    bought standoff) is found along the hole's axis wherever the part is: clear through that wall,
    with the part around it through the wall. When the part does not screw to the product, a hole's
    pad is only where a standoff may bear (check_fit leaves it out of min_gap)."""
    prod, exp = spec["product"], spec["expect"]
    body = prod["body"]
    holes = [f for f in prod.get("features", []) if f["kind"] == "hole"]
    pats = exp.get("part_holes") or []
    if not holes and not pats:
        return [], {}
    if part is None:
        part, bad = closed_part(mesh)
        if part is None:
            return [bad], {}
    why, out = [], {}
    R, t = M[:3, :3], M[:3, 3]
    ret = eng.get("retention") or {}
    screw_d = _screw_hole(ret) if ret.get("type") == "screw" else None
    through = ret.get("type") == "screw" and ret.get("method") == "through"
    for f in holes if ret.get("type") == "screw" else []:
        _, hi = face_range(exp, f["face"], *fit["range"])
        hole = screw_d or float(f["size"][0])  # the part's hole: the screw's, or the product's own
        n = np.array(NORMAL[f["face"]], float)
        p0 = R @ (uv_point(f["face"], f["c"][0], f["c"][1], body) + n * 0.05) + t
        a = R @ n
        bore_d = max(0.3, hole - 2 * HOLE_TOL)
        if through:
            found = _wall_from(mesh, p0, a, hole / 2 + HOLE_TOL + MIN_WALL / 2)
            if found is None:
                out[f["name"]] = {"wall_mm": None}
                why.append(f"holes: {f['name']} has nothing to bear on: no part under it along its axis")
                continue
            enter, wall = found
            depth = enter + wall - 0.05
            vol, seat = probe_hole(part, p0 + a * enter, a, bore_d, max(wall - 0.05, 0.1), hole / 2 + HOLE_TOL,
                                   wall, lead=enter)
            out[f["name"]] = {"bore_mm3": round(vol, 2), "seat": round(seat, 3), "from_mm": round(enter, 2),
                              "wall_mm": round(wall, 2)}
            where = f"in its {wall:.1f} mm wall {enter:.1f} mm from the product"
        else:
            depth = hi + PAST_WALL
            vol, seat = probe_hole(part, p0, a, bore_d, depth, hole / 2 + HOLE_TOL, hi + REACH)
            out[f["name"]] = {"bore_mm3": round(vol, 2), "seat": round(seat, 3)}
            where = f"within {hi + REACH:.2f} mm of the product"
        if vol > BLOCKED_MM3:
            what = "clear through the part's wall" if through else f"{depth:.1f} mm deep"
            why.append(f"holes: {f['name']} has no hole in the part: {vol:.1f} mm3 of it in a {bore_d:.2f} mm bore "
                       f"{what}")
        if seat < SEAT_MIN:
            why.append(f"holes: {f['name']} has nothing to bear on: {seat:.0%} of a {MIN_WALL:g} mm ring around "
                       f"it {where} is the part (need {SEAT_MIN:.0%})")
    placed = eng.get("part_holes") or {}
    reach = float(np.linalg.norm(mesh.extents)) + 2.0
    for ph in pats:
        name = ph["name"]
        at = placed.get(name) or {}
        c, u = _point(at.get("c")), _unit(at.get("u"))
        if c is None or u is None:
            why.append(f"holes: engineering.json does not place {name} (part_holes.{name} c and u)")
            continue
        a = R @ np.array(NORMAL[ph["axis"]], float)  # out of the part's back, away from the product
        if abs(float(u @ a)) > 1e-3:
            why.append(f"holes: {name}'s u is not square to the product's {ph['axis']} face")
            continue
        v = np.cross(a, u)
        d = float(ph["d"])
        bore_d = d - 2 * HOLE_TOL
        res = []
        for pu, pv in ph["pattern"]:
            p = c + u * pu + v * pv
            vol, seat = probe_hole(part, p, -a, bore_d, reach, d / 2 + HOLE_TOL, MIN_WALL, lead=1.0)
            res.append({"at": [round(float(x), 2) for x in p], "bore_mm3": round(vol, 2), "seat": round(seat, 3)})
        out[name] = res
        clogged = [r for r in res if r["bore_mm3"] > BLOCKED_MM3]
        bare = [r for r in res if r["seat"] < SEAT_MIN]
        if clogged:
            why.append(f"holes: {name}: {len(clogged)} of {len(res)} holes are not clear through the part as "
                       f"{bore_d:.2f} mm bores (up to {max(r['bore_mm3'] for r in clogged):.1f} mm3 in one)")
        if bare:
            why.append(f"holes: {name}: {len(bare)} of {len(res)} holes have no part around them (a "
                       f"{MIN_WALL:g} mm ring {MIN_WALL:g} mm deep, need {SEAT_MIN:.0%} of it)")
    return why, out


def _num(ret: dict, keys: str, what: str, positive: bool = True) -> tuple[list[float], str]:
    """The named inputs as finite numbers (and above 0 when positive), or a line saying which is not."""
    names = keys.split()
    none = [math.nan] * len(names)
    vals = []
    for k in names:
        try:
            x = float(ret[k])
        except KeyError:
            return none, f"{what} is missing {k}"
        except (TypeError, ValueError):
            return none, f"{what} has {k} {ret[k]!r}, not a number"
        if not math.isfinite(x) or (positive and x <= 0):
            return none, f"{what} has {k} {x:g} (it must be a number above 0)"
        vals.append(x)
    return vals, ""


def check_retention(eng: dict, spec: dict) -> list[str]:
    exp = spec["expect"]
    mat = eng.get("material")
    ret = eng.get("retention") or {}
    kind = ret.get("type")
    want = exp.get("retention", "any")
    why = []
    if kind not in ("friction", "snap", "screw", "none"):
        return [f"retention: type {kind!r} is not friction, snap, screw or none"]
    if want != "any" and kind != want:
        why.append(f"retention: {kind} (want {want})")
    try:
        if kind == "snap":
            (y, t, L), bad = _num(ret, "y t L", "retention: the snap")
            if bad:
                return why + [bad]
            eps = 1.5 * y * t / (L * L)
            lim = SNAP_STRAIN.get(mat)
            if lim is None:
                why.append(f"retention: no snap strain limit for {mat}")
            elif eps > lim:
                why.append(f"retention: snap arm strain {eps:.1%} (1.5 x {y:g} x {t:g} / {L:g}^2) is over "
                           f"{lim:.0%} for {mat}")
        elif kind == "friction":
            (gap,), bad = _num(ret, "gap", "retention: the friction fit", positive=False)
            if bad:
                return why + [bad]
            lo, hi = FIT[(mat, exp["fit"])]
            if not lo - 1e-9 <= gap <= hi + 1e-9:
                why.append(f"retention: friction lid gap {gap:.2f} mm is outside {lo:.2f} to {hi:.2f} mm "
                           f"({mat} {exp['fit']})")
        elif kind == "screw":
            size, method = ret["size"], ret["method"]
            (hole,), bad = _num(ret, "hole_d", "retention: the screw")
            if bad:
                return why + [bad]
            if size not in SCREW_D:
                return why + [f"retention: screw size {size} (M2, M2.5 or M3)"]
            if method == "through":  # a bolt and nut, or a bought standoff screwed through the part
                fine, _, coarse = CLEARANCE[size]
                if not fine - HOLE_TOL - 1e-9 <= hole <= coarse + HOLE_TOL + 1e-9:
                    why.append(f"retention: {size} through hole {hole:.2f} mm (want the ISO 273 clearance hole, "
                               f"{fine:g} to {coarse:g} mm, +/- {HOLE_TOL} mm)")
                return why
            if method == "insert":
                need = INSERT_HOLE[size]
            elif method == "self_tap":
                if mat not in PILOT_K:
                    return why + [f"retention: a self-tapping screw does not hold in {mat}"]
                need = PILOT_K[mat] * SCREW_D[size]
            else:
                return why + [f"retention: screw method {method!r} (self_tap, insert or through)"]
            if abs(hole - need) > HOLE_TOL + 1e-9:
                why.append(f"retention: {size} {method} hole {hole:.2f} mm (want {need:.2f} +/- {HOLE_TOL} mm)")
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as e:
        why.append(f"retention: {kind} is missing an input of its calculation ({e})")
    return why


def _through(mesh, p: np.ndarray, d: np.ndarray) -> float:
    """The part's thickness through p (inside it) along +d and -d."""
    return float(_first_hit(mesh, p[None], d[None])[0] + _first_hit(mesh, p[None], -d[None])[0])


def _hook(mesh, at: np.ndarray, td: np.ndarray, ld: np.ndarray, span: float) -> float:
    """How far the arm stands out past its root face along +td in its outer half: the catch, with td
    pointing toward the product (a bump on the far face hooks nothing). The root face is where a ray
    from `at` along td leaves the part; at each station from half the arm's length to its tip the
    same ray from the arm's line reads the arm's face there."""
    r_plus = float(_first_hit(mesh, at[None], td[None])[0])
    s_ = np.arange(span / 2, span - 0.05, HOOK_STEP)
    if not len(s_):
        return 0.0
    P = at[None] + ld[None] * s_[:, None]
    P = P[mesh.contains(P)]
    if not len(P):
        return 0.0
    over = _first_hit(mesh, P, np.tile(td, (len(P), 1))) - r_plus
    over = over[np.isfinite(over)]
    return float(over.max()) if len(over) else 0.0


def _wall_along(mesh, p: np.ndarray, ax: np.ndarray, off: float) -> float | None:
    """The part's thickness along ax from the plane through p, read by four rays `off` mm beside p
    (past a hole and its ring), the median; None when none of them meets the part."""
    e1 = np.cross(ax, [1.0, 0, 0] if abs(ax[0]) < 0.9 else [0, 1.0, 0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(ax, e1)
    O = np.array([p + e * off + ax * 0.01 for e in (e1, e2, -e1, -e2)])
    t = _first_hit(mesh, O, np.tile(ax, (4, 1)))
    t = t[np.isfinite(t)]
    return float(np.median(t)) + 0.01 if len(t) else None


def _wall_from(mesh, p: np.ndarray, ax: np.ndarray, off: float) -> tuple[float, float] | None:
    """Where the part starts along ax from p and how thick it is there, read by four rays `off` mm
    beside p (past a hole and its ring), the medians: (0, the thickness) when p is in the part
    already; None when no ray meets the part."""
    e1 = np.cross(ax, [1.0, 0, 0] if abs(ax[0]) < 0.9 else [0, 1.0, 0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(ax, e1)
    O = np.array([p + e * off for e in (e1, e2, -e1, -e2)])
    A = np.tile(ax, (4, 1))
    enter = np.where(mesh.contains(O), 0.0, _first_hit(mesh, O, A))
    ok = np.isfinite(enter)
    if not ok.any():
        return None
    wall = _first_hit(mesh, O[ok] + A[ok] * (enter[ok][:, None] + 0.01), A[ok]) + 0.01
    fine = np.isfinite(wall)
    if not fine.any():
        return None
    return float(np.median(enter[ok][fine])), float(np.median(wall[fine]))


def _on_surface(mesh, p: np.ndarray, ax: np.ndarray, off: float) -> bool:
    """A hole's mouth lies on the part's surface: beside it (`off` mm out, past the hole), the part
    is just past p along ax and not just before it, at most of four points."""
    e1 = np.cross(ax, [1.0, 0, 0] if abs(ax[0]) < 0.9 else [0, 1.0, 0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(ax, e1)
    O = np.array([p + e * off for e in (e1, e2, -e1, -e2)])
    return int(np.sum(mesh.contains(O + ax * 0.05) & ~mesh.contains(O - ax * 0.05))) >= 3


def check_retention_mesh(mesh, eng: dict, part=None, spec: dict | None = None) -> list[str]:
    """What engineering.json says holds the product, found in the mesh: a snap arm that joins the
    part at its root, is t thick there, runs L, is free at its sides along its length and has a catch
    y high toward the product at its tip; screw holes of the declared size with the part around them.
    With the spec and the frame, the catch is read on the side of the arm the product is on; without,
    on +t_dir."""
    ret = eng.get("retention") or {}
    kind = ret.get("type")
    if kind == "snap":
        at, td, ld = _point(ret.get("at")), _unit(ret.get("t_dir")), _unit(ret.get("L_dir"))
        (y, t, L, w), bad = _num(ret, "y t L w", "retention: the snap")
        if bad:
            return [bad]
        if at is None or td is None or ld is None:
            return ["retention: the snap arm is not placed in the part (at, t_dir, L_dir)"]
        if abs(float(td @ ld)) > 1e-3:
            return ["retention: the snap arm's t_dir is not square to its L_dir"]
        if not mesh.contains(at[None])[0]:
            return [f"retention: the snap arm's root {[round(float(x), 2) for x in at]} is not inside the part"]
        why = []
        wd = np.cross(ld, td)
        tm, Lm = _through(mesh, at, td), float(_first_hit(mesh, at[None], ld[None])[0])
        if abs(tm - t) > SECTION_TOL + 1e-9:
            why.append(f"retention: the snap arm is {tm:.2f} mm thick at its root in the part (t says {t:g})")
        if not abs(Lm - L) <= SECTION_TOL + 1e-9:
            why.append(f"retention: the snap arm runs {Lm:.2f} mm from its root in the part (L says {L:g})")
        back = at - ld * ROOT_BEHIND
        wb = _through(mesh, back, wd) if mesh.contains(back[None])[0] else 0.0
        if not wb > w + SECTION_TOL + 1e-9:
            why.append(f"retention: the snap arm's root is not where it joins the part: {ROOT_BEHIND:g} mm behind "
                       f"it the part is {wb:.1f} mm wide (w says {w:g}, so the part there must be wider)")
        span = Lm if math.isfinite(Lm) else L
        for s_ in np.unique(np.append(np.arange(span * SNAP_FIRST, span - SNAP_LAST, SNAP_PITCH),
                                      max(span - SNAP_LAST, span * SNAP_FIRST))):
            share = s_ / span
            p = at + ld * s_
            if not mesh.contains(p[None])[0]:
                why.append(f"retention: the snap arm is not in the part {share:.0%} along it")
                break
            wm = _through(mesh, p, wd)
            if not wm <= w + SECTION_TOL + 1e-9:
                why.append(f"retention: the snap arm is not free at its sides: the part is {wm:.1f} mm wide "
                           f"{share:.0%} along it (w says {w:g})")
                break
        M, _ = read_frame(eng.get("frame"))
        if spec is not None and M is not None:  # the catch faces the product
            b = spec["product"]["body"]
            mid = M[:3, :3] @ np.array([b["w"] / 2, b["d"] / 2, b["h"] / 2], float) + M[:3, 3]
            if float((mid - at) @ td) < 0:
                td = -td
        ym = _hook(mesh, at, td, ld, span)
        if ym < SECTION_TOL:
            why.append(f"retention: the snap arm has no catch: it stands out {ym:.2f} mm toward the product past "
                       f"its root face in its outer half (y says {y:g})")
        elif abs(ym - y) > SECTION_TOL + 1e-9:
            why.append(f"retention: the snap arm's catch stands out {ym:.2f} mm in the part (y says {y:g})")
        return why
    if kind == "screw":
        hole, size = _screw_hole(ret), ret.get("size")
        holes = ret.get("holes") or []
        if hole is None or size not in SCREW_D:
            return []  # check_retention already says why
        if not holes:
            return ["retention: the screw holes are not placed in the part (holes: [{at, axis}])"]
        if part is None:
            part, bad = closed_part(mesh)
            if part is None:
                return [bad]
        why = []
        depth = SCREW_DEPTH_K * SCREW_D[size]
        through = ret.get("method") == "through"
        for i, hl in enumerate(holes):
            at, ax = _point(hl.get("at")), _unit(hl.get("axis"))
            if at is None or ax is None:
                why.append(f"retention: screw hole {i} has no at and axis")
                continue
            bore_d = max(0.3, hole - 2 * HOLE_TOL)
            off = hole / 2 + HOLE_TOL + MIN_WALL / 2
            if not _on_surface(mesh, at, ax, off):
                why.append(f"retention: screw hole {i}'s mouth {[round(float(x), 2) for x in at]} is not on the part's "
                           f"surface (beside it the part must start there along its axis)")
                continue
            bore_len = seat_len = depth
            if through:  # through the wall at the hole, read beside it, not on to whatever lies past it
                wall = _wall_along(mesh, at, ax, off)
                bore_len = max(wall - 0.05, 0.1) if wall is not None else depth
                seat_len = wall if wall is not None else depth  # the part rings the bolt through its wall
            vol, seat = probe_hole(part, at, ax, bore_d, bore_len, hole / 2 + HOLE_TOL, seat_len, lead=0.5)
            if vol > BLOCKED_MM3:
                what = "clear through the part" if through else f"{depth:.1f} mm deep"
                why.append(f"retention: screw hole {i} is not in the part: {vol:.1f} mm3 of it in a {bore_d:.2f} mm "
                           f"bore {what}")
            if seat < SEAT_MIN:
                why.append(f"retention: screw hole {i} has no part around it ({seat:.0%} of a {MIN_WALL:g} mm "
                           f"ring {seat_len:.1f} mm deep; need {SEAT_MIN:.0%})")
        return why
    return []


def _head_room(part, mesh, spec: dict, M: np.ndarray, p: np.ndarray, n: np.ndarray, size: str,
               coarse: float) -> tuple[str | None, dict]:
    """Where the attach screw's head goes: ("pan" or "flat", the numbers) when it fits, (None, the
    numbers) when it does not. A pan head sits on the part under the wall, a cylinder PAN_HEAD long
    from the seat (the part's face beside the hole, read past the clearance hole: the wall's inner
    face, or a counterbore's floor) toward the product, and must not meet the product or the part.
    A flat head sits flush in a countersink: its 90 degree cone, its top at the wall's inner face
    beside the head, must be clear of the part."""
    dk, k = PAN_HEAD[size]
    seat = _wall_along(mesh, p - n * 0.01, -n, (coarse / 2 + HOLE_TOL + dk / 2) / 2)
    out = {}
    if seat is not None:
        p0 = p - n * (seat + 0.02)
        head = _cylinder(p0, -n, k, dk / 2)
        into = float((head ^ product_box(spec, M)).volume())
        hit = float((head ^ part).volume())
        out.update(seat_mm=round(seat, 2), head_in_product_mm3=round(into, 2), head_in_part_mm3=round(hit, 2))
        if into <= BLOCKED_MM3 and hit <= BLOCKED_MM3:
            return "pan", out
    fk_d, _ = FLAT_HEAD[size]
    wall = _wall_along(mesh, p - n * 0.01, -n, fk_d / 2 + HOLE_TOL + MIN_WALL / 2)
    cone_h = fk_d / 2 - coarse / 2
    if wall is not None and wall >= cone_h:
        top = p - n * (wall - 0.02)  # the head's flat top, flush with the wall's inner face
        cone = _cylinder(top, n, cone_h, fk_d / 2 - HOLE_TOL, coarse / 2 - HOLE_TOL)
        hit = float((cone ^ part).volume())
        out.update(flat_in_part_mm3=round(hit, 2))
        if hit <= BLOCKED_MM3:
            return "flat", out
    return None, out


def attach_holes(mesh, spec: dict, eng: dict, M: np.ndarray, part=None) -> tuple[list[str], dict, list]:
    """The spec's attach: screw holes through the wall that goes against the desk or wall, at least
    `min` of them, each an ISO 273 clearance hole for `screw` (clear through that wall at the fine
    size less HOLE_TOL, the part around it from the coarse size plus HOLE_TOL), its mouth on the
    part's outermost plane on that side, with room for the screw's head on the inside (_head_room).
    The wall's thickness is read beside the hole, past its ring. The holes that count must spread
    ATTACH_SPREAD of the part across that face. Returns (why, measured, the mouths of the good holes)."""
    att = spec["expect"].get("attach")
    if not att:
        return [], {}, []
    face, size, need = att["face"], att["screw"], int(att.get("min", 2))
    against = att.get("against", "the mounting surface")
    if size not in PAN_HEAD:
        return [f"attach: no screw head size for {size}"], {}, []
    if part is None:
        part, bad = closed_part(mesh)
        if part is None:
            return [bad], {}, []
    fine, _, coarse = CLEARANCE[size]
    n = M[:3, :3] @ np.array(NORMAL[face], float)  # out of the part toward the desk or wall
    V = np.asarray(mesh.vertices)
    top = float(np.max(V @ n))
    why, res, good = [], [], []
    for i, hl in enumerate((eng.get("attach") or {}).get("holes") or []):
        p = _point(hl.get("at")) if isinstance(hl, dict) else None
        if p is None:
            why.append(f"attach: hole {i} has no at")
            continue
        r = {"at": [round(float(x), 2) for x in p], "in_mm": round(top - float(p @ n), 2)}
        res.append(r)
        if r["in_mm"] > SECTION_TOL:
            why.append(f"attach: hole {i}'s mouth is {r['in_mm']:.2f} mm in from the part's {face} side, the side "
                       f"that goes against {against}")
            continue
        if any(float(np.linalg.norm(p - q)) < coarse for q in good):
            why.append(f"attach: hole {i} is a hole already counted")
            continue
        wall = _wall_along(mesh, p - n * 0.01, -n, coarse / 2 + HOLE_TOL + MIN_WALL / 2)
        wall = MIN_WALL if wall is None else wall
        vol, seat = probe_hole(part, p, -n, fine - 2 * HOLE_TOL, max(wall - 0.05, 0.1), coarse / 2 + HOLE_TOL,
                               MIN_WALL, lead=1.0)
        r.update(wall_mm=round(wall, 2), bore_mm3=round(vol, 2), seat=round(seat, 3))
        if vol > BLOCKED_MM3:
            why.append(f"attach: hole {i} is not clear through its {wall:.1f} mm wall as a {fine - 2 * HOLE_TOL:.2f} "
                       f"mm bore ({vol:.1f} mm3 in it)")
            continue
        if seat < SEAT_MIN:
            why.append(f"attach: hole {i} has no part around it ({seat:.0%} of a {MIN_WALL:g} mm ring past the "
                       f"{coarse:g} mm coarse hole; need {SEAT_MIN:.0%}), so the screw head has nothing to bear on")
            continue
        head, hm = _head_room(part, mesh, spec, M, p, n, size, coarse)
        r.update(head=head, **hm)
        if head is None:
            dk, k = PAN_HEAD[size]
            why.append(f"attach: hole {i} has no room for its screw head: a {size} pan head (Ø{dk:g} x {k:g} mm) on "
                       f"the part {hm.get('seat_mm', wall):.1f} mm in meets the product or the part, and no "
                       f"countersink holds a flat head (Ø{FLAT_HEAD[size][0]:g}), so the product cannot go in or "
                       f"bears on the head")
            continue
        good.append(p)
    out = {"face": face, "holes": res, "good": len(good)}
    if len(good) < need:
        why.append(f"attach: {len(good)} good screw holes on the {face} side for {size} (need {need}, ISO 273 "
                   f"{fine:g} to {coarse:g} mm, through its wall), so it cannot be screwed to {against}")
    elif need >= 2:
        e1 = np.cross(n, [1.0, 0, 0] if abs(n[0]) < 0.9 else [0, 1.0, 0])
        e1 /= np.linalg.norm(e1)
        e2 = np.cross(n, e1)
        across = float(max(np.ptp(V @ e1), np.ptp(V @ e2)))
        G = np.asarray(good)
        spread = float(np.max(np.linalg.norm(G[:, None] - G[None], axis=2)))
        out.update(spread_mm=round(spread, 1), across_mm=round(across, 1))
        if spread < ATTACH_SPREAD * across - 1e-9:
            why.append(f"attach: the good screw holes are {spread:.1f} mm apart at most (need "
                       f"{ATTACH_SPREAD * across:.1f}, {ATTACH_SPREAD:.0%} of the part's {across:.0f} mm across its "
                       f"{face} side), so it can turn about them")
    return why, out, good


def _piece(part, at: np.ndarray, axis: np.ndarray):
    """The piece of the part on the +axis side of the section's plane (through `at`, square to axis)
    that the section itself belongs to, as a trimesh; None when it cannot be cut out."""
    if part is None:
        return None
    above, _ = part.split_by_plane(tuple(float(x) for x in axis), float(at @ axis))
    probe = (at + axis * 0.05)[None]
    for piece in above.decompose():
        tm = _trimesh(piece)
        if len(tm.faces) and tm.contains(probe)[0]:
            return tm
    return None


def _statics(pts: np.ndarray, c: np.ndarray, load: np.ndarray) -> np.ndarray:
    """Each bearing point's share of the load, summing to 1. The product is a rigid body on equal
    springs, as a pile cap on its piles under an eccentric load: in the plane square to the load,
    share_i = 1/n + (p_i - p_mean) . C^-1 (c - p_mean), with C the points' scatter about their mean,
    so the shares' centroid lies on the load's line through the product's middle c (a strap on one
    side of the product takes its half of the load, not its share of the area). A share under 0 (the
    product would lift off there) is taken as 0 and the rest scaled to sum to 1."""
    n = len(pts)
    Q = pts - np.outer(pts @ load, load)
    m = Q.mean(axis=0)
    D = Q - m
    mu = np.linalg.pinv(D.T @ D, rcond=1e-9) @ (c - (c @ load) * load - m)
    w = np.clip(1.0 / n + D @ mu, 0.0, None)
    return w / w.sum() if w.sum() > 0 else np.full(n, 1.0 / n)


class _LoadPath:
    """Where the load enters the part and where it leaves: the support face's bearing samples, each
    with its statics share (_statics; the product's middle, all of it, without a support face), and
    with an attach the screw hole each share goes to, its nearest square to the load."""

    def __init__(self, spec: dict, M: np.ndarray, fit: dict | None, load: np.ndarray, holes: list, part):
        body = spec["product"]["body"]
        mid = M[:3, :3] @ np.array([body["w"] / 2, body["d"] / 2, body["h"] / 2], float) + M[:3, 3]
        bear = bearing(spec, fit) if fit is not None else None
        if bear is not None and bear.any():
            self.pts, g = fit["_P"][bear], fit["_g"][bear]
            self.contact = self.pts + fit["_N"][bear] * (np.maximum(g, 0.0) + 0.05)[:, None]
            self.share = _statics(self.pts, mid, load)
            self.what = "where the product bears"
        else:
            self.pts, self.contact, self.share, self.what = mid[None], None, np.ones(1), "the product's middle"
        self.load, self.part = load, part
        self.H = np.asarray(holes, float).reshape(-1, 3)
        self.near, self.ring = None, None
        if len(self.H):
            D = self.pts[:, None, :] - self.H[None, :, :]
            D = D - (D @ load)[..., None] * load
            self.near = np.argmin(np.linalg.norm(D, axis=2), axis=1)
            att = spec["expect"].get("attach") or {}
            if att.get("face") in NORMAL and att.get("screw") in CLEARANCE:  # the part around each hole's mouth
                n = M[:3, :3] @ np.array(NORMAL[att["face"]], float)
                e1 = np.cross(n, [1.0, 0, 0] if abs(n[0]) < 0.9 else [0, 1.0, 0])
                e1 /= np.linalg.norm(e1)
                E = np.array([e1, np.cross(n, e1), -e1, -np.cross(n, e1)])
                r = CLEARANCE[att["screw"]][2] / 2 + HOLE_TOL + MIN_WALL / 2
                self.ring = (self.H[:, None, :] - n * 0.3 + E[None] * r).reshape(-1, 3)

    def carried(self, piece, idx: np.ndarray, at: np.ndarray, toward: np.ndarray) -> np.ndarray:
        """Of the shares idx (on the `toward` side of the cut through at), which load the cut: those
        that bear on the piece, and with an attach, whose screw is not on that piece."""
        keep = np.ones(len(idx), bool)
        if piece is not None and self.contact is not None and len(idx):
            keep &= piece.contains(self.contact[idx])
        if len(self.H) and keep.any():
            if piece is not None and self.ring is not None:
                on_piece = piece.contains(self.ring).reshape(len(self.H), 4).any(axis=1)
            else:
                on_piece = (self.H - at) @ toward > 0
            keep &= ~on_piece[self.near[idx]]
        return keep


def _measured_arm(spec: dict, M: np.ndarray, fit: dict | None, at: np.ndarray, axis: np.ndarray,
                  load: np.ndarray, holes: list, part=None, path: _LoadPath | None = None
                  ) -> tuple[float, str, tuple[float, float]]:
    """The moment the section carries over the load, mm: an arm, what it runs from, and the span
    along the beam's axis from the section (0) out to those shares and to the screws they go to. The
    load enters where the product bears on the part (_LoadPath). On each side of the section's plane
    only the piece of the part the section belongs to loads it (a lip on the far side of the product
    loads its own root, not this one), so a share counts only where it bears on that piece, at its
    distance along the beam's axis. With an attach each share goes to its nearest screw hole and
    loads the section only when that screw is not on its own piece, and the two sides add; without,
    the side that hangs is not known, and the larger counts."""
    path = path or _LoadPath(spec, M, fit, load, holes, part)
    s = (path.pts - at) @ axis
    moments, span = [], [0.0]
    for side in (1.0, -1.0):
        idx = np.flatnonzero(s * side > 0)
        piece = _piece(part, at, axis * side) if len(idx) else None
        idx = idx[path.carried(piece, idx, at, axis * side)]
        moments.append(float(np.sum(path.share[idx] * np.abs(s[idx]))))
        if len(idx):
            span += [float(s[idx].min()), float(s[idx].max())]
            if len(path.H):
                span += list((path.H[np.unique(path.near[idx])] - at) @ axis)
    lim = (min(span), max(span))
    if len(path.H):
        return sum(moments), f"{path.what}, on its way to the nearest screw hole", lim
    return max(moments), path.what, lim


def _cut_face(piece, p: np.ndarray, toward: np.ndarray, load: np.ndarray, bd: np.ndarray):
    """The piece's face on the cut through p (the piece lies on the `toward` side): (its section
    modulus I / c for bending under the load, mm3; its size along b_dir and along the load, mm), or
    None when the piece has no face there. I is about the face's centroid, from each triangle's
    exact integral of v^2 dA, v along the load; c is the farthest point of the face from it."""
    V, F = np.asarray(piece.vertices), np.asarray(piece.faces)
    on = np.abs((V - p) @ toward) < 1e-3
    cap = F[on[F].all(axis=1) & (np.asarray(piece.face_normals) @ toward < -0.99)]
    if not len(cap):
        return None
    T = V[cap]
    A = 0.5 * np.linalg.norm(np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]), axis=1)
    v = (T - p) @ load
    area = float(A.sum())
    if area < 1e-6:
        return None
    vbar = float(np.sum(A * v.sum(axis=1) / 3)) / area
    i2 = float(np.sum(A / 6 * (np.sum(v * v, axis=1) + v[:, 0] * v[:, 1] + v[:, 1] * v[:, 2] + v[:, 0] * v[:, 2])))
    inertia = i2 - area * vbar * vbar
    c = float(np.max(np.abs(v - vbar)))
    if inertia <= 1e-12 or c <= 1e-9:
        return None
    P = V[np.unique(cap)]
    return inertia / c, float(np.ptp(P @ bd)), float(np.ptp(P @ load))


def _sweep(path: _LoadPath, part, at: np.ndarray, axis: np.ndarray, bd: np.ndarray,
           lim: tuple[float, float]) -> dict | None:
    """The worst cut on the load path: the part cut square to the beam's axis at stations from
    lim[0] to lim[1] along it (SWEEP_PITCH apart, at most SWEEP_MAX), and on each side of each cut
    every piece that carries a share (_LoadPath.carried) bends at its cut face under those shares'
    moment. {"s": the station, "arm": moment over the whole load, mm, "z": I / c, mm3, "b", "h"} at
    the highest moment over I / c, or None when no cut carries any."""
    import manifold3d as m3

    lo, hi = lim
    n = int(min(SWEEP_MAX, max(1, math.ceil((hi - lo) / SWEEP_PITCH))))
    s_all = (path.pts - at) @ axis
    worst = None
    for k in range(n + 1):
        s = lo + (hi - lo) * k / max(n, 1) + SWEEP_SHIFT * (1 if k < n else -1)
        p = at + axis * s
        for side in (1.0, -1.0):
            toward = axis * side
            idx = np.flatnonzero((s_all - s) * side > 0)
            if not len(idx):
                continue
            half, _ = part.split_by_plane(tuple(float(x) for x in toward), float(p @ toward))
            for piece_m in half.decompose():
                if piece_m.status() != m3.Error.NoError or piece_m.is_empty():
                    continue
                piece = _trimesh(piece_m)
                if not len(piece.faces):
                    continue
                mine = idx[path.carried(piece, idx, p, toward)]
                arm = float(np.sum(path.share[mine] * np.abs(s_all[mine] - s)))
                if arm <= 1e-9:
                    continue
                face = _cut_face(piece, p, toward, path.load, bd)
                if face is None:
                    continue
                z, b, h = face
                if worst is None or arm / z > worst["arm"] / worst["z"]:
                    worst = {"s": round(float(s), 2), "arm": arm, "z": z, "b": b, "h": h}
    return worst


def _cut_stress(piece, p: np.ndarray, toward: np.ndarray, pts: np.ndarray, share: np.ndarray, load: np.ndarray,
                bd: np.ndarray):
    """The highest normal stress on the piece's face on the cut through p, per newton of the whole
    load, MPa/N, under the shares at pts (all on the piece): their pull through the face's area and
    their moment about its centroid, read by the face's own second moment of area in its plane, so a
    cut whose face the load runs along is graded too. With the face's size along b_dir and square to
    it, mm, and the moment per newton, mm; None when the piece has no face there."""
    V, F = np.asarray(piece.vertices), np.asarray(piece.faces)
    on = np.abs((V - p) @ toward) < 1e-3
    cap = F[on[F].all(axis=1) & (np.asarray(piece.face_normals) @ toward < -0.99)]
    if not len(cap):
        return None
    T = V[cap]
    A = 0.5 * np.linalg.norm(np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]), axis=1)
    area = float(A.sum())
    if area < 1e-6:
        return None
    c = np.sum(A[:, None] * T.mean(axis=1), axis=0) / area
    D = T - c
    S = D.sum(axis=1)
    J = (np.einsum("t,tvi,tvj->ij", A, D, D) + np.einsum("t,ti,tj->ij", A, S, S)) / 12  # integral of d d^T dA
    m = -toward  # the face's outward normal
    e1 = np.cross(m, bd)
    if np.linalg.norm(e1) < 1e-6:
        e1 = np.cross(m, [1.0, 0, 0] if abs(m[0]) < 0.9 else [0, 1.0, 0])
    e1 /= np.linalg.norm(e1)
    E = np.stack([e1, np.cross(m, e1)], axis=1)  # 3 x 2, the face's plane
    J2 = E.T @ J @ E
    if np.linalg.det(J2) <= 1e-12:
        return None
    f = float(share.sum()) * load  # the shares' pull on the piece, per newton
    mom = np.sum(share[:, None] * np.cross(pts - c, load), axis=0)
    mb = mom - (mom @ m) * m  # bending; twist about the normal is not graded here
    # the face holds the piece: its stresses sum to -f and their moment to -mb
    s0 = -float(f @ m) / area
    a = np.linalg.solve(J2, E.T @ np.cross(-m, mb))
    P = V[np.unique(cap)]
    k = float(np.max(np.abs(s0 + ((P - c) @ E) @ a)))
    return k, float(np.ptp(P @ bd)), float(np.ptp(P @ e1)), float(np.linalg.norm(mb))


def _sweep_load(path: _LoadPath, part, at: np.ndarray, bd: np.ndarray) -> dict | None:
    """The worst cut square to the load, on a part that hangs from screws: the part cut at stations
    along the load from the farthest share to the farthest screw (SWEEP_PITCH apart, at most
    SWEEP_MAX), and on each side of each cut every piece that carries a share (_LoadPath.carried)
    graded on its whole cut face by _cut_stress. A side wall or a hanger the load runs down is cut
    across here; the beam sweep (_sweep) cuts only square to the declared axis. {"s": the station
    along the load from the declared section, "k": MPa per newton, "b", "h", "mom"} or None."""
    import manifold3d as m3

    if not len(path.H):
        return None
    load = path.load
    u = np.concatenate([(path.pts - at) @ load, (path.H - at) @ load])
    lo, hi = float(u.min()), float(u.max())
    n = int(min(SWEEP_MAX, max(1, math.ceil((hi - lo) / SWEEP_PITCH))))
    s_all = (path.pts - at) @ load
    worst = None
    for k in range(n + 1):
        s = lo + (hi - lo) * k / max(n, 1) + SWEEP_SHIFT * (1 if k < n else -1)
        p = at + load * s
        for side in (1.0, -1.0):
            toward = load * side
            idx = np.flatnonzero((s_all - s) * side > 0)
            if not len(idx):
                continue
            half, _ = part.split_by_plane(tuple(float(x) for x in toward), float(p @ toward))
            for piece_m in half.decompose():
                if piece_m.status() != m3.Error.NoError or piece_m.is_empty():
                    continue
                piece = _trimesh(piece_m)
                if not len(piece.faces):
                    continue
                mine = idx[path.carried(piece, idx, p, toward)]
                if not len(mine) or float(path.share[mine].sum()) <= 1e-9:
                    continue
                got = _cut_stress(piece, p, toward, path.pts[mine], path.share[mine], load, bd)
                if got is None:
                    continue
                kk, b, h, mom = got
                if worst is None or kk > worst["k"]:
                    worst = {"s": round(float(s), 2), "k": kk, "b": b, "h": h, "mom": mom}
    return worst


def check_strength(eng: dict, spec: dict, safety: float, mesh=None, M: np.ndarray | None = None,
                   fit: dict | None = None, holes: list | None = None, part=None) -> tuple[list[str], dict]:
    """Bending at the critical section. With the mesh, b and h are measured through the section's
    point; with the frame too, h_dir must lie along the load, b_dir square to it, the arm is measured
    from what the section carries of the load on its way to the support or the screw holes
    (_measured_arm), the layers are read from the beam's axis against the STL's z, and the weakest
    cut on the load path is graded too (_sweep)."""
    exp = spec["expect"]
    if not exp.get("load_n"):
        return [], {}
    mat = eng.get("material")
    if mat == "TPU":
        return [], {"skipped": "TPU"}
    if mat not in STRENGTH:
        return [f"strength: no yield strength for {mat}"], {}
    ld = eng.get("load")
    if not ld:
        return [f"strength: no load in engineering.json (the spec asks {exp['load_n']} N)"], {}
    why = []
    (F, arm, b, h), bad = _num(ld, "n arm b h", "strength: the load")
    if bad:
        return [bad], {}
    if F < exp["load_n"]:
        why.append(f"strength: designed for {F:g} N (the spec asks {exp['load_n']} N)")
    if exp.get("load_dir") and ld.get("dir") != exp["load_dir"]:
        why.append(f"strength: load direction {ld.get('dir')} (want {exp['load_dir']})")
    across = bool(ld.get("across_layers"))
    out = {}
    if mesh is not None:  # the section engineering.json names, measured in the part
        sec = ld.get("section") or {}
        at, bd, hd = _point(sec.get("at")), _unit(sec.get("b_dir")), _unit(sec.get("h_dir"))
        if at is None or bd is None or hd is None:
            why.append("strength: the critical section is not placed in the part (section at, b_dir, h_dir)")
        elif not mesh.contains(at[None])[0]:
            why.append(f"strength: the critical section's point {[round(float(x), 2) for x in at]} is not inside "
                       f"the part")
        else:
            bm, hm = _through(mesh, at, bd), _through(mesh, at, hd)
            out["section_mm"] = [round(bm, 2), round(hm, 2)]
            if bm < b - SECTION_TOL or hm < h - SECTION_TOL:
                why.append(f"strength: the critical section is {bm:.2f} x {hm:.2f} mm in the part (b x h says "
                           f"{b:g} x {h:g})")
            b, h = min(b, bm), min(h, hm)
            face = exp.get("load_dir") or ld.get("dir")
            if M is not None and face in NORMAL:
                load = M[:3, :3] @ np.array(NORMAL[face], float)
                if abs(float(bd @ hd)) > 1e-3:
                    why.append("strength: the section's b_dir is not square to its h_dir")
                if abs(abs(float(hd @ load)) - 1.0) > 1e-3:
                    why.append(f"strength: the section's h_dir is not along the load ({face}): bending under it "
                               f"is across h")
                axis = np.cross(bd, hd)
                n_ax = float(np.linalg.norm(axis))
                if n_ax > 1e-9:
                    axis /= n_ax
                    tilt = abs(float(axis[2]))
                    out["axis_tilt_deg"] = round(math.degrees(math.asin(min(1.0, tilt))), 1)
                    if tilt > IN_LAYERS_TILT:
                        across = True
                    if part is None:
                        part, _ = closed_part(mesh)
                    path = _LoadPath(spec, M, fit, load, holes or [], part)
                    am, what, lim = _measured_arm(spec, M, fit, at, axis, load, holes or [], part, path)
                    out["arm_mm"] = round(am, 2)
                    if am <= 1e-9:
                        why.append("strength: the critical section carries none of the load: no share of it "
                                   "crosses the section, so it is not the critical one")
                    elif arm < am - SECTION_TOL:
                        why.append(f"strength: the arm is {am:.1f} mm in the part, from the section to {what} "
                                   f"(arm says {arm:g})")
                    arm = max(arm, am)
                    if am > 1e-9 and part is not None and path.contact is not None:
                        weak = _sweep(path, part, at, axis, bd, lim)
                        if weak is not None:
                            out["weakest"] = {"along_mm": weak["s"], "arm_mm": round(weak["arm"], 2),
                                              "cut_mm": [round(weak["b"], 2), round(weak["h"], 2)],
                                              "z_mm3": round(weak["z"], 2), "k": weak["arm"] / weak["z"]}
                        down = _sweep_load(path, part, at, bd)
                        if down is not None and down["k"] > out.get("weakest", {}).get("k", 0.0):
                            # its stress runs along the load: across the layers when the load is
                            out["weakest"] = {"across_load": True, "across_layers": across or abs(float(load[2])) > IN_LAYERS_TILT,
                                              "along_mm": down["s"],
                                              "moment_mm": round(down["mom"], 2),
                                              "cut_mm": [round(down["b"], 2), round(down["h"], 2)], "k": down["k"]}
    # bending of a rectangle: sigma = M c / I, M = F arm, c = h / 2, I = b h^3 / 12, so 6 F arm / (b h^2)
    sigma = F * arm * (h / 2) / (b * h ** 3 / 12)
    allowed = STRENGTH[mat] * (ACROSS_LAYERS if across else 1.0) / safety
    rule = f"({mat} {STRENGTH[mat]:g} MPa" + (f", x{ACROSS_LAYERS} across layers" if across else "") + \
        f", safety {safety:g})"
    if sigma > allowed:
        why.append(f"strength: {sigma:.1f} MPa at the critical section ({F:g} N x {arm:g} mm on {b:g} x {h:g} mm), "
                   f"allowed {allowed:.1f} MPa {rule}")
    weak = out.get("weakest")
    if weak:  # the load path swept: the weakest cut is graded whatever section was declared
        ws = F * weak.pop("k")
        weak["sigma_mpa"] = round(ws, 2)
        down = weak.get("across_layers", across)  # a cut across the load reads its own layers
        allowed_w = STRENGTH[mat] * (ACROSS_LAYERS if down else 1.0) / safety
        rule_w = f"({mat} {STRENGTH[mat]:g} MPa" + (f", x{ACROSS_LAYERS} across layers" if down else "") + \
            f", safety {safety:g})"
        weak["allowed_mpa"] = round(allowed_w, 2)
        if ws > allowed_w and weak.get("across_load"):
            why.append(f"strength: {ws:.1f} MPa at the weakest cut across the load, {weak['along_mm']:g} mm along it "
                       f"from the declared section ({F:g} N, its moment {weak['moment_mm']:g} mm, on a cut "
                       f"{weak['cut_mm'][0]:g} x {weak['cut_mm'][1]:g} mm), allowed {allowed_w:.1f} MPa {rule_w}")
        elif ws > allowed:
            why.append(f"strength: {ws:.1f} MPa at the weakest cut on the load path, {weak['along_mm']:g} mm along the "
                       f"beam from the declared section ({F:g} N x {weak['arm_mm']:g} mm on a cut "
                       f"{weak['cut_mm'][0]:g} x {weak['cut_mm'][1]:g} mm), allowed {allowed:.1f} MPa {rule}")
    return why, {**out, "sigma_mpa": round(sigma, 2), "allowed_mpa": round(allowed, 2), "across_layers": across}


def _url(s: str) -> str | None:
    """The http(s) URL a source starts with, when it has a host; else None."""
    from urllib.parse import urlsplit

    tok = s.split()[0].rstrip(".,;:)'\"") if s.split() else ""
    try:
        u = urlsplit(tok)
    except ValueError:
        return None
    return tok.rstrip("/") if u.scheme in ("http", "https") and "." in u.netloc else None


def _cited(text) -> set[str]:
    import re

    return {u for u in (_url(m) for m in re.findall(r"https?://\S+", str(text))) if u}


def check_sources(eng: dict, spec: dict) -> list[str]:
    """A source for every size, the profile of a profiled body, and every feature. From text or a
    model number the part cannot have measured the product, so each source must be a URL the spec
    cites for that number in its own body or feature source (product.sources lists every document,
    so it ties a URL to no number); from a photo it may also be "calipers" or "photo with <a
    reference>", or any URL with a host."""
    src = eng.get("sources") or {}
    prod = spec["product"]
    own = {k: v for k, v in (prod.get("body_sources") or {}).items()}
    own.update({f["name"]: f.get("source", "") for f in prod.get("features", [])})
    need = ["w", "d", "h", "corner_r"] + (["profile"] if prod["body"].get("profile") else []) + \
        [f["name"] for f in prod.get("features", [])]
    photo = spec.get("input") == "photo"

    def good(k) -> bool:
        s = str(src.get(k) or "").strip()
        u = _url(s)
        if photo:
            return u is not None or s == "calipers" or (s.startswith("photo with ") and len(s) > len("photo with "))
        return u is not None and u in _cited(own.get(k, ""))

    bad = [k for k in need if not good(k)]
    if not bad:
        return []
    why = "a URL the spec cites for it" if not photo else "a URL, calipers or a photo with a reference"
    return [f"sources: no source for {', '.join(bad)} ({why})"]


def grade(job: Path, spec: dict, stl: Path | None) -> dict:
    """{"why": failure lines (empty when it all passes), "measured": the numbers}."""
    ej = Path(job) / "build" / "engineering.json"
    if not ej.exists():
        return {"why": [NO_FILE], "measured": {}}
    try:
        eng = json.loads(ej.read_text())
    except ValueError as e:
        return {"why": [f"engineering.json does not read as JSON ({e})"], "measured": {}}
    exp = spec["expect"]
    why: list[str] = []
    measured: dict = {}
    mat = eng.get("material")
    if mat != exp["material"]:
        why.append(f"material {mat} (want {exp['material']})")
    if (mat, exp["fit"]) not in FIT:
        return {"why": why + [f"no fit range for {mat} {exp['fit']}"], "measured": {}}
    why += check_retention(eng, spec)
    why += check_sources(eng, spec)
    M, bad = read_frame(eng.get("frame"))
    if M is None:
        why.append(bad)
    if M is None or stl is None or not Path(stl).exists():
        sw, sm = check_strength(eng, spec, float(exp.get("safety", 2)))
        measured["strength"] = sm
        return {"why": why + sw, "measured": measured}

    import trimesh

    from smoothstone import check as checks
    from smoothstone import slicer

    mesh = trimesh.load(str(stl), force="mesh")
    fw, fit = check_fit(mesh, spec, M, mat)
    why += fw
    uw, sup = check_support(spec, fit)
    why += uw
    part, bad = closed_part(mesh)
    if part is None:
        why.append(bad)
        acc, holes, att, good = {}, {}, {}, []
    else:
        aw, acc = check_access(mesh, spec, M, fit, part)
        hw, holes = check_holes(mesh, spec, eng, M, fit, part)
        tw, att, good = attach_holes(mesh, spec, eng, M, part)
        why += aw + hw + tw + check_retention_mesh(mesh, eng, part, spec)
    sw, sm = check_strength(eng, spec, float(exp.get("safety", 2)), mesh, M, fit, good, part)
    why += sw
    measured["strength"] = sm
    measured["attach"] = att
    measured["fit"] = {k: v for k, v in fit.items() if not k.startswith("_")}
    measured["support"] = sup
    measured["access"] = acc
    measured["holes"] = holes
    wall = checks.thinnest_wall(mesh)
    measured["min_wall"] = None if wall is None else round(wall, 2)
    if wall is not None and wall < MIN_WALL:
        why.append(f"walls: thinnest wall {wall:.2f} mm (need {MIN_WALL} mm)")
    rep = slicer.slice_mesh(mesh)
    measured["printable"] = rep.ok
    if not rep.ok:
        kinds = sorted({p.kind for p in rep.problems if p.kind in slicer.FAILS})
        why.append(f"printable: the slicer pass fails ({', '.join(kinds)})")
    return {"why": why, "measured": measured}
