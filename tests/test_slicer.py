"""The slicer check (slicer.py): what an FDM slicer prints wrong, found with no slicer installed."""

import numpy as np
import pytest
import trimesh

from smoothstone import printable, slicer


def _box(size, at):
    b = trimesh.creation.box(size)
    b.apply_translation(np.add(at, np.divide(size, 2)))
    return b


def _union(*parts):
    import manifold3d as m3d

    return printable.from_manifold(m3d.Manifold.batch_boolean([printable.to_manifold(p) for p in parts], m3d.OpType.Add))


def _hanging_cone():
    """A base, a post, an arm off its top, and a cone hanging point down from the arm. The cone's
    tip starts as a speck in the air and widens on itself, layer by layer, like a lock of hair."""
    base = _box((44, 20, 2), (0, 0, 0))
    post = _box((8, 8, 22), (2, 6, 2))
    arm = _box((36, 8, 4), (2, 6, 24))
    cone = trimesh.creation.cone(3.0, 8.0)
    cone.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0]))
    cone.apply_translation((30, 10, 24.5))  # flipped: the tip points down, 8 mm under the arm's top
    return _union(base, post, arm, cone)


def test_a_box_slices_cleanly():
    rep = slicer.slice_mesh(_box((10, 20, 5), (0, 0, 0)))
    assert rep.ok and not rep.problems
    assert rep.first_layer == pytest.approx(200, abs=2)
    assert rep.layers == 25


def test_a_tip_that_hangs_from_an_arm_floats():
    rep = slicer.slice_mesh(_hanging_cone())
    assert not rep.ok
    (p,) = [p for p in rep.problems if p.kind == "floating"]
    assert p.z == pytest.approx(16.5, abs=0.5) and p.where == pytest.approx((30, 10), abs=0.3)
    assert rep.floating[0]["rise"] > 4  # it hangs on itself until it reaches the arm


def test_a_piece_that_joins_on_the_next_layer_is_an_overhang_not_a_float():
    """A 60 degree slope: each layer reaches a little past the one below, and is held by it."""
    steps = [_box((2 + 0.35 * k, 12, 0.2), (0, 0, 0.2 * k)) for k in range(20)]
    rep = slicer.slice_mesh(_union(*steps))
    assert rep.ok and not [p for p in rep.problems if p.kind == "floating"]


def test_a_wide_shelf_is_a_ledge_that_warns_but_prints():
    rep = slicer.slice_mesh(_union(_box((4, 10, 10), (0, 0, 0)), _box((12, 10, 2), (0, 0, 10))))
    assert rep.ok
    assert [p.kind for p in rep.problems] == ["ledge"]


def test_a_fin_thinner_than_a_line_is_dropped():
    rep = slicer.slice_mesh(_union(_box((10, 10, 4), (0, 0, 0)), _box((0.1, 8, 4), (12, 1, 0))))
    assert rep.dropped > 1.0


def test_a_mesh_with_a_hole_does_not_close():
    b = _box((10, 10, 10), (0, 0, 0))
    b.update_faces(np.arange(len(b.faces)) != 0)
    rep = slicer.slice_mesh(b)
    assert not rep.ok and "open" in {p.kind for p in rep.problems}


def test_brace_holds_up_a_tip_that_starts_as_a_speck():
    """Every round 6 figure of the random five sliced with pieces in the air: a lock of hair or a
    fingertip starts thinner than brace's 0.25 mm grid sees and widens on itself. Brace takes them
    from the slicer check, so the braced part slices cleanly (the owner: they need to be PRINTABLE)."""
    mesh = _hanging_cone()
    braced, struts, left, cut = printable.brace(mesh, rounds=3)
    assert struts or cut
    assert slicer.slice_mesh(braced).ok


def test_no_strut_holds_up_a_spot_on_the_face():
    """A strut under the brow ran down across Christopher Abbott's face to his shoulder (random five,
    slice check). A spot on the face gets no strut; brace cuts it back instead."""
    grid = printable.occupancy(_hanging_cone())
    k = 72  # 18 mm up: the cone, 2 mm above its tip
    cells = np.argwhere(grid.occ[:, :, k])
    cells = cells[np.linalg.norm(grid.xy(cells) - [30, 10], axis=1) < 3]
    isl = printable.Island(18.0, len(cells) * grid.pitch ** 2, 30.0, 10.0, cells, k)
    struts, missed = printable.plan_struts(grid, [isl])
    assert struts and not missed
    struts, missed = printable.plan_struts(grid, [isl], keep_off=lambda q: q[2] > 17)
    assert not struts and missed == [isl]


def test_a_lifted_figure_braced_slices_cleanly(tmp_path):
    """Lamine Yamal's round 6 figure (random five), decimated to 14k faces: braced on main, a piece
    by his hand still started in mid air at a slicer's resolution, though stone's own checks passed
    it. The owner: they also need to be PRINTABLE."""
    import gzip
    from pathlib import Path

    src = tmp_path / "figure.stl"
    src.write_bytes(gzip.decompress((Path(__file__).parent / "fixtures" / "lamine_round6_figure.stl.gz").read_bytes()))
    params = {"height": 90, "name": "LAMINE"}
    printable.brace_figure(src, tmp_path / "braced.stl", params)
    braced = trimesh.load(tmp_path / "braced.stl", force="mesh")
    braced.apply_scale(printable.plinth(params)[0])
    rep = slicer.slice_mesh(braced)
    assert rep.ok, slicer.summary(rep)


def test_a_part_far_bigger_than_the_bed_stops_at_size():
    """A figure exported in microns is 1000 times too big; slicing it would run out of memory."""
    import time

    t = time.process_time()
    rep = slicer.slice_mesh(_box((90000, 40000, 90000), (0, 0, 0)))
    assert time.process_time() - t < 1.0
    assert not rep.ok and [p.kind for p in rep.problems] == ["size"] and rep.floating == []


def test_slice_json_prints_only_json(tmp_path, capsys):
    import json

    from smoothstone import cli

    f = tmp_path / "box.stl"
    _box((10, 20, 5), (0, 0, 0)).export(f)
    cli.main(["slice", str(f), "--json"])
    assert json.loads(capsys.readouterr().out)["ok"] is True
