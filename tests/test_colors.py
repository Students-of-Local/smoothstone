"""stone colors: regions on the mesh, Orca's paint codes, and a painted 3MF that reads back clean."""
import json

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
