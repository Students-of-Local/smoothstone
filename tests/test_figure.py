"""The figure recipe without the style and lift models: a stand-in mesh goes through repair,
the plinth recipe and every print check, and the CLI points at stone find when photos are missing."""
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import trimesh

from smoothstone import cli, figure

REPO = Path(__file__).resolve().parent.parent


def stone(*argv):
    text, code = cli.run(list(argv))
    assert text.splitlines()[-1].startswith("NEXT: "), text
    return text, code, text.splitlines()[-1][6:]


def standin(path: Path) -> Path:
    """A little person, Y up and facing +Z like a lift model writes it: body, head, two feet."""
    body = trimesh.creation.capsule(height=0.9, radius=0.35)  # along Z
    body.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
    body.apply_translation([0, 0.8, 0])
    head = trimesh.creation.icosphere(subdivisions=3, radius=0.45)
    head.apply_translation([0, 1.85, 0.05])
    feet = [trimesh.creation.box([0.25, 0.2, 0.4]) for _ in range(2)]
    feet[0].apply_translation([-0.15, 0.1, 0.05])
    feet[1].apply_translation([0.15, 0.1, 0.05])
    m = trimesh.boolean.union([body, head, *feet], engine="manifold")
    m.export(path)
    return path


def armed(path: Path) -> Path:
    """The stand-in with arms hanging at its sides from a shoulder bar: each fingertip is the lowest
    point of its arm and has only air under it, like the hands of every lifted figure (2026-11-20)."""
    body = trimesh.load(standin(path.with_name("body.glb")), force="mesh")
    parts = [body, trimesh.creation.box([1.1, 0.1, 0.14])]
    parts[1].apply_translation([0, 1.2, 0])
    for x in (-0.5, 0.5):
        arm = trimesh.creation.capsule(height=0.5, radius=0.08)
        arm.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
        arm.apply_translation([x, 0.9, 0])
        parts.append(arm)
    trimesh.boolean.union(parts, engine="manifold").export(path)
    return path


def test_repair_orients_and_scales(tmp_path):
    info = figure.repair(standin(tmp_path / "lift.glb"), tmp_path / "figure.stl")
    m = trimesh.load(tmp_path / "figure.stl")
    lo, hi = m.bounds
    assert info["watertight"] and m.is_watertight
    assert abs((hi[2] - lo[2]) - 1) < 1e-6 and abs(lo[2]) < 1e-6  # unit height, feet on z = 0
    top = m.vertices[m.vertices[:, 2] > 0.8]
    assert top[:, 1].mean() < 0.02  # the face that pointed +Z now points -Y


def test_prompt_names_the_style():
    assert "chibi" in figure.prompt("chibi", "animal") and "this exact person" in figure.prompt("chibi")
    assert "large head" in figure.prompt("chibi")  # a person's chibi is the likeness figure
    assert "this exact animal" in figure.prompt("statue", "animal")
    with pytest.raises(figure.FigureProblem):
        figure.make([], Path("."), "nope")


def test_build_without_photos_asks_for_find(jobenv, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    stone("new", "A mini figure of Ada Lovelace, 80 mm tall")
    stone("set", "figure", "height=80")
    text, code, nxt = stone("build")
    assert code == 1 and nxt == 'stone find "Ada Lovelace"'
    assert stone("status")[2] == 'stone find "Ada Lovelace"'


def test_set_points_a_figure_without_photos_at_find(jobenv, monkeypatch):
    """A build with no photos only ends in a FIX that says stone find; set goes there directly, one
    step less on a path that ran out of steps for the small model (evals/distill.py, f5 and f6)."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    stone("new", "A mini figure of Ada Lovelace, 80 mm tall")
    assert stone("set", "figure", "height=80")[2] == 'stone find "Ada Lovelace"'
    stone("new", "A guard for a 92 mm fan")
    assert stone("set", "fan_guard", "size=92")[2] == "stone build"


def test_set_after_a_given_photo_goes_to_build(jobenv, monkeypatch, tmp_path):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    stone("new", "A mini figure of Ada Lovelace, 80 mm tall")
    from PIL import Image
    Image.new("RGB", (64, 64), "white").save(tmp_path / "me.png")
    stone("image", str(tmp_path / "me.png"))
    assert stone("set", "figure", "height=80")[2] == "stone build"


def test_figure_on_plinth_passes_checks(jobenv, monkeypatch, openscad, tmp_path):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    fig = tmp_path / "figure.stl"
    figure.repair(standin(tmp_path / "lift.glb"), fig)
    stone("new", 'A figure 70 mm tall with "ADA" on the base')
    stone("set", "figure", f"figure={fig}", "height=70", "name=ADA")
    text, code, nxt = stone("build")
    assert code == 0, text
    assert "Part ready" in text and "70.0 mm" in text


def test_cached_steps_skip_models(tmp_path, monkeypatch):
    """A second build with the same photos and settings reuses every file and runs no model."""
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"jpeg")
    calls = []

    def fake_style(photos, out, *a, **k):
        calls.append("style")
        shutil.copyfile(photo, out)
        return out

    def fake_lift(render, out, seed):
        calls.append("lift")
        standin(out)
        return out

    def fake_describe(photo, out, who):
        calls.append("describe")
        out.write_text("short silver hair\n")
        return "short silver hair"

    monkeypatch.setattr(figure, "describe", fake_describe)
    monkeypatch.setattr(figure, "style", fake_style)
    monkeypatch.setattr(figure, "lift", fake_lift)
    monkeypatch.setattr(figure, "traits", lambda *a, **k: None)
    a = figure.make([photo], tmp_path / "fig", say=lambda s: None)
    b = figure.make([photo], tmp_path / "fig", say=lambda s: None)
    assert a == b and a.exists() and calls == ["describe", "style", "lift"]


def test_find_leaves_other_plans_alone(jobenv, monkeypatch):
    """stone find on a fan guard job downloads nothing and keeps the job's NEXT."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    from smoothstone import find as findtool

    def no_fetch(*a, **k):
        raise AssertionError("find downloaded photos for a fan guard")

    monkeypatch.setattr(findtool, "fetch", no_fetch)
    stone("new", "A fan guard for a 120 mm fan")
    stone("set", "fan_guard", "size=120")
    before = stone("status")[2]
    text, code, nxt = stone("find", "fan guard")
    assert code == 1 and "figure" in text
    assert stone("status")[2] == before


def test_mini_alone_does_not_pick_figure(monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    from smoothstone import recipes as rc
    top = rc.rank(list(rc.load_all().values()), "a mini planter for a succulent")[0][1]
    assert top.name != "figure"


def test_find_before_a_plan_leaves_a_fan_guard_alone(jobenv, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    from smoothstone import find as findtool

    def no_fetch(*a, **k):
        raise AssertionError("find downloaded photos for a fan guard")

    monkeypatch.setattr(findtool, "fetch", no_fetch)
    stone("new", "A guard for a 120 mm fan")
    text, code, nxt = stone("find", "fan guard")
    assert code == 1 and "figure" in text and nxt == "stone show fan_guard"


def test_own_photo_on_a_figure_plan_goes_to_build(jobenv, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    stone("new", "A mini figure of my dog, 80 mm tall")
    stone("set", "figure", "height=80")
    assert stone("build")[2] == "stone image <path to photo>"
    photo = REPO / "examples" / "dog.png"
    if not photo.exists():
        photo = REPO / "evals" / "heldout" / "dog.png"
    text, code, nxt = stone("image", str(photo))
    assert nxt == "stone build", text
    assert stone("status")[2] == "stone build"


@pytest.mark.parametrize("request_text", ["A guard for a 120 mm fan", "A mini Abraham Lincoln, 80 mm tall",
                                          "A minifigure of Ada Lovelace", "a tiny Einstein"])
def test_find_never_loops_back_to_find(jobenv, monkeypatch, request_text):
    """A bare find, then a named find: the second NEXT is never another find that refuses."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    from smoothstone import find as findtool
    got = []
    monkeypatch.setattr(findtool, "fetch", lambda q, d, n=4: got.append(q) or [])
    stone("new", request_text)
    stone("find")
    text, code, nxt = stone("find", "fan guard" if "fan" in request_text else "Abraham Lincoln")
    if "fan" in request_text:
        assert not got and code == 1 and not nxt.startswith("stone find")
    else:
        assert got, text  # a subject with no part named is a figure


def _style_picture(path: Path) -> None:
    """A stand-in style picture: a skin-colored head over a black body on white."""
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (256, 512), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([60, 170, 196, 470], fill=(20, 20, 20))
    d.rectangle([70, 470, 186, 505], fill=(20, 20, 20))
    d.ellipse([70, 20, 186, 180], fill=(225, 180, 150))
    im.save(path)


def test_stone_colors_end_to_end_on_a_figure_with_a_style_picture(jobenv, monkeypatch, openscad, tmp_path):
    """Review medium (cli.py:1299): cmd_colors on a real figure job, listing and then painting."""
    from smoothstone import colors

    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    d = tmp_path / "abc123"
    d.mkdir()
    fig = d / "figure.stl"
    figure.repair(standin(tmp_path / "lift.glb"), fig)
    _style_picture(d / "style.png")
    stone("new", 'A figure 70 mm tall with "ADA" on the base, all white but the body, which is black')
    stone("set", "figure", f"figure={fig}", "height=70", "name=ADA")
    text, code, nxt = stone("build")
    assert code == 0 and "Part ready" in text, text
    assert nxt.startswith("stone colors"), text

    text, code, nxt = stone("colors")
    assert code == 0, text
    assert "Color regions of figure.stl" in text and "base" in text
    assert "% of surface" in text
    assert nxt.startswith("stone colors ") and "rest=" in nxt, text
    regions = json.loads((jobenv / "stone-job" / "build" / "regions.json").read_text())
    assert regions["anatomy"]["top"] > 0

    text, code, nxt = stone(*nxt.split()[1:])
    assert code == 0, text
    assert "PASS color_edges" in text, text
    out = jobenv / "stone-job" / "figure.3mf"
    assert out.is_file(), text
    n = len(colors.read_3mf(out)[1])
    assert colors.check_3mf(out, n, len(status_json_colors(jobenv)["filaments"])) == []
    assert nxt == cli.DONE_NEXT
    assert (jobenv / "stone-job" / "build" / "views.png").is_file()

    # SPEC3 C: the eval grader reads the parts' colors back from the 3MF
    import sys

    sys.path.insert(0, str(REPO / "evals"))
    import run as evrun

    job = jobenv / "stone-job"
    got = evrun.grade_colors(job, "figure", {"rest": "none"})["parts"]
    assert "base" in got and len(set(got.values())) >= 2, got
    rest = got["base"]
    want: dict = {"rest": rest}
    for part, c in got.items():
        if c != rest:
            want.setdefault(c, []).append(part)
    g = evrun.grade_colors(job, "figure", want)
    assert g["why"] == [] and abs(sum(g["shares"].values()) - 1) < 0.01, g
    odd = next(p for p, c in got.items() if c != rest)
    wrong = {"rest": rest, rest: [odd]}
    assert f"{odd} is {got[odd]} (want {rest})" in evrun.grade_colors(job, "figure", wrong)["why"]

    # PR 6 review r2 sol-sol-F4: a part painted 60% right and 40% wrong must fail, though its
    # majority is right. Repaint 40% of the odd part's area (by region) in the rest color.
    import numpy as np

    V, F, codes, main = colors.read_3mf(job / "figure.3mf")
    fil = status_json_colors(jobenv)["filaments"]
    face = np.array([colors.decode_paint(c) if c else main for c in codes])
    num = np.load(job / "build" / "paint.npy")
    regs = json.loads((job / "build" / "regions.json").read_text())["regions"]
    sel = np.isin(num, [d["n"] for d in regs if (d.get("part") or "other") == odd])
    area = colors.load_stl_mesh(V, F).area_faces
    idx = np.where(sel & (face == fil.index(got[odd]) + 1))[0]
    flip = idx[np.cumsum(area[idx]) <= 0.4 * area[sel].sum()]
    face[flip] = fil.index(rest) + 1
    colors.write_3mf(job / "figure.3mf", V, F, face, "figure")
    why = evrun.grade_colors(job, "figure", want)["why"]
    assert any(w.startswith(f"{odd} is ") and f"not {got[odd]}" in w for w in why), why


def test_a_failing_color_edge_never_points_back_at_the_same_mapping(jobenv, monkeypatch, openscad, tmp_path):
    """Review first-F1: a ledge fault must give a NEXT that changes the mapping (the region on the
    failing edge takes the rest color, or the part prints in one color), so following NEXT ends in
    a written 3MF instead of a loop. "body" is no part's name, so the request gives no part a
    color: a color it gives one is never given up
    (test_a_color_the_request_names_is_never_given_up_for_a_rough_edge)."""
    import numpy as np

    from smoothstone import colors

    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    d = tmp_path / "abc123"
    d.mkdir()
    fig = d / "figure.stl"
    figure.repair(standin(tmp_path / "lift.glb"), fig)
    _style_picture(d / "style.png")
    stone("new", 'A figure 70 mm tall with "ADA" on the base, all white but the body, which is black')
    stone("set", "figure", f"figure={fig}", "height=70", "name=ADA")
    text, code, nxt = stone("build")
    assert code == 0 and nxt.startswith("stone colors"), text

    real = colors.ledges

    def always_a_ledge(V, F, face_fil, lines):  # every two-color paint climbs a ledge
        out = real(V, F, face_fil, lines)
        if len(np.unique(face_fil)) > 1 and out:
            out[0] = {**out[0], "area": 1.0, "angle": 15.0, "fil": int(face_fil.max()), "faces": 9}
        return out

    monkeypatch.setattr(colors, "ledges", always_a_ledge)
    if nxt == "stone colors":
        text, code, nxt = stone("colors")
    tried = []
    for _ in range(6):
        mapping = nxt
        text, code, nxt = stone(*mapping.split()[1:])
        tried.append(mapping)
        if nxt == cli.DONE_NEXT:
            break
        assert "climbs onto a ledge" in text, text
        assert nxt != mapping and nxt != "stone colors", text  # never the mapping that just failed
    assert nxt == cli.DONE_NEXT, tried
    assert len(tried) > 1, tried
    out = jobenv / "stone-job" / "figure.3mf"
    assert out.is_file()
    assert len(status_json_colors(jobenv)["shares"].split(";")) == 1  # the one-color print


def status_json_colors(work: Path) -> dict:
    return json.loads((work / "stone-job" / "status.json").read_text())["colors"]


def test_a_build_after_stone_colors_with_nothing_changed_keeps_the_paint(jobenv, monkeypatch, openscad, tmp_path):
    """Review r2 second-N2: a small model that reads a FIX from stone colors as "fix, then stone
    build again" must not undo the paint: the rebuild wiped the 3MF and re-suggested the first
    mapping, so a retry looped forever. With the plan unchanged the build is skipped."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    d = tmp_path / "abc123"
    d.mkdir()
    fig = d / "figure.stl"
    figure.repair(standin(tmp_path / "lift.glb"), fig)
    _style_picture(d / "style.png")
    stone("new", 'A figure 70 mm tall with "ADA" on the base, all white but the body, which is black')
    stone("set", "figure", f"figure={fig}", "height=70", "name=ADA")
    text, code, nxt = stone("build")
    assert code == 0 and nxt.startswith("stone colors"), text
    text, code, nxt = stone("colors")
    text, code, nxt = stone(*nxt.split()[1:])
    assert nxt == cli.DONE_NEXT, text
    painted = jobenv / "stone-job" / "figure.3mf"
    before = painted.read_bytes()
    text, code, nxt = stone("build")
    assert code == 0, text
    assert painted.exists() and painted.read_bytes() == before, text
    assert nxt == cli.DONE_NEXT and "Nothing changed" in text, text
    assert status_json_colors(jobenv), "the colors were dropped from status"
    # a real change still rebuilds, and drops the old paint
    stone("set", "figure", f"figure={fig}", "height=72", "name=ADA")
    text, code, nxt = stone("build")
    assert "Nothing changed" not in text and not painted.exists(), text


def _stub_figure(monkeypatch, fig: Path) -> list:
    """figure_step stand-in for the tier-S flow (no figure= given): records the figure as made."""
    calls = []

    def made(job, r, params, out):
        calls.append(1)
        d = job.image_dir / "figure"
        d.mkdir(parents=True, exist_ok=True)
        (d / "latest.txt").write_text(str(fig))
        return fig
    monkeypatch.setattr(cli, "figure_step", made)
    return calls


def _painted_job(jobenv, monkeypatch, tmp_path):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    d = tmp_path / "abc123"
    d.mkdir()
    fig = d / "figure.stl"
    figure.repair(standin(tmp_path / "lift.glb"), fig)
    _style_picture(d / "style.png")
    calls = _stub_figure(monkeypatch, fig)
    stone("new", 'A figure 70 mm tall with "ADA" on the base, all white but the body, which is black')
    stone("set", "figure", "height=70", "name=ADA")
    text, code, nxt = stone("build")
    assert code == 0 and nxt.startswith("stone colors"), text
    text, code, nxt = stone("colors")
    text, code, nxt = stone(*nxt.split()[1:])
    assert nxt == cli.DONE_NEXT, text
    return fig, calls, jobenv / "stone-job" / "figure.3mf"


def test_the_tier_s_flow_skips_a_no_op_build_before_the_figure_step(jobenv, monkeypatch, openscad, tmp_path):
    """Review PR 9 second-F4: S.md sets only height and name, so the figure comes from the figure
    step. A build after stone colors must skip without running that step again."""
    fig, calls, painted = _painted_job(jobenv, monkeypatch, tmp_path)
    before = painted.read_bytes()
    text, code, nxt = stone("build")
    assert "Nothing changed" in text and nxt == cli.DONE_NEXT, text
    assert painted.read_bytes() == before
    assert len(calls) == 1, "the figure step ran again on a build that changed nothing"


def test_a_new_figure_at_the_same_path_rebuilds(jobenv, monkeypatch, openscad, tmp_path):
    """Review PR 9 first-F2: the skip must key on what the build reads, not on a path string."""
    fig, calls, painted = _painted_job(jobenv, monkeypatch, tmp_path)
    m = trimesh.load(fig)
    m.apply_scale([1.0, 1.0, 0.9])
    m.export(fig)
    text, code, nxt = stone("build")
    assert "Nothing changed" not in text, text


def test_an_edited_recipe_source_rebuilds(jobenv, monkeypatch, openscad, tmp_path):
    fig, calls, painted = _painted_job(jobenv, monkeypatch, tmp_path)
    own = tmp_path / "edited_recipes"
    shutil.copytree(REPO / "recipes", own)
    monkeypatch.setenv("STONE_RECIPES", str(own))
    text, code, nxt = stone("build")
    assert "Nothing changed" in text, text  # a copy with the same source is the same recipe
    with open(own / "figure" / "recipe.scad", "a") as f:
        f.write("\n// edited\n")
    text, code, nxt = stone("build")
    assert "Nothing changed" not in text, text


def test_the_style_prompt_takes_the_kind_wikidata_gave_the_found_subject(jobenv, monkeypatch):
    """An elephant or a golden retriever is an animal and a tower is an object, though neither
    word is in the animal list; only a photo the owner gives falls back to the request's words."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    stone("new", "A figurine of an african elephant, 80 mm tall")
    job = cli.Job(jobenv / "stone-job")
    found = job.image_dir / "found"
    found.mkdir(parents=True)
    (found / "found.json").write_text(json.dumps({"query": "african elephant", "kind": "animal"}))
    assert cli.figure_who(job, "chibi") == "animal"
    (found / "found.json").write_text(json.dumps({"query": "Eiffel Tower", "kind": "object"}))
    assert cli.figure_who(job, "chibi") == "object"
    assert cli.figure_who(job, "object") == "object"


ELON_LOOK = ("The person has light brown, wavy hair, no glasses, no facial hair, appears to be middle-aged, "
             "and is of fair complexion. They are wearing a black suit jacket, a white shirt, and a black tie.")


def test_a_person_without_glasses_gets_no_glasses_in_the_style_prompt():
    """The Elon render came back with thick black glasses: the prompt named glasses twice, once in
    the likeness line and once as 'no glasses' from the description, and naming them draws them."""
    p = figure.prompt("chibi", "person", ELON_LOOK)
    assert "glasses" not in p.lower() and "facial hair" not in p.lower()


def test_a_person_is_styled_from_the_photo_not_from_the_description():
    """Owner: "Those things look nothing like elon". The description's "light brown hair" made his
    hair too light: the blind likeness judge gave 8 with the description in the prompt and 9 on
    both seeds without it, so for a person the photo alone carries the look."""
    p = figure.prompt("chibi", "person", ELON_LOOK)
    assert "light brown" not in p and "middle-aged" not in p
    assert "the real face from the photo" in p and "the same jaw" in p and "large head" in p
    assert "expression" in p and "smile" not in p  # a smile he does not have was drawn on
    assert "friendly smile" in figure.prompt("chibi", "animal")  # animals keep the chibi look
    assert "light brown" in figure.prompt("chibi", "animal", "light brown fur.")


def test_a_person_with_glasses_keeps_them_exactly():
    p = figure.prompt("chibi", "person", "The person has short grey hair and thin round glasses. They wear a jacket "
                      "with no tie.")
    assert "same frame shape" in p and "tie" not in p


def test_the_photo_check_decides_the_glasses_over_the_description():
    """The traits check looked at the photo; the description is one model's sentence about it."""
    assert "same frame shape" in figure.prompt("chibi", "person", "", glasses=True)
    assert "glasses" not in figure.prompt("chibi", "person", "He wears glasses.", glasses=False).lower()


def test_the_positive_words_of_a_description():
    assert figure.positive("short hair, no beard, without a hat, a red shirt.") == "short hair, a red shirt."
    assert figure.positive("He is not wearing glasses. He has a black jacket.") == "He has a black jacket."


def _models(tmp_path, monkeypatch, answers):
    """Fake describe, style and lift; traits answers by file name. Returns the style calls."""
    calls = []

    def fake_style(photos, out, style_name, who, seed, extra="", glasses=None, plain=False):
        calls.append((photos[0].name, seed) + (("plain",) if plain else ()))
        out.write_bytes(f"render {seed}".encode())
        return out

    def fake_traits(images, who, log):
        return [answers(Path(i).name) for i in images]

    monkeypatch.setattr(figure, "describe", lambda photo, out, who: (out.write_text("hair\n"), "hair")[1])
    monkeypatch.setattr(figure, "style", fake_style)
    monkeypatch.setattr(figure, "lift", lambda render, out, seed: standin(out))
    monkeypatch.setattr(figure, "traits", fake_traits)
    monkeypatch.setattr(figure, "face_crop", lambda photo, out: None)
    return calls


BARE = {"face": True, "glasses": False, "beard": False, "hat": False}


def test_a_photo_with_no_face_never_sets_the_likeness(tmp_path, monkeypatch):
    """For "DHH" the finder once put a protein first, and the describe model then wrote a man with
    gold glasses from it. Only a photo that shows the face may lead; a cap goes behind a bare head."""
    photos = []
    for name in ("protein.png", "cap.jpg", "talk.jpg"):
        photos.append(tmp_path / name)
        photos[-1].write_bytes(name.encode())
    said = []
    calls = _models(tmp_path, monkeypatch, lambda n: {"protein.png": {"face": False},
                                                      "cap.jpg": {**BARE, "hat": True}}.get(n, BARE))
    figure.make(photos, tmp_path / "fig", say=said.append)
    assert calls[0][0] == "talk.jpg"
    assert any("Left out 1 photo with no face" in x for x in said)


def test_no_photo_with_a_face_stops_the_figure_with_a_way_on(tmp_path, monkeypatch):
    photo = tmp_path / "car.jpg"
    photo.write_bytes(b"car")
    _models(tmp_path, monkeypatch, lambda n: {"face": False})
    with pytest.raises(figure.FigureProblem, match="stone image"):
        figure.make([photo], tmp_path / "fig", say=lambda s: None)


def test_a_render_that_adds_glasses_is_styled_again_with_the_next_seed(tmp_path, monkeypatch):
    """The Elon render came back with thick black glasses he does not wear."""
    photo = tmp_path / "elon.jpg"
    photo.write_bytes(b"elon")
    calls = _models(tmp_path, monkeypatch,
                    lambda n: {**BARE, "glasses": n == "style-7.png"})
    said = []
    fig = figure.make([photo], tmp_path / "fig", seed=7, say=said.append)
    assert [c[1] for c in calls] == [7, 8]
    assert (fig.parent / "style.png").read_bytes() == b"render 8"
    assert json.loads((fig.parent / "check.json").read_text())["differs"] == []
    assert any("added glasses" in x and "seed 8" in x for x in said)


def test_a_render_with_lettering_on_the_clothes_is_styled_again_in_plain_colors(tmp_path, monkeypatch):
    """DHH's lead photo is him in a race suit, and the render copied its sponsor logos and an
    "Abu Dhabi Racing" shirt: lettering a figure cannot print or paint, and other people's marks."""
    photo = tmp_path / "dhh.jpg"
    photo.write_bytes(b"dhh")
    calls = _models(tmp_path, monkeypatch, lambda n: {**BARE, "lettering": n in ("dhh.jpg", "style-7.png")})
    said = []
    fig = figure.make([photo], tmp_path / "fig", seed=7, say=said.append)
    assert calls == [("dhh.jpg", 7), ("dhh.jpg", 8, "plain")]
    assert (fig.parent / "style.png").read_bytes() == b"render 8"
    assert any("lettering" in x and "plain" in x and "seed 8" in x for x in said)


def test_a_render_with_plain_clothes_keeps_the_clothes_it_has():
    """The plain look is only for a render that came back with lettering: as the first try it
    turned Jensen's leather jacket into a sweater."""
    same, plain = figure.prompt("chibi", "person"), figure.prompt("chibi", "person", plain=True)
    assert "the same clothes," in same and "plain solid colors" not in same
    assert "plain solid colors" in plain and "the same clothes," not in plain


def test_the_render_check_asks_about_lettering_on_the_clothes():
    import importlib.util
    spec = importlib.util.spec_from_file_location("describe", Path(__file__).resolve().parents[1] / "tools" / "figure" / "describe.py")
    d = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(d)
    assert "logo" in d.TRAITS["person"]["lettering"]


def test_a_render_that_never_matches_keeps_the_closest(tmp_path, monkeypatch):
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"p")
    beard = {"style-7.png": {**BARE, "glasses": True, "beard": True}, "style-8.png": {**BARE, "glasses": True}}
    calls = _models(tmp_path, monkeypatch, lambda n: beard.get(n, {**BARE, "hat": True, "beard": True}
                                                               if n.startswith("style") else BARE))
    fig = figure.make([photo], tmp_path / "fig", seed=7, say=lambda s: None)
    assert [c[1] for c in calls] == [7, 8, 9]
    assert (fig.parent / "style.png").read_bytes() == b"render 8"


def test_the_face_crop_leads_the_style_references(tmp_path, monkeypatch):
    """With the whole photo alone the face is a few pixels of a 768 px render and comes out generic;
    the face crop first and the photo second took the likeness judge from 6 to 9 on Elon."""
    photo = tmp_path / "elon.jpg"
    photo.write_bytes(b"elon")
    refs = []
    _models(tmp_path, monkeypatch, lambda n: BARE)
    monkeypatch.setattr(figure, "style", lambda photos, out, *a, **k: (refs.append([p.name for p in photos]),
                                                                      out.write_bytes(b"r"))[1] and out)

    def crop(src, out):
        out.write_bytes(b"face")
        return out
    monkeypatch.setattr(figure, "face_crop", crop)
    figure.make([photo], tmp_path / "fig", say=lambda s: None)
    assert refs[0] == ["face.png", "elon.jpg"]


def test_no_face_crop_for_an_animal_or_when_it_fails(tmp_path, monkeypatch):
    photo = tmp_path / "dog.jpg"
    photo.write_bytes(b"dog")
    refs = []
    _models(tmp_path, monkeypatch, lambda n: BARE)
    monkeypatch.setattr(figure, "style", lambda photos, out, *a, **k: (refs.append([p.name for p in photos]),
                                                                      out.write_bytes(b"r"))[1] and out)
    monkeypatch.setattr(figure, "face_crop", lambda src, out: (_ for _ in ()).throw(AssertionError("cropped")))
    figure.make([photo], tmp_path / "a", who="animal", say=lambda s: None)
    monkeypatch.setattr(figure, "face_crop", lambda src, out: None)
    figure.make([photo], tmp_path / "p", say=lambda s: None)
    assert refs == [["dog.jpg"], ["dog.jpg"]]


def test_face_crop_fails_open_without_a_face_or_a_venv(tmp_path, monkeypatch):
    monkeypatch.setenv("STONE_MFLUX", str(tmp_path / "nowhere"))
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"p")
    assert figure.face_crop(photo, tmp_path / "face.png") is None


def test_a_fictional_character_is_styled_as_that_character(jobenv, monkeypatch):
    """Review of PR 23: Mario or a superhero is no human on Wikidata, and was styled as an object."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    stone("new", "A chibi figure of Snoopy, 70 mm tall")
    job = cli.Job(jobenv / "stone-job")
    found = job.image_dir / "found"
    found.mkdir(parents=True)
    (found / "found.json").write_text(json.dumps({"query": "Snoopy", "kind": "character"}))
    assert cli.figure_who(job, "chibi") == "character"
    p = figure.prompt("chibi", "character")
    assert "this exact character" in p and "costume" in p


def test_the_owners_own_photo_is_never_stopped_by_the_face_check(tmp_path, monkeypatch):
    """Review of PR 23: a small or side-on photo the owner gave read as no face, with no way on."""
    photo = tmp_path / "source.jpg"
    photo.write_bytes(b"me")
    calls = _models(tmp_path, monkeypatch, lambda n: {"face": False} if n == "source.jpg" else BARE)
    figure.make([photo], tmp_path / "fig", say=lambda s: None)
    assert calls[0][0] == "source.jpg"


def test_a_render_is_checked_only_for_what_the_photo_check_answered(tmp_path, monkeypatch):
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"p")
    asked = []
    _models(tmp_path, monkeypatch, lambda n: {"face": True})
    real = figure.traits
    monkeypatch.setattr(figure, "traits", lambda images, who, log: (asked.append(images), real(images, who, log))[1])
    figure.make([photo], tmp_path / "fig", say=lambda s: None)
    assert len(asked) == 1  # the photo only: no glasses, beard or hat answer to hold a render to


def _dies_mid_write(target_arg):
    """A stand-in subprocess.run that writes half a file to the path it was given, then fails."""
    def run(cmd, **kw):
        Path(target_arg(cmd)).write_bytes(b"half")
        return type("R", (), {"returncode": -9})()
    return run


def _writes(target_arg, data=b"done"):
    def run(cmd, **kw):
        Path(target_arg(cmd)).write_bytes(data)
        return type("R", (), {"returncode": 0})()
    return run


def test_a_style_cut_off_mid_write_leaves_no_picture_under_the_final_name(tmp_path, monkeypatch):
    """first-F5: the harness kills a slow build mid-write, and the next run took the half picture as done."""
    monkeypatch.setattr(figure, "_mflux_bin", lambda: tmp_path / "mflux-generate")
    monkeypatch.setattr(figure, "_style_model", lambda: [])
    out_arg = lambda cmd: cmd[cmd.index("--output") + 1]
    out = tmp_path / "style.png"
    monkeypatch.setattr(figure.subprocess, "run", _dies_mid_write(out_arg))
    with pytest.raises(figure.FigureProblem):
        figure.style([tmp_path / "p.jpg"], out, "chibi", "person", 7)
    assert not out.exists()
    monkeypatch.setattr(figure.subprocess, "run", _writes(out_arg))
    assert figure.style([tmp_path / "p.jpg"], out, "chibi", "person", 7).read_bytes() == b"done"
    assert [p.name for p in tmp_path.glob("style*.png")] == ["style.png"]


def test_a_lift_cut_off_mid_write_leaves_no_mesh_under_the_final_name(tmp_path, monkeypatch):
    monkeypatch.setenv("STONE_LIFT", "lift")
    out = tmp_path / "lift.glb"
    monkeypatch.setattr(figure.subprocess, "run", _dies_mid_write(lambda cmd: cmd[2]))
    with pytest.raises(figure.FigureProblem):
        figure.lift(tmp_path / "style.png", out, 7)
    assert not out.exists()
    monkeypatch.setattr(figure.subprocess, "run", _writes(lambda cmd: cmd[2]))
    assert figure.lift(tmp_path / "style.png", out, 7).read_bytes() == b"done"
    assert [p.name for p in tmp_path.glob("lift*.glb")] == ["lift.glb"]


def test_a_repair_that_dies_mid_write_leaves_no_figure_under_the_final_name(tmp_path, monkeypatch):
    src = standin(tmp_path / "lift.glb")
    out = tmp_path / "figure.stl"

    def half(self, path, *a, **k):
        Path(path).write_bytes(b"half")
        raise OSError("killed")
    with monkeypatch.context() as m:
        m.setattr(trimesh.Trimesh, "export", half)
        with pytest.raises(OSError):
            figure.repair(src, out)
    assert not out.exists()
    figure.repair(src, out)
    assert trimesh.load(out).is_watertight and out.with_suffix(".json").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["figure.json", "figure.stl", "lift.glb"]


def test_a_style_check_cut_off_while_copying_leaves_no_picture_under_the_final_name(tmp_path, monkeypatch):
    """style_checked copies the kept try onto style.png; a half copy must not stand as the render."""
    monkeypatch.setattr(figure, "style", lambda photos, out, *a, **k: (out.write_bytes(b"render"), out)[1])
    monkeypatch.setattr(figure, "traits", lambda *a, **k: [{"glasses": False}])

    def half(src, dst, *a, **k):
        Path(dst).write_bytes(b"half")
        raise OSError("killed")
    monkeypatch.setattr(figure.shutil, "copyfile", half)
    out = tmp_path / "style.png"
    with pytest.raises(OSError):
        figure.style_checked([tmp_path / "p.jpg"], out, "chibi", "person", 7, "", {"glasses": False})
    assert not out.exists()


def test_the_figure_seed_follows_the_eval_run_seed_unless_one_is_set(jobenv, monkeypatch, tmp_path):
    """Donovan, 2026-11-19: the held-out bar ran each case on 2 seeds, but the figure always used
    seed 7, so both seeds painted one figure. The eval harness sets STONE_FIGURE_SEED to the run's
    seed; a seed set with stone set still wins."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    stone("new", "A mini figure of Ada, 70 mm tall")
    job = cli.Job(jobenv / "stone-job")
    job.image_dir.mkdir(parents=True, exist_ok=True)
    _style_picture(job.image_dir / "source.png")
    seeds = []

    def fake_make(photos, out, style_name="chibi", who="person", seed=7, extra="", say=print, shown=None):
        seeds.append(seed)
        raise figure.FigureProblem("stop here")

    monkeypatch.setattr(figure, "make", fake_make)
    stone("set", "figure", "height=70")
    monkeypatch.setenv("STONE_FIGURE_SEED", "3")
    stone("build")
    monkeypatch.setenv("STONE_FIGURE_SEED", "4")
    stone("build")
    stone("set", "seed=11")
    stone("build")
    assert seeds == [3, 4, 11], seeds
    src = (REPO / "evals" / "run.py").read_text()
    assert '"STONE_FIGURE_SEED": str(a.seed)' in src


def _named_figure_job(jobenv, monkeypatch, tmp_path):
    """A built figure job whose request names a part's color: the jacket black, the rest white."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    d = tmp_path / "abc123"
    d.mkdir()
    fig = d / "figure.stl"
    figure.repair(standin(tmp_path / "lift.glb"), fig)
    _style_picture(d / "style.png")
    stone("new", 'A figure 70 mm tall with "ADA" on the base, all white but the jacket, which is black')
    stone("set", "figure", f"figure={fig}", "height=70", "name=ADA")
    text, code, nxt = stone("build")
    assert code == 0 and nxt.startswith("stone colors"), text
    if nxt == "stone colors":
        text, code, nxt = stone("colors")
    assert "top=black" in nxt, nxt
    return nxt


def test_a_color_the_request_names_is_never_given_up_for_a_rough_edge(jobenv, monkeypatch, openscad, tmp_path):
    """Jensen r3 (Mac, 2026-11-19, 2 of 2 seeds): the jacket's edge failed the smoothness check,
    stone colors gave the jacket the rest color, and NEXT then said the part was ready with a
    white jacket the person had asked to be black. A color the request names is never given up:
    when the edge cannot be made clean, the person decides."""
    import numpy as np

    from smoothstone import colors

    nxt = _named_figure_job(jobenv, monkeypatch, tmp_path)
    real = colors.ledges

    def always_a_ledge(V, F, face_fil, lines):  # every two-color paint climbs a ledge
        out = real(V, F, face_fil, lines)
        if len(np.unique(face_fil)) > 1 and out:
            out[0] = {**out[0], "area": 1.0, "angle": 15.0, "fil": int(face_fil.max()), "faces": 9}
        return out

    monkeypatch.setattr(colors, "ledges", always_a_ledge)
    for _ in range(6):
        if not nxt.startswith("stone colors"):
            break
        text, code, nxt = stone(*nxt.split()[1:])
        assert nxt != cli.DONE_NEXT, text  # never ready with the body's black given up
    assert nxt.startswith("ask the person"), (nxt, text)
    assert not (jobenv / "stone-job" / "figure.3mf").exists()
    # review first-F1: the question offers only what the tools can carry out. The figure file was
    # given, so no seed makes another; another color is a new request
    assert "print it as it is" not in nxt and "another seed" not in nxt, nxt
    assert 'stone new --force "<the request, with the color they name>"' in text, text
    # review second-F1: the model driving stone cannot answer for the person. Giving the jacket's
    # part the rest color itself, after the question, is refused like any mapping that drops it
    text, code, nxt = stone("colors", "top=white", "rest=white")
    assert "the request makes the jacket black" in text and nxt != cli.DONE_NEXT, text
    assert not (jobenv / "stone-job" / "figure.3mf").exists()
    # the person's answer, a jacket in white too, is a new request, and that one prints
    fig = jobenv.parent / "abc123" / "figure.stl"
    stone("new", "--force", 'A figure 70 mm tall with "ADA" on the base, all white')
    stone("set", "figure", f"figure={fig}", "height=70", "name=ADA")
    text, code, nxt = stone("build")
    for _ in range(4):
        if not nxt.startswith("stone colors"):
            break
        text, code, nxt = stone(*nxt.split()[1:])
    assert nxt == cli.DONE_NEXT, text
    assert (jobenv / "stone-job" / "figure.3mf").is_file()


def test_a_named_edge_on_a_figure_stone_made_offers_another_seed(jobenv, monkeypatch, openscad, tmp_path):
    """When the figure step made the figure, another seed makes another figure: the question offers
    it, and the command it gives builds the figure again with that seed."""
    import numpy as np

    from smoothstone import colors

    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    stone("new", 'A mini figure of Ada, 70 mm tall, with "ADA" on the base, all white but the jacket, which is black')
    job = cli.Job(jobenv / "stone-job")
    job.image_dir.mkdir(parents=True, exist_ok=True)
    _style_picture(job.image_dir / "source.png")
    made = tmp_path / "made"
    made.mkdir()
    figure.repair(standin(tmp_path / "lift.glb"), made / "figure.stl")
    _style_picture(made / "style.png")
    seeds = []

    def fake_make(photos, out, style_name="chibi", who="person", seed=7, extra="", say=print, shown=None):
        seeds.append(seed)
        out.mkdir(parents=True, exist_ok=True)
        (out / "latest.txt").write_text(str(made / "figure.stl"))  # as make does
        return made / "figure.stl"

    monkeypatch.setattr(figure, "make", fake_make)
    monkeypatch.delenv("STONE_FIGURE_SEED", raising=False)
    stone("set", "figure", "height=70", "name=ADA")
    text, code, nxt = stone("build")
    assert nxt.startswith("stone colors"), text
    real = colors.ledges

    def always_a_ledge(V, F, face_fil, lines):
        out = real(V, F, face_fil, lines)
        if len(np.unique(face_fil)) > 1 and out:
            out[0] = {**out[0], "area": 1.0, "angle": 15.0, "fil": int(face_fil.max()), "faces": 9}
        return out

    monkeypatch.setattr(colors, "ledges", always_a_ledge)
    for _ in range(6):
        if not nxt.startswith("stone colors"):
            break
        text, code, nxt = stone(*nxt.split()[1:])
    assert nxt.startswith("ask the person") and "another seed" in nxt, (nxt, text)
    line = next(ln for ln in text.splitlines() if ln.startswith("If the person wants the figure made again"))
    assert "stone set seed=8, then stone build" in line, line
    text, code, _ = stone("set", "seed=8")
    assert code == 0, text
    stone("build")
    assert seeds[-1] == 8, seeds


def test_a_named_part_the_figure_has_no_region_for_asks_for_another_figure(jobenv, monkeypatch, openscad, tmp_path):
    """Review second-S1: shoes the region finder merged into the trousers have no region, so no
    mapping can paint them black. NEXT asks for another figure, never for a mapping that cannot be.
    Here the jacket has no region of its own."""
    _named_figure_job(jobenv, monkeypatch, tmp_path)
    real = cli._part_regions
    monkeypatch.setattr(cli, "_part_regions", lambda info, key: [] if key == "top" else real(info, key))
    text, code, nxt = stone("colors", "rest=white")
    assert nxt.startswith("ask the person: the figure file has no separate jacket"), (nxt, text)
    assert "stone set figure figure=" in text, text
    assert not (jobenv / "stone-job" / "figure.3mf").exists()


def test_a_named_color_that_fairing_shrinks_away_is_never_called_ready(jobenv, monkeypatch, openscad, tmp_path):
    """Review first-F2: the named colors are checked on the paint itself after fairing, not only on
    the mapping. A wide smoothing that leaves the black jacket mostly white asks the person."""
    import numpy as np

    from smoothstone import colors

    nxt = _named_figure_job(jobenv, monkeypatch, tmp_path)
    real_faults, real_cut = colors.edge_faults, colors.smooth_cut
    calls = []

    def rough_once(lines):  # the first paint has a jagged edge, so the edges are faired
        calls.append(1)
        out = real_faults(lines)
        if len(calls) == 1 and lines:
            out = out + [{**max(lines, key=lambda x: x["length"]), "ratio": 1.5}]
        return out

    def faired_away(vertices, faces, face_fil, radius, fixed=None):  # the faired paint loses the black
        V, F, ff, parent = real_cut(vertices, faces, face_fil, radius=radius, fixed=fixed)
        if radius > colors.FAIR_RADII[0]:
            vals, n = np.unique(ff, return_counts=True)
            ff = np.where(ff == ff, vals[np.argmax(n)], ff)
        return V, F, ff, parent

    monkeypatch.setattr(colors, "edge_faults", rough_once)
    monkeypatch.setattr(colors, "smooth_cut", faired_away)
    text, code, nxt = stone(*nxt.split()[1:])
    assert "leaves the top with under 50% of its own color" in text, text
    assert nxt.startswith("ask the person"), nxt
    assert not (jobenv / "stone-job" / "figure.3mf").exists()


def test_a_mapping_that_drops_a_named_color_is_refused(jobenv, monkeypatch, openscad, tmp_path):
    """Ready means every part the request colors has its color: a mapping that leaves the black
    jacket white writes no file and points back at one that keeps it."""
    _named_figure_job(jobenv, monkeypatch, tmp_path)
    text, code, nxt = stone("colors", "rest=white")
    assert "the request makes the jacket black" in text, text
    assert nxt.startswith("stone colors") and "black" in nxt and nxt != cli.DONE_NEXT, nxt
    assert not (jobenv / "stone-job" / "figure.3mf").exists()
    text, code, nxt = stone(*nxt.split()[1:])
    assert nxt == cli.DONE_NEXT, text
    # naming the jacket's part with another color is no way around it while nobody asked the person
    text, code, nxt = stone("colors", "top=white", "rest=white")
    assert "the request makes the jacket black" in text and nxt != cli.DONE_NEXT, text
    assert not (jobenv / "stone-job" / "figure.3mf").exists()


def test_a_rough_edge_is_faired_before_any_color_is_given_up(jobenv, monkeypatch, openscad, tmp_path):
    """A boundary that fails the smoothness check is first cut again along a wider smoothing
    (colors.FAIR_RADII); only then is anything given up."""
    from smoothstone import colors

    nxt = _named_figure_job(jobenv, monkeypatch, tmp_path)
    real = colors.edge_faults
    calls = []

    def rough_once(lines):  # the first paint has a jagged edge, the faired one does not
        calls.append(1)
        out = real(lines)
        if len(calls) == 1 and lines:
            ln = max(lines, key=lambda x: x["length"])
            out = [{**ln, "ratio": colors.JAGGED + 0.05}]
        return out

    monkeypatch.setattr(colors, "edge_faults", rough_once)
    text, code, nxt = stone(*nxt.split()[1:])
    assert "faired" in text and nxt == cli.DONE_NEXT, text
    assert "black" in status_json_colors(jobenv)["mapping"]


def test_a_lift_missing_a_module_is_a_setup_problem(tmp_path, monkeypatch):
    """Mac verify run 2026-11-19: lift.py raised ModuleNotFoundError (hy3dgen) and stone said
    only "uv failed, see lift.log", so the build looked worth retrying."""
    monkeypatch.setenv("STONE_LIFT", "lift")

    def run(cmd, stdout=None, **k):
        stdout.write("Traceback (most recent call last):\n  File \"lift.py\", line 9\n"
                     "ModuleNotFoundError: No module named 'hy3dgen'\n")
        return type("R", (), {"returncode": 1})()

    monkeypatch.setattr(figure.subprocess, "run", run)
    with pytest.raises(figure.FigureProblem) as e:
        figure.lift(tmp_path / "style.png", tmp_path / "lift.glb", 7)
    assert e.value.setup and "hy3dgen" in str(e.value) and figure.SETUP in str(e.value)


def test_a_lift_that_fails_for_another_reason_is_not_a_setup_problem(tmp_path, monkeypatch):
    monkeypatch.setenv("STONE_LIFT", "lift")
    log = tmp_path / "lift.log"
    log.write_text("ModuleNotFoundError: No module named 'old'\n")  # an earlier run's, fixed since

    def run(cmd, stdout=None, **k):
        stdout.write("RuntimeError: MPS backend out of memory\n")
        return type("R", (), {"returncode": 1})()

    monkeypatch.setattr(figure.subprocess, "run", run)
    with pytest.raises(figure.FigureProblem) as e:
        figure.lift(tmp_path / "style.png", tmp_path / "lift.glb", 7)
    assert not e.value.setup


def _figure_with_photo():
    stone("new", "A mini figure of my dog, 80 mm tall")
    stone("set", "figure", "height=80")
    photo = REPO / "examples" / "dog.png"
    if not photo.exists():
        photo = REPO / "evals" / "heldout" / "dog.png"
    assert stone("image", str(photo))[2] == "stone build"


def test_a_figure_step_that_is_not_set_up_asks_the_person_instead_of_building_again(jobenv, monkeypatch):
    """Mac verify run 2026-11-19 (log.json of r3_black_shoes s1): the lift was not set up, NEXT
    said stone build every time, and LFM3 ran the same failing build 4 times and spent all 10 steps."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    _figure_with_photo()

    def make(*a, **k):
        raise figure.FigureProblem("lift.py is not set up (ModuleNotFoundError: No module named 'hy3dgen'), "
                                   f"run {figure.SETUP} once", setup=True)

    monkeypatch.setattr(figure, "make", make)
    text, code, nxt = stone("build")
    assert code == 1 and nxt.startswith("ask the person") and "setup.sh" in nxt, text
    assert stone("status")[2] == nxt
    assert nxt.endswith("When they say to go on: stone build"), nxt  # review of #37: a way to resume


def test_a_lift_program_that_is_missing_is_a_setup_problem(tmp_path, monkeypatch):
    """Review of #37: with no uv (or a STONE_LIFT that does not exist) the run raises
    FileNotFoundError, which must take the setup path, not stone's internal error."""
    monkeypatch.setenv("STONE_LIFT", str(tmp_path / "no-such-lift"))
    with pytest.raises(figure.FigureProblem) as e:
        figure.lift(tmp_path / "style.png", tmp_path / "lift.glb", 7)
    assert e.value.setup and figure.SETUP in str(e.value)


def test_the_same_failure_twice_in_a_row_asks_the_person(jobenv, monkeypatch):
    """A failure that is not setup: one retry, as NEXT says, then a second identical failure stops
    the model instead of a third try; a status between does not count as a change."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    _figure_with_photo()

    def make(*a, **k):
        raise figure.FigureProblem("lift.py failed, see lift.log")

    monkeypatch.setattr(figure, "make", make)
    assert stone("build")[2] == "stone build"
    stone("status")
    text, code, nxt = stone("build")
    assert code == 1 and nxt.startswith("ask the person") and "lift.py failed" in nxt, text
    assert nxt.endswith("say to try again: stone build"), nxt


def test_a_look_between_two_identical_failures_still_counts_them_in_a_row(jobenv, monkeypatch):
    """Review of #37: build, then show (or a slip), then the same failing build must still stop:
    a command that only looks does not end the run of failures."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    _figure_with_photo()

    def make(*a, **k):
        raise figure.FigureProblem("lift.py failed, see lift.log")

    monkeypatch.setattr(figure, "make", make)
    assert stone("build")[2] == "stone build"
    stone("show", "figure")
    stone("bogus")
    assert stone("build")[2].startswith("ask the person")


def test_a_figure_build_says_each_long_step_on_the_terminal_as_it_starts(jobenv, monkeypatch, capsys):
    """Donovan, 2026-11-20, a Sam Altman figure on the Mac: stone build printed nothing for minutes
    while it described, styled and lifted, so it looked hung. Each step's line reaches the terminal
    as it starts, on stderr, and stdout still ends with NEXT."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    _figure_with_photo()
    capsys.readouterr()

    def make(*a, say=print, **k):
        say("Lifting the render to 3D (Hunyuan3D-2mini, about 4 minutes)...")
        assert "Lifting the render" in capsys.readouterr().err  # shown before the step ends
        raise figure.FigureProblem("lift.py failed, see lift.log")

    monkeypatch.setattr(figure, "make", make)
    text, code, nxt = stone("build")
    assert nxt == "stone build" and "Lifting" not in text, text
    assert "Lifting the render to 3D" in (jobenv / "stone-job" / "log.txt").read_text()


def test_find_asks_which_person_when_two_well_known_people_share_the_name(jobenv, monkeypatch):
    """Donovan, 2026-11-20: "For figures it needs to ensure the figure referenced is the correct one they want"."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    from smoothstone import find as findtool
    asked = []

    def which(q, d, n=4):
        asked.append(q)
        raise findtool.WhichOne("Michael Jordan", [
            {"id": "Q41421", "label": "Michael Jordan", "description": "American basketball player"},
            {"id": "Q3308285", "label": "Michael I. Jordan", "description": "American computer scientist"}])

    monkeypatch.setattr(findtool, "fetch", which)
    stone("new", "A mini figure of Michael Jordan, 80 mm tall")
    text, code, nxt = stone("find")
    assert asked == ["Michael Jordan"]  # a size says nothing about which one
    assert nxt.startswith("ask the person: which Michael Jordan do you mean")
    assert "computer scientist" in nxt and "basketball player" in nxt
    assert 'stone find "Michael Jordan, ' in nxt
    assert stone("status")[2] == nxt  # a compacted model finds the question again


def _plinth(tmp_path, openscad, **given):
    """Build the figure recipe with the stand-in figure; (mesh, results by name)."""
    from smoothstone import check, recipes, scad

    fig = tmp_path / "figure.stl"
    figure.repair(standin(tmp_path / "lift.glb"), fig)
    r = recipes.load("figure", REPO / "recipes")
    params = r.merged({"figure": str(fig), **given})
    run = scad.build_stl(openscad, r, params, tmp_path / "part.stl")
    assert run.ok, run.error
    res = {x.name: x for x in check.check_stl(tmp_path / "part.stl", recipe=r, params=params, log=run.log)}
    return check._load(tmp_path / "part.stl"), res


def test_hex_plinth_name_stands_proud_on_the_front_face(tmp_path, openscad, monkeypatch):
    """The audit: on a hex plinth the letters sat on an arc while the faces are flat, so the outer
    letters of a 4 letter name sank into the faces (and the front of the hex was a corner)."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    m, res = _plinth(tmp_path, openscad, base="hex", name="IIIIII")
    assert all(x.ok for x in res.values()), [x for x in res.values() if not x.ok]
    bd = 2 * m.bounds[1][0]  # the hex's corners lie on X
    face = (bd / 2 - 1.2) * np.cos(np.radians(30))  # the drum's front face, base_h 12: c = 1.2
    seg = trimesh.intersections.mesh_plane(m, [0, 0, 1], [0, 0, 2.4 + 8.4 / 2])
    front = seg[(seg[:, :, 1] < -(face + 0.6)).all(axis=1)]  # letters stand 0.9 mm proud of the face
    spans = sorted((min(a, b), max(a, b)) for a, b in front[:, :, 0])
    letters = []  # each I's front, merged from its segments
    for lo, hi in spans:
        if letters and lo <= letters[-1][1] + 0.05:
            letters[-1][1] = max(letters[-1][1], hi)
        else:
            letters.append([lo, hi])
    assert len(letters) == 6, letters


def test_short_plinth_name_fix_is_base_h_12(jobenv, monkeypatch, openscad, tmp_path):
    """base_h 8 leaves 3.6 mm letters, strokes of 0.54 mm: too thin for a 0.4 mm nozzle."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    fig = tmp_path / "figure.stl"
    figure.repair(standin(tmp_path / "lift.glb"), fig)
    stone("new", 'A figure 70 mm tall with "ADA" on a low base')
    stone("set", "figure", f"figure={fig}", "height=70", "name=ADA", "base_h=8")
    text, code, nxt = stone("build")
    assert code == 1 and "FIX: text letter strokes 0.54 mm" in text, text
    assert nxt == "stone set base_h=12", text
    stone("set", "base_h=12")
    text, code, nxt = stone("build")
    assert "Part ready" in text, text


def test_figure_without_plinth_gets_the_bed_chamfer(tmp_path, openscad, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    m, res = _plinth(tmp_path, openscad, base="none")
    assert res["bed_edge"].ok, res["bed_edge"].detail
    # two small feet and no plinth: the stand-in tips (test_a_figure_that_tips_gets_a_plinth)
    assert all(x.ok for x in res.values() if x.name != "tipping"), [x for x in res.values() if not x.ok]


def test_a_figure_that_tips_gets_a_plinth(tmp_path, openscad, monkeypatch):
    """A figure on two small feet with no plinth leans 8 degrees before it falls: a nozzle bump
    knocks it over mid-print. The fix is the plinth."""
    from smoothstone import recipes

    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    r = recipes.load("figure", REPO / "recipes")
    _, got = _plinth(tmp_path, openscad, base="none")
    res = [x for x in got.values() if not x.ok]
    assert [x.name for x in res] == ["tipping"], res
    texts, nxt = cli.plan_fix(r, {"base": "none"}, res)
    assert nxt == "stone set base=round", (texts, nxt)


def _armed_mm(tmp_path, height=70.0):
    from smoothstone import printable

    fig = tmp_path / "figure.stl"
    figure.repair(armed(tmp_path / "lift.glb"), fig)
    m = trimesh.load(fig, force="mesh")
    m.apply_scale(printable.plinth({"height": height, "name": "ADA"})[0])
    return fig, m


def test_the_islands_check_finds_hanging_fingertips(tmp_path):
    """Donovan, 2026-11-20: "This needs to be utter and total perfection designed to be printed".
    Every lifted figure had fingertips that start in mid-air and stone said nothing about it."""
    from smoothstone import check, recipes

    _, m = _armed_mm(tmp_path)
    res = {r.name: r for r in check.check_mesh(m)}
    assert not res["islands"].ok and res["islands"].value == 2, res["islands"]
    assert "mm up" in res["islands"].detail
    sup = {r.name: r for r in check.check_mesh(m, recipe=recipes.load("figure"))}
    assert sup["islands"].ok and "supports on" in sup["islands"].detail


def test_struts_hold_up_every_fingertip(tmp_path):
    from smoothstone import check, printable

    fig, _ = _armed_mm(tmp_path)
    out = tmp_path / "braced.stl"
    struts, held, spots = printable.brace_figure(fig, out, {"height": 70, "name": "ADA"})
    assert len(struts) >= 2 and spots == [], (held, spots)
    b = trimesh.load(out, force="mesh")
    assert b.is_watertight and len(b.split(only_watertight=False)) == 1
    b.apply_scale(printable.plinth({"height": 70, "name": "ADA"})[0])
    res = {r.name: r for r in check.check_mesh(b)}
    assert res["islands"].ok and res["islands"].value == 0, res["islands"]
    for s in struts:  # steep enough to print without help, and short
        drop = s.top[2] - s.foot[2]
        assert drop > 0 and np.hypot(*(s.top[:2] - s.foot[:2])) <= printable.STRUT_SLOPE * drop + 1e-6
        assert np.linalg.norm(s.top - s.foot) <= printable.STRUT_REACH


def test_build_braces_the_figure(jobenv, openscad, monkeypatch, tmp_path):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    fig = tmp_path / "abc123" / "figure.stl"
    fig.parent.mkdir()
    figure.repair(armed(tmp_path / "lift.glb"), fig)
    stone("new", 'A figure 70 mm tall with "ADA" on the base')
    stone("set", "figure", f"figure={fig}", "height=70", "name=ADA")
    text, code, nxt = stone("build")
    assert code == 0 and "Part ready" in text, text
    assert "Built-in supports:" in text and "In the slicer" not in text, text
    assert "PASS islands: every layer stands on the one below" in text, text
    assert "PASS tipping" in text, text


def test_no_plinth_no_strut_below_the_bed(tmp_path):
    """Review first-F1 and second-F4 (PR #50): with base=none a low island far from the body got a
    strut standing on the bed, whose root reached below z = 0. With no plinth the spot goes to the
    slicer instead."""
    from smoothstone import printable

    post = trimesh.creation.box((6, 6, 70))
    post.apply_translation((0, 0, 35))
    arm = trimesh.creation.box((30, 6, 3))
    arm.apply_translation((14, 0, 68.5))
    drop = trimesh.creation.box((4, 4, 63))
    drop.apply_translation((26, 0, 4 + 31.5))  # its foot 4 mm over the bed, 23 mm from the post
    m = trimesh.boolean.union([post, arm, drop], engine="manifold")
    m.apply_scale(1 / 70)
    fig = tmp_path / "figure.stl"
    m.export(fig)
    out = tmp_path / "braced.stl"
    struts, _, spots = printable.brace_figure(fig, out, {"height": 70, "base": "none"})
    b = trimesh.load(out, force="mesh")
    assert b.bounds[0][2] > -1e-6, b.bounds  # nothing under the bed
    assert struts == [] and len(spots) == 1, (struts, spots)
    with_plinth = printable.brace_figure(fig, out, {"height": 70, "base_d": 80})
    assert len(with_plinth[0]) >= 1 and with_plinth[2] == []  # the plinth top holds it
    assert all(s.top[2] - s.foot[2] >= 2 * printable.PITCH for s in with_plinth[0])
