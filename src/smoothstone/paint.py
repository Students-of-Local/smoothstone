"""Color a figure from its front and back views, then reduce it to a few filament colors.

The style model draws the figure from the front (style.png) and, from that, from behind
(back.png). Both are projected straight onto the mesh: faces in the front half take the
front picture, faces at the back take the mirrored back picture, and the middle blends the two by
where they sit between the front and back surfaces. Background pixels are filled with the nearest figure color first,
so an edge never picks up the white backdrop.

Pure numpy and scipy on the CPU, a few seconds for 250k faces.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

WHITE_CUT = 40  # a pixel this close to white (sum of 255 - channel) is backdrop


def _load(path: Path) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """RGB float image with the backdrop filled from the nearest figure pixel, and the figure bbox."""
    from PIL import Image
    from scipy import ndimage

    a = np.asarray(Image.open(path).convert("RGB")).astype(np.float32)
    fg = (255 * 3 - a.sum(2)) > WHITE_CUT
    fg = ndimage.binary_opening(fg, iterations=2)
    lab, n = ndimage.label(fg)
    if n > 1:  # keep the figure, drop specks
        sizes = ndimage.sum(fg, lab, range(1, n + 1))
        fg = lab == (1 + int(np.argmax(sizes)))
    core = ndimage.binary_erosion(fg, iterations=3)  # antialiased rim pixels are half backdrop
    idx = ndimage.distance_transform_edt(~core, return_distances=False, return_indices=True)
    filled = a[idx[0], idx[1]]
    ys, xs = np.where(fg)
    return filled, (xs.min(), xs.max(), ys.min(), ys.max())


def _fg(path: Path) -> np.ndarray:
    """The figure's mask in a picture on white."""
    from PIL import Image
    from scipy import ndimage

    a = np.asarray(Image.open(path).convert("RGB")).astype(np.float32)
    fg = ndimage.binary_opening((255 * 3 - a.sum(2)) > WHITE_CUT, iterations=2)
    lab, n = ndimage.label(fg)
    if n > 1:
        sizes = ndimage.sum(fg, lab, range(1, n + 1))
        fg = lab == (1 + int(np.argmax(sizes)))
    return ndimage.binary_fill_holes(fg)


def _extents(rows_of: np.ndarray, cols_of: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Left and right edge of a silhouette in each of n rows, gaps filled, lightly smoothed."""
    from scipy import ndimage

    L = np.full(n, np.inf)
    R = np.full(n, -np.inf)
    np.minimum.at(L, rows_of, cols_of)
    np.maximum.at(R, rows_of, cols_of)
    ok = np.isfinite(L)
    idx = np.arange(n)
    L = np.interp(idx, idx[ok], L[ok])
    R = np.interp(idx, idx[ok], R[ok])
    return ndimage.median_filter(L, 5, mode="nearest"), ndimage.median_filter(R, 5, mode="nearest")


def register(x: np.ndarray, z: np.ndarray, fg: np.ndarray, rows: int = 400):
    """Map mesh points (x across, z up, as the camera sees them) to pixels of a drawing of the same figure.

    A bounding box is not enough: the lift model makes the head a little smaller or the legs a
    little longer than the drawing, and then the eyes land on the nose. So the heights are
    matched by the shape of the outline (the width of the figure at each height, matched with
    dynamic time warping), and each row is then stretched between its own left and right edges.
    """
    z0, z1 = z.min(), z.max()
    rm = np.clip(((z - z0) / max(z1 - z0, 1e-9) * (rows - 1)).round().astype(int), 0, rows - 1)
    Lm, Rm = _extents(rm, x, rows)

    ys, xs = np.where(fg)
    y0, y1 = ys.min(), ys.max()
    ri = np.clip(((y1 - ys) / max(y1 - y0, 1) * (rows - 1)).round().astype(int), 0, rows - 1)
    Li, Ri = _extents(ri, xs.astype(float), rows)

    wm = (Rm - Lm) / max((Rm - Lm).max(), 1e-9)
    wi = (Ri - Li) / max((Ri - Li).max(), 1e-9)
    path = _dtw(wm, wi, band=int(rows * 0.12))
    match = np.zeros(rows)
    cnt = np.zeros(rows)
    np.add.at(match, path[:, 0], path[:, 1])
    np.add.at(cnt, path[:, 0], 1)
    match = np.maximum.accumulate(match / np.maximum(cnt, 1))

    def to_px(xq: np.ndarray, zq: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        r = np.clip((zq - z0) / max(z1 - z0, 1e-9) * (rows - 1), 0, rows - 1)
        j = np.interp(r, np.arange(rows), match)
        lm, rmx = np.interp(r, np.arange(rows), Lm), np.interp(r, np.arange(rows), Rm)
        li, rix = np.interp(j, np.arange(rows), Li), np.interp(j, np.arange(rows), Ri)
        a = np.clip((xq - lm) / np.maximum(rmx - lm, 1e-9), -0.05, 1.05)
        px = li + a * (rix - li)
        py = y1 - j / (rows - 1) * (y1 - y0)
        return np.clip(px, 0, fg.shape[1] - 1), np.clip(py, 0, fg.shape[0] - 1)

    return to_px


def _dtw(a: np.ndarray, b: np.ndarray, band: int) -> np.ndarray:
    """Monotonic row-to-row match of two profiles inside a diagonal band, as (i, j) pairs."""
    n, m = len(a), len(b)
    D = np.full((n + 1, m + 1), np.inf)
    D[0, 0] = 0
    for i in range(1, n + 1):
        lo, hi = max(1, i - band), min(m, i + band)
        c = np.abs(a[i - 1] - b[lo - 1:hi])
        for k, j in enumerate(range(lo, hi + 1)):
            D[i, j] = c[k] + min(D[i - 1, j - 1], D[i - 1, j] + 0.01, D[i, j - 1] + 0.01)
    i, j, path = n, m, []
    while i > 0 and j > 0:
        path.append((i - 1, j - 1))
        step = np.argmin([D[i - 1, j - 1], D[i - 1, j], D[i, j - 1]])
        i, j = (i - 1, j - 1) if step == 0 else (i - 1, j) if step == 1 else (i, j - 1)
    return np.array(path[::-1])


def _sample(img: np.ndarray, box, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """u, v in 0..1 across the figure bbox (v = 0 at the feet) to RGB."""
    x0, x1, y0, y1 = box
    px = np.clip(x0 + u * (x1 - x0), 0, img.shape[1] - 1)
    py = np.clip(y1 - v * (y1 - y0), 0, img.shape[0] - 1)
    return img[py.round().astype(int), px.round().astype(int)]


def vertex_colors(mesh, front: Path, back: Path | None = None) -> np.ndarray:
    """Per-vertex RGB (0..255 float) for a unit-height figure: Z up, face toward -Y."""
    fimg, fbox = _load(front)
    bimg, bbox = _load(back) if back and Path(back).exists() else (None, None)
    v = mesh.vertices
    lo, hi = v.min(0), v.max(0)
    u = (v[:, 0] - lo[0]) / max(hi[0] - lo[0], 1e-9)
    h = (v[:, 2] - lo[2]) / max(hi[2] - lo[2], 1e-9)
    cf = _sample(fimg, fbox, u, h)
    if bimg is None:
        return cf
    cb = _sample(bimg, bbox, 1 - u, h)  # seen from behind, left and right swap
    t = _depth(v, u, h)
    wb = np.clip((t - 0.38) / 0.24, 0, 1)
    wb = wb * wb * (3 - 2 * wb)  # smoothstep: front half takes the front picture, back half the back
    return cf * (1 - wb[:, None]) + cb * wb[:, None]


def _depth(v: np.ndarray, u: np.ndarray, h: np.ndarray, rows: int = 240) -> np.ndarray:
    """Where each vertex sits between the front surface (0) and the back surface (1) along its line of sight."""
    from scipy import ndimage

    ext = v.max(0) - v.min(0)
    cols = max(8, int(rows * ext[0] / max(ext[2], 1e-9)))
    r = np.clip((h * (rows - 1)).round().astype(int), 0, rows - 1)
    c = np.clip((u * (cols - 1)).round().astype(int), 0, cols - 1)
    zf = np.full((rows, cols), np.inf)
    zb = np.full((rows, cols), -np.inf)
    np.minimum.at(zf, (r, c), v[:, 1])
    np.maximum.at(zb, (r, c), v[:, 1])
    empty = np.isinf(zf)
    if empty.any():
        idx = ndimage.distance_transform_edt(empty, return_distances=False, return_indices=True)
        zf, zb = zf[idx[0], idx[1]], zb[idx[0], idx[1]]
    f, b = zf[r, c], zb[r, c]
    return np.clip((v[:, 1] - f) / np.maximum(b - f, 1e-6), 0, 1)


def palette(colors: np.ndarray, most: int = 4, merge: float = 25.0, seed: int = 7) -> tuple[np.ndarray, np.ndarray]:
    """Up to `most` filament colors: k-means in Lab, then colors closer than `merge` (delta E) join,
    so shine on black leather stays black, and groups under 2% fold into their nearest color."""
    from scipy.cluster.vq import kmeans2

    lab = _to_lab(colors)
    rng = np.random.default_rng(seed)
    pick = lab[rng.choice(len(lab), size=min(len(lab), 20000), replace=False)]
    cent, _ = kmeans2(pick, most + 2, minit="++", seed=seed)
    while len(cent) > 1:
        labels = ((lab[:, None, :] - cent[None, :, :]) ** 2).sum(2).argmin(1)
        share = np.bincount(labels, minlength=len(cent)) / len(lab)
        d = np.sqrt(((cent[:, None] - cent[None]) ** 2).sum(2)) + np.eye(len(cent)) * 1e9
        i, j = np.unravel_index(d.argmin(), d.shape)
        small = share.argmin()
        if d[i, j] < merge or len(cent) > most:
            keep = i if share[i] >= share[j] else j
            drop = j if keep == i else i
        elif share[small] < 0.02:
            drop = small
        else:
            break
        cent = np.delete(cent, drop, 0)
    labels = ((lab[:, None, :] - cent[None, :, :]) ** 2).sum(2).argmin(1)
    pal = np.array([np.median(colors[labels == i], 0) for i in range(len(cent))])
    return pal, labels


def _to_lab(rgb: np.ndarray) -> np.ndarray:
    c = rgb / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = c @ m.T / np.array([0.9505, 1.0, 1.089])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], 1)


def clean_labels(mesh, labels: np.ndarray, rounds: int = 3) -> np.ndarray:
    """Majority vote over each vertex's neighbors, which removes salt-and-pepper specks."""
    k = labels.max() + 1
    edges = mesh.edges_unique
    for _ in range(rounds):
        votes = np.zeros((len(labels), k))
        votes[np.arange(len(labels)), labels] += 1.5
        np.add.at(votes, (edges[:, 0], labels[edges[:, 1]]), 1)
        np.add.at(votes, (edges[:, 1], labels[edges[:, 0]]), 1)
        labels = votes.argmax(1)
    return labels


def _lines(img: np.ndarray, box) -> tuple[np.ndarray, np.ndarray]:
    """Thin dark lines in a drawing (glasses frames): the picture with them painted over from the
    colors around them, and their mask. A lift model turns such lines into raised rims that sit
    elsewhere and run wider than the drawn line, so the rims are painted from the mesh instead."""
    from scipy import ndimage

    r = max(3, int(0.008 * (box[3] - box[2])))
    lum = img @ np.array([0.299, 0.587, 0.114])
    dark = lum < 70
    thin = dark & ~ndimage.binary_opening(dark, iterations=r)
    thin = ndimage.binary_dilation(thin, iterations=1) & dark
    lab, n = ndimage.label(thin)
    if n:  # keep line pieces long enough to be a frame, not specks along a jacket edge
        size = ndimage.sum(thin, lab, range(1, n + 1))
        thin = np.isin(lab, 1 + np.where(size >= 8 * r)[0])
    if not thin.any():
        return img, thin
    edge = ndimage.binary_dilation(thin, iterations=2)
    idx = ndimage.distance_transform_edt(edge, return_distances=False, return_indices=True)
    out = img.copy()
    out[edge] = img[idx[0][edge], idx[1][edge]]
    return out, thin


def relief(mesh, seed: float = 0.0035, grow: float = 0.0015, rounds: int = 20):
    """Labels for raised thin features (rims, ridges) on a unit-height mesh, 0 where there are none.

    Each vertex's offset along its normal from a smoothed copy picks out detail narrower than the
    smoothing. Seeds above `seed` grow through neighbors above `grow` (hysteresis)."""
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components

    v, e, n = mesh.vertices, mesh.edges_unique, len(mesh.vertices)
    A = sp.coo_matrix((np.ones(len(e) * 2), (np.r_[e[:, 0], e[:, 1]], np.r_[e[:, 1], e[:, 0]])), shape=(n, n)).tocsr()
    L = sp.diags(1 / np.maximum(np.asarray(A.sum(1)).ravel(), 1)) @ A
    sm = v.copy()
    for _ in range(rounds):
        sm = L @ sm
    d = ((v - sm) * mesh.vertex_normals).sum(1)
    weak = d > grow
    keep = e[weak[e[:, 0]] & weak[e[:, 1]]]
    G = sp.coo_matrix((np.ones(len(keep)), (keep[:, 0], keep[:, 1])), shape=(n, n))
    _, lab = connected_components(G, directed=False)
    strong = np.unique(lab[d > seed])
    out = np.where(weak & np.isin(lab, strong), lab + 1, 0)
    return out


def textured(mesh, front: Path, back: Path | None, out_png: Path):
    """The mesh with a texture: the front picture on the front half, the back picture on the back.

    Writes a two-panel atlas (front left, back right) to out_png and returns a trimesh with UVs.
    Faces split at the middle depth, so the seam runs down the sides where both pictures agree.
    """
    import trimesh
    from PIL import Image

    raw_f, fbox = _load(front)
    raw_b, bbox = _load(back) if back and Path(back).exists() else (raw_f, fbox)
    fimg, fline = _lines(raw_f, fbox)
    bimg, _ = _lines(raw_b, bbox)
    SW = 32  # a column of solid swatches for painted relief
    hgt = max(fimg.shape[0], bimg.shape[0])
    atlas = np.full((hgt, fimg.shape[1] + bimg.shape[1] + SW, 3), 255, np.float32)
    atlas[:fimg.shape[0], :fimg.shape[1]] = fimg
    atlas[:bimg.shape[0], fimg.shape[1]:fimg.shape[1] + bimg.shape[1]] = bimg
    W = atlas.shape[1]

    has_back = bool(back and Path(back).exists())
    v = mesh.vertices
    lo, hi = v.min(0), v.max(0)
    u = (v[:, 0] - lo[0]) / max(hi[0] - lo[0], 1e-9)
    h = (v[:, 2] - lo[2]) / max(hi[2] - lo[2], 1e-9)
    t = _depth(v, u, h)
    f = mesh.faces
    side = (t[f].mean(1) > 0.5) if has_back else np.zeros(len(f), bool)

    # where each vertex lands in the front picture and, mirrored, in the back picture
    fpx, fpy = register(v[:, 0], v[:, 2], _fg(front))(v[:, 0], v[:, 2])
    if has_back:
        bpx, bpy = register(-v[:, 0], v[:, 2], _fg(back))(-v[:, 0], v[:, 2])
    else:
        bpx, bpy = fpx, fpy
    pick = np.repeat(side[:, None], 3, 1)
    cx = np.where(pick, fimg.shape[1] + bpx[f], fpx[f])
    cy = np.where(pick, bpy[f], fpy[f])
    corner = np.stack([cx / W, 1 - cy / hgt], -1)  # (F, 3, 2)
    # faces seen edge-on (rim walls of glasses, tops of shoes) smear the picture: give each one the
    # color at the center of the nearest face its camera sees squarely
    ny = mesh.face_normals[:, 1]
    conf = np.where(side, ny, -ny)
    ok = conf > 0.4
    center = corner.mean(1)
    if (~ok).any() and ok.any():
        adj = mesh.face_adjacency
        src = center.copy()
        done = ok.copy()
        for _ in range(64):
            a_, b_ = adj[:, 0], adj[:, 1]
            grow_a = done[b_] & ~done[a_]
            grow_b = done[a_] & ~done[b_]
            if not (grow_a.any() or grow_b.any()):
                break
            src[a_[grow_a]] = src[b_[grow_a]]
            src[b_[grow_b]] = src[a_[grow_b]]
            done[a_[grow_a]] = True
            done[b_[grow_b]] = True
        fix = ~ok & done
        corner[fix] = src[fix][:, None, :]
    # raised rims near drawn lines take the line's color
    painted = np.zeros(len(v), bool)
    if fline.any():
        from scipy import ndimage

        x0, x1, y0, y1 = fbox
        px, py = fpx.round().astype(int), fpy.round().astype(int)
        dist = ndimage.distance_transform_edt(~fline)[py, px]
        near = dist < 0.04 * (y1 - y0)
        on_line = dist < 0.015 * (y1 - y0)  # registered, a rim sits on its line; a nose or cheek does not
        lab = relief(mesh)
        for c in np.unique(lab[lab > 0]):
            sel = (lab == c) & (t < 0.5)
            if sel.sum() >= 30 and near[sel].mean() > 0.6:
                painted |= (lab == c) & on_line
        if painted.any():
            color = np.median(raw_f[fline], 0)
            atlas[:SW, -SW:] = color
            pf = painted[f].sum(1) >= 2
            corner[pf] = np.array([(W - SW / 2) / W, 1 - (SW / 2) / hgt])
    Image.fromarray(atlas.clip(0, 255).astype(np.uint8)).save(out_png)
    m = trimesh.Trimesh(vertices=v[f].reshape(-1, 3), faces=np.arange(len(f) * 3).reshape(-1, 3), process=False)
    m.visual = trimesh.visual.TextureVisuals(uv=corner.reshape(-1, 2))
    m.merge_vertices(merge_tex=False, merge_norm=True)
    mat = trimesh.visual.material.PBRMaterial(baseColorTexture=Image.open(out_png), roughnessFactor=0.5,
                                              metallicFactor=0.0)
    m.visual = trimesh.visual.TextureVisuals(uv=m.visual.uv, material=mat)
    return m
