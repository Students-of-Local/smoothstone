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
