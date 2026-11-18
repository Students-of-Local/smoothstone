"""A part must reach the slicer closed: no non-manifold edges, no zero-area faces, at float32.

Regression: a Jensen figure passed every check on OpenSCAD's float64 mesh, and Creality Print then
reported 14 non-manifold edges on the STL that shipped (2026-11-18)."""
import numpy as np
import trimesh

from smoothstone import check, clean


def near_twin_sphere(n_edges=8, gap=1e-9):
    """A closed sphere where a few edges get a new vertex `gap` mm from one end, splitting both
    faces on that edge. Closed by index in float64; in float32 the new vertex lands on the old one
    and its faces collapse, the failure Creality Print reported."""
    b = trimesh.creation.icosphere(subdivisions=3, radius=10)
    v, f = [p for p in b.vertices], [list(x) for x in b.faces]
    done = set()
    for a, c in b.edges_unique[: n_edges * 7 : 7]:
        if a in done or c in done:
            continue
        done |= {a, c}
        v.append(b.vertices[a] + gap * (b.vertices[c] - b.vertices[a]))
        n = len(v) - 1
        for i, face in enumerate(list(f)):
            if a in face and c in face:
                k = face.index(a)
                rot = face[k:] + face[:k]  # a first, keeps winding
                if rot[1] == c:
                    f[i] = [a, n, rot[2]]; f.append([n, c, rot[2]])
                else:
                    f[i] = [a, rot[1], n]; f.append([n, rot[1], c])
    return trimesh.Trimesh(np.array(v), np.array(f), process=False), b.volume


def test_collapsed_face_fails_the_slicer_check():
    b = trimesh.creation.box((10, 10, 10))
    f = np.vstack([b.faces, [[0, 0, 1]]])  # a face with a repeated corner, as a bad union leaves
    m = trimesh.Trimesh(b.vertices, f, process=False)
    r = {x.name: x for x in check.check_mesh(m)}
    assert not r["slicer"].ok
    assert "zero-area" in r["slicer"].detail


def test_near_twin_vertices_fail_once_read_at_float32():
    m, _ = near_twin_sphere()
    assert m.is_watertight  # fine by index, the way the old check saw it
    assert clean.problems(clean.slicer_view(m.vertices, m.faces))
    r = {x.name: x for x in check.check_mesh(m)}
    assert not r["slicer"].ok


def test_for_slicer_returns_a_clean_closed_part():
    m, vol = near_twin_sphere()
    out = clean.for_slicer(m)
    assert clean.problems(clean.slicer_view(out.vertices, out.faces)) == []
    assert out.is_watertight
    assert abs(out.volume - vol) / vol < 0.01


def test_box_passes_the_slicer_check():
    r = {x.name: x for x in check.check_mesh(trimesh.creation.box((20, 20, 20)))}
    assert r["slicer"].ok
