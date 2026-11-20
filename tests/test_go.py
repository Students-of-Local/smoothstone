"""stone go: a person's one command follows the NEXT lines to a ready part, or stops on a question."""
import json
import shutil
from pathlib import Path

from smoothstone import cli, recipes
from smoothstone.go import go

REPO = Path(__file__).resolve().parents[1]


def _go(capsys, *argv):
    code = cli.main(list(argv))
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1].startswith("NEXT: "), lines
    return code, lines


def test_one_command_takes_a_request_to_a_ready_part(jobenv, openscad, monkeypatch, capsys):
    """Donovan, 2026-11-20: trying a figure took four commands and a silent wait. One command does it."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    code, lines = _go(capsys, "go", "A guard for a 120 mm PC fan, 3 mm thick.")
    text = "\n".join(lines)
    assert code == 0 and lines[-1] == f"NEXT: {cli.DONE_NEXT}", text
    assert "[1] stone new" in text and "stone build" in text and "print checks passed" in text, text
    assert "From the request: size=120 thickness=3" in text, text
    assert any(ln.startswith("Ready in ") and ln.endswith("fan_guard.stl") for ln in lines), text
    assert (jobenv / "stone-job" / "fan_guard.stl").is_file()


def test_the_request_alone_is_the_same_command(jobenv, openscad, monkeypatch, capsys):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    code, lines = _go(capsys, "A guard for a 120 mm PC fan, 3 mm thick.")
    assert code == 0 and lines[-1] == f"NEXT: {cli.DONE_NEXT}", lines


def test_it_stops_with_a_plain_question_and_goes_on_after_the_answer(jobenv, openscad, monkeypatch, capsys):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    code, lines = _go(capsys, "go", "A cover for the cable hole in my desk.")
    assert code == 1 and any(ln.startswith("Needs you: ") for ln in lines), lines
    assert "When that is done, run: stone go" in lines and lines[-1].startswith("NEXT: ask the person"), lines
    cli.run(["note", "It is a round hole, 60 mm across."])
    capsys.readouterr()
    code, lines = _go(capsys, "go")
    assert code == 0 and lines[-1] == f"NEXT: {cli.DONE_NEXT}", lines


def test_a_bare_set_takes_the_values_the_request_names(jobenv, monkeypatch):
    """Donovan and the Mac run, 2026-11-20: "stone set figure" after a request with "SAM" on the
    base left the name empty. A bare set on a new plan takes what stone show offers."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    cli.run(["new", 'A mini figure of Sam Altman, 90 mm tall, with "SAM" on the base'])
    text, code = cli.run(["set", "figure"])
    assert code == 0 and "From the request:" in text and "name=SAM" in text, text
    assert (jobenv / "stone-job" / "plan.json").read_text().count('"SAM"') == 1
    text, _ = cli.run(["set", "figure", "--reset"])
    assert '"SAM"' not in (jobenv / "stone-job" / "plan.json").read_text(), text  # a reset is still defaults


def test_a_request_no_recipe_makes_stops_instead_of_a_wrong_part(jobenv, monkeypatch, capsys):
    """Blind run of 43 everyday requests, 2026-11-20: a birdhouse came back a ready box, a stove
    knob a gear, a chip clip a cable comb. A recipe that does not make what is asked is not handed over."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    code, lines = _go(capsys, "go", "Can you make a birdhouse for my backyard?")
    assert code == 1 and lines[-1].startswith("NEXT: ask the person: stone has no recipe for this yet"), lines
    assert not (jobenv / "stone-job" / "plan.json").exists()


def test_fit_reads_what_the_request_asks_for():
    from smoothstone import recipes as rc
    r = {n: x for n, x in rc.load_all(REPO / "recipes").items()}
    assert rc.fit(r["box"], "Can you make a birdhouse for my backyard?") == 0
    assert rc.fit(r["spur_gear"], "I need a new stove knob that fits a 6 mm D-shaped shaft.") == 0
    assert rc.fit(r["cable_comb"], "I need a clip to keep my bag of chips closed.") == 0
    assert rc.fit(r["cable_comb"], "little clips that stick under my desk and hold the cables up") >= 1
    stand = "Make a phone stand for my iPhone 15 Pro that works with the case on."
    assert rc.fit(r["phone_stand"], stand) == 3 > rc.fit(r["phone_case"], stand)
    assert rc.fit(r["fan_guard"], "fan gaurd for an 80mm fan") >= 1  # a typo in a long word still fits
    assert rc.fit(r["planter"], "plant labels for my tomatoes") == 0  # plant is not planter
    assert rc.fit(r["hook"], "a stand for my hex keys that holds sizes from 1.5 to 10 mm") == 0


def test_the_part_the_request_starts_with_beats_one_it_mentions_later(jobenv, monkeypatch):
    """Review of #45 round 2: "A guard for a 120 mm PC fan inside a box" handed over the box."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    for req, want in (("A guard for a 120 mm PC fan inside a box", "fan_guard"),
                      ("A box to keep my 120 mm fan guard in", "box"),
                      ("A phone stand for my desk, next to a box of pens", "phone_stand")):
        shutil.rmtree(jobenv / "stone-job", ignore_errors=True)
        cli.run(["new", req])
        text, _ = cli.run(["recipes"])
        assert text.splitlines()[-1] == f"NEXT: stone show {want}", (req, text)


def test_narrowing_words_never_stop_the_job(jobenv, monkeypatch):
    """Review of #45: stone recipes fan is the narrowing stone itself suggests; it must not ask the person."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    cli.run(["new", "A guard for a 120 mm PC fan"])
    text, _ = cli.run(["recipes", "fan"])
    assert "fan_guard" in text and text.splitlines()[-1] == "NEXT: stone show fan_guard", text


def test_a_bare_set_keeps_two_words_without_quote_marks(jobenv, monkeypatch):
    """Review of #45: "WELCOME HOME" was saved with its quote marks and would print them."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    cli.run(["new", 'A door sign that says "WELCOME HOME"'])
    text, code = cli.run(["set", "sign"])
    plan = json.loads((jobenv / "stone-job" / "plan.json").read_text())
    assert "WELCOME HOME" in plan["params"].values(), (text, plan)
    assert not any(isinstance(v, str) and '"' in v for v in plan["params"].values()), plan


def test_every_eval_request_still_fits_its_recipe(monkeypatch):
    """Review of #45: a makes list narrower than its tags would refuse requests that work today."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    allr = recipes.load_all()
    misses = []
    for f in sorted(REPO.glob("evals/*/*.json")):
        try:
            spec = json.loads(f.read_text())
        except ValueError:
            continue
        want = (spec.get("expect") or {}).get("recipe") if isinstance(spec, dict) else None
        if want in allr and spec.get("request") and recipes.fit(allr[want], spec["request"]) == 0:
            misses.append((f.name, want))
    assert not misses
    assert recipes.fit(allr["hook"], "a headphone holder for my desk") >= 1
    assert recipes.fit(allr["panel"], "a plate with two holes for a wall") >= 1


def test_after_no_recipe_one_command_makes_the_nearest(jobenv, openscad, monkeypatch, capsys):
    """Review of #45: after the no-recipe stop, stone go alone asked the same question again."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    code, lines = _go(capsys, "go", "A birdhouse for my backyard")
    make = next((ln for ln in lines if ln.startswith("To make the nearest anyway: ")), None)
    assert code == 1 and make and any(ln.startswith("To ask another way: ") for ln in lines), lines
    show = make[len("To make the nearest anyway: "):].split(", then")[0]
    cli.run(show.split()[1:])
    capsys.readouterr()
    code, lines = _go(capsys, "go")
    assert code == 0 and lines[-1] == f"NEXT: {cli.DONE_NEXT}", lines


def test_a_step_that_answers_differently_each_time_is_progress():
    """Review of #45: build, fix, build, fix, build, reset, build is a job moving on, not a loop."""
    said, n = [], {"build": 0}

    def run(argv):
        if argv[0] == "new":
            return "Job.\nNEXT: stone build", 0
        if argv[0] == "build":
            n["build"] += 1
            if n["build"] < 5:
                return f"FAIL check {n['build']}\nNEXT: stone set x a={n['build']}", 1
            return "Part ready: /p.stl\nNEXT: none, the part is ready", 0
        return "Plan: x\nNEXT: stone build", 0

    assert go(["a part"], run, say=said.append, hooks={}) == 0, said
    said.clear()
    assert go(["a part"], lambda argv: ("FAIL same\nNEXT: stone build", 1), say=said.append, hooks={}) == 1
    assert any(s.startswith("Stopped: stone build keeps coming back") for s in said), said


def test_job_given_as_one_word_reaches_every_step():
    seen = []

    def run(argv):
        seen.append(argv)
        return ("Job.\nNEXT: none, the part is ready", 0)

    go(["--job=elsewhere", "a part"], run, say=lambda s: None, hooks={})
    assert seen == [["new", "a part", "--job=elsewhere"]]
