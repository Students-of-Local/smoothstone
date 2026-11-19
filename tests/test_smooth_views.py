"""Smooth shading in the views the blind judge reads (r1: a lit facet read as a paint notch)."""

import numpy as np
import trimesh
from PIL import Image

from smoothstone import colors as C


def _sphere():
    return trimesh.creation.icosphere(subdivisions=2, radius=10.0)


def test_corner_normals_follow_the_faces_own_order():
    """trimesh's smooth_shade reorders faces on real meshes; ours must not."""
    m = _sphere()
    perm = np.random.default_rng(3).permutation(len(m.faces))
    a = C.corner_normals(m.vertices, m.faces)
    b = C.corner_normals(m.vertices, m.faces[perm])
    assert np.allclose(a[perm], b)
    radial = m.vertices[m.faces] / np.linalg.norm(m.vertices[m.faces], axis=2, keepdims=True)
    assert (np.sum(a * radial, axis=2) > 0.99).all()


def test_a_real_fold_stays_sharp():
    box = trimesh.creation.box((10, 10, 10))
    cn = C.corner_normals(box.vertices, box.faces)
    assert np.allclose(cn, box.face_normals[:, None, :].repeat(3, 1))


def _steps(img: np.ndarray, mask: np.ndarray) -> float:
    """The largest brightness jump between neighbor pixels inside the mask (away from its rim)."""
    from scipy import ndimage

    inner = ndimage.binary_erosion(mask, iterations=4)
    g = img.mean(2)
    dx = np.abs(np.diff(g, axis=1))[inner[:, 1:] & inner[:, :-1]]
    dy = np.abs(np.diff(g, axis=0))[inner[1:, :] & inner[:-1, :]]
    return float(max(dx.max(), dy.max()))


def test_one_color_surface_has_no_lit_facets(tmp_path):
    """A coarse sphere in one color: flat shading makes a step at every facet edge, the kind the
    judge called a "light notch". The views must read it as one smooth surface."""
    m = _sphere()
    rgb = np.full((len(m.faces), 3), 225.0)
    out = tmp_path / "v.png"
    C.render(m, rgb, out, views=(("front", 0.3, 0.2),), px=300)
    img = np.asarray(Image.open(out).convert("RGB"), float)
    body = np.abs(img - 136).sum(2) > 6  # not the gray background
    body[:30] = False  # the title
    assert _steps(img, body) < 6, "a facet edge shows as a step in the light"


def test_a_paint_edge_stays_sharp(tmp_path):
    """Smoothing is for the light only: a color edge still jumps at once."""
    m = _sphere()
    top = m.triangles_center[:, 2] > 0
    rgb = np.where(top[:, None], [[30.0, 30, 30]], [[225.0, 225, 225]])
    out = tmp_path / "v.png"
    C.render(m, rgb, out, views=(("front", 0.0, 0.0),), px=300)
    img = np.asarray(Image.open(out).convert("RGB"), float)
    col = img[:, img.shape[1] // 2].mean(1)
    assert np.abs(np.diff(col[60:-60])).max() > 60


def test_a_sub_nozzle_crease_like_the_r1_fist_corner_is_blended():
    """r1's "light notch" was a 49.7 degree crease in the sculpt, 0.17 mm across: too small to
    print, so it must not light up as an edge."""
    t = np.radians(50)
    v = np.array([[0, 0, 0], [0, 1, 0], [1, 0, 0], [1, 1, 0],
                  [1 + np.cos(t), 0, np.sin(t)], [1 + np.cos(t), 1, np.sin(t)]], float)
    f = np.array([[0, 2, 1], [1, 2, 3], [2, 4, 3], [3, 4, 5]])
    cn = C.corner_normals(v, f)
    at_bend = cn[1, 1]  # face 1's corner at vertex 2, on the bend
    assert np.allclose(at_bend, cn[2, 0]), "both faces at the bend share one normal"
