"""The engineering grade: does a part made for a real product fit it, leave its ports open, hold it,
carry its load, print, and name a source for every size it was built to?

evals/run.py calls grade() from grade_job when a spec has "product" (evals/engineering/). The spec
holds the product's published sizes (the truth); the part only says where the product sits in it,
in build/engineering.json (schema in evals/README.md):

  {"frame": 4x4 rigid matrix, product frame to part coordinates (row major),
   "material": "PLA" | "PETG" | "TPU",
   "clearance": mm per side, a number or {"+x": mm, ...},
   "retention": {"type": "snap", "y": undercut mm, "t": arm thickness at the root mm, "L": arm length mm}
              | {"type": "friction", "gap": mm (negative is interference)}
              | {"type": "screw", "size": "M2" | "M2.5" | "M3", "method": "self_tap" | "insert", "hole_d": mm}
              | {"type": "none"},
   "load": {"n": N, "dir": "-z", "arm": mm, "b": mm, "h": mm, "across_layers": bool} (when the spec has load_n),
   "sources": {"w": url, "d": ..., "h": ..., "corner_r": ..., "<feature name>": ...}}

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
FEATURE_MARGIN = 0.5  # mm around a feature's rectangle left out of the fit numbers

# --- access ---------------------------------------------------------------------------------------
PAST_WALL = 3.0  # mm past the wall the plug's path must be clear
BLOCKED_MM3 = 0.5  # mm3 of material in a plug's path that blocks it (below: boolean slivers)

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


def sample_box(body: dict, step: float = STEP) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Points on the product's surface, at least 1 / step^2 per mm2, with their outward normals and
    the face each counts for. The four vertical edges are rounded by corner_r; a point on a rounded
    corner counts for the side its normal is nearest, so a round shaft still has four sides."""
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
    dirs = np.array([NORMAL[f] for f in FACES], float)
    label = np.array(FACES)[np.argmax(N @ dirs.T, axis=1)]
    return P, N, label


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


def feature_mask(P: np.ndarray, label: np.ndarray, body: dict, features: list[dict]) -> np.ndarray:
    """True for samples on a feature's rectangle (plug or size, the larger) plus FEATURE_MARGIN."""
    m = np.zeros(len(P), bool)
    for f in features:
        on = label == f["face"]
        if not on.any():
            continue
        uv = face_uv(f["face"], P[on], body)
        sw = max(f["size"][0], (f.get("plug") or f["size"])[0]) / 2 + FEATURE_MARGIN
        sh = max(f["size"][1], (f.get("plug") or f["size"])[1]) / 2 + FEATURE_MARGIN
        hit = (np.abs(uv[:, 0] - f["c"][0]) <= sw) & (np.abs(uv[:, 1] - f["c"][1]) <= sh)
        idx = np.flatnonzero(on)
        m[idx[hit]] = True
    return m


def _to_manifold(mesh):
    import manifold3d as m3

    return m3.Manifold(m3.Mesh(vert_properties=np.asarray(mesh.vertices, np.float32),
                               tri_verts=np.asarray(mesh.faces, np.uint32)))


def plug_path(f: dict, body: dict, M: np.ndarray, length: float):
    """The plug (or the feature's own size) as a box from the product's face outward `length` mm,
    in part coordinates, as a manifold."""
    import manifold3d as m3

    pw, ph = f.get("plug") or f["size"]
    eu, ev = (np.array(a, float) for a in face_axes(f["face"]))
    n = np.array(NORMAL[f["face"]], float)
    c = uv_point(f["face"], f["c"][0], f["c"][1], body)
    start = 0.05  # mm off the face: the product's own surface touching the part is not a block
    corner = c - eu * pw / 2 - ev * ph / 2 + n * start
    # a unit cube [0,1]^3 mapped so x runs along u, y along v and z along the normal
    A = np.eye(4)
    A[:3, 0], A[:3, 1], A[:3, 2], A[:3, 3] = eu * pw, ev * ph, n * (length - start), corner
    T = M @ A
    return m3.Manifold.cube([1, 1, 1]).transform(T[:3, :].tolist())


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
    tight = g < min(lo, 0.0) - TOUCH
    if tight.any():
        worst = float(g[tight].min())
        faces = sorted(set(label[tight]))
        typ = float(np.median(g[tight]))
        why.append(f"fit: {int(tight.sum())} spots of the product are inside the part, {-typ:.2f} mm deep "
                   f"(up to {-worst:.2f}), "
                   f"on {', '.join(faces)} (want a gap of {lo:.2f} to {hi:.2f} mm)")
    for face in exp.get("covered", []):
        sel = (label == face) & ~feat
        if not sel.any():
            why.append(f"covered: {face} has no surface outside its features to cover")
            continue
        gf = g[sel]
        reach = float(np.mean(gf <= hi + REACH))
        med = float(np.median(gf))
        out["faces"][face] = {"median_gap": round(med, 3) if math.isfinite(med) else None,
                              "covered": round(reach, 3)}
        if reach < COVERED_MIN:
            why.append(f"covered: {face} is {reach:.0%} covered (the part within {hi + REACH:.2f} mm; need "
                       f"{COVERED_MIN:.0%})")
        elif not lo - 1e-9 <= med <= hi + 1e-9:
            why.append(f"fit: {face} gap {med:.2f} mm (want {lo:.2f} to {hi:.2f} mm for {material} {exp['fit']})")
    for face in exp.get("open", []):
        sel = (label == face) & ~feat
        if not sel.any():
            continue
        blocked = float(np.mean(g[sel] <= OPEN_REACH))
        out["faces"].setdefault(face, {})["blocked"] = round(blocked, 3)
        if blocked > OPEN_MAX:
            why.append(f"open: {face} is {blocked:.0%} blocked by the part within {OPEN_REACH:.0f} mm "
                       f"(at most {OPEN_MAX:.0%})")
    out["_g"], out["_P"], out["_N"], out["_label"], out["_feat"] = g, Pp, Np, label, feat
    return why, out


def check_access(mesh, spec: dict, M: np.ndarray, fit: dict) -> tuple[list[str], dict]:
    """Every feature on a covered face: its plug's path through the wall plus PAST_WALL is empty."""
    prod, exp = spec["product"], spec["expect"]
    body = prod["body"]
    covered = set(exp.get("covered", []))
    feats = [f for f in prod.get("features", []) if f["face"] in covered]
    if not feats:
        return [], {}
    lo, hi = fit["range"]
    g, Pp, Np, label, feat = fit["_g"], fit["_P"], fit["_N"], fit["_label"], fit["_feat"]
    part = _to_manifold(mesh)
    why, out = [], {}
    for f in feats:
        sel = (label == f["face"]) & ~feat & np.isfinite(g) & (g >= 0) & (g <= hi + REACH)
        t = wall_beyond(mesh, Pp[sel], Np[sel], g[sel]) if sel.any() else np.array([])
        t = t[np.isfinite(t)]
        wall = float(np.median(t)) if len(t) else MIN_WALL
        length = hi + wall + PAST_WALL
        vol = float((part ^ plug_path(f, body, M, length)).volume())
        out[f["name"]] = {"blocked_mm3": round(vol, 2), "path_mm": round(length, 2)}
        if vol > BLOCKED_MM3:
            what = "plug" if f.get("plug") else "opening"
            why.append(f"access: {f['name']} ({f['kind']} on {f['face']}) is blocked: {vol:.1f} mm3 of the part "
                       f"in its {what} path ({length:.1f} mm out from the product)")
    return why, out


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
            y, t, L = float(ret["y"]), float(ret["t"]), float(ret["L"])
            eps = 1.5 * y * t / (L * L)
            lim = SNAP_STRAIN.get(mat)
            if lim is None:
                why.append(f"retention: no snap strain limit for {mat}")
            elif eps > lim:
                why.append(f"retention: snap arm strain {eps:.1%} (1.5 x {y:g} x {t:g} / {L:g}^2) is over "
                           f"{lim:.0%} for {mat}")
        elif kind == "friction":
            gap = float(ret["gap"])
            lo, hi = FIT[(mat, exp["fit"])]
            if not lo - 1e-9 <= gap <= hi + 1e-9:
                why.append(f"retention: friction lid gap {gap:.2f} mm is outside {lo:.2f} to {hi:.2f} mm "
                           f"({mat} {exp['fit']})")
        elif kind == "screw":
            size, method, hole = ret["size"], ret["method"], float(ret["hole_d"])
            if size not in SCREW_D:
                return why + [f"retention: screw size {size} (M2, M2.5 or M3)"]
            if method == "insert":
                need = INSERT_HOLE[size]
            elif method == "self_tap":
                if mat not in PILOT_K:
                    return why + [f"retention: a self-tapping screw does not hold in {mat}"]
                need = PILOT_K[mat] * SCREW_D[size]
            else:
                return why + [f"retention: screw method {method!r} (self_tap or insert)"]
            if abs(hole - need) > HOLE_TOL + 1e-9:
                why.append(f"retention: {size} {method} hole {hole:.2f} mm (want {need:.2f} +/- {HOLE_TOL} mm)")
    except (KeyError, TypeError, ValueError) as e:
        why.append(f"retention: {kind} is missing an input of its calculation ({e})")
    return why


def check_strength(eng: dict, spec: dict, safety: float) -> tuple[list[str], dict]:
    exp = spec["expect"]
    if not exp.get("load_n"):
        return [], {}
    mat = eng.get("material")
    if mat == "TPU":
        return [], {"skipped": "TPU"}
    ld = eng.get("load")
    if not ld:
        return [f"strength: no load in engineering.json (the spec asks {exp['load_n']} N)"], {}
    why = []
    try:
        F, arm, b, h = float(ld["n"]), float(ld["arm"]), float(ld["b"]), float(ld["h"])
    except (KeyError, TypeError, ValueError) as e:
        return [f"strength: the load is missing an input of its calculation ({e})"], {}
    if F < exp["load_n"]:
        why.append(f"strength: designed for {F:g} N (the spec asks {exp['load_n']} N)")
    if exp.get("load_dir") and ld.get("dir") != exp["load_dir"]:
        why.append(f"strength: load direction {ld.get('dir')} (want {exp['load_dir']})")
    # bending of a rectangle: sigma = M c / I, M = F arm, c = h / 2, I = b h^3 / 12, so 6 F arm / (b h^2)
    sigma = F * arm * (h / 2) / (b * h ** 3 / 12)
    across = bool(ld.get("across_layers"))
    allowed = STRENGTH[mat] * (ACROSS_LAYERS if across else 1.0) / safety
    if sigma > allowed:
        why.append(f"strength: {sigma:.1f} MPa at the critical section ({F:g} N x {arm:g} mm on {b:g} x {h:g} mm), "
                   f"allowed {allowed:.1f} MPa ({mat} {STRENGTH[mat]:g} MPa"
                   + (f", x{ACROSS_LAYERS} across layers" if across else "") + f", safety {safety:g})")
    return why, {"sigma_mpa": round(sigma, 2), "allowed_mpa": round(allowed, 2)}


def check_sources(eng: dict, spec: dict) -> list[str]:
    src = eng.get("sources") or {}
    need = ["w", "d", "h", "corner_r"] + [f["name"] for f in spec["product"].get("features", [])]

    def good(s) -> bool:
        s = str(s or "").strip()
        return s.startswith(("http://", "https://")) or s == "calipers" or \
            (s.startswith("photo with ") and len(s) > len("photo with "))

    bad = [k for k in need if not good(src.get(k))]
    return [f"sources: no source for {', '.join(bad)}"] if bad else []


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
    sw, sm = check_strength(eng, spec, float(exp.get("safety", 2)))
    why += sw
    measured["strength"] = sm
    why += check_sources(eng, spec)
    M, bad = read_frame(eng.get("frame"))
    if M is None:
        why.append(bad)
    if M is None or stl is None or not Path(stl).exists():
        return {"why": why, "measured": measured}

    import trimesh

    from smoothstone import check as checks
    from smoothstone import slicer

    mesh = trimesh.load(str(stl), force="mesh")
    fw, fit = check_fit(mesh, spec, M, mat)
    why += fw
    aw, acc = check_access(mesh, spec, M, fit)
    why += aw
    measured["fit"] = {k: v for k, v in fit.items() if not k.startswith("_")}
    measured["access"] = acc
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
