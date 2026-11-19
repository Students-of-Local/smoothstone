"""stone colors: regions on the mesh, Orca's paint codes, and a painted 3MF that reads back clean."""
import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from smoothstone import clean, cli, colors, config, recipes, scad
from smoothstone import recipes as rc
from smoothstone.job import Job
from test_cli import status_json, stone


def test_paint_codes_round_trip_for_16_filaments():
    codes = [colors.paint_code(n) for n in range(1, 17)]
    assert codes[:4] == ["4", "8", "0C", "1C"] and codes[-1] == "DC"
    assert [colors.decode_paint(c) for c in codes] == list(range(1, 17))
    assert len(set(codes)) == 16
    for bad in (0, 17):
        with pytest.raises(ValueError):
            colors.paint_code(bad)
    for bad in ("", "EC", "3", "0C0"):
        with pytest.raises(ValueError):
            colors.decode_paint(bad)


def test_box_with_top_half_painted_reads_back_clean(tmp_path):
    box = trimesh.creation.box((20, 20, 20)).subdivide().subdivide()
    m = colors.load_stl_mesh(box.vertices, box.faces)
    fil = np.where(m.triangles_center[:, 2] > 0, 2, 1)
    out = tmp_path / "box.3mf"
    main = colors.write_3mf(out, m.vertices, m.faces, fil, "box.stl")
    assert colors.check_3mf(out, len(m.faces), 2) == []
    v, f, codes, obj = colors.read_3mf(out)
    assert len(f) == len(m.faces) and obj == main
    back = trimesh.Trimesh(v, f, process=False)
    assert back.is_watertight
    assert all(x == 0 for x in clean.slicer_view(v, f).values())
    got = np.array([colors.decode_paint(c) if c else obj for c in codes])
    assert set(got) == {1, 2}
    assert (got == fil).all()  # each triangle keeps its filament, in face order


def test_check_3mf_finds_a_missing_filament(tmp_path):
    box = trimesh.creation.box((10, 10, 10))
    m = colors.load_stl_mesh(box.vertices, box.faces)
    fil = np.where(m.triangles_center[:, 2] > 0, 3, 1)
    out = tmp_path / "box.3mf"
    colors.write_3mf(out, m.vertices, m.faces, fil, "box.stl")
    assert colors.check_3mf(out, len(m.faces), 3) == []
    assert any("paint codes" in p for p in colors.check_3mf(out, len(m.faces), 2))
    assert any("faces" in p for p in colors.check_3mf(out, len(m.faces) + 1, 3))


def test_two_same_color_blobs_are_two_regions():
    a = trimesh.creation.icosphere(subdivisions=3, radius=5)
    b = a.copy()
    b.apply_translation((20, 0, 0))
    m = trimesh.util.concatenate([a, b])
    reg = colors.regions(m, np.zeros(len(m.faces), int))
    assert reg.max() == 1
    assert len(set(reg[: len(a.faces)])) == 1 and len(set(reg[len(a.faces):])) == 1


def test_a_small_patch_joins_its_neighbor_and_the_base_stays():
    m = trimesh.creation.icosphere(subdivisions=4, radius=10)
    c = m.triangles_center
    lab = np.zeros(len(m.faces), int)
    lab[c[:, 2] > 5] = 1  # a cap, well over 1.5%
    speck = np.argmin(np.linalg.norm(c - [10, 0, 0], axis=1))
    lab[speck] = 2  # one face: under 1.5%, joins the face around it
    base = c[:, 2] < -9.75  # a tiny base, under 1.5%, still its own region
    assert m.area_faces[base].sum() / m.area > 0 and m.area_faces[base].sum() / m.area < colors.MIN_SHARE
    reg = colors.regions(m, lab, base=base)
    assert reg.max() + 1 == 3  # body, cap, base
    assert reg[speck] == reg[np.argmin(np.linalg.norm(c - [10, 0, -1], axis=1))]
    assert len(set(reg[base])) == 1 and reg[base][0] not in reg[~base]


def test_a_small_patch_that_stands_out_stays_its_own_region():
    """White hands on a black jacket are about 1% of a figure each: under MIN_SHARE, but not noise."""
    m = trimesh.creation.icosphere(subdivisions=5, radius=10)
    c = m.triangles_center
    near = np.linalg.norm(c - [10, 0, 0], axis=1)
    patch = near < np.sort(near)[int(0.01 * len(c))]  # about 1% of the faces
    labels = np.where(patch, 1, 0)
    black_white = colors._lab([[20, 20, 20], [240, 240, 240]])
    black_gray = colors._lab([[20, 20, 20], [45, 45, 45]])
    kept = colors.regions(m, labels, lab=black_white)
    assert kept.max() + 1 == 2 and len(set(kept[patch])) == 1 and kept[patch][0] not in kept[~patch]
    merged = colors.regions(m, labels, lab=black_gray)  # shading on the same cloth
    assert merged.max() + 1 == 1


def test_layer_changes_counts_mixed_layers():
    box = trimesh.creation.box((10, 10, 10)).subdivide().subdivide().subdivide()
    m = colors.load_stl_mesh(box.vertices, box.faces)
    one = np.ones(len(m.faces), int)
    assert colors.layer_changes(m, one) == (0, 0)
    half = np.where(m.triangles_center[:, 0] > 0, 2, 1)  # left and right halves: every layer mixed
    mixed, changes = colors.layer_changes(m, half)
    assert mixed >= 48 and changes >= mixed


def test_color_names_and_requests():
    assert colors.color_name((20, 20, 20)) == "black"
    assert colors.color_name((235, 238, 240)) == "white"
    assert colors.color_name((200, 30, 40)) == "red"
    assert colors.asks_for_color("a red keychain") and colors.asks_for_color("a two-color sign")
    assert not colors.asks_for_color("A guard for a 120 mm PC fan, 3 mm thick.")
    assert not colors.asks_for_color("A ribbed planter for a small succulent with a drain hole")
    assert colors.request_colors("white with a red dress") == ["white", "red"]


def test_filaments_from_stone_toml(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert config.filaments(tmp_path) == ["white", "black"]
    (tmp_path / "stone.toml").write_text('[filaments]\n1 = "white"\n2 = "red"\n3 = "matte black"\n')
    assert config.filaments(tmp_path) == ["white", "red", "matte black"]


def test_filaments_from_the_machine_config(tmp_path, monkeypatch):
    """The printer's slots are set once per machine, not per job: a K2 with red, white, blue, black."""
    monkeypatch.chdir(tmp_path)
    xdg = tmp_path / "xdg"
    (xdg / "smoothstone").mkdir(parents=True)
    (xdg / "smoothstone" / "stone.toml").write_text('[filaments]\n1 = "red"\n2 = "white"\n3 = "blue"\n4 = "black"\n')
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    assert config.filaments(tmp_path / "job") == ["red", "white", "blue", "black"]


# the slicer repair (PR #4 review)


def test_for_slicer_runs_the_quadric_pass_when_problems_remain(monkeypatch):
    calls = {"n": 0}
    real = clean.problems

    def once(view):  # the first manifold rebuild "leaves a sliver"
        calls["n"] += 1
        return ["1 non-manifold edges"] if calls["n"] == 1 else real(view)

    import fast_simplification

    simp = {"n": 0}
    real_simplify = fast_simplification.simplify

    def counting(*a, **k):
        simp["n"] += 1
        return real_simplify(*a, **k)

    monkeypatch.setattr(clean, "problems", once)
    monkeypatch.setattr(fast_simplification, "simplify", counting)
    m = trimesh.creation.icosphere(subdivisions=3, radius=10)
    out = clean.for_slicer(m)
    assert simp["n"] == 1
    assert real(clean.slicer_view(out.vertices, out.faces)) == []
    assert out.is_watertight


def test_for_slicer_raises_when_problems_are_left(monkeypatch):
    monkeypatch.setattr(clean, "problems", lambda view: ["3 non-manifold edges"])
    with pytest.raises(ValueError, match="3 non-manifold edges"):
        clean.for_slicer(trimesh.creation.icosphere(subdivisions=2, radius=10))


def test_build_stl_output_passes_slicer_view(openscad, tmp_path):
    r = recipes.load("_demo")
    out = tmp_path / "part.stl"
    run = scad.build_stl(openscad, r, r.merged({}), out)
    assert run.ok, run.log
    m = trimesh.load(str(out), force="mesh", process=False)
    assert clean.slicer_view(m.vertices, m.faces) == {"collapsed": 0, "zero_area": 0, "bad_edges": 0}


def test_a_mesh_left_unclean_fails_the_build_with_a_fix(jobenv, openscad, monkeypatch):
    def broken(mesh, tolerance=0.01):
        raise ValueError("still 2 non-manifold edges after three repair passes")

    monkeypatch.setattr(clean, "for_slicer", broken)
    stone("new", "a small plate with one hole")
    stone("set", "_demo", "w=50")
    text, code, nxt = stone("build")
    assert code == 1
    assert f"FIX: {scad.SLICER_ERROR}: still 2 non-manifold edges" in text
    assert nxt == "stone set _demo --reset"
    assert status_json(jobenv)["passed"] is False


# the command


def test_a_one_color_part_names_its_filament_and_is_done(jobenv, openscad):
    stone("new", "a small red plate with one hole")
    stone("set", "_demo", "w=50")
    text, code, nxt = stone("build")
    assert code == 0 and "Part ready" in text
    assert "This part prints in one color: red. Load that filament." in text
    assert nxt == cli.DONE_NEXT

    text, code, nxt = stone("colors")
    assert code == 0, text
    assert "1  red" in text and "100% of surface" in text and "whole part" in text
    assert nxt == "stone colors rest=red"
    assert (jobenv / "stone-job" / "build" / "regions.png").is_file()

    text, code, nxt = stone(*nxt.split()[1:])
    assert code == 0, text
    assert "red is not in stone.toml [filaments], so it is filament 3" in text
    assert "filament 3 red: 100% of surface" in text
    assert "In the slicer: filament 3 must be red." in text
    assert nxt == cli.DONE_NEXT
    f3 = jobenv / "stone-job" / "_demo.3mf"
    assert f3.is_file()
    assert colors.check_3mf(f3, len(colors.load_stl(jobenv / "stone-job" / "_demo.stl").faces), 3) == []
    assert (jobenv / "stone-job" / "build" / "colors.png").is_file()

    # status keeps the mapping, for a model whose context was compacted
    text, code, nxt = stone("status")
    assert "Colors: filament 3 red: 100% of surface (stone colors rest=red)" in text
    assert "_demo.3mf" in text and nxt == cli.DONE_NEXT
    assert status_json(jobenv)["colors"]["mapping"] == "rest=red"

    # a new build drops the old 3MF and mapping
    stone("set", "_demo", "w=40")
    stone("build")
    assert not f3.exists()
    assert not status_json(jobenv).get("colors")


def test_build_without_a_color_word_is_done(jobenv, openscad):
    stone("new", "a small plate with one hole")
    stone("set", "_demo", "w=50")
    text, code, nxt = stone("build")
    assert code == 0 and nxt == cli.DONE_NEXT


def test_colors_needs_a_passing_build_and_a_known_color(jobenv, openscad):
    stone("new", "a small plate with one hole")
    text, code, nxt = stone("colors")
    assert code == 1 and "FIX: stone colors needs a passing build first" in text
    stone("set", "_demo", "w=50")
    stone("build")
    (jobenv / "stone.toml").write_text('[filaments]\n1 = "white"\n2 = "black"\n')
    text, code, nxt = stone("colors", "1=sparkly")
    assert code == 1 and 'FIX: "sparkly" is not a color' in text
    assert nxt == "stone colors rest=white"
    text, code, nxt = stone("colors", "7=black")
    assert code == 1 and 'FIX: no region "7"' in text
    text, code, nxt = stone("colors", "1=2")
    assert code == 0 and "filament 2 black: 100% of surface" in text
    assert json.loads((jobenv / "stone-job" / "status.json").read_text())["colors"]["filaments"] == ["white", "black"]


# review round 1


def ada_regions():
    """Regions like a figure of Ada Lovelace in a red dress: base, dress, face, hair."""
    def reg(n, rgb, share, base=False):
        return {"n": n, "rgb": rgb, "share": share, "base": base, "color": None if rgb is None else colors.color_name(rgb),
                "z0": 0, "z1": 10, "pos": "base" if base else "middle", "region": n - 1}
    return [reg(1, None, 0.40, base=True), reg(2, [178, 32, 40], 0.30), reg(3, [232, 188, 152], 0.18),
            reg(4, [40, 30, 28], 0.12)]


def test_suggestion_follows_the_colors_the_request_names():
    line = cli._suggest_line(ada_regions(), ["white", "black"], "A mini figure of Ada Lovelace, white with a red dress")
    assert line == "stone colors 2=red rest=white"


def test_suggestion_takes_rest_from_the_phrase_not_the_word_order():
    """Review round 2, first-F1: the accent color named first must not become rest."""
    line = cli._suggest_line(ada_regions(), ["white", "black"],
                             "A mini figure of Ada Lovelace in a red dress, white everywhere else")
    assert line == "stone colors 2=red rest=white"
    line = cli._suggest_line(ada_regions(), ["white", "black", "red"],
                             "Ada Lovelace in a red dress, the rest white")
    assert line == "stone colors 2=red rest=white"


def test_one_named_color_keeps_the_other_photo_colors():
    """Review round 2, second-S1: one named color must not paint the whole figure one color."""
    line = cli._suggest_line(ada_regions(), ["white", "black", "red"], "A mini figure of Ada Lovelace in a red dress")
    assert line == "stone colors 2=red 4=black rest=white"
    # the owner's own words: everything white except the part named, which keeps its photo color
    line = cli._suggest_line(ada_regions(), ["white", "black", "red"], "Ada Lovelace, all white but the dress")
    assert "rest=white" in line and "2=red" in line
    line = cli._suggest_line(ada_regions(), ["white", "black"], "Ada Lovelace, all white")
    assert line == "stone colors rest=white"


def test_suggestion_keeps_the_photo_colors_when_the_request_names_none():
    line = cli._suggest_line(ada_regions(), ["white", "black"], "A mini figure of Ada Lovelace")
    assert line == "stone colors 3=white rest=black"  # the red dress is nearer black than white


def test_colors_refuses_when_the_plan_changed_after_the_build(jobenv, openscad):
    stone("new", "a small plate with one hole")
    stone("set", "_demo", "w=50")
    stone("build")
    stone("set", "_demo", "w=40")
    text, code, nxt = stone("colors")
    assert code == 1 and "FIX: the plan changed after the last build" in text
    assert nxt == "stone build"


def test_feet_beside_the_plinth_keep_their_color():
    """A figure face with plinth faces on every side: the plinth must not vote it into palette color 0."""
    m = trimesh.creation.icosphere(subdivisions=3, radius=10)
    foot = int(np.argmin(np.linalg.norm(m.triangles_center - [0, 0, -10], axis=1)))
    base = m.triangles_center[:, 2] < 0
    base[foot] = False
    near = set(m.face_adjacency[(m.face_adjacency == foot).any(1)].ravel()) - {foot}
    assert len(near) == 3 and all(base[list(near)])
    fig = np.zeros((~base).sum(), int)  # the head: palette color 0
    fig[np.where(~base)[0] == foot] = 1  # the foot: palette color 1
    labels = colors.figure_labels(m, fig, base, npal=2)
    assert labels[foot] == 1
    assert (labels[base] == 2).all() and set(labels[~base]) <= {0, 1}


def test_only_a_figure_with_a_style_picture_goes_on_to_stone_colors(tmp_path, monkeypatch):
    monkeypatch.delenv("STONE_RECIPES", raising=False)
    job = Job(tmp_path / "job")
    d = job.image_dir / "figure" / "abc123"
    d.mkdir(parents=True)
    params = {"figure": str(tmp_path / "elsewhere" / "abc123" / "figure.stl")}
    fig = rc.load("figure")
    assert not cli._many_colors(job, fig, params)  # no picture yet
    (d / "style.png").write_bytes(b"png")
    assert cli._many_colors(job, fig, params)
    assert not cli._many_colors(job, rc.load("_demo"), params)


# smooth color boundaries (SPEC2)


def _sphere_halves():
    s = trimesh.creation.icosphere(subdivisions=3, radius=6)  # about 0.9 mm edges, a coarse figure
    m = colors.load_stl_mesh(s.vertices, s.faces)
    fil = np.where(m.triangles_center[:, 2] > 0, 2, 1)
    return m, fil


def test_cut_iso_keeps_a_closed_mesh_watertight_clean_and_its_volume():
    s = trimesh.creation.icosphere(subdivisions=3, radius=6)
    V, F = np.asarray(s.vertices), np.asarray(s.faces)
    f = V[:, 2] + 0.3 * V[:, 0]  # a tilted plane: it crosses edges anywhere, near vertices too
    for level in (0.0, 1.234, -4.5):
        V2, F2, par = clean.cut_iso(V, F, f, level, parents=True)
        m = trimesh.Trimesh(V2, F2, process=False)
        assert m.is_watertight and m.is_winding_consistent
        assert all(x == 0 for x in clean.slicer_view(V2, F2).values())
        assert abs(m.volume - s.volume) < 1e-6 * s.volume  # new vertices lie on the old edges
        assert len(F2) > len(F) and len(par) == len(F2) and par.max() < len(F)
        new = V2[len(V):]
        lv = new[:, 2] + 0.3 * new[:, 0]
        assert len(new) > 10 and np.abs(lv - level).max() < 1e-9  # every new vertex is on the level
        # no face crosses the level any more: each lies on one side (or touches it)
        g = np.r_[f, lv] - level
        g[np.abs(g) < 0.03] = 0
        side = np.sign(g)[F2]
        assert not ((side.max(1) > 0) & (side.min(1) < 0)).any()


def test_cut_iso_follows_a_slowly_changing_field_through_the_triangles():
    s = trimesh.creation.icosphere(subdivisions=3, radius=6)
    V, F = np.asarray(s.vertices), np.asarray(s.faces)
    f = 0.01 * (V[:, 2] + 0.3 * V[:, 0])  # 0.01 per mm: a snap in units of f would take a 3 mm band
    V2, F2, g = clean.cut_iso(V, F, f, 0.0, fields=f)
    fil = np.where(g[F2].mean(1) > 0, 2, 1)
    worst, lines = colors.color_edges(V2, F2, fil)
    assert len(lines) == 1 and worst < 1.03  # a curve through the triangles, not along their edges
    on_old = (lines[0]["verts"] < len(V)).mean()
    assert on_old < 0.2


def test_cut_iso_interpolates_fields_onto_new_vertices():
    s = trimesh.creation.icosphere(subdivisions=2, radius=5)
    V, F = np.asarray(s.vertices), np.asarray(s.faces)
    V2, F2, X = clean.cut_iso(V, F, V[:, 2], 0.0, fields=V[:, :2].copy())
    assert np.allclose(X, V2[:, :2])  # a field linear in position comes out exact


def test_an_uncut_color_edge_is_jagged_and_the_cut_one_is_smooth():
    m, fil = _sphere_halves()
    worst, lines = colors.color_edges(m.vertices, m.faces, fil)
    assert len(lines) == 1 and lines[0]["closed"]
    assert worst > 1.10  # the edge runs along triangle edges: the check must be able to fail
    V, F, fil2, parent = colors.smooth_cut(m.vertices, m.faces, fil)
    cut = colors.load_stl_mesh(V, F)
    assert cut.is_watertight and all(x == 0 for x in clean.slicer_view(V, F).values())
    assert abs(cut.volume - m.volume) < colors.VOLUME_TOL * m.volume
    worst2, lines2 = colors.color_edges(V, F, fil2)
    assert worst2 < 1.03
    assert len(parent) == len(F) and set(fil2) == {1, 2}


def test_a_clean_small_loop_is_not_called_jagged():
    t = np.linspace(0, 2 * np.pi, 400, endpoint=False)
    for r in (1.5, 4.0, 20.0):  # a moving average shrinks small loops; the check corrects for it
        pts = np.c_[r * np.cos(t), r * np.sin(t), 0 * t]
        assert colors.jaggedness(np.vstack([pts, pts[:1]]), True) < 1.01


def test_a_sawtooth_line_is_jagged():
    x = np.arange(0, 30.01, 0.5)
    pts = np.c_[x, 0.25 * (np.arange(len(x)) % 2), 0 * x]  # 0.5 mm teeth, 0.25 mm high
    assert colors.jaggedness(pts, False) > colors.JAGGED
    assert colors.jaggedness(np.c_[x, 0 * x, 0 * x], False) < 1.001


def test_fixed_faces_keep_their_filament_and_their_edge():
    box = trimesh.creation.box((20, 20, 20)).subdivide().subdivide().subdivide()
    m = colors.load_stl_mesh(box.vertices, box.faces)
    zc = m.triangles_center[:, 2]
    base = zc < -5
    fil = np.where(base, 1, 2)
    fil[(zc > 5)] = 1
    V, F, fil2, parent = colors.smooth_cut(m.vertices, m.faces, fil, fixed=base)
    assert (fil2[base[parent]] == 1).all()  # the plinth stays its color
    # the figure's color runs right down to the seam: no other color creeps onto it
    zc2 = V[F].mean(1)[:, 2]
    seam = (~base[parent]) & (zc2 < -4)
    assert (fil2[seam] == 2).all()


def test_check_3mf_finds_a_volume_change(tmp_path):
    box = trimesh.creation.box((10, 10, 10))
    m = colors.load_stl_mesh(box.vertices, box.faces)
    fil = np.where(m.triangles_center[:, 2] > 0, 2, 1)
    out = tmp_path / "box.3mf"
    colors.write_3mf(out, m.vertices, m.faces, fil, "box.stl")
    assert colors.check_3mf(out, len(m.faces), 2, volume=1000.0) == []
    assert any("volume" in p for p in colors.check_3mf(out, len(m.faces), 2, volume=1010.0))


def test_every_passing_build_writes_views_with_10_panels(jobenv, openscad):
    from PIL import Image

    stone("new", "a small plate with one hole")
    stone("set", "_demo", "w=50")
    text, code, nxt = stone("build")
    assert code == 0, text
    png = jobenv / "stone-job" / "build" / "views.png"
    assert f"Views: {png} (look at every panel before you call it done)" in text
    assert len(colors.VIEWS) == 10
    im = Image.open(png)
    assert im.size == (5 * colors.VIEW_PX, 2 * colors.VIEW_PX)  # 5 a row, 2 rows
    # every panel shows the part: some pixels differ from the gray background
    a = np.asarray(im.convert("RGB")).astype(int)
    for i in range(10):
        r, c = divmod(i, 5)
        cell = a[r * colors.VIEW_PX:(r + 1) * colors.VIEW_PX, c * colors.VIEW_PX:(c + 1) * colors.VIEW_PX]
        assert (np.abs(cell - 136).sum(2) > 30).mean() > 0.02, f"panel {i} is empty"


def test_a_jagged_color_edge_writes_no_file(jobenv, openscad, monkeypatch):
    stone("new", "a small red plate with one hole")
    stone("set", "_demo", "w=50")
    stone("build")
    pts = np.c_[np.arange(0, 10.0, 0.5), np.zeros(20), np.zeros(20)]
    line = {"pair": (1, 3), "pts": pts, "verts": np.arange(20), "closed": False, "length": 9.5, "ratio": 1.2}
    monkeypatch.setattr(colors, "color_edges", lambda V, F, fil: (1.2, [line]))
    text, code, nxt = stone("colors", "rest=red")
    assert code != 0
    assert "FIX: color boundary is jagged: filament 1/3 at z 0 mm is 1.20 times its smoothed length" in text
    assert "no file written" in text
    assert not (jobenv / "stone-job" / "_demo.3mf").exists()
    assert (jobenv / "stone-job" / "build" / "boundaries.png").is_file()
    assert not status_json(jobenv).get("colors")


def test_a_painted_part_passes_color_edges_and_writes_views(jobenv, openscad):
    stone("new", "a small red plate with one hole")
    stone("set", "_demo", "w=50")
    stone("build")
    text, code, nxt = stone("colors", "rest=red")
    assert code == 0, text
    assert "PASS color_edges: every color boundary is a smooth curve" in text
    assert "Views: " in text and (jobenv / "stone-job" / "build" / "views.png").is_file()
    assert status_json(jobenv)["colors"]["color_edges"] == 1.0


# review mediums from PR #5: names that are color words, hyphenated shades


def test_hyphenated_shades_map_to_their_base_color():
    assert colors.word_color("dark-red") == "red"
    assert colors.word_color("sky-blue") == "blue"
    assert colors.word_color("light-grey") == "gray"
    assert colors.request_colors("a dark-red mug") == ["red"]
    assert colors.asks_for_color("a sky-blue vase")


def test_a_name_that_is_a_color_word_is_not_a_color():
    for req in ("A mini figure of Jack Black, 90 mm tall", "a bust of Betty White",
                "Charlie Brown on a plinth", "a figure of Hank Green"):
        names = colors.subject_names(req)
        assert colors.request_colors(req, names) == [], req
        assert not colors.asks_for_color(req, names), req
        assert colors.part_colors(req, names) == {}, req


def test_the_name_stone_find_searched_counts_even_in_lower_case():
    req = "a mini figure of jack black with a red shirt"
    names = colors.subject_names(req, ["Jack Black"])
    assert colors.request_colors(req, names) == ["red"]
    assert {k: v for k, v in colors.part_colors(req, names).items() if not k.startswith("word:")} == {"top": "red"}


def test_a_named_person_still_gets_the_colors_the_request_gives():
    req = "Betty White in a red dress, all blue but the dress"
    names = colors.subject_names(req)
    assert colors.request_colors(req, names) == ["red", "blue"]


# SPEC3 B: the request decides exactly, by part


def jensen_regions():
    """Regions like the Jensen figure: base, face, hair, jacket, pants, glasses, two hands."""
    def reg(n, rgb, share, part, base=False):
        return {"n": n, "rgb": rgb, "share": share, "base": base, "part": part,
                "color": None if rgb is None else colors.color_name(rgb),
                "z0": 0, "z1": 10, "pos": "base" if base else "middle", "region": n - 1}
    return [reg(1, None, 0.48, "base", base=True), reg(2, [225, 180, 150], 0.17, "face"),
            reg(3, [235, 235, 235], 0.14, "hair"), reg(4, [25, 25, 25], 0.13, "jacket"),
            reg(5, [30, 30, 30], 0.05, "pants"), reg(6, [20, 20, 20], 0.01, "glasses"),
            reg(7, [225, 180, 150], 0.01, "hands"), reg(8, [225, 180, 150], 0.01, "hands")]


FIL = ["red", "white", "blue", "black"]


@pytest.mark.parametrize("req", [
    "A mini figure of Jensen Huang, 90 mm tall, all white but the jacket",
    "A mini figure of Jensen Huang, 90 mm tall, with \"JENSEN\" on the base, all white but the jacket, which is black.",
    "Jensen Huang, all white except the jacket",
    "Jensen Huang in a black jacket, white everywhere else",
    "Jensen Huang, white with a black jacket",
    "Jensen Huang with the jacket in black, the rest white",
    "A mini figure of Jensen Huang in a black jacket",
    "A mini figure of Jensen Huang with a black jacket",
])
def test_part_phrases_give_exactly_that_mapping(req):
    names = colors.subject_names(req)
    line = cli._suggest_line(jensen_regions(), FIL, colors.without_names(req, names))
    assert line == "stone colors jacket=black rest=white", (req, line)


def test_part_phrase_forms():
    pc = lambda r: {k: v for k, v in colors.part_colors(r).items() if not k.startswith("word:")}
    assert pc("a black jacket") == {"top": "black"}
    assert pc("the jacket in black") == {"top": "black"}
    assert pc("all white but the jacket") == {"top": "picture"}
    assert pc("all white but the jacket, which is black") == {"top": "black"}
    assert pc("red shoes and blue pants") == {"shoes": "red", "pants": "blue"}
    assert colors.part_colors("a black jacket")["word:top"] == "jacket"


def test_a_part_after_but_keeps_its_picture_color_or_the_next_most_different():
    # the jacket is black in the picture and black is loaded: jacket=black
    line = cli._suggest_line(jensen_regions(), FIL, "all white but the jacket")
    assert line == "stone colors jacket=black rest=white"
    # a jacket that is white in the picture, all white but the jacket: not white again
    regs = jensen_regions()
    regs[3]["rgb"] = [240, 240, 240]
    regs[3]["color"] = "white"
    line = cli._suggest_line(regs, FIL, "all white but the jacket")
    assert "rest=white" in line and "jacket=white" not in line and "jacket=" in line, line


def test_a_plain_color_alone_is_the_rest():
    assert cli._suggest_line(jensen_regions(), FIL, "Jensen Huang in white") == "stone colors rest=white"


@pytest.mark.parametrize("req,want", [
    ('A mini figure of Jensen Huang in white, 90 mm tall, with "JENSEN" on the base', "white"),
    ('A mini figure of Jensen Huang in red, 90 mm tall, with "JENSEN" on the base', "red"),
])
def test_one_color_with_the_base_mentioned_is_a_one_color_print(req, want):
    """Review round 2 first-F1: "base" (or name, head, face) mentioned without a color is not a
    part given a color, so one named color still means the whole figure in it."""
    names = colors.subject_names(req)
    line = cli._suggest_line(jensen_regions(), FIL, colors.without_names(req, names))
    assert line == f"stone colors rest={want}", (req, line)


def test_with_no_part_named_the_photo_colors_stay():
    line = cli._suggest_line(jensen_regions(), FIL, "A mini figure of Jensen Huang")
    assert "jacket=black" in line and "rest=" in line


# SPEC3 E1: the wobble limit on Jensen's wrists


def test_wobble_fails_the_spec2_wrists_and_passes_the_plane_cut():
    """The Spec 2 wrists (paint that wandered up and down the cuff, wavy at 90 and 270 degrees) score
    0.37 and 0.40 mm; the lead's plane cut scores 0.03. The whole-line ratio passed both (1.03)."""
    d = np.load(Path(__file__).parent / "fixtures" / "edges" / "wrists.npz")
    for k in ("spec2_0", "spec2_1"):
        w = colors.wobble(d[k].astype(float), True)
        assert w > colors.WOBBLE, (k, w)
        assert colors.jaggedness(d[k].astype(float), True) < colors.JAGGED  # the old check missed it
    for k in ("plane_0", "plane_1"):
        assert colors.wobble(d[k].astype(float), True) < colors.WOBBLE / 3, k


def test_close_ups_are_antialiased_so_a_straight_edge_shows_no_pixel_stairs():
    # a flat square facing the camera, black above a straight edge tilted 7 degrees, white below;
    # drawn without supersampling the edge is a run of one-pixel steps the judge reads as a stepped
    # paint line (r1, 2026-11-18); antialiased, the edge pixels blend the two colors
    from smoothstone.colors import _panel
    n = 60
    xs, zs = np.meshgrid(np.linspace(-5, 5, n), np.linspace(-5, 5, n))
    V = np.c_[xs.ravel(), np.zeros(n * n), zs.ravel()]
    F = []
    for i in range(n - 1):
        for j in range(n - 1):
            a = i * n + j
            F += [[a, a + 1, a + n], [a + 1, a + n + 1, a + n]]  # facing the camera (-y)
    F = np.array(F)
    c = V[F].mean(1)
    black = c[:, 2] > np.tan(np.radians(7)) * c[:, 0]
    rgb = np.where(black[:, None], [[20, 20, 20]], [[240, 240, 240]]).astype(float)
    def mids(ss):
        im = np.asarray(_panel(V, F, rgb, 0.0, 0.0, np.zeros(3), 4.0, 200, ss=ss).convert("L"), float)
        assert im.min() < 30 and im.max() > 180  # both colors drawn (shaded white is about 193)
        return int(((im > 40) & (im < 170)).sum())
    assert mids(1) < 20  # aliased: the stairs are pure black or white pixels
    assert mids(3) > 150  # antialiased: about one blended pixel per column along the edge


def test_three_colors_meeting_cut_on_mesh_edges():
    """Review round 2 sol-sol-F3: three sectors of a sphere meet at the poles, where the smoothed
    indicators sit near 1/3 and none crosses 0.5, so the largest-indicator boundary ran inside the
    triangles and zigzagged (ratio 1.10). Cutting where each filament stops being the largest puts
    that boundary on edges."""
    import trimesh

    s = trimesh.creation.icosphere(subdivisions=5, radius=10.0)
    m = colors.load_stl_mesh(s.vertices, s.faces)
    c = m.triangles_center
    fil = 1 + (((np.degrees(np.arctan2(c[:, 1], c[:, 0])) % 360 + 7) // 120).astype(int) % 3)
    V, F, out, parent = colors.smooth_cut(m.vertices, m.faces, fil)
    assert set(np.unique(out)) == {1, 2, 3}
    worst, lines = colors.color_edges(V, F, out)
    assert len(lines) >= 3 and colors.edge_faults(lines) == [], [(ln["pair"], ln["ratio"], ln["wobble"]) for ln in lines]
    assert worst < colors.JAGGED
    t = trimesh.Trimesh(V, F, process=False)
    assert t.is_watertight and abs(t.volume - m.volume) < 1e-6 * m.volume + 1e-6


# PR 6 review mediums, open since: each fails on the code before its fix


@pytest.mark.parametrize("req", [
    "A mini figure of Jensen Huang in a Black Jacket, white everywhere else",
    "Jensen Huang In A Black Jacket, White Everywhere Else",
])
def test_title_case_colors_are_not_taken_for_a_name(req):
    """Review r2 first-F2: "Black Jacket" is two capitalized words, but it is a color and a part,
    not a person, so its color must survive."""
    names = colors.subject_names(req, ["Jensen Huang"])
    assert "Black Jacket" not in names and not any(n.split()[0].lower() == "black" for n in names), names
    line = cli._suggest_line(jensen_regions(), FIL, colors.without_names(req, names))
    assert line == "stone colors jacket=black rest=white", line


def test_a_title_case_color_on_a_plain_part_still_counts():
    names = colors.subject_names("A Black Gridfinity Bin, 2 by 1")
    assert colors.asks_for_color("A Black Gridfinity Bin, 2 by 1", names)
    # a real name that is also a color word stays a name
    assert colors.subject_names("A mini figure of Betty White") == ["Betty White"]


def test_a_leading_color_with_the_base_mentioned_is_a_one_color_print():
    """Review r2 sol-sol-F5: "A white mini figure ... on the base" is the whole figure in white."""
    req = 'A white mini figure of Jensen Huang, 90 mm tall, with "JENSEN" on the base'
    names = colors.subject_names(req)
    line = cli._suggest_line(jensen_regions(), FIL, colors.without_names(req, names))
    assert line == "stone colors rest=white", line


def test_a_named_part_with_no_rest_color_does_not_paint_the_rest_its_color():
    """Review r1 first-F3: "in a black jacket" with no rest phrase. Every other part takes one rest
    color, and that rest comes from the parts not named; the jacket's own black must not decide
    it, even when the jacket covers more of the figure than anything else."""
    regs = jensen_regions()
    regs[3]["share"] = 0.45  # a long coat: the biggest region by far
    line = cli._suggest_line(regs, FIL, "A mini figure of Jensen Huang in a black jacket")
    assert line == "stone colors jacket=black rest=white", line


def test_a_part_asked_for_is_in_the_line_even_past_the_listed_regions():
    """Review r1 sol-F3: ten regions, the shoes ranked ninth and tenth. "red shoes, rest white"
    must paint them red, though the listing shows only the first eight."""
    regs = jensen_regions()
    def reg(n, rgb, share, part):
        return {"n": n, "rgb": rgb, "share": share, "base": False, "part": part,
                "color": colors.color_name(rgb), "z0": 0, "z1": 10, "pos": "middle", "region": n - 1}
    regs += [reg(9, [90, 60, 40], 0.004, "shoes"), reg(10, [90, 60, 40], 0.004, "shoes")]
    assert len(regs) > colors.LIST_MAX
    line = cli._suggest_line(regs, FIL, "Jensen Huang with red shoes, white everywhere else")
    assert line == "stone colors shoes=red rest=white", line


# PR 9 review round 1


def test_a_name_that_starts_with_a_color_word_stays_a_name():
    """Review first-F1: "Gray Davis" and "Black Francis" are people, so gray and black are not
    asked for."""
    assert colors.subject_names("A bust of Gray Davis, 80 mm tall") == ["Gray Davis"]
    assert colors.subject_names("A mini figure of Black Francis") == ["Black Francis"]
    req = "A bust of Gray Davis, 80 mm tall"
    assert colors.request_colors(req, colors.subject_names(req)) == []


@pytest.mark.parametrize("req", [
    "Jensen Huang In A Long Black Jacket, White Everywhere Else",
    "A mini figure of Jensen Huang in a Long Black Jacket, white everywhere else",
])
def test_a_word_in_front_of_a_title_case_color_part_keeps_its_color(req):
    """Review second-F3: one adjective in front of "Black Jacket" made "Long Black Jacket" a
    name, so the jacket lost its black."""
    names = colors.subject_names(req, ["Jensen Huang"])
    assert not any("Black" in n for n in names), names
    line = cli._suggest_line(jensen_regions(), FIL, colors.without_names(req, names))
    assert line == "stone colors jacket=black rest=white", line


def test_an_adjective_before_a_title_case_color_on_a_plain_part():
    req = "A Small Red Gridfinity Bin, 2 by 1"
    assert colors.request_colors(req, colors.subject_names(req)) == ["red"]


def test_numbered_regions_past_the_listing_take_the_rest_color():
    """Review second-F5: regions with no part past LIST_MAX were never shown, so the line must not
    give them their own photo colors; the listing says they take the rest color."""
    def reg(n, rgb, share):
        return {"n": n, "rgb": rgb, "share": share, "base": False, "part": None,
                "color": colors.color_name(rgb), "z0": 0, "z1": 10, "pos": "middle", "region": n - 1}
    regs = [reg(n, [235, 235, 235] if n % 2 else [200, 30, 30], 0.3 if n == 1 else 0.05)
            for n in range(1, 11)]
    assert len(regs) > colors.LIST_MAX
    line = cli._suggest_line(regs, FIL, "A vase with stripes")
    keys = [i.split("=")[0] for i in line.split()[2:]]
    assert keys and all(k == "rest" or int(k) <= colors.LIST_MAX for k in keys), line


def test_a_color_after_a_list_of_parts_paints_every_part_in_it():
    """"the jacket and shoes, which are black" gave the shoes black and left the jacket to the
    photo's color; Jensen's jacket only came out black because it is black in his photo."""
    pc = lambda r: {k: v for k, v in colors.part_colors(r).items() if not k.startswith("word:")}
    assert pc("all white but the jacket and shoes, which are black") == {"top": "black", "shoes": "black"}
    assert pc("all white but the jacket and shoes, which are black, and the pants, which are blue.") == \
        {"top": "black", "shoes": "black", "pants": "blue"}
    assert pc("all white but the hair, the jacket and the shoes, which are red") == \
        {"hair": "red", "top": "red", "shoes": "red"}


def test_a_suit_is_the_jacket_and_the_pants():
    pc = lambda r: {k: v for k, v in colors.part_colors(r).items() if not k.startswith("word:")}
    assert pc("a figure of him in a black suit") == {"top": "black", "pants": "black"}
    assert pc("in a black racing suit, white everywhere else") == {"top": "black", "pants": "black"}
    assert pc("all white but the suit and shoes, which are black") == \
        {"top": "black", "pants": "black", "shoes": "black"}
    assert pc("a grey suit and red shoes") == {"top": "gray", "pants": "gray", "shoes": "red"}
    assert pc("a blue jumpsuit") == {"top": "blue", "pants": "blue"}
