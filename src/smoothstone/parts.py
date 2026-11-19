"""The parts of a figure, found from its shape, so colors go to a jacket or the hands and not just
to whatever the picture made black.

The figure stands on a plinth whose top is at z = top. From the shape alone:
- the hem: the highest z where the figure below it is still two or more pieces standing on the
  plinth (the legs), plus HEM_ABOVE, so the line runs as one ring around the hips; or, when the
  top ends higher (a jacket over shorts), the top's own hem: a groove all the way round, within
  HEM_FOLD of the height above that, where the body steps out going up (hem_fold);
- the hands: below the arm junction each hand is a piece of its own (connected over shared edges,
  not standing on the plinth, off to one side); the junction is the highest z where it still is;
- the neck: the narrowest horizontal section between the shoulders and the head.

The mesh is cut along those planes (clean.cut_iso), so every face lies on one side of each line,
and a color boundary within SNAP mm of a line is moved onto it: the picture decides which side is
which color, the shape decides where the line runs.
"""
from __future__ import annotations

import re

import numpy as np

BASE, LEGS, TORSO, HANDS, HEAD, SHOES = range(6)
ZONES = ("base", "legs", "torso", "hands", "head", "shoes")
PIECE_MIN = 0.0005  # share of the figure's surface: a smaller loose piece is noise, not a hand
HEM_ABOVE = 0.5  # mm above the last level where the legs are apart: one ring, not two
HEM_FOLD = 0.15  # share of the figure's height above the leg split searched for the top's own hem
ANKLE_REACH = 0.45  # share of the legs' height (plinth to split) searched for the top of each shoe
ANKLE_STEP = 1.08  # a leg's section 0.5 mm under a shoe's top is at least this much bigger than 0.5 mm over
ANKLE_CREASE_BELOW = 1.0  # mm under the steepest step: the middle of the band searched for the hem's crease
ANKLE_CREASE_BAND = 1.5  # mm each side of it
ANKLE_RIM_GAP = 0.2  # mm: an up-facing face starting within this of the shoe's rim so far is still the shoe
ANKLE_RIM_NZ = 0.4  # a face whose normal points up at least this much is the top of the shoe
ANKLE_RIM_REACH = 3.0  # mm over the ankle line searched for the rest of the shoe's rim
ANKLE_SETTLED = 0.01  # the leg over a shoe holds its section within this share: the shoe's taper ended
HEM_STEP = 1.08  # the body's section 1 mm above a hem fold is at least this much bigger than 1 mm below
SNAP = 3.0  # mm: a color boundary this close to a line of the shape moves onto it
BAND = 2.0  # mm each side of a line that keeps its color through the edge smoothing
NECK_VALLEY = 1.25  # the neck section is at least this much smaller than the torso and the head
CORNER = 60.0  # degrees: a region edge that turns more than this within CORNER_MM has a corner
CORNER_MM = 1.5
MIRROR_MIN = 0.5  # share of a region whose mirror image lands on its own color
GLASSES_SHARE = 0.03  # a glasses region is at most this share of the surface
FRAME_RADIUS = 1.0  # mm: the head is smoothed over this much; a thin frame stands out of it...
FRAME_OFF = 0.25  # ...by at least this much (mm), where cheeks and the nose, being wide, do not
FRAME_WIDTH = 0.3  # a frame spans at least this share of the head's width
CLEAR = 3.0  # mm around the frames where the picture's frame color is face paint, not frames

# the words for each part, the first the default name; a request or look.txt may use any
PART_WORDS = {
    "top": ("top", "jacket", "shirt", "dress", "sweater", "coat", "t-shirt", "tshirt", "hoodie",
            "blazer", "suit", "vest", "blouse", "robe", "uniform", "jersey", "cardigan"),
    "pants": ("pants", "jeans", "trousers", "legs", "skirt", "shorts", "leggings"),
    "shoes": ("shoes", "shoe", "boots", "boot", "sneakers", "feet", "sandals"),
    "hands": ("hands", "hand", "gloves", "glove"),
    "hair": ("hair", "beard"),
    "face": ("face", "skin", "head"),
    "glasses": ("glasses", "spectacles", "eyeglasses", "sunglasses", "frames"),
    "base": ("base", "plinth", "stand", "name"),
}
WORD_PART = {w: p for p, ws in PART_WORDS.items() for w in ws}


def part_of(word: str) -> str | None:
    """The part a word names ("jacket" -> "top"), or None."""
    w = word.strip().lower()
    if w.endswith("s") and w not in WORD_PART and w[:-1] in WORD_PART:
        w = w[:-1]
    return WORD_PART.get(w)


def look_words(look: str) -> dict[str, str]:
    """The word look.txt uses for each part it names: {"top": "jacket"}."""
    out: dict[str, str] = {}
    for w in re.findall(r"[a-z]+(?:-[a-z]+)?", (look or "").lower()):
        p = part_of(w)
        if p in ("top", "pants") and p not in out:
            out[p] = w
    return out


# the shape


def _figure_faces(mesh, top: float) -> np.ndarray:
    z = mesh.vertices[mesh.faces][:, :, 2]
    return (z.min(1) >= top - 1e-6) & ~(z.max(1) <= top + 0.01)


def _pieces(mesh, mask: np.ndarray, top: float, min_area: float) -> list[dict]:
    """Pieces of the faces in mask, connected over shared edges, at least min_area each."""
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components

    adj = mesh.face_adjacency
    keep = mask[adj[:, 0]] & mask[adj[:, 1]]
    n = len(mesh.faces)
    G = sp.coo_matrix((np.ones(int(keep.sum())), (adj[keep, 0], adj[keep, 1])), shape=(n, n))
    _, comp = connected_components(G, directed=False)
    comp = np.where(mask, comp, -1)
    area = mesh.area_faces
    c = mesh.triangles_center
    zmin = mesh.vertices[mesh.faces][:, :, 2].min(1)
    out = []
    ids, inv = np.unique(comp[mask], return_inverse=True)
    a = np.bincount(inv, weights=area[mask])
    for k in np.where(a >= min_area)[0]:
        sel = comp == ids[k]
        out.append({"sel": sel, "area": float(a[k]), "cx": float(c[sel, 0].mean()),
                    "stands": bool(zmin[sel].min() < top + 0.5)})
    return out


ON_LINE = 0.03  # mm: a cut snaps corners this close onto the line (clean.cut_iso), so they count as on it


def _below(mesh, fig: np.ndarray, z: float, tol: float = 1e-6) -> np.ndarray:
    return fig & (mesh.vertices[mesh.faces][:, :, 2].max(1) <= z + tol)


def _scan(lo: float, hi: float, test, step: float = 0.5, fine: float = 0.1) -> float | None:
    """The highest z in [lo, hi] where test(z) holds in the run that starts at the first z where it
    holds, to `fine`; None when it never holds."""
    zs = np.arange(lo, hi, step)
    hits = [bool(test(z)) for z in zs]
    if not any(hits):
        return None
    i = hits.index(True)
    while i + 1 < len(hits) and hits[i + 1]:
        i += 1
    best = float(zs[i])
    for z in np.arange(zs[i] + fine, zs[i] + step, fine):
        if test(z):
            best = float(z)
        else:
            break
    return best


def section_area(seg: np.ndarray, step: float = 0.25) -> float:
    """Area inside the closed loops of a horizontal section (segments, x and y), by scanlines:
    the loops' orientation does not matter."""
    if not len(seg):
        return 0.0
    a, b = seg[:, 0, :2], seg[:, 1, :2]
    y0, y1 = min(a[:, 1].min(), b[:, 1].min()), max(a[:, 1].max(), b[:, 1].max())
    tot = 0.0
    for y in np.arange(y0 + step / 2, y1, step):
        hit = (a[:, 1] - y) * (b[:, 1] - y) < 0
        if not hit.any():
            continue
        t = (y - a[hit, 1]) / (b[hit, 1] - a[hit, 1])
        x = np.sort(a[hit, 0] + t * (b[hit, 0] - a[hit, 0]))
        m = len(x) // 2
        tot += float((x[1:2 * m:2] - x[0:2 * m:2]).sum()) * step
    return tot


def _areas(mesh, zs: np.ndarray) -> np.ndarray:
    from trimesh.intersections import mesh_multiplane

    segs, _, _ = mesh_multiplane(mesh, plane_origin=[0, 0, 0], plane_normal=[0, 0, 1], heights=zs)
    return np.array([section_area(s) for s in segs])


def anatomy(mesh, top: float) -> dict:
    """{"hem", "neck": z or None, "wrists": [{"z", "side"}], "center": x of the mirror plane,
    "top": the plinth's top, "height": the figure's top} from the shape of a figure on a plinth."""
    fig = _figure_faces(mesh, top)
    zt = float(mesh.vertices[:, 2].max())
    H = zt - top
    res = {"top": float(top), "height": zt, "hem": None, "neck": None, "wrists": [], "ankles": [],
           "center": float((mesh.bounds[0, 0] + mesh.bounds[1, 0]) / 2)}
    if not fig.any() or H <= 5:
        return res
    min_area = PIECE_MIN * float(mesh.area_faces[fig].sum())

    def legs_apart(z):
        return sum(p["stands"] for p in _pieces(mesh, _below(mesh, fig, z), top, min_area)) >= 2

    split = _scan(top + 1.0, top + 0.6 * H, legs_apart) if legs_apart(top + 1.0) else None
    low = split + HEM_ABOVE if split is not None else None
    fold = hem_fold(mesh, low, low + HEM_FOLD * H, legs_apart) if low is not None else None
    hem = fold if fold is not None else low
    res["hem"] = hem
    if fold is not None:
        res["hem_fold"] = True
    if split is not None:
        for side in (-1, 1):
            a = ankle(mesh, top, split, res["center"], side)
            if a is not None:
                res["ankles"].append({"z": a[0], "steep": a[1], "side": side})

    # the neck: the deepest valley of the section area between the torso and the head
    lo = hem if hem is not None else top + 0.25 * H
    zs = np.arange(lo + 1.0, zt - 1.0, 0.4)
    if len(zs) > 5:
        A = _areas(mesh, zs)
        below = np.maximum.accumulate(A)
        above = np.maximum.accumulate(A[::-1])[::-1]
        score = np.minimum(below, above) / np.maximum(A, 1e-9)
        score[A <= 0] = 0
        i = int(score.argmax())
        if score[i] >= NECK_VALLEY:
            fz = np.arange(zs[i] - 0.4, zs[i] + 0.41, 0.1)
            res["neck"] = float(fz[int(_areas(mesh, fz).argmin())])
    neck = res["neck"]

    # the hands: loose pieces off to each side, below the arm junction
    hi = (neck - 1.0) if neck is not None else top + 0.8 * H
    start = low if low is not None else top + 1.0
    x0 = res["center"]
    for side in (-1, 1):
        def hand(z, side=side):
            return any(not p["stands"] and (p["cx"] - x0) * side > 0
                       for p in _pieces(mesh, _below(mesh, fig, z), top, min_area))
        w = _scan(start, hi, hand)
        if w is not None:
            res["wrists"].append({"z": w, "side": side})
    res["lines"] = find_lines(mesh, res)
    return res


# the lines: each anatomy line is a plane, or the sculpted groove next to it


GROOVE_BAND = 3.0  # mm each side of a line searched for a groove; none within it: the plane
GROOVE_COST = 0.2  # per mm of loop: below this the loop runs mostly along concave edges, a groove
GROOVE_REACH = 0.7  # the groove loop is at least this share of the line's own ring, not a small loop
GROOVE_SOFT = 8.0  # degrees of concavity that make an edge e times cheaper to follow
GROOVE_SIGMA = 12.0  # degrees of angle round the line's center the groove height is smoothed over
ON_FIT = 1e-6  # mm: a face center this close to the groove's smooth fit lies on it
GROOVE_HUG = 0.08  # mm: the curve stays at least this far on the hidden side of the groove
GROOVE_ROLL = 10  # degrees each way the envelope looks for the farthest groove point
HAND_REACH = 8.0  # mm from a hand's axis: the faces below a cuff line that can be the hand


def _rings(mesh, z: float) -> list[np.ndarray]:
    """The closed loops (points, x and y) of the horizontal section at z."""
    import trimesh

    segs = trimesh.intersections.mesh_plane(mesh, [0, 0, 1], [0, 0, z])
    if not len(segs):
        return []
    try:
        path = trimesh.load_path(segs)
        return [np.asarray(d)[:, :2] for d in path.discrete if len(d) >= 4]
    except Exception:
        return []


def _ring_area(p: np.ndarray) -> float:
    x, y = p[:, 0], p[:, 1]
    return abs(float((x * np.roll(y, -1) - np.roll(x, -1) * y).sum())) / 2


def crease_loop(mesh, center, z0: float, z1: float, rmax: float, seeds: int = 60):
    """(vertex loop, cost): the cheapest closed path on the edge graph that goes once around the
    vertical axis through center, between z0 and z1 and within rmax of the axis. An edge costs its
    length times (0.02 + exp(-concave degrees / GROOVE_SOFT)), so the path follows a groove where
    there is one. Winding once is forced by a two-layer copy of the graph: crossing the angle seam
    moves to the other layer, and the path ends on the other layer's copy of its start."""
    import scipy.sparse as sp
    from scipy.sparse.csgraph import dijkstra

    V = np.asarray(mesh.vertices, float)
    cx, cy = center
    th = np.arctan2(V[:, 1] - cy, V[:, 0] - cx)
    r = np.hypot(V[:, 0] - cx, V[:, 1] - cy)
    band = (V[:, 2] > z0) & (V[:, 2] < z1) & (r < rmax)
    E = mesh.face_adjacency_edges
    conc = np.where(mesh.face_adjacency_convex, 0.0, np.degrees(mesh.face_adjacency_angles))
    ok = band[E[:, 0]] & band[E[:, 1]]
    E, conc = E[ok], conc[ok]
    if not len(E):
        return None, np.inf
    L = np.linalg.norm(V[E[:, 0]] - V[E[:, 1]], axis=1)
    w = L * (0.02 + np.exp(-conc / GROOVE_SOFT))
    n = len(V)
    a, b = E[:, 0], E[:, 1]
    cross = np.abs(th[a] - th[b]) > np.pi
    rows, cols, ws = [], [], []
    for k in (0, 1):
        o, q = k * n, (1 - k) * n
        rows += [a[~cross] + o, a[cross] + o]
        cols += [b[~cross] + o, b[cross] + q]
        ws += [w[~cross], w[cross]]
    G = sp.coo_matrix((np.concatenate(ws), (np.concatenate(rows), np.concatenate(cols))),
                      shape=(2 * n, 2 * n)).tocsr()
    G = G.maximum(G.T)
    cand = np.where(band & (np.abs(np.abs(th) - np.pi) < 0.08))[0]
    if not len(cand):
        return None, np.inf
    cand = cand[np.argsort(V[cand, 2], kind="stable")][:: max(1, len(cand) // seeds)]  # same seeds on any CPU
    D, P = dijkstra(G, indices=cand, return_predecessors=True)
    cost = D[np.arange(len(cand)), cand + n]
    i = int(np.argmin(cost))
    if not np.isfinite(cost[i]):
        return None, np.inf
    path, j = [], cand[i] + n
    while j != cand[i] and j >= 0:
        path.append(j % n)
        j = P[i, j]
    path.append(cand[i])
    return np.array(path[::-1]), float(cost[i])


_BINS = np.radians(np.arange(-180, 180, 1.0))


def _gauss(zb: np.ndarray, sig: float) -> np.ndarray:
    """Periodic gaussian over 360 one-degree bins, sigma in degrees."""
    h = int(min(359, np.ceil(3 * sig)))
    k = np.exp(-0.5 * (np.arange(-h, h + 1) / sig) ** 2)
    k /= k.sum()
    ext = np.concatenate([zb, zb, zb])
    return np.convolve(ext, k, "same")[360:720]


def _envelope(z: np.ndarray, th: np.ndarray, zs: np.ndarray, sig: float, W: int) -> np.ndarray:
    """zs lifted until it stays GROOVE_HUG over every point (th, z): a rolling max of the
    shortfall over +-W degrees, smoothed by the same gaussian, added until nothing is short."""
    lift = np.zeros_like(zs)
    bi = np.round(np.degrees(th) + 180).astype(int) % 360
    for _ in range(30):
        under = z + GROOVE_HUG - np.interp(th, _BINS, zs + lift, period=2 * np.pi)
        if under.max() <= 1e-9:
            break
        need = np.zeros_like(zs)
        np.maximum.at(need, bi, np.clip(under, 0, None))
        ext = np.concatenate([need[-W:], need, need[:W]])
        roll = np.array([ext[i:i + 2 * W + 1].max() for i in range(360)])
        lift += _gauss(roll, sig) + 1e-4 * (roll > 0)
    return zs + lift


def groove_curve(pts: np.ndarray, center, side: int = 1, lift: bool = True) -> np.ndarray:
    """The groove's height at each degree around center (360 values from -180), smooth: the median
    per degree, gaps filled, a periodic gaussian of GROOVE_SIGMA degrees; then lifted to a tight
    envelope on `side` (+1 above, -1 below, which works on -z) so it stays GROOVE_HUG mm or more
    past every groove point (lift=False: the plain smooth fit, which runs through the groove)."""
    cx, cy = center
    th = np.arctan2(pts[:, 1] - cy, pts[:, 0] - cx)
    z = side * pts[:, 2]
    near = np.abs(np.angle(np.exp(1j * (th[None, :] - _BINS[:, None])))) < np.radians(3)
    zb = np.array([np.median(z[m]) if m.any() else np.nan for m in near])
    ok = ~np.isnan(zb)
    zb = np.interp(_BINS, _BINS[ok], zb[ok], period=2 * np.pi)
    zs = _gauss(zb, GROOVE_SIGMA)
    return side * (_envelope(z, th, zs, GROOVE_SIGMA, GROOVE_ROLL) if lift else zs)


def field(line: dict, X: np.ndarray) -> np.ndarray:
    """Signed height of points over a line: z minus the plane, or minus the groove curve at each
    point's angle around the line's center."""
    X = np.asarray(X, float)
    if line.get("curve") is None:
        return X[:, 2] - line["z"]
    return _curve_field(line["curve"], line["center"], X)


def side_of(mesh, line: dict) -> np.ndarray:
    """+1 or -1 per face: the side of the line it lies on, on a mesh cut along the line. Taken from
    the corner farthest from the line, since a cut snaps corners close to the line onto it, and a
    face's center can sit just across the line from the face's own side."""
    d = field(line, np.asarray(mesh.vertices, float))[np.asarray(mesh.faces)]
    k = np.abs(d).argmax(1)
    return np.where(d[np.arange(len(d)), k] > 0, 1, -1)


VIEW_DIRS = [(az, el, 0.5 if el < 0 else 1.0) for el in (-15, 15, 45) for az in range(0, 360, 22)]


def visible_faces(mesh, sel: np.ndarray) -> np.ndarray:
    """Seen area of each face in sel (mm2, one per selected face, in order): from cameras at 16
    azimuths and three elevations (-15, 15, 45 degrees; from slightly below counts half), the
    projected area where the face faces the camera with nothing in the way (a ray cast from the
    face), averaged over the cameras."""
    idx = np.where(sel)[0]
    out = np.zeros(len(idx))
    if not len(idx):
        return out
    n = mesh.face_normals[idx]
    c = mesh.triangles_center[idx]
    a = mesh.area_faces[idx]
    for az, el, w in VIEW_DIRS:
        A, E = np.radians(az), np.radians(el)
        d = np.array([np.cos(E) * np.cos(A), np.cos(E) * np.sin(A), np.sin(E)])
        cos = n @ d
        f = cos > 0.05
        if not f.any():
            continue
        hit = mesh.ray.intersects_any(c[f] + n[f] * 0.01, np.repeat(d[None], int(f.sum()), 0))
        k = np.where(f)[0][~hit]
        out[k] += w * a[k] * cos[k]
    return out / sum(w for *_, w in VIEW_DIRS)


def visible_area(mesh, sel: np.ndarray) -> float:
    """How much of the faces in sel a person sees, in mm2 (visible_faces, summed)."""
    return float(visible_faces(mesh, sel).sum())


def _curve_field(curve, center, X: np.ndarray) -> np.ndarray:
    cx, cy = center
    th = np.arctan2(X[:, 1] - cy, X[:, 0] - cx)
    return X[:, 2] - np.interp(th, _BINS, np.asarray(curve, float), period=2 * np.pi)


def strip_seen(mesh, pts: np.ndarray, center, line: dict, side: int, only=None) -> tuple[float, float]:
    """(seen mm2, area mm2) of the wrong-color strip a line leaves: the faces between the groove's
    plain smooth fit (no lift: it runs through the groove) and the line, within 3 mm outside the
    groove's widest radius (and among only(line)'s faces and one ring round them, when given)."""
    c = mesh.triangles_center
    cx, cy = center
    near = np.hypot(c[:, 0] - cx, c[:, 1] - cy) < float(np.hypot(pts[:, 0] - cx, pts[:, 1] - cy).max()) + 3.0
    g0 = _curve_field(groove_curve(pts, center, 1, lift=False), center, c)
    g = field(line, c)
    # a face on the groove's own level (a flat rim or chin underside) sits at g0 ~ 1e-16, whose
    # sign is rounding noise that differs between CPUs: it belongs to the part above when it
    # faces down (the underside of the overhang) and to the part below when it faces up
    upper = np.where(np.abs(g0) > ON_FIT, g0 > 0, mesh.face_normals[:, 2] < 0)
    strip = near & (upper & (g < 0) if side > 0 else ~upper & (g > 0))
    if only is not None:
        hf = only(line)
        if hf is not None:
            strip &= _with_ring(mesh.faces, hf, len(mesh.vertices))[1]
    return round(visible_area(mesh, strip), 3), round(float(mesh.area_faces[strip].sum()), 2)


def _with_ring(F: np.ndarray, sel: np.ndarray, nv: int) -> tuple[np.ndarray, np.ndarray]:
    """(vertex mask, face mask) of the faces in sel and one ring of faces round them."""
    va = np.zeros(nv, bool)
    va[F[sel].ravel()] = True
    ring = va[F].any(1)
    vr = np.zeros(nv, bool)
    vr[F[ring].ravel()] = True
    return vr, ring


def choose_side(mesh, pts: np.ndarray, center, only=None) -> tuple[int, dict]:
    """(side, {side: (seen mm2, strip mm2)}): the side of the groove the color edge goes to. For
    each side the curve is lifted just past the groove that way; the strip between the groove
    and that curve takes the wrong color, and the side whose strip a person sees least
    (visible_area) wins. A head over a neck goes up, onto the underside of the chin; a cuff over
    a wrist goes down, onto the hand where the cuff's rim hides it, where going up would leave a
    lip of the hand's color on the rim."""
    out = {}
    for side in (1, -1):
        line = {"center": list(center), "curve": groove_curve(pts, center, side)}
        out[side] = strip_seen(mesh, pts, center, line, side, only)
    return (1 if out[1][0] <= out[-1][0] else -1), out


def find_groove(mesh, line: dict, only=None) -> dict:
    """The line with its groove, when a groove runs all the way round within GROOVE_BAND mm of the
    plane: "curve" (360 heights round the center, on the side choose_side picks); "groove" says
    what was found and used. With no groove the line stays the level plane. only(line) gives the
    faces a line cuts (a hand's, for a cuff), when it cuts only some."""

    z, (cx, cy), rmax = line["z"], line["center"], line["rmax"]
    out = {**line, "curve": None, "groove": None}
    band = line.get("band", GROOVE_BAND)
    loop, cost = crease_loop(mesh, (cx, cy), z - band, z + band, rmax)
    if loop is None:
        return out
    P = np.asarray(mesh.vertices, float)[loop]
    length = float(np.linalg.norm(np.diff(P, axis=0), axis=1).sum())
    g = {"cost": round(cost / max(length, 1e-9), 3), "length": round(length, 1), "used": False}
    out["groove"] = g
    if length <= 0 or cost / length > GROOVE_COST or length < GROOVE_REACH * line["ring"]:
        return out
    th = np.arctan2(P[:, 1] - cy, P[:, 0] - cx)
    side, seen = choose_side(mesh, P, (cx, cy), only)
    cv = groove_curve(P, (cx, cy), side)
    cand = {**line, "curve": [round(float(v), 4) for v in cv]}
    dev = side * (np.interp(th, _BINS, cv, period=2 * np.pi) - P[:, 2])
    g["seen"] = {"up": seen[1][0], "down": seen[-1][0]}
    out = {**cand, "groove": {**g, "used": True, "side": side,
                              "z": [round(float(P[:, 2].min()), 2), round(float(P[:, 2].max()), 2)],
                              "off": [round(float(dev.min()), 2), round(float(np.median(dev)), 2),
                                      round(float(dev.max()), 2)]}}
    return out


def _line_ring(mesh, z: float, pick) -> tuple[np.ndarray, float, float] | None:
    """(center, radius, perimeter) of the section loop at z that pick(loops) chooses."""
    rings = _rings(mesh, z)
    if not rings:
        return None
    p = pick(rings)
    if p is None:
        return None
    c = p.mean(0)
    return c, float(np.linalg.norm(p - c, axis=1).max()), float(np.linalg.norm(np.diff(np.vstack([p, p[:1]]), axis=0), axis=1).sum())


def hem_fold(mesh, lo: float, hi: float, legs_apart=None) -> float | None:
    """The z of the top's own hem above the legs: the lowest groove in (lo, hi] that runs all the
    way round the body (crease_loop costs under GROOVE_COST per mm, at least GROOVE_REACH of the
    ring) where the body's section 1 mm above is at least HEM_STEP times the section 1 mm below: a
    jacket's edge over shorts. A belt on a long coat is no hem: the coat below it is as wide.

    lo is just above the legs' split. A groove whose section 1 mm below lies between the legs
    (legs_apart) is skipped, since the widest ring there is one leg and any groove would pass. The
    groove search runs only at a scan height where the section 2 mm above already steps out from
    the one 2 mm below (or at lo), so a figure with no such step, in trousers or a long coat, costs
    a few sections and no crease_loop."""
    rings_at: dict[float, np.ndarray | None] = {}

    def body(z):
        z = round(float(z), 3)
        if z not in rings_at:
            rings = _rings(mesh, z)
            rings_at[z] = max(rings, key=_ring_area) if rings else None
        return rings_at[z]

    def steps(za, zb):
        a, b = body(za), body(zb)
        return a is not None and b is not None and _ring_area(a) >= HEM_STEP * _ring_area(b)

    for z in np.arange(lo + 0.5, hi, 0.5):
        if not steps(z + 2.0, max(z - 2.0, lo)):
            continue
        p = body(z)
        if p is None:
            continue
        c = p.mean(0)
        r = float(np.linalg.norm(p - c, axis=1).max())
        ring = float(np.linalg.norm(np.diff(np.vstack([p, p[:1]]), axis=0), axis=1).sum())
        loop, cost = crease_loop(mesh, (float(c[0]), float(c[1])), z - 1.0, z + 1.0, r + SNAP)
        if loop is None:
            continue
        P = np.asarray(mesh.vertices, float)[loop]
        length = float(np.linalg.norm(np.diff(P, axis=0), axis=1).sum())
        if length <= 0 or cost / length > GROOVE_COST or length < GROOVE_REACH * ring:
            continue
        gz = float(np.median(P[:, 2]))
        if legs_apart is not None and legs_apart(gz - 1.0):
            continue
        if steps(gz + 1.0, gz - 1.0):
            return gz
    return None


def _leg_ring(mesh, z: float, x0: float, side: int):
    """The largest ring of the section at z on one side of the mirror plane: that leg, or None."""
    rings = [p for p in _rings(mesh, z) if (p[:, 0].mean() - x0) * side > 0]
    return max(rings, key=_ring_area) if rings else None


def ankle(mesh, top: float, split: float, x0: float, side: int) -> tuple[float, float] | None:
    """The z of the top of a shoe on one leg: in the lowest ANKLE_REACH of the legs, the height
    where the leg's section steps in the most going up (the shoe wider than the leg over it), when
    the section 0.5 mm under it is at least ANKLE_STEP times the one 0.5 mm over it, raised to where
    that taper ends. Returns (that height, the steepest step's) or None: a leg that narrows evenly to
    the plinth has no shoe line. The step can be a trouser hem flaring over the shoe; ankle_line
    looks for the crease under it first."""
    def area(z):
        p = _leg_ring(mesh, z, x0, side)
        return _ring_area(p) if p is not None else None

    best, at = ANKLE_STEP, None
    for z in np.arange(top + 1.0, top + ANKLE_REACH * (split - top), 0.25):
        a, b = area(z - 0.5), area(z + 0.5)
        if a is not None and b:
            if a / b >= best:
                best, at = a / b, float(z)
    if at is None:
        return None
    # the shoe's top is where its taper ends: the first height over the steepest step where the
    # section holds within ANKLE_SETTLED over the next 0.3 mm
    for z in np.arange(at, at + 1.0, 0.05):
        a, b = area(z), area(z + 0.3)
        if a and b and abs(a - b) / a < ANKLE_SETTLED:
            return round(float(z), 3), at
    return at, at


def leg_vertices(V: np.ndarray, anat: dict, side: int) -> np.ndarray:
    """The vertices of one leg, from the plinth's top (its sole's own corners included) to the hem:
    the side of the mirror plane, and low. Plinth faces in it are the base zone all the same."""
    V = np.asarray(V, float)
    hi = anat.get("hem") if anat.get("hem") is not None else anat["top"] + 0.5 * (anat["height"] - anat["top"])
    return ((V[:, 0] - anat["center"]) * side > 0) & (V[:, 2] >= anat["top"] - 1e-6) & (V[:, 2] < hi)


def find_lines(mesh, anat: dict) -> list[dict]:
    """The hem, the neck and each wrist as lines: {"name", "z", "center", "rmax", "ring"}, each on
    its groove when one is near (find_groove)."""
    out: list[dict] = []
    x0 = anat["center"]
    H = anat["height"] - anat["top"]

    def widest(rings):
        return max(rings, key=_ring_area)

    def middle(rings):
        ok = [p for p in rings if abs(p[:, 0].mean() - x0) < 0.15 * H]
        return max(ok, key=_ring_area) if ok else None

    if anat.get("hem") is not None:
        z = anat["hem"]
        rg = _line_ring(mesh, z, widest)
        if rg is not None:
            out.append({"name": "hem", "z": z, "center": [float(rg[0][0]), float(rg[0][1])],
                        "rmax": rg[1] + SNAP, "ring": rg[2], **({"band": 1.0} if anat.get("hem_fold") else {})})
        else:
            out.append({"name": "hem", "z": z, "center": [x0, 0.0], "rmax": 0.0, "ring": 0.0})
    if anat.get("neck") is not None:
        z = anat["neck"]
        rg = _line_ring(mesh, z, middle)
        if rg is not None:
            out.append({"name": "neck", "z": z, "center": [float(rg[0][0]), float(rg[0][1])],
                        "rmax": rg[1] + SNAP, "ring": rg[2]})
        else:
            out.append({"name": "neck", "z": z, "center": [x0, 0.0], "rmax": 0.0, "ring": 0.0})
    fig = _figure_faces(mesh, anat["top"])
    min_area = PIECE_MIN * float(mesh.area_faces[fig].sum())
    c = mesh.triangles_center
    seeds: dict[int, np.ndarray] = {}
    for w in anat.get("wrists", []):
        ps = [p for p in _pieces(mesh, _below(mesh, fig, w["z"], ON_LINE), anat["top"], min_area)
              if not p["stands"] and (p["cx"] - x0) * w["side"] > 0]
        line = {"name": "wrist", "side": w["side"], "z": w["z"], "center": [x0 + w["side"], 0.0], "rmax": 0.0, "ring": 0.0}
        if ps:
            sel = max(ps, key=lambda p: p["area"])["sel"]
            ring = sel & (c[:, 2] > w["z"] - 1.0)
            xy = c[ring, :2] if ring.any() else c[sel, :2]
            ctr = xy.mean(0)
            r = float(np.linalg.norm(xy - ctr, axis=1).max())
            line.update(center=[float(ctr[0]), float(ctr[1])], rmax=r + SNAP, ring=2 * np.pi * r * 0.8)
            seeds[id(line)] = sel
        out.append(line)
    ankles = [ankle_line(mesh, anat, a) for a in anat.get("ankles", [])]
    res = []
    for ln in out:
        if all(abs(ln["z"] - o["z"]) > 0.2 or (ln["name"], ln.get("side")) != (o["name"], o.get("side")) for o in res):
            if ln["rmax"] <= 0:
                res.append({**ln, "curve": None, "groove": None})
                continue
            seed = seeds.get(id(ln))
            only = None
            if seed is not None:
                def only(cand, seed=seed, wz=ln["z"]):
                    return _hand_mask(mesh, seed, cand, wz, fig)
            res.append(find_groove(mesh, ln, only))
    return res + ankles


def ankle_line(mesh, anat: dict, a: dict) -> dict:
    """The top of one shoe as a line, on its groove when one runs round that leg within 1 mm. The
    groove is searched on that leg's own faces, so the loop cannot cross to the other leg."""
    line = {"name": "ankle", "side": a["side"], "z": a["z"], "center": [anat["center"] + a["side"], 0.0],
            "rmax": 0.0, "ring": 0.0, "band": 1.0, "curve": None, "groove": None}
    p = _leg_ring(mesh, a["z"], anat["center"], a["side"])
    if p is None:
        return line
    ctr = p.mean(0)
    line.update(center=[float(ctr[0]), float(ctr[1])], rmax=float(np.linalg.norm(p - ctr, axis=1).max()) + 1.0,
                ring=float(np.linalg.norm(np.diff(np.vstack([p, p[:1]]), axis=0), axis=1).sum()))
    keep = leg_vertices(mesh.vertices, anat, a["side"])[np.asarray(mesh.faces)].all(1)
    if not keep.any():
        return line
    leg = mesh.submesh([np.nonzero(keep)[0]], append=True)
    # the crease where a trouser hem meets the shoe, under the hem's flare (the steepest step)
    zc = a.get("steep", a["z"]) - ANKLE_CREASE_BELOW
    near = {**line, "z": zc, "band": ANKLE_CREASE_BAND}
    q = _leg_ring(mesh, zc, anat["center"], a["side"])  # the crease is as wide as the flare's foot
    if q is not None:
        qc = q.mean(0)
        near.update(center=[float(qc[0]), float(qc[1])], rmax=float(np.linalg.norm(q - qc, axis=1).max()) + 1.0,
                    ring=float(np.linalg.norm(np.diff(np.vstack([q, q[:1]]), axis=0), axis=1).sum()))
    crease = find_groove(leg, near)
    if crease.get("curve") is not None and not _ledge_curve(crease, zc):
        return crease
    found = find_groove(leg, line)
    if found.get("curve") is not None and not _ledge_curve(found, a["z"]):
        return found
    line = {**line, "groove": found.get("groove")}
    rim = shoe_rim(mesh, line, keep)
    if rim is not None:
        # the rim is its own course, not the groove the search rejected
        line = {**line, "curve": [round(float(v), 4) for v in rim], "rim": True, "groove": None}
    return line


def shoe_rim(mesh, line: dict, keep: np.ndarray) -> np.ndarray | None:
    """The top of a shoe whose rim is not level (a toe box rising to the tongue): 360 heights round
    the leg's center. At each 10 degrees, from the ankle line up, the up-facing faces that start
    within ANKLE_RIM_GAP of the rim so far are still the shoe; the first gap ends it, so a fold of
    the trousers higher up keeps the trousers' color. None when the rim is level with the line."""
    z0, (cx, cy) = line["z"], line["center"]
    F = np.asarray(mesh.faces)
    fz = np.asarray(mesh.vertices, float)[F][:, :, 2]
    c = mesh.triangles_center
    r = np.hypot(c[:, 0] - cx, c[:, 1] - cy)
    sel = keep & (mesh.face_normals[:, 2] > ANKLE_RIM_NZ) & (r < line["rmax"] + 1.0) & \
        (fz.max(1) > z0) & (fz.min(1) < z0 + ANKLE_RIM_REACH)
    th = np.degrees(np.arctan2(c[:, 1] - cy, c[:, 0] - cx))
    tops = np.full(36, z0)
    for b in range(36):
        inb = np.nonzero(sel & (th >= b * 10 - 180) & (th < b * 10 - 170))[0]
        top = z0
        for i in inb[np.argsort(fz[inb].min(1))]:
            if fz[i].min() > top + ANKLE_RIM_GAP:
                break
            top = max(top, float(fz[i].max()))
        tops[b] = top
    if tops.max() - z0 < 0.1:
        return None
    deg = np.repeat(tops, 10)  # one value per degree, on _BINS (-180 to 179)
    # widen each rise by 8 degrees each way and smooth it, never below the rim itself
    wide = np.max([np.roll(deg, k) for k in range(-8, 9)], axis=0)
    return np.maximum(_gauss(wide, 3.0), deg) + 0.05


def _ledge_curve(line: dict, z: float) -> bool:
    """A groove curve that strays more than 2 mm from the step it was found for: not the shoe's top."""
    cv = np.asarray(line["curve"], float)
    return bool(np.abs(cv - z).max() > 2.0)


def _line(anat: dict, name: str, side: int | None = None) -> dict | None:
    for ln in anat.get("lines") or []:
        if ln["name"] == name and (side is None or ln.get("side") == side):
            return ln
    z = anat.get(name)
    return {"name": name, "z": z, "curve": None} if z is not None and name in ("hem", "neck") else None


def levels(anat: dict) -> list[float]:
    """The z of every plane line (lines on a groove are curves, not planes)."""
    out: list[float] = []
    for z in [anat.get("hem"), anat.get("neck")] + [w["z"] for w in anat.get("wrists", [])]:
        if z is not None and all(abs(z - o) > 0.2 for o in out):
            out.append(float(z))
    return out


def all_lines(anat: dict) -> list[dict]:
    """Every line to cut along: the found lines, or the planes when none were found."""
    if anat.get("lines"):
        return anat["lines"]
    out = []
    for name in ("hem", "neck"):
        if anat.get(name) is not None:
            out.append({"name": name, "z": anat[name], "curve": None})
    for w in anat.get("wrists", []):
        out.append({"name": "wrist", "side": w["side"], "z": w["z"], "curve": None})
    for a in anat.get("ankles", []):
        out.append({"name": "ankle", "side": a["side"], "z": a["z"], "curve": None})
    return out


def cut(V, F, anat: dict):
    """The mesh cut along every line of the shape: each face then lies on one side of each."""
    from .clean import cut_iso

    V = np.asarray(V, float)
    F = np.asarray(F, np.int64)
    done: list[float] = []
    lines = all_lines(anat)
    for ln in lines:
        curved = ln.get("curve") is not None
        if (ln["name"] == "wrist" and curved) or ln["name"] == "ankle":
            continue
        if not curved:
            if any(abs(ln["z"] - z) <= 0.2 for z in done):
                continue
            done.append(ln["z"])
        V, F = cut_iso(V, F, field(ln, V), 0.0, snap=0.02)
        V = V.astype(np.float32).astype(float)
    # a cuff line cuts only round its hand: the hand's faces and one ring round them get the true
    # field, every other vertex +1, so no cut runs over the hip or a leg near the hand
    import trimesh

    for w in anat.get("wrists", []):
        ln = next((x for x in lines if x["name"] == "wrist" and x.get("side") == w["side"]), None)
        if ln is None or ln.get("curve") is None:
            continue
        m = trimesh.Trimesh(V, F, process=False)
        hf = hand_faces(m, anat, w)
        if hf is None:
            continue
        vr = _with_ring(F, hf, len(V))[0]
        V, F = cut_masked(V, F, field(ln, V), vr)
        V = V.astype(np.float32).astype(float)
    # a shoe line cuts only its own leg; every other vertex keeps the side of the line's level, so
    # no cut runs where the leg's zone ends
    for ln in [x for x in lines if x["name"] == "ankle"]:
        d = field(ln, V)
        inside = leg_vertices(V, anat, ln["side"]) & (V[:, 2] > ln["z"] - 3.0) & (V[:, 2] < ln["z"] + ANKLE_RIM_REACH + 0.5)
        V, F = cut_iso(V, F, np.where(inside, d, np.sign(V[:, 2] - ln["z"])), 0.0, snap=0.02, slope=d)
        V = V.astype(np.float32).astype(float)
    return V, F


def cut_masked(V, F, d: np.ndarray, inside: np.ndarray):
    """Cut along d == 0 only among the `inside` vertices: every other vertex counts as +1. The snap
    distance comes from d itself, not from the jump to +1 at the rim of the zone."""
    from .clean import cut_iso

    return cut_iso(V, F, np.where(inside, d, 1.0), 0.0, snap=0.02, slope=d)


def _wrist_lines(anat: dict) -> list[dict]:
    return [ln for ln in all_lines(anat) if ln["name"] == "wrist"]


def _hand_seed(mesh, anat: dict, w: dict) -> np.ndarray | None:
    """The loose piece below a wrist's level on its side (the junction the anatomy found)."""
    top = anat["top"]
    fig = _figure_faces(mesh, top)
    min_area = PIECE_MIN * float(mesh.area_faces[fig].sum())
    ps = [p for p in _pieces(mesh, _below(mesh, fig, w["z"], ON_LINE), top, min_area)
          if not p["stands"] and (p["cx"] - anat["center"]) * w["side"] > 0]
    return max(ps, key=lambda p: p["area"])["sel"] if ps else None


def _hand_mask(mesh, seed: np.ndarray, ln: dict, wz: float, fig: np.ndarray) -> np.ndarray:
    """The faces below a cuff line within HAND_REACH mm of the hand's axis, in the pieces
    (connected through such faces) that hold the seed. Below the wrist's level only the seed
    counts: the hip and legs there are pieces of their own."""
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components

    c = mesh.triangles_center
    ax = c[seed, :2].mean(0)
    above = mesh.vertices[mesh.faces][:, :, 2].max(1) > wz + ON_LINE
    cand = fig & (side_of(mesh, ln) < 0) & (np.hypot(c[:, 0] - ax[0], c[:, 1] - ax[1]) < HAND_REACH) & (above | seed)
    adj = mesh.face_adjacency
    keep = cand[adj[:, 0]] & cand[adj[:, 1]]
    n = len(mesh.faces)
    _, comp = connected_components(sp.coo_matrix((np.ones(int(keep.sum())), (adj[keep, 0], adj[keep, 1])),
                                                 shape=(n, n)), directed=False)
    ids = np.unique(comp[seed & cand])
    return cand & np.isin(comp, ids) if len(ids) else seed


def hand_faces(mesh, anat: dict, w: dict) -> np.ndarray | None:
    """A hand's faces (_hand_mask round the seed below its wrist). A plane line at the wrist
    level gives the seed itself."""
    seed = _hand_seed(mesh, anat, w)
    ln = next((x for x in _wrist_lines(anat) if x.get("side") == w["side"]), None)
    if seed is None or ln is None or (ln.get("curve") is None and abs(ln["z"] - w["z"]) < 1e-6):
        return seed
    return _hand_mask(mesh, seed, ln, w["z"], _figure_faces(mesh, anat["top"]))


def hands(mesh, anat: dict) -> list[np.ndarray]:
    """One face mask per hand (hand_faces)."""
    out = []
    for w in anat.get("wrists", []):
        h = hand_faces(mesh, anat, w)
        if h is not None:
            out.append(h)
    return out


def zones(mesh, anat: dict, base: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(zone per face, hand number per face or -1), on a mesh cut along the lines."""
    c = mesh.triangles_center
    zone = np.full(len(mesh.faces), TORSO, int)
    hem, neck = _line(anat, "hem"), _line(anat, "neck")
    if hem is not None:
        zone[side_of(mesh, hem) < 0] = LEGS
    if neck is not None:
        zone[side_of(mesh, neck) > 0] = HEAD
    for a in [x for x in all_lines(anat) if x["name"] == "ankle"]:
        # the legs are apart this low, so the side of a face's center is its leg
        own = (c[:, 0] - anat["center"]) * a["side"] > 0
        zone[own & (zone == LEGS) & (side_of(mesh, a) < 0)] = SHOES
    hand = np.full(len(mesh.faces), -1, int)
    for i, m in enumerate(hands(mesh, anat)):
        zone[m] = HANDS
        hand[m] = i
    zone[base] = BASE
    return zone, hand


def _dominant(labels: np.ndarray, area: np.ndarray, sel: np.ndarray) -> int | None:
    if not sel.any():
        return None
    return int(np.bincount(labels[sel], weights=area[sel]).argmax())


def snap(mesh, labels: np.ndarray, zone: np.ndarray, hand: np.ndarray, anat: dict) -> tuple[np.ndarray, np.ndarray]:
    """(labels, fixed): every hand takes its main color, and near each line the color of each
    side's band runs right up to the line. `fixed` marks the faces within BAND of a line, which
    keep their color through the edge smoothing, so the edge stays on the line."""
    labels = labels.copy()
    area = mesh.area_faces
    c = mesh.triangles_center
    xy = c[:, :2]
    fixed = np.zeros(len(labels), bool)
    lines = []
    hem, neck = _line(anat, "hem"), _line(anat, "neck")
    if hem is not None:
        d = field(hem, c)
        lines.append((d, (zone == LEGS) & (d > -SNAP), (zone == TORSO) & (d < SNAP)))
    if neck is not None:
        d = field(neck, c)
        lines.append((d, (zone == TORSO) & (d > -SNAP), (zone == HEAD) & (d < SNAP)))
    for a in [x for x in all_lines(anat) if x["name"] == "ankle"]:
        d = field(a, c)
        own = (c[:, 0] - anat["center"]) * a["side"] > 0
        lines.append((d, own & (zone == SHOES) & (d > -SNAP), own & (zone == LEGS) & (d < SNAP)))
    wl = _wrist_lines(anat)
    for i in range(int(hand.max()) + 1 if len(hand) else 0):
        hm = hand == i
        a = _dominant(labels, area, hm)
        labels[hm] = a  # a hand is one color: skin, or a glove
        side = 1 if c[hm, 0].mean() > anat["center"] else -1
        ln = next((w for w in wl if w.get("side") == side), None)
        if ln is None:
            w = float(mesh.vertices[mesh.faces[hm]][:, :, 2].max())
            ln = {"z": w, "curve": None}
        d = field(ln, c)
        ring = hm & (d > -1.0)
        ctr = xy[ring].mean(0) if ring.any() else xy[hm].mean(0)
        r = float(np.linalg.norm(xy[ring] - ctr, axis=1).max()) if ring.any() else 0.0
        near = np.linalg.norm(xy - ctr, axis=1) < r + SNAP
        lines.append((d, hm, (zone == TORSO) & (np.abs(d) < SNAP) & near))
    for d, A, B in lines:
        a, b = _dominant(labels, area, A), _dominant(labels, area, B)
        if a is not None and b is not None and a != b:
            labels[A & (labels == b)] = a
            labels[B & (labels == a)] = b
        fixed |= (A & (np.abs(d) < BAND)) | (B & (np.abs(d) < BAND))
    fixed |= hand >= 0
    return labels, fixed


# glasses


def frames(mesh, anat: dict, zone: np.ndarray):
    """(offset per vertex, face mask) of glasses frames found from the shape: on the front of the
    head at eye height, the faces that stand more than FRAME_OFF mm out of the head smoothed over
    FRAME_RADIUS mm, in pieces that together span both sides of the face and at least FRAME_WIDTH
    of the head's width. Wide bumps (nose, cheeks) and the eyes are pieces of their own and too
    narrow. None when no such frames are there."""
    import trimesh

    from .colors import _diffuse

    neck, zt = anat.get("neck"), anat["height"]
    head = zone == HEAD
    if neck is None or head.sum() < 100:
        return None
    hv = np.unique(mesh.faces[head])
    remap = np.full(len(mesh.vertices), -1)
    remap[hv] = np.arange(len(hv))
    Vh = np.asarray(mesh.vertices, float)[hv]
    Fh = remap[mesh.faces[head]]
    Vs = _diffuse(Vh, Fh, Vh.copy(), FRAME_RADIUS)
    n = np.asarray(trimesh.Trimesh(Vs, Fh, process=False).vertex_normals)
    off = np.zeros(len(mesh.vertices))
    off[hv] = ((Vh - Vs) * n).sum(1)
    c = mesh.triangles_center
    hc = c[head]
    h = zt - neck
    eye = (c[:, 2] > neck + 0.2 * h) & (c[:, 2] < neck + 0.6 * h)
    front = c[:, 1] < hc[:, 1].mean()
    cand = head & eye & front & (off[mesh.faces].mean(1) > FRAME_OFF)
    if not cand.any():
        return None
    width = float(hc[:, 0].max() - hc[:, 0].min())
    x0 = anat["center"]
    keep = np.zeros(len(cand), bool)
    for p in _pieces(mesh, cand, anat["top"], 0.0):
        xs = c[p["sel"], 0]
        if xs.max() - xs.min() >= FRAME_WIDTH * width / 2:
            keep |= p["sel"]
    if not keep.any():
        return None
    a = mesh.area_faces
    left, right = a[keep & (c[:, 0] < x0)].sum(), a[keep & (c[:, 0] >= x0)].sum()
    if min(left, right) < 0.25 * (left + right):
        return None  # frames are on both eyes; one-sided is something else
    return off, keep


# odd shapes


def _turn(pts: np.ndarray, closed: bool, chord: float = CORNER_MM) -> float:
    """The largest turn in degrees between the chords before and after any point of a line,
    after a 1 mm moving average takes out the steps of the triangles."""
    from .colors import _moving_average, _resample

    r, L, ds = _resample(pts, closed)
    if L < 2 * chord:
        return 0.0
    k = max(3, int(round(1.0 / ds)) | 1)
    m = _moving_average(r, k, closed)
    n = max(1, int(round(chord / ds)))
    if closed:
        a, b, c = np.roll(m, n, 0), m, np.roll(m, -n, 0)
    else:
        if len(m) <= 2 * n:
            return 0.0
        a, b, c = m[:-2 * n], m[n:-n], m[2 * n:]
    u, v = b - a, c - b
    cos = (u * v).sum(1) / np.maximum(np.linalg.norm(u, axis=1) * np.linalg.norm(v, axis=1), 1e-12)
    return float(np.degrees(np.arccos(np.clip(cos, -1, 1))).max())


def corner(mesh, region: np.ndarray, r: int) -> float:
    """The sharpest turn of region r's edge, in degrees."""
    from .colors import boundary_lines

    f = np.where(region == r, 2, 1)
    lines = boundary_lines(mesh.vertices, mesh.faces, f)
    return max((_turn(ln["pts"], ln["closed"]) for ln in lines if ln["length"] >= 2 * CORNER_MM), default=0.0)


def mirror(mesh, region: np.ndarray, labels: np.ndarray, r: int, x0: float) -> float:
    """Share of region r (by area) whose mirror image across x = x0 lands on its own color."""
    from scipy.spatial import cKDTree

    c = mesh.triangles_center
    sel = region == r
    if not sel.any():
        return 1.0
    p = c[sel].copy()
    p[:, 0] = 2 * x0 - p[:, 0]
    _, j = cKDTree(c).query(p)
    lab = labels[sel][0] if len(set(labels[sel])) == 1 else np.bincount(labels[sel]).argmax()
    a = mesh.area_faces[sel]
    return float(a[labels[j] == lab].sum() / a.sum())


def _region_zone(region: np.ndarray, zone: np.ndarray, area: np.ndarray) -> dict[int, int]:
    R = int(region.max()) + 1
    w = np.zeros((R, len(ZONES)))
    np.add.at(w, (region, zone), area)
    return {r: int(w[r].argmax()) for r in range(R) if w[r].sum() > 0}


def merge_odd(mesh, region: np.ndarray, labels: np.ndarray, zone: np.ndarray, keep: set[int], x0: float):
    """(region, merged): a region not in keep whose edge has a corner sharper than CORNER, or that
    is far from mirror-symmetric (a collar patch on one side of the neck), joins the neighbor in
    its zone it shares the longest edge with. Returns the new numbering (0..R-1, the same order
    where nothing merged) and [(region, into, why)]."""
    region = region.copy()
    adj = mesh.face_adjacency
    ev = mesh.face_adjacency_edges
    elen = np.linalg.norm(mesh.vertices[ev[:, 0]] - mesh.vertices[ev[:, 1]], axis=1)
    merged = []
    for r in range(int(region.max()) + 1):
        if r in keep or not (region == r).any():
            continue
        zr = int(np.bincount(zone[region == r]).argmax())
        why = None
        m = mirror(mesh, region, labels, r, x0)
        if m < MIRROR_MIN:
            why = f"one-sided ({m * 100:.0f}% matches its mirror image)"
        else:
            t = corner(mesh, region, r)
            if t > CORNER:
                why = f"a sharp corner ({t:.0f} degrees)"
        if why is None:
            continue
        rz = _region_zone(region, zone, mesh.area_faces)
        ra, rb = region[adj[:, 0]], region[adj[:, 1]]
        touch = (ra == r) ^ (rb == r)
        other = np.where(ra[touch] == r, rb[touch], ra[touch])
        nb: dict[int, float] = {}
        for o in np.unique(other):
            if rz.get(int(o)) == zr:
                nb[int(o)] = float(elen[touch][other == o].sum())
        if not nb:
            continue
        into = max(nb, key=nb.get)
        region[region == r] = into
        merged.append((r, into, why))
    return region, merged


# names


def name_parts(mesh, region: np.ndarray, info: list[dict], zone: np.ndarray, anat: dict,
               look: str = "", glasses: set[int] | None = None) -> None:
    """Set d["part"] on each region entry: base, shoes, pants, top, hands, face, hair, glasses or
    other, with the words look.txt uses ("jacket" for top)."""
    from .colors import NAMES, _lab

    words = look_words(look)
    area = mesh.area_faces
    total = float(area.sum())
    zc = mesh.triangles_center[:, 2]
    top, zt = anat["top"], anat["height"]
    by_r = {d["region"]: d for d in info}
    zr = {}
    for d in info:
        sel = region == d["region"]
        zr[d["region"]] = int(np.bincount(zone[sel], weights=area[sel]).argmax())
        d["part"] = "other"
    for d in info:
        if d["base"]:
            d["part"] = "base"
    hem = anat.get("hem")
    legs = sorted([d for d in info if zr[d["region"]] == LEGS and not d["base"]], key=lambda d: -d["share"])
    for d in legs:
        sel = region == d["region"]
        if hem is not None and d["z0"] < top + 0.5 and d["z1"] < top + 0.45 * (hem - top) and len(legs) > 1:
            d["part"] = "shoes"
    rest = [d for d in legs if d["part"] == "other"]
    if rest:
        rest[0]["part"] = "pants"
    torso = sorted([d for d in info if zr[d["region"]] == TORSO and not d["base"]], key=lambda d: -d["share"])
    if torso:
        torso[0]["part"] = "top"
    for d in info:
        if zr[d["region"]] == HANDS:
            d["part"] = "hands"
        elif zr[d["region"]] == SHOES and not d["base"]:
            d["part"] = "shoes"
    skin = _lab([NAMES["skin"]])[0]
    # the garment between hem and neck, body and arms: every region of it, not just the largest, so
    # sleeves of another shade are the jacket too. Skin there is bare arms, not the garment. These
    # extra regions stay open to merge_odd, which cleans up stray patches ("extra").
    for d in torso[1:]:
        if d["part"] == "other" and d["rgb"] is not None and np.linalg.norm(_lab(d["rgb"])[0] - skin) >= 40:
            d["part"], d["extra"] = "top", True
    head = sorted([d for d in info if zr[d["region"]] == HEAD and not d["base"]], key=lambda d: -d["share"])
    face = None
    for d in head:
        if d["rgb"] is not None and np.linalg.norm(_lab(d["rgb"])[0] - skin) < 40 and (region == d["region"]).any():
            face = d
            break
    if face is None and head:
        face = head[0]
    if face is not None:
        face["part"] = "face"
    for d in head:
        if d is not face and d["z1"] >= zt - 1.0:
            d["part"] = "hair"
            break
    neck = anat.get("neck")
    for d in head:
        if d["part"] != "other":
            continue
        if glasses is not None:
            if d["region"] in glasses:
                d["part"] = "glasses"
            continue
        sel = region == d["region"]
        h0 = neck if neck is not None else top + 0.6 * (zt - top)
        mid = float((zc[sel] * area[sel]).sum() / area[sel].sum())
        front = float(mesh.triangles_center[sel, 1].mean()) < float(mesh.triangles_center[zone == HEAD, 1].mean())
        if d["share"] < GLASSES_SHARE and front and h0 + 0.25 * (zt - h0) < mid < h0 + 0.65 * (zt - h0):
            d["part"] = "glasses"
    for d in info:
        if d["part"] == "top" and "top" in words:
            d["part"] = words["top"]
        elif d["part"] == "pants" and "pants" in words:
            d["part"] = words["pants"]
    del by_r
