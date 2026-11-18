import json
import os
import subprocess
import sys
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from smoothstone import cli, recipes

REPO = Path(__file__).resolve().parent.parent


def stone(*argv):
    text, code = cli.run(list(argv))
    lines = text.splitlines()
    # contract: short output, one NEXT line, at the end, no tracebacks
    assert len(lines) <= cli.MAX_LINES, text
    assert lines[-1].startswith("NEXT: "), text
    assert sum(ln.startswith("NEXT:") for ln in lines) == 1, text
    assert "Traceback" not in text
    assert "\u2014" not in text and "\u2013" not in text
    for ln in lines:
        if "FIX" in ln.split(":")[0]:
            assert ln.startswith("FIX: "), ln
    return text, code, lines[-1][len("NEXT: "):]


def status_json(work):
    return json.loads((work / "stone-job" / "status.json").read_text())


def test_flow_end_to_end(jobenv, openscad):
    text, code, nxt = stone("status")
    assert "No job" in text and nxt == 'stone new "<what to make>"'

    text, code, nxt = stone("new", "a small plate with one hole")
    assert code == 0 and nxt == "stone recipes"
    assert "a small plate with one hole" in (jobenv / "stone-job" / "brief.md").read_text()

    text, code, nxt = stone("recipes", "plate")
    assert "_demo" not in text  # hidden
    text, code, nxt = stone("recipes", "--all", "plate")
    assert text.splitlines()[1].startswith("_demo  Rounded plate with a hole  (default size 60 x 40 x 4 mm)")
    assert nxt == "stone show _demo"

    text, code, nxt = stone("show", "_demo")
    assert "w = 60  (number, 10..200 mm) width along X" in text
    assert "Example: stone set _demo w=40 d=30 hole_d=4" in text
    assert nxt == "stone set _demo"  # the request names no parameter, so the defaults

    text, code, nxt = stone("set", "_demo", "w=50")
    assert code == 0 and nxt == "stone build"
    plan = json.loads((jobenv / "stone-job" / "plan.json").read_text())
    assert plan == {"recipe": "_demo", "params": {"w": 50.0}}

    text, code, nxt = stone("build")
    assert code == 0, text
    assert "Size: 50.0 x 40.0 x 4.0 mm" in text
    assert "FIX" not in text
    assert nxt == cli.DONE_NEXT and "Part ready" in text
    assert (jobenv / "stone-job" / "_demo.stl").is_file()  # a passing build is the finished part
    b = jobenv / "stone-job" / "build"
    for f in ("params.json", "part.stl", "preview.png", "check.json", "openscad.log"):
        assert (b / f).is_file(), f
    assert json.loads((b / "params.json").read_text())["params"]["w"] == 50.0
    assert status_json(jobenv)["passed"] is True
    assert status_json(jobenv)["builds"] == 1

    text, code, nxt = stone("check")
    assert code == 0 and nxt == "stone done"

    text, code, nxt = stone("done")
    assert code == 0 and nxt == cli.DONE_NEXT
    assert (jobenv / "stone-job" / "_demo.stl").is_file()

    text, code, nxt = stone("status")
    assert "Stage: done" in text and nxt == cli.DONE_NEXT


def test_status_after_context_loss(jobenv):
    stone("new", "a plate")
    stone("set", "_demo", "w=45", "h=3")
    # fresh process, only the job dir survives
    env = dict(os.environ)
    env["STONE_JOB"] = ""
    r = subprocess.run(
        [sys.executable, "-m", "smoothstone.cli", "--job", str(jobenv / "stone-job"), "status"],
        capture_output=True, text=True, cwd="/", env=env,
    )
    out = r.stdout
    assert r.returncode == 0, r.stderr
    assert "Request: a plate" in out
    assert "Recipe: _demo" in out
    assert "w=45 h=3 (6 more at default)" in out
    assert out.strip().splitlines()[-1] == "NEXT: stone build"


def test_status_prints_tier_rules(jobenv, monkeypatch, tmp_path):
    skill = tmp_path / "skill" / "tiers"
    skill.mkdir(parents=True)
    (skill / "M.md").write_text(
        "# Tier M\n\n## Rules\n\n- one\n- two\n* three\n\n## Other\n\n- not a rule\n"
    )
    monkeypatch.setattr(cli.config, "skill_dir", lambda: tmp_path / "skill")
    (jobenv / "stone.toml").write_text('tier = "M"\n')
    text, _, _ = stone("status")
    assert "Tier: M" in text
    assert "- one\n- two\n- three" in text
    assert "not a rule" not in text
    monkeypatch.setenv("STONE_TIER", "L")
    text, _, _ = stone("status")
    assert "Tier: L" in text


def test_recipes_tier_and_ranking(jobenv, monkeypatch):
    stone("new", "a hook for the wall")
    text, _, nxt = stone("recipes")
    assert "fake_hook" in text and "fake_gear" not in text and "_demo" not in text
    assert nxt == "stone show fake_hook"
    monkeypatch.setenv("STONE_TIER", "L")
    text, _, nxt = stone("recipes", "gears")
    assert nxt == "stone show fake_gear"
    text, _, nxt = stone("recipes", "zebra")
    assert "No recipe matches" in text


def test_set_validation(jobenv):
    stone("new", "a plate")
    text, code, nxt = stone("set", "_dmo", "w=50")
    assert code == 1 and 'FIX: no recipe "_dmo"; closest: _demo' in text
    assert nxt == "stone show _demo"

    text, code, nxt = stone("set", "w=50")
    assert code == 1 and nxt == "stone recipes"

    stone("set", "_demo", "w=50")
    text, code, nxt = stone("set", "width=40")
    assert code == 1 and "closest: w" in text and nxt == "stone set _demo w=40"

    text, code, nxt = stone("set", "w=500")
    assert code == 1 and "range 10..200 mm" in text and nxt == "stone set _demo w=200"
    assert json.loads((jobenv / "stone-job" / "plan.json").read_text())["params"]["w"] == 50.0

    text, code, nxt = stone("set", "quality=20.5")
    assert code == 1 and "whole number" in text

    text, code, nxt = stone("set", "hole_place=middle")
    assert code == 1 and "center, left" in text and nxt == "stone show _demo"

    text, code, nxt = stone("set", "chamfer=maybe")
    assert code == 1 and "true or false" in text

    text, code, nxt = stone("set", "w=abc")
    assert code == 1 and "needs a number" in text

    # merge keeps earlier keys, units and spaces are accepted
    text, code, nxt = stone("set", "h=3mm", "hole_place=LEFT", "chamfer=no", "d", "35")
    assert code == 0, text
    plan = json.loads((jobenv / "stone-job" / "plan.json").read_text())
    assert plan["params"] == {"w": 50.0, "h": 3.0, "hole_place": "left", "chamfer": False, "d": 35.0}

    # a different recipe replaces the plan
    stone("set", "fake_hook", "size=30")
    plan = json.loads((jobenv / "stone-job" / "plan.json").read_text())
    assert plan == {"recipe": "fake_hook", "params": {"size": 30.0}}

    text, code, nxt = stone("set", "fake_hook", "--reset")
    plan = json.loads((jobenv / "stone-job" / "plan.json").read_text())
    assert plan["params"] == {} and "back to defaults" in text


def test_set_needs_job(jobenv):
    text, code, nxt = stone("set", "_demo", "w=50")
    assert code == 1 and nxt == 'stone new "<what to make>"'


def test_new_refuses_then_force(jobenv):
    stone("new", "first")
    text, code, nxt = stone("new", "second")
    assert code == 1 and "--force" in text and nxt == "stone status"
    text, code, nxt = stone("new", "second", "--force")
    assert code == 0
    assert (jobenv / "stone-job.old-1" / "brief.md").read_text().strip().endswith("first")
    assert "second" in (jobenv / "stone-job" / "brief.md").read_text()


def test_build_thin_wall_suggests_fix(jobenv, openscad):
    stone("new", "a plate")
    stone("set", "_demo", "h=0.5")
    text, code, nxt = stone("build")
    assert code == 1
    assert "FIX: min_wall" in text and "set h=1" in text
    assert nxt == "stone set h=1"
    assert status_json(jobenv)["passed"] is False
    text, code, nxt = stone("done")
    assert code == 1 and "did not pass" in text and nxt == "stone set h=1"
    text, _, nxt = stone("status")
    assert nxt == "stone set h=1"
    assert not list((jobenv / "stone-job").glob("*.stl"))  # a failed build leaves no finished part
    stone("set", "h=1")
    text, code, nxt = stone("build")
    assert code == 0 and nxt == cli.DONE_NEXT, text


def test_build_compile_error_names_param(jobenv, openscad):
    stone("new", "a plate")
    stone("set", "_demo", "corner_r=30")
    text, code, nxt = stone("build")
    assert code == 1
    assert "ERROR: Assertion" in text
    assert "FIX: change corner_r (now 30 mm, default 4 mm)" in text
    assert nxt == "stone set corner_r=4"
    log = (jobenv / "stone-job" / "log.txt").read_text()
    assert "Assertion" in log


def test_reset_after_four_failures(jobenv, openscad):
    stone("new", "a plate")
    for h in ("0.3", "0.4", "0.5", "0.6"):
        stone("set", "_demo", f"h={h}")
        text, code, nxt = stone("build")
    assert nxt == "stone set _demo --reset"
    stone("set", "_demo", "--reset")
    assert status_json(jobenv)["failed_builds"] == 0


def test_done_requires_build(jobenv):
    stone("new", "a plate")
    stone("set", "_demo")
    text, code, nxt = stone("done")
    assert code == 1 and nxt == "stone build"


def test_done_refuses_changed_plan(jobenv, openscad):
    stone("new", "a plate")
    stone("set", "_demo")
    stone("build")
    stone("set", "w=55")
    text, code, nxt = stone("done")
    assert code == 1 and nxt == "stone build"


def test_check_any_stl_without_job(jobenv, tmp_path):
    import trimesh

    m = trimesh.creation.box((20, 20, 10))
    m.apply_translation((0, 0, 5))
    f = tmp_path / "b.stl"
    m.export(f)
    text, code, nxt = stone("check", str(f))
    assert code == 0 and nxt == "none, the file passes"
    m.apply_translation((0, 0, 3))
    m.export(f)
    text, code, nxt = stone("check", str(f))
    assert code == 1 and "FIX: resting" in text


def test_image_command_and_image_param(jobenv, tmp_path, recipes_root):
    im = Image.new("RGB", (200, 100), "white")
    ImageDraw.Draw(im).rectangle((40, 20, 160, 80), fill="black")
    f = tmp_path / "pic.png"
    im.save(f)
    text, code, nxt = stone("image", str(f))
    assert code == 1 and nxt == f'stone new "<what to make>" --image {f}'
    text, code, nxt = stone("new", "a keychain from my logo", "--image", str(f))
    assert code == 0, text
    assert "Aspect 1.98" in text and "silhouette" in text
    assert nxt == "stone recipes keychain cookie cutter sign"
    job = jobenv / "stone-job"
    assert (job / "image" / "silhouette.svg").is_file()
    # recipe with an image param gets the absolute path
    d = recipes_root / "fake_logo"
    d.mkdir()
    (d / "recipe.scad").write_text('img = "";\nlinear_extrude(2) resize([40, 0], auto = true) import(img);\n')
    (d / "recipe.json").write_text(json.dumps({
        "name": "fake_logo", "title": "Logo", "tier": "S",
        "params": [{"name": "img", "type": "image", "image_kind": "silhouette", "default": ""}],
    }))
    text, code, nxt = stone("set", "fake_logo", "img=image")
    assert code == 0, text
    plan = json.loads((job / "plan.json").read_text())
    assert plan["params"]["img"] == str((job / "image" / "silhouette.svg").resolve())
    text, code, nxt = stone("set", "fake_logo", "img=" + str(f))  # the picture given to stone new is the job image
    assert code == 0, text
    assert json.loads((job / "plan.json").read_text())["params"]["img"] == str((job / "image" / "silhouette.svg").resolve())


def test_scad_literals():
    p_text = recipes.Param("label", "text", "")
    assert recipes.scad_literal(p_text, 'say "hi" \\ there') == '"say \\"hi\\" \\\\ there"'
    assert recipes.scad_literal(recipes.Param("b", "bool", True), True) == "true"
    assert recipes.scad_literal(recipes.Param("n", "number", 1), 50.0) == "50"
    assert recipes.scad_literal(recipes.Param("n", "number", 1), 0.25) == "0.25"
    assert recipes.scad_literal(recipes.Param("i", "int", 1), 3) == "3"


def test_usage_error_is_short(jobenv):
    text, code, nxt = stone("bogus")
    assert code == 1 and "unknown command bogus" in text and nxt == cli.NEW_NEXT


def test_internal_error_goes_to_log(jobenv, monkeypatch):
    stone("new", "a plate")

    def boom(args, job):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(cli.COMMANDS, "recipes", boom)
    text, code, nxt = stone("recipes")
    assert "internal problem" in text and nxt == "stone status"
    assert "kaboom" in (jobenv / "stone-job" / "log.txt").read_text()


def test_console_script_installed():
    exe = Path(sys.executable).parent / "stone"
    assert exe.exists()


def test_vendor_library_resolves(jobenv, openscad, recipes_root, tmp_path, monkeypatch):
    # stands in for vendor/BOSL2: include <LIB/std.scad> must resolve via OPENSCADPATH
    vendor = tmp_path / "vendor"
    (vendor / "FAKELIB").mkdir(parents=True)
    (vendor / "FAKELIB" / "std.scad").write_text("module plate(s) { cube([s, s, 3]); }\n")
    monkeypatch.setattr(cli.config, "vendor_dir", lambda: vendor)
    d = recipes_root / "fake_lib"
    d.mkdir()
    (d / "recipe.scad").write_text("include <FAKELIB/std.scad>\ns = 30;\ntranslate([-s/2, -s/2, 0]) plate(s);\n")
    (d / "recipe.json").write_text(json.dumps({
        "name": "fake_lib", "title": "Lib test", "tier": "S",
        "params": [{"name": "s", "type": "number", "default": 30, "min": 10, "max": 50}],
        "dims": {"x": "s", "y": "s", "z": "3"},
    }))
    stone("new", "lib test")
    stone("set", "fake_lib", "s=25")
    text, code, nxt = stone("build")
    assert code == 0, text
    assert "Size: 25.0 x 25.0 x 3.0 mm" in text



def test_build_without_required_picture_points_to_stone_image(jobenv, recipes_root):
    d = recipes_root / "fake_cutter"
    d.mkdir()
    (d / "recipe.scad").write_text('image = "";\ncube(10);\n')
    (d / "recipe.json").write_text(json.dumps({
        "name": "fake_cutter", "title": "Cutter", "summary": "Needs a picture.", "tags": ["cutter"],
        "tier": "S", "params": [{"name": "image", "type": "image", "default": "", "image_kind": "outline",
                                 "required": True, "help": "picture"}]}))
    stone("new", "a cookie cutter")
    stone("set", "fake_cutter")
    text, code, nxt = stone("build")
    assert code == 1 and "needs a picture" in text and nxt == "stone image <path to picture>"


def test_image_goes_to_the_recipe_the_request_names(jobenv, recipes_root):
    """A picture plus "lithophane" in the request: NEXT shows the lithophane, not the first picture recipe."""
    from PIL import Image
    for name, title in [("fake_cutter", "Cookie cutter"), ("fake_litho", "Lithophane")]:
        d = recipes_root / name
        d.mkdir()
        (d / "recipe.scad").write_text('image = "";\ncube(10);\n')
        (d / "recipe.json").write_text(json.dumps({
            "name": name, "title": title, "summary": "Uses a picture.", "tags": [],
            "tier": "S", "params": [{"name": "image", "type": "image", "default": "", "image_kind": "height",
                                     "help": "picture"}]}))
    png = jobenv / "pic.png"
    im = Image.new("L", (60, 40), 255)
    im.paste(0, (10, 10, 50, 30))
    im.save(png)
    text, code, nxt = stone("new", "Turn this picture into a lithophane", "--image", str(png))
    assert code == 0 and nxt == "stone show fake_litho"


def test_slips_from_lfm3_runs(jobenv):
    """Commands LFM3-1.7B sent in the round 2 tuning sweep: stone answers each with the fixed line."""
    stone("new", "a plate 50 mm wide")
    job = str(jobenv / "stone-job")
    # a path after a command that takes none
    text, code, nxt = stone("status", job)
    assert "Request: a plate 50 mm wide" in text
    # a synonym for a command
    text, code, nxt = stone("list")
    assert nxt == "stone show _demo" or nxt.startswith("stone show ")
    # bare values: the whole line comes back with names, read from the request
    text, code, nxt = stone("set", "_demo", "50")
    assert code != 0 or "FIX" in text
    assert nxt == "stone set _demo w=50", text
    # the recipe name written as name=value
    text, code, nxt = stone("set", "_demo=50", "w=50")
    assert nxt == "stone build", text


def test_slips_never_send_status_back_to_itself(jobenv):
    """Tuning sweep, no card: after a syntax slip in the image stage, status said NEXT: stone status forever."""
    stone("new", "a plate 50 mm wide")
    stone("recipes")
    text, code, nxt = stone("image")  # no path
    assert nxt == "stone show _demo" or nxt.startswith("stone show"), text
    text, code, nxt = stone("show")  # no recipe
    assert nxt != "stone status", text
    stone("generate", "plate")  # unknown command
    text, code, nxt = stone("status")
    assert nxt != "stone status", text
    # an unknown command that names a recipe goes to that recipe
    text, code, nxt = stone("_demo", "50", "mm")
    assert nxt == "stone show _demo", text


def test_show_names_numbers_it_could_not_place(jobenv):
    """Held-out 1: the S card model copied the suggested line and never added sizes the matcher missed."""
    stone("new", "a plate 50 mm wide with 7 rubber feet")
    text, code, nxt = stone("show", "_demo")
    assert "From the request: w=50" in text
    assert "Not placed yet: 7 rubber feet." in text, text


def test_status_repeats_what_is_not_placed(jobenv):
    """Held-out 1: compaction right after stone show lost the sizes the matcher missed."""
    stone("new", "a plate 50 mm wide with 7 rubber feet")
    stone("show", "_demo")
    text, code, nxt = stone("status")
    assert "Not placed yet: 7 rubber feet. Names and meanings: stone show _demo" in text, text


def test_a_typed_out_job_picture_path_gets_the_recipes_kind(jobenv, tmp_path, recipes_root, openscad):
    """Blind set 4, S card: LFM3 typed the path to silhouette.svg for a cookie cutter with no flange. The
    silhouette keeps the fish's eye hole, the cutter came out in 2 pieces, and every run ran out of steps."""
    shutil.copytree(REPO / "recipes" / "cookie_cutter", recipes_root / "cookie_cutter")
    shutil.copytree(REPO / "recipes" / "lib", recipes_root / "lib")
    im = Image.new("RGB", (300, 200), "white")
    ImageDraw.Draw(im).ellipse((30, 30, 270, 170), fill="black")
    ImageDraw.Draw(im).ellipse((200, 80, 230, 110), fill="white")  # the eye
    f = tmp_path / "fish.png"
    im.save(f)
    stone("new", "a cookie cutter of this fish, 60 mm wide, no flange", "--image", str(f))
    job = jobenv / "stone-job"
    text, code, nxt = stone("set", "cookie_cutter", "size=60", "flange=0", "image=" + str(job / "image" / "silhouette.svg"))
    assert code == 0, text
    plan = json.loads((job / "plan.json").read_text())
    assert plan["params"]["image"] == str((job / "image" / "outline.svg").resolve())
    text, code, nxt = stone("build")
    assert "Part ready" in text, text


def test_the_picture_given_to_stone_new_means_the_job_image(jobenv, tmp_path, recipes_root):
    """Blind set 5, S card compacted: LFM3 set a relief's image to the png it was given at stone new. The raw
    picture went to surface() unstretched, the plaque came out in 2 pieces, and raising base_t never fixed it."""
    shutil.copytree(REPO / "recipes" / "relief", recipes_root / "relief")
    shutil.copytree(REPO / "recipes" / "lib", recipes_root / "lib")
    im = Image.new("RGB", (300, 200), "white")
    ImageDraw.Draw(im).ellipse((30, 30, 270, 170), fill="black")
    f = tmp_path / "leaf.png"
    im.save(f)
    stone("new", "a relief plaque of this leaf, no frame", "--image", str(f))
    job = jobenv / "stone-job"
    text, code, nxt = stone("set", "relief", "frame=0", "image=" + str(f))
    assert code == 0, text
    plan = json.loads((job / "plan.json").read_text())
    assert plan["params"]["image"] == str((job / "image" / "height.png").resolve())


def test_a_signs_picture_takes_image_and_doubled_names(jobenv, tmp_path, recipes_root):
    """Blind set 5, S card: on a sign LFM3 wrote icon=image=<path> and then image=<path>. stone refused both and
    suggested rim=<path>, so the run ran out of steps with no part."""
    shutil.copytree(REPO / "recipes" / "sign", recipes_root / "sign")
    shutil.copytree(REPO / "recipes" / "lib", recipes_root / "lib")
    im = Image.new("RGB", (200, 200), "white")
    ImageDraw.Draw(im).ellipse((30, 30, 170, 170), fill="black")
    f = tmp_path / "sun.png"
    im.save(f)
    stone("new", "a sign that says SHOP with this icon", "--image", str(f))
    job = jobenv / "stone-job"
    want = str((job / "image" / "silhouette.svg").resolve())
    for value in ("icon=image=" + want, "image=" + want, "image=" + str(f), "picture=image"):
        text, code, nxt = stone("set", "sign", "text=SHOP", value)
        assert code == 0, (value, text)
        assert json.loads((job / "plan.json").read_text())["params"]["icon"] == want, value


def test_a_plate_too_narrow_for_its_cutouts_grows(jobenv, recipes_root, openscad):
    """Blind set 4 on the NEXT driver: 4 arcade buttons of 22 mm do not fit the default 60 mm plate. stone's fix
    put the count back to 2, so the part was ready with half the buttons."""
    shutil.copytree(REPO / "recipes" / "panel", recipes_root / "panel")
    shutil.copytree(REPO / "recipes" / "lib", recipes_root / "lib")
    stone("new", "a plate for 4 arcade buttons, 22 mm round holes")
    stone("set", "panel", "cutouts=4", "cut_shape=round", "cut_w=22")
    text, code, nxt = stone("build")
    assert nxt == "stone set w=128", text
    stone("set", "w=128")
    text, code, nxt = stone("build")
    assert "Part ready" in text, text


def test_note_keeps_facts_through_status(jobenv):
    stone("new", "a case for an iPhone 17 Pro")
    _, _, before = stone("status")
    text, code, nxt = stone("note", "width = 71.9 mm, apple.com/iphone/compare")
    assert code == 0 and "Noted (1 notes)" in text
    assert nxt == before  # a note never moves NEXT
    stone("note", "width = 71.9 mm, apple.com/iphone/compare")  # the same fact twice is kept once
    stone("note", "look: thin half-rim glasses")
    text, _, nxt = stone("status")
    assert "Notes (2): width = 71.9 mm, apple.com/iphone/compare | look: thin half-rim glasses" in text
    assert nxt == before
    text, code, _ = stone("note")
    assert code == 1 and "stone note" in text


def test_set_asks_for_the_size_of_what_a_part_fits(jobenv, recipes_root):
    # a small model built a default part for "the cable hole in my desk" in 3 of 3 runs before this
    shutil.copytree(REPO / "recipes" / "panel", recipes_root / "panel")
    stone("new", "A cover for the cable hole in my desk.")
    text, code, nxt = stone("set", "panel")
    assert code == 1 and nxt.startswith("ask the person: What are the measurements of the cable hole in your desk")
    _, _, again = stone("status")
    assert again == nxt  # a compacted model finds the question again
    _, code, nxt = stone("note", "It is a round hole, 60 mm across.")
    assert code == 0 and nxt == "stone show panel"
    text, _, _ = stone("show", "panel")
    assert "cut_shape=round" in text and "cut_w=60" in text
    _, code, nxt = stone("set", "panel", "cut_shape=round", "cut_w=60")
    assert code == 0 and nxt == "stone build"


def test_fit_check_leaves_plain_requests_alone():
    from smoothstone import match, recipes as rc
    box = rc.load("box")
    assert box is not None
    for req in ("A box with a lid.", "A case for my iPhone 17 Pro.", "A mini figure of my dog Rex.",
                "A cable comb, 100 mm long, for 8 cables 6 mm thick."):
        assert match.missing_fit_size(box, req) is None, req
    assert match.missing_fit_size(box, "A holder for my pens.")
    assert match.missing_fit_size(rc.load("figure"), "A stand that fits my figure.") is None


def test_a_round_cutout_taller_than_the_panel_grows_the_panel(jobenv, recipes_root, openscad):
    # a 60 mm round cut in a 40 mm tall panel split it in 3 bodies, and build looped on show and set
    shutil.copytree(REPO / "recipes" / "panel", recipes_root / "panel")
    shutil.copytree(REPO / "recipes" / "lib", recipes_root / "lib", dirs_exist_ok=True)
    stone("new", "A faceplate with one round 60 mm hole.")
    stone("set", "panel", "cut_shape=round", "cut_w=60")
    nxt, seen = "stone build", []
    for _ in range(6):
        text, code, nxt = stone(*nxt.split()[1:])
        seen.append(nxt)
        if nxt.startswith("none"):
            break
    assert nxt.startswith("none"), seen
    assert "Part ready" in text, text


def test_a_desk_hole_cover_is_a_grommet():
    from smoothstone import recipes as rc
    from smoothstone import match
    g = rc.load("grommet")
    assert g is not None and g.tier == "S"
    assert match.suggest(g, "It is a round hole, 60 mm across.") == {"hole_d": 60}


def test_naming_the_product_in_set_answers_the_question(jobenv, recipes_root):
    # the model asked "which phone?" itself, then set phone=iphone_17_pro, and stone asked again
    shutil.copytree(REPO / "recipes" / "phone_case", recipes_root / "phone_case")
    shutil.copytree(REPO / "recipes" / "lib", recipes_root / "lib", dirs_exist_ok=True)
    stone("new", "A case for my phone.")
    _, code, nxt = stone("set", "phone_case")
    assert code == 1 and nxt.startswith("ask the person")
    _, code, nxt = stone("set", "phone_case", "phone=iphone_17_pro")
    assert code == 0 and nxt == "stone build"


def test_a_word_inside_the_request_is_not_a_product(jobenv, recipes_root):
    # "cover" is a buttons choice and "tpu" a material: neither names the phone
    shutil.copytree(REPO / "recipes" / "phone_case", recipes_root / "phone_case")
    shutil.copytree(REPO / "recipes" / "lib", recipes_root / "lib", dirs_exist_ok=True)
    stone("new", "A cover for my phone.")
    _, code, nxt = stone("set", "phone_case")
    assert code == 1 and nxt.startswith("ask the person")
    _, code, nxt = stone("set", "phone_case", "material=tpu", "wall=1.6")
    assert code == 1 and nxt.startswith("ask the person")


def test_a_length_in_the_set_line_answers_the_question(jobenv, recipes_root):
    # the model asked in chat, got "60 mm", and set it: stone must not ask again
    shutil.copytree(REPO / "recipes" / "grommet", recipes_root / "grommet")
    shutil.copytree(REPO / "recipes" / "lib", recipes_root / "lib", dirs_exist_ok=True)
    stone("new", "A cover for the cable hole in my desk.")
    _, code, nxt = stone("set", "grommet")
    assert code == 1 and nxt.startswith("ask the person")
    _, code, nxt = stone("set", "grommet", "hole_d=60")
    assert code == 0 and nxt == "stone build"


def test_a_phone_the_case_does_not_know_is_still_asked_about(jobenv, recipes_root):
    # "15" is a number but no size: building a 17 Pro case for an iPhone 15 would be a guess
    shutil.copytree(REPO / "recipes" / "phone_case", recipes_root / "phone_case")
    shutil.copytree(REPO / "recipes" / "lib", recipes_root / "lib", dirs_exist_ok=True)
    stone("new", "A case for my iPhone 15.")
    _, code, nxt = stone("set", "phone_case")
    assert code == 1 and nxt.startswith("ask the person") and "iphone 17 pro max" in nxt.lower()
