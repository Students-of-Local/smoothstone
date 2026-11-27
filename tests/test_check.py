import time

import numpy as np
import pytest
import trimesh

from smoothstone import check, recipes


def on_bed(mesh):
    mesh.apply_translation((0, 0, -mesh.bounds[0][2]))
    return mesh


def by_name(results):
    return {r.name: r for r in results}


def box(x, y, z):
    return on_bed(trimesh.creation.box((x, y, z)))


def t_shape():
    # T profile in XY, extruded along Z, then stood up so the stem is on the bed
    v = np.array([
        [-3, 0], [3, 0], [3, 20], [-3, 20],          # stem 0..3
        [-20, 20], [20, 20], [20, 24], [-20, 24],    # bar 4..7
    ], float)
    f = np.array([
        [0, 1, 2], [0, 2, 3],
        [7, 4, 3], [7, 3, 2], [7, 2, 5], [7, 5, 6],
    ])
    m = trimesh.creation.extrude_triangulation(v, f, 20)
    m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (1, 0, 0)))
    return on_bed(m)


def test_box_passes():
    res = check.check_mesh(box(20, 20, 10))
    assert check.passed(res), [r for r in res if not r.ok]
    assert by_name(res)["min_wall"].value == pytest.approx(10, abs=0.1)


def test_two_boxes_fail_bodies():
    a = box(10, 10, 10)
    b = box(10, 10, 10)
    b.apply_translation((30, 0, 0))
    res = by_name(check.check_mesh(trimesh.util.concatenate([a, b])))
    assert not res["bodies"].ok
    assert res["bodies"].value == 2


def test_floating_box_fails_resting():
    m = box(20, 20, 10)
    m.apply_translation((0, 0, 5))
    res = by_name(check.check_mesh(m))
    assert not res["resting"].ok
    assert "5.00" in res["resting"].detail


def test_thin_plate_fails_wall():
    res = by_name(check.check_mesh(box(30, 30, 0.4)))
    assert not res["min_wall"].ok
    assert res["min_wall"].value == pytest.approx(0.4, abs=0.05)


def case_shell(wall=3.2, win_h=10, win_z=5):
    """The case recipe's own geometry, made with trimesh: 80x60x30 shell, open top, one window cut.

    The window's bottom face is a 3.2 mm deep sill ledge. It is a step, not a wall.
    """
    from trimesh.creation import box
    outer = box((80, 60, 30))
    outer.apply_translation((0, 0, 15))
    cavity = box((80 - 2 * wall, 60 - 2 * wall, 30 - wall))
    cavity.apply_translation((0, 0, wall + (30 - wall) / 2))
    shell = outer.difference(cavity)
    cut = box((50, 90, win_h))
    cut.apply_translation((0, 0, wall + win_z + win_h / 2))
    return on_bed(shell.difference(cut))


def test_window_sill_is_not_a_wall():
    res = by_name(check.check_mesh(case_shell(wall=3.2)))
    assert res["min_wall"].ok
    assert res["min_wall"].value == pytest.approx(3.2, abs=0.2)


def test_post_boss_face_is_still_reported(openscad, tmp_path):
    # the real recipe with posts but no window/port: the post's front face sits 1.698 mm off the
    # inner back wall. It is a distinct surface, so the step rule must not hide it.
    from smoothstone import scad
    from pathlib import Path
    r = recipes._load_one(Path(__file__).resolve().parent.parent / "recipes" / "case")
    assert r is not None
    params = r.merged({"win_w": 0, "win_h": 0, "port_w": 0})
    out = tmp_path / "case.off"
    assert scad.build_stl(openscad, r, params, out).ok
    res = by_name(check.check_stl(out, recipe=r, params=params))
    assert res["min_wall"].value == pytest.approx(1.7, abs=0.1)


def test_genuine_thin_wall_with_a_window_still_fails():
    res = by_name(check.check_mesh(case_shell(wall=0.8, win_h=8)))
    assert not res["min_wall"].ok
    assert res["min_wall"].value == pytest.approx(0.8, abs=0.2)


def test_t_shape_fails_overhang():
    m = t_shape()
    res = by_name(check.check_mesh(m))
    assert res["watertight"].ok and res["bodies"].ok
    assert not res["overhang"].ok
    assert res["overhang"].value > 0.05


def test_chamfer_at_45_degrees_passes_overhang():
    # a downward 45 degree face must not count
    v = np.array([[-10, 0], [10, 0], [20, 10], [-20, 10]], float)
    f = np.array([[0, 1, 2], [0, 2, 3]])
    m = trimesh.creation.extrude_triangulation(v, f, 20)
    m.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, (1, 0, 0)))
    res = by_name(check.check_mesh(on_bed(m)))
    assert res["overhang"].ok, res["overhang"].detail


def test_bed_from_settings():
    res = by_name(check.check_mesh(box(300, 20, 10)))
    assert not res["bed"].ok
    res = by_name(check.check_mesh(box(300, 20, 10), bed=(350, 350, 350)))
    assert res["bed"].ok


def test_dims_against_recipe(recipes_root):
    r = recipes.load("_demo", recipes_root)
    res = by_name(check.check_mesh(box(60, 40, 4), recipe=r, params={}))
    assert res["dims"].ok
    res = by_name(check.check_mesh(box(60, 40, 4), recipe=r, params={"w": 50}))
    assert not res["dims"].ok
    assert "x 60.0 mm, expected 50.0 mm" in res["dims"].detail


def test_check_stl_bad_file(tmp_path):
    f = tmp_path / "junk.stl"
    f.write_text("not a mesh")
    res = check.check_stl(f)
    assert not res[0].ok and res[0].name == "loads"


@pytest.mark.timing
def test_fast_on_200k_faces():
    m = trimesh.creation.icosphere(subdivisions=7, radius=20)  # 327,680 faces
    m = on_bed(trimesh.Trimesh(m.vertices, m.faces))
    t = time.perf_counter()
    check.check_mesh(m)
    # 3 s before check_mesh sliced every layer (slicer.py, PR 56); the slicer adds about 1.5 s here
    # and CI's runner took 4.1 s, so the budget is 6 s
    assert time.perf_counter() - t < 6.0


def test_format_lines_one_per_check():
    res = check.check_mesh(box(30, 30, 0.4))
    lines = check.format_results(res, fix_line=lambda r: "set h=1.2" if r.name == "min_wall" else None)
    assert len(lines) == len(res)
    fix = [ln for ln in lines if ln.startswith("FIX: ")]
    assert fix == [l for l in lines if "min_wall" in l]
    assert fix[0].endswith("set h=1.2")


def test_safe_eval():
    assert recipes.safe_eval("w + 2*t", {"w": 10, "t": 1.5}) == 13
    assert recipes.safe_eval("max(a, b) - abs(-1)", {"a": 3, "b": 5}) == 4
    assert recipes.safe_eval("w + (4 if lip else 0)", {"w": 1, "lip": True}) == 5
    for bad in ("__import__('os')", "w.real", "open('x')", "[1, 2]", "lambda: 1"):
        with pytest.raises(ValueError):
            recipes.safe_eval(bad, {"w": 1})



def test_a_bead_hanging_under_a_shelf_fails_islands():
    # a post, a shelf off its top, and a bead hanging under the shelf's far end: the bead's
    # bottom layer has nothing under it
    post = trimesh.creation.box((6, 6, 30))
    post.apply_translation((0, 0, 15))
    shelf = trimesh.creation.box((30, 6, 3))
    shelf.apply_translation((12, 0, 28.5))
    bead = trimesh.creation.box((4, 4, 6))
    bead.apply_translation((24, 0, 24))
    m = on_bed(trimesh.boolean.union([post, shelf, bead], engine="manifold"))
    res = by_name(check.check_mesh(m))
    assert not res["islands"].ok and res["islands"].value == 1, res["islands"]
    assert "21.0 mm up" in res["islands"].detail, res["islands"].detail


def test_a_box_stands_on_every_layer_and_does_not_tip():
    res = by_name(check.check_mesh(box(20, 20, 10)))
    assert res["islands"].ok and res["islands"].value == 0
    assert res["tipping"].ok and res["tipping"].value > 60


def test_a_leaning_tower_fails_tipping():
    m = box(6, 6, 60)
    shear = np.eye(4)
    shear[0, 2] = 0.5  # the top sits 30 mm over, far past a 6 mm foot
    m.apply_transform(shear)
    res = by_name(check.check_mesh(on_bed(m)))
    assert not res["tipping"].ok and res["tipping"].value == 0, res["tipping"]
