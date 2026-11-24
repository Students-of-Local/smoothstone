"""stone strength: words parse, checks run along and between layers, the command reports and points on."""

import json
import shlex

import numpy as np
import trimesh
from PIL import Image

from smoothstone import strength
from test_cli import stone


def beam(path=None):
    """100 x 10 x 10 mm bar lying along x."""
    m = trimesh.creation.box(extents=[100, 10, 10])
    m.apply_translation([50, 5, 5])
    if path:
        m.export(path)
    return m


def test_words_parse_with_units_and_say_what_is_wrong():
    case, file, bad = strength.parse(["load=2kg", "at=tip", "dir=-y", "fixed=holes+bottom", "material=petg cf", "walls=3",
                                      "orient=x", "part.stl"])
    assert not bad and abs(case.load - 2 * 9.80665) < 1e-9 and case.dir == (1, -1)
    assert case.material == "PETG-CF" and case.walls == 3 and case.build == 0 and file.name == "part.stl"
    assert strength.parse(["load=5lb", "dir=down"])[0].dir == (2, -1)
    _, _, bad = strength.parse(["load=heavy", "at=nose", "colour=red"])
    assert len(bad) == 3 and "20N" in bad[0] and "tip" in bad[1] and "not a strength word" in bad[2]
    assert strength.parse(["at=tip"])[2] == ["load: give the load, like load=20N or load=2kg"]


def test_solid_cantilever_matches_hand_numbers():
    """Solid PLA bar, 10 N at the far end: stress 6PL/bh^2 = 6 MPa, safety factor 35 / 6, tip PL^3/3EI + shear."""
    case = strength.parse(["load=10N", "at=right", "dir=down", "fixed=left", "infill=100", "sag=100"])[0]
    p = strength.material("PLA")
    st, res = strength.solve(beam(), case, p, 33_750)  # 2/3 mm cells, a whole number across the bar
    assert res.mode == "along" and abs(res.sf / (p.s_xy / 6) - 1) < 0.05, (res.sf, res.stress)
    i, g = 10 * 10 ** 3 / 12, p.e_xy / (2 * (1 + strength.NU))
    theory = 10 * 100 ** 3 / (3 * p.e_xy * i) + 10 * 100 / (5 / 6 * g * 100)
    assert abs(res.deflection / theory - 1) < 0.15, (res.deflection, theory)


def test_a_beam_printed_standing_up_fails_between_layers():
    case = strength.parse(["load=10N", "at=right", "dir=down", "fixed=left", "material=PETG", "sag=100"])[0]
    p = strength.material("PETG")
    flat = strength.solve(beam(), case, p, 20_000)[1]
    case.build = 0  # the bar's long axis points up on the bed: bending pulls the layers apart
    standing = strength.solve(beam(), case, p, 20_000)[1]
    assert flat.mode == "along" and standing.mode == "layers", (flat.mode, standing.mode)
    assert standing.sf < flat.sf


def test_holes_are_found_and_held():
    plate = trimesh.creation.box(extents=[60, 30, 5])
    for x in (-15, 15):
        plate = plate.difference(trimesh.creation.cylinder(radius=2.1, height=20, sections=48).apply_translation([x, 0, 0]))
    case = strength.parse(["load=5N", "at=right", "dir=down", "fixed=holes"])[0]
    st = strength.setup(plate, case, strength.material("PLA"), 30_000)
    held = st.model.coords[st.fixed]
    r = np.minimum(np.hypot(held[:, 0] + 15, held[:, 1]), np.hypot(held[:, 0] - 15, held[:, 1]))
    assert len(held) > 50 and r.max() < 2.1 + 2 * st.grid.pitch, r.max()
    assert st.held == "the 2 holes at (-15, 0, 0), (15, 0, 0)"


def test_a_thin_bar_at_the_default_cells_reads_its_surface_stress():
    m = trimesh.creation.box(extents=[100, 20, 2])  # 3 N at 100 mm: 6PL/bh^2 = 22.5 MPa at the root
    case = strength.parse(["load=3N", "at=right", "dir=down", "fixed=left", "infill=100", "sag=100"])[0]
    p = strength.material("PLA")
    _, res = strength.solve(m, case, p)
    assert not res.thin and abs(res.sf / (p.s_xy / 22.5) - 1) < 0.10, (res.sf, res.stress)


def test_a_wall_under_three_cells_is_never_called_fine(jobenv, monkeypatch):
    monkeypatch.setattr(strength, "VOXELS", 6_000)
    monkeypatch.setattr(strength, "REFINE", 7_000)
    trimesh.creation.box(extents=[100, 100, 2]).export(jobenv / "plate.stl")
    text, code, nxt = stone("strength", str(jobenv / "plate.stl"), "load=1N", "at=right", "dir=down", "fixed=left")
    assert "not sure, the loaded spot is under 3 cells" in text and ": fine" not in text, text
    assert nxt.startswith("stone strength ") and "voxels=400000" in nxt, nxt


def test_walls_do_not_thicken_the_top_and_bottom():
    """A flat shelf bent through its layers: walls=6 adds perimeters only, so it gains little."""
    shelf = trimesh.creation.box(extents=[100, 60, 10])
    case = strength.parse(["load=20N", "at=right", "dir=down", "fixed=left", "sag=100"])[0]
    p = strength.material("PLA")
    two = strength.solve(shelf, case, p, 40_000)[1]
    case.walls = 6
    six = strength.solve(shelf, case, p, 40_000)[1]
    assert six.deflection > 0.8 * two.deflection, (two.deflection, six.deflection)


def test_a_load_on_the_hold_is_refused(jobenv, monkeypatch):
    monkeypatch.setattr(strength, "VOXELS", 10_000)
    beam(jobenv / "bar.stl")
    for words in (["at=bottom"], ["at=top", "fixed=top"], ["at=50,5,10", "fixed=0,0,0,100,10,10"]):
        text, code, nxt = stone("strength", str(jobenv / "bar.stl"), "load=20N", *words)
        assert code == 1 and "sits on the held place" in text and "Safety factor" not in text, text
        assert nxt.startswith("ask the person: "), nxt


def test_each_held_place_must_hold_something():
    p, m = strength.material("PLA"), beam()
    for fixed, want in (("holes+left", "fixed=holes"), ("500,500,500,501,501,501", "nothing to hold"),
                        ("0,0,0,0.1,0.1,0.1", "turning")):
        st, res = strength.solve(m, strength.parse(["load=5N", "at=right", f"fixed={fixed}"])[0], p, 8_000)
        assert res is None and want in st.problem, (fixed, st.problem)


def test_a_loose_piece_is_not_held_by_another():
    two = trimesh.util.concatenate([beam(), beam().apply_translation([0, 30, 0])])
    case = strength.parse(["load=5N", "at=100,35,5", "fixed=0,0,0,1,10,10"])[0]
    st, res = strength.solve(two, case, strength.material("PLA"), 10_000)
    assert res is None and "turning" in st.problem, st.problem


def test_engraving_and_slots_are_not_holes():
    from smoothstone import fea

    solid = np.ones((40, 60, 10), bool)
    solid[5:9, 5:9, :] = False  # a through hole, 2 mm
    solid[20:24, 5:9, 9:] = False  # 0.5 mm deep engraving
    solid[30:36, 10:50, :] = False  # a 3 x 20 mm slot
    cells = strength.hole_cells(fea.Grid(solid, 0.5, np.zeros(3)))
    assert cells[6, 6, 5] and not cells[21, 6, 9] and not cells[32, 30, 5]


def test_layers_that_slide_apart_count():
    """A short peg standing on the bed, pushed sideways: shear across layers governs, not the along check."""
    peg = trimesh.creation.box(extents=[10, 10, 6]).apply_translation([0, 0, 3])
    case = strength.parse(["load=200N", "at=top", "dir=right", "fixed=bottom", "infill=100", "sag=100"])[0]
    p = strength.material("PLA")
    res = strength.solve(peg, case, p, 20_000)[1]
    assert res.mode == "layers" and res.stress["across_layers_mpa"] > 3 ** 0.5 * 200 / 100, res.stress


def test_a_center_load_is_read_on_the_far_side():
    bar = trimesh.creation.box(extents=[100, 10, 3])
    case = strength.parse(["load=10N", "at=top", "dir=down", "fixed=left+right", "infill=100", "sag=100"])[0]
    st, res = strength.solve(bar, case, strength.material("PLA"), 30_000)
    c = st.grid.centers()
    under = np.argmin(np.linalg.norm(c - [0, 0, -1.5], axis=1))
    assert res.ratio[under] > 0.5 * res.ratio.max()


def test_thickening_adds_cells_outside_but_never_on_the_hold():
    m, p = beam(), strength.material("PLA")
    case = strength.parse(["load=5N", "at=right", "dir=down", "fixed=left"])[0]
    base = strength.setup(m, case, p, 8_000)
    big = strength.setup(m, case, p, 8_000, (np.array([2.0, 5.0, 10.0]), 10.0, 1.0))
    assert big.grid.solid.sum() > base.grid.solid.sum()
    assert np.allclose(np.sort(big.model.coords[big.fixed], 0), np.sort(base.model.coords[base.fixed], 0))
    assert big.model.coords[:, 0].min() > -1e-6  # nothing past the held face


def test_shown_rounds_down():
    assert strength.shown(1.96) == 1.9 and strength.shown(0.97) == 0.9 and strength.shown(2.0) == 2.0
    assert strength.shown(1e12) == 99


def test_bad_numbers_say_so():
    for word in ("fixed=a,b,c", "sag=-2", "sag=0", "orient=", "walls=21", "infill=0", "voxels=1e400"):
        assert strength.parse(["load=5N", word])[2], word


def test_stone_strength_reports_and_writes_its_files(jobenv, monkeypatch):
    monkeypatch.setattr(strength, "VOXELS", 15_000)
    beam(jobenv / "bar.stl")
    text, code, nxt = stone("strength", str(jobenv / "bar.stl"), "load=5N", "at=right", "dir=down", "fixed=left")
    assert code == 0 and "Safety factor" in text and "Deflection" in text and "99.5th percentile" in text, text
    d = json.loads((jobenv / "strength.json").read_text())
    assert d["safety_factor"] > 2 and d["inputs"]["material"] == "PLA" and d["advice"] and d["assumptions"]
    assert nxt == "none, the part holds"
    img = np.asarray(Image.open(jobenv / "strength.png").convert("RGB"))
    assert "strength.png" in text and (img == 0).all(-1).sum() > 100  # the ring
    text, code, nxt = stone("strength", str(jobenv / "bar.stl"), "load=400N", "at=right", "dir=down", "fixed=left")
    assert "fails" in text and (nxt.startswith("stone strength ") or nxt.startswith("ask the person: ")), text
    text, code, nxt = stone("strength", str(jobenv / "bar.stl"), "load=15N", "at=right", "dir=down", "fixed=left",
                            "sag=100", "material=petg cf")
    assert nxt.startswith("stone strength ") and shlex.split(nxt)[2] == str(jobenv / "bar.stl"), (text, nxt)
    assert "material=petg cf" in shlex.split(nxt) or "material=" in nxt
    text, code, nxt = stone(*shlex.split(nxt)[1:])  # the advised command runs, and says what it depends on
    assert "bar.stl" in text and "Safety factor" in text, text
    assert "tell the person" in text and nxt.startswith("ask the person: it holds 15 N only printed with"), (text, nxt)
    text, code, nxt = stone("strength", "load=lots")
    assert code == 1 and "FIX: " in text and nxt.startswith("stone strength load=<")
    text, code, nxt = stone("strength", "bar.stl", "load=20N", "at=nose", "dir=-y", "fixed=holes")
    assert code == 1 and "bar.stl load=20N dir=-y fixed=holes at=<" in nxt, nxt  # only the bad word is asked again
    text, code, nxt = stone("strength", "gone.stl", "load=3N", "at=right")
    assert code == 1 and "no file" in text and nxt.startswith("ask the person: ") and "gone.stl load=3N at=right" in nxt, nxt


def test_nothing_held_says_so(jobenv, monkeypatch):
    monkeypatch.setattr(strength, "VOXELS", 10_000)
    beam(jobenv / "bar.stl")
    text, code, nxt = stone("strength", str(jobenv / "bar.stl"), "load=10N", "at=right", "fixed=top")
    assert "Safety factor" in text, text
    text, code, nxt = stone("strength", str(jobenv / "bar.stl"), "load=10N", "at=right", "fixed=1000,1000,1000,1001,1001,1001", "walls=4")
    assert code == 1 and "FIX: found nothing to hold" in text and nxt.startswith("ask the person: what holds"), text
    assert "bar.stl load=10N walls=4 at=<" in nxt and "fixed=<" in nxt, nxt
    text, code, nxt = stone("strength", str(jobenv / "bar.stl"), "load=10N", "at=100,5,200", "fixed=left")
    assert code == 1 and "190 mm off the part" in text, text


def test_an_open_mesh_is_refused(jobenv):
    m = beam()
    m.update_faces(np.arange(len(m.faces)) > 0)
    m.export(jobenv / "open.stl")
    text, code, nxt = stone("strength", str(jobenv / "open.stl"), "load=10N")
    assert code == 1 and "not a closed shape" in text and "open.stl load=10N" in nxt, (text, nxt)


def test_a_filament_with_no_data_is_asked_about_and_stays_named(jobenv, monkeypatch):
    from smoothstone import cli

    monkeypatch.setattr(strength, "VOXELS", 10_000)
    job, words = cli.Job(jobenv / "stone-job"), ["load=5N", "at=right", "dir=down", "fixed=left"]
    job.create("a bar")
    job.build_dir.mkdir(parents=True, exist_ok=True)
    beam(job.build_dir / "part.stl")
    out = cli.Out()
    strength.report(job, words, out, "PVB")
    assert out.code == 1 and "PVB" in out.next and "material=<" in out.next and "load=5N" in out.next, out.next
    out = cli.Out()
    strength.report(job, [*words, "material=PLA"], out, "PVB")
    assert "print with PLA; tell the person" in " ".join(out.lines), out.lines


def test_a_thin_tab_the_cells_miss_is_never_called_fine():
    block = trimesh.creation.box(extents=[100, 100, 50])
    tab = trimesh.creation.box(extents=[20, 20, 1]).apply_translation([59.9, 0, 2.2])
    case = strength.parse(["load=5N", "at=right", "dir=down", "fixed=left"])[0]
    p = strength.material("PLA")
    st, res = strength.solve(block.union(tab), case, p, 5_000)
    assert st.lost and res.thin and "thinner than this model's cells" in strength.verdict(st, res, case, p)[0]
    assert not strength.setup(block, case, p, 5_000).lost


def test_a_whole_number_of_cells_stays_whole():
    from smoothstone import fea

    for side in (2.1, 4.2, 4.3):  # side / (side / 7) is a hair over 7 for each
        grid = fea.voxelize(trimesh.creation.box(extents=[40, 40, side]), side / 7)
        assert grid.shape[2] == 7 and grid.solid.any((0, 1)).sum() == 7, side


def test_a_slender_post_pushed_toward_its_hold_buckles():
    """3 x 3 x 100 mm PLA post on the bed: pi^2 E I / (2L)^2 is under 2 N in any PLA, far under what crushes it."""
    post = trimesh.creation.box(extents=[3, 3, 100]).apply_translation([0, 0, 50])
    p = strength.material("PLA")
    case = strength.parse(["load=20N", "at=top", "dir=down", "fixed=bottom", "infill=100"])[0]
    st, res = strength.solve(post, case, p, 30_000)
    euler = np.pi ** 2 * p.e_z * 3 ** 4 / 12 / (4 * 100 ** 2) / 20
    assert res.mode == "buckle" and res.sf < 1 and abs(res.buckle / euler - 1) < 0.05, (res.mode, res.buckle, euler)
    assert "buckles" in strength.verdict(st, res, case, p)[0]
    case.dir = (2, 1)  # pulled, not pushed
    assert strength.solve(post, case, p, 30_000)[1].buckle == np.inf


def test_the_picture_reddens_and_rings_the_held_end(tmp_path):
    from smoothstone.strengthview import picture

    case = strength.parse(["load=80N", "at=right", "dir=down", "fixed=left", "infill=100"])[0]
    st, res = strength.solve(beam(), case, strength.material("PLA"), 20_000)
    picture(st, res, tmp_path / "s.png")
    top = np.asarray(Image.open(tmp_path / "s.png").convert("RGB")).astype(int)[30:, :275]  # the view from above
    red = np.argwhere((top[..., 0] == 255) & (top[..., 1] < 60) & (top[..., 2] < 60))
    ring = np.argwhere((top < 10).all(-1))
    assert len(red) > 50 and len(ring) > 100 and red[:, 1].max() < 140 and ring[:, 1].max() < 60, (len(red), len(ring))
