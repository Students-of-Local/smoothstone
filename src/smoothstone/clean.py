"""Make a built mesh safe for a slicer, and measure it the way a slicer reads it.

OpenSCAD's exact mesh is watertight in float64, but an STL stores float32. Vertices that differ by
less than float32 can resolve merge into one point, faces collapse, and the slicer then reports
non-manifold edges (Creality Print showed 14 on a figure our own check had passed). So the part is
rebuilt through manifold3d, which keeps it a closed 2-manifold at float32, and every check runs on
the STL exactly as it will be shipped.
"""
from __future__ import annotations

import numpy as np

ZERO_AREA = 1e-9  # mm2: a face this small is dropped by a slicer's repair, opening its edges


def slicer_view(vertices, faces) -> dict:
    """Read a mesh as a slicer does: float32 coordinates, vertices merged by exact position,
    faces with a repeated corner dropped. Returns the counts that make a slicer complain."""
    v = np.asarray(vertices, dtype=np.float32).astype(np.float64)
    uniq, inv = np.unique(v, axis=0, return_inverse=True)
    f = inv.reshape(-1)[np.asarray(faces, dtype=np.int64)]
    collapsed = (f[:, 0] == f[:, 1]) | (f[:, 1] == f[:, 2]) | (f[:, 0] == f[:, 2])
    f = f[~collapsed]
    p = uniq[f]
    area = np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1) / 2
    edges = np.sort(np.vstack([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return {
        "collapsed": int(collapsed.sum()),
        "zero_area": int((area <= ZERO_AREA).sum()),
        "bad_edges": int((counts != 2).sum()),
    }


def for_slicer(mesh, tolerance: float = 0.01):
    """Return the mesh rebuilt as a float32 2-manifold, with edges under `tolerance` mm collapsed
    (well below a 0.4 mm nozzle line). Raises ValueError when the mesh cannot be made manifold, or
    when three quadric passes still leave non-manifold edges or zero-area faces."""
    import fast_simplification
    import manifold3d as m3
    import trimesh

    def rebuild(v, f):
        g = m3.Mesh(vert_properties=np.asarray(v, dtype=np.float32), tri_verts=np.asarray(f, dtype=np.uint32))
        g.merge()
        man = m3.Manifold(g)
        if man.status() != m3.Error.NoError:
            raise ValueError(f"not a closed manifold: {man.status().name}")
        if tolerance:
            man = man.simplify(tolerance)
        o = man.to_mesh()
        return np.asarray(o.vert_properties[:, :3], dtype=np.float64), np.asarray(o.tri_verts, dtype=np.int64)

    v, f = rebuild(mesh.vertices, mesh.faces)
    # manifold3d keeps a sliver it cannot collapse now and then; a light quadric pass removes it
    for reduction in (0.02, 0.05, 0.1):
        if not problems(slicer_view(v, f)):
            break
        v2, f2 = fast_simplification.simplify(v.astype(np.float32), f.astype(np.int32), target_reduction=reduction)
        v, f = rebuild(v2, f2)
    left = problems(slicer_view(v, f))
    if left:  # never hand a slicer a part it will complain about
        raise ValueError("still " + " and ".join(left) + " after three repair passes")
    return trimesh.Trimesh(v, f, process=False)


def problems(view: dict) -> list[str]:
    bad = []
    if view["bad_edges"]:
        bad.append(f"{view['bad_edges']} non-manifold edges")
    if view["collapsed"] or view["zero_area"]:
        bad.append(f"{view['collapsed'] + view['zero_area']} zero-area faces")
    return bad


def cut_iso(V, F, s, level, snap=0.02, fields=None, parents=False, slope=None):
    """Cut a closed triangle mesh along the level set s == level, so a color boundary can run on a
    clean line instead of zigzagging along triangle edges.

    s is one value per vertex. Every edge whose ends sit strictly on opposite sides gets one new
    vertex, shared by both faces on that edge, so the mesh stays watertight; the new vertex lies on
    the edge, so the shape and volume do not change. Vertices within `snap` mm of the level count
    as on it, so no sliver faces are made. That distance is the value over the steepest slope of s
    along the vertex's edges: a snap in units of s would take in a wide band of vertices where s
    changes slowly, and the line would step along triangle edges there. `fields` (one row per
    vertex) are interpolated onto the new vertices. Returns (V, F), then fields when given, then
    (with parents=True) the input face each output face came from. `slope` (one value per vertex,
    default s) is the field whose slope sets that distance: give the true field when s is held at
    a constant outside a zone, or the jump at the zone's rim makes the slope steep there and
    vertices well off the line count as on it."""
    V = np.asarray(V, float)
    F = np.asarray(F, np.int64)
    d = np.asarray(s, float) - level
    t = d if slope is None else np.asarray(slope, float)
    E = np.vstack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    rate = np.abs(t[E[:, 0]] - t[E[:, 1]]) / np.maximum(np.linalg.norm(V[E[:, 0]] - V[E[:, 1]], axis=1), 1e-12)
    g = np.zeros(len(V))
    np.maximum.at(g, E[:, 0], rate)
    np.maximum.at(g, E[:, 1], rate)
    side = np.where(np.abs(d) <= snap * g, 0, np.sign(d)).astype(int)
    new_v: list[np.ndarray] = []
    new_w: list[tuple[int, int, float]] = []
    key: dict[tuple[int, int], int] = {}
    n0 = len(V)

    def P(i):
        return V[i] if i < n0 else new_v[i - n0]

    def mid(a, b):
        k = (a, b) if a < b else (b, a)
        if k not in key:
            i, j = k
            t = d[i] / (d[i] - d[j])
            key[k] = n0 + len(new_v)
            new_v.append(V[i] + t * (V[j] - V[i]))
            new_w.append((i, j, t))
        return key[k]

    sf = side[F]
    cross = ((sf == 1).any(1)) & ((sf == -1).any(1))
    out = [F[~cross]]
    par = [np.where(~cross)[0]]
    for fi, f in zip(np.where(cross)[0], F[cross]):
        a, b, c = (int(x) for x in f)
        sa, sb, sc = side[a], side[b], side[c]
        for _ in range(3):  # turn the face until the odd corner is first; winding is kept
            if sa == 0 and sb * sc < 0:  # the line passes through a and crosses bc
                m = mid(b, c)
                out.append(np.array([[a, b, m], [a, m, c]]))
                par.append(np.full(2, fi))
                break
            if sa != 0 and sb != 0 and sc != 0 and sb == sc and sa != sb:  # a alone on its side
                m1, m2 = mid(a, b), mid(a, c)
                tri = [[a, m1, m2]]
                if np.linalg.norm(P(m1) - P(c)) < np.linalg.norm(P(b) - P(m2)):  # shorter diagonal
                    tri += [[m1, b, c], [m1, c, m2]]
                else:
                    tri += [[m1, b, m2], [b, c, m2]]
                out.append(np.array(tri))
                par.append(np.full(3, fi))
                break
            a, b, c = b, c, a
            sa, sb, sc = sb, sc, sa
        else:
            out.append(np.array([[a, b, c]]))
            par.append(np.full(1, fi))
    V2 = np.vstack([V, np.array(new_v).reshape(-1, 3)])
    F2 = np.vstack(out)
    res = [V2, F2]
    if fields is not None:
        fields = np.asarray(fields, float)
        if new_w:
            i, j, t = (np.array(x) for x in zip(*new_w))
            tt = t.reshape((-1,) + (1,) * (fields.ndim - 1))
            fields = np.concatenate([fields, fields[i] + tt * (fields[j] - fields[i])])
        res.append(fields)
    if parents:
        res.append(np.concatenate(par))
    return tuple(res)
