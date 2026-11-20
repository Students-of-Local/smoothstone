"""stone go: a person's one command follows the NEXT lines to a ready part, or stops on a question."""
from pathlib import Path

from smoothstone import cli

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
    assert rc.fit(r["cable_comb"], "little clips that stick under my desk and hold the cables up") == 1
    stand = "Make a phone stand for my iPhone 15 Pro that works with the case on."
    assert rc.fit(r["phone_stand"], stand) == 2 > rc.fit(r["phone_case"], stand)
    assert rc.fit(r["fan_guard"], "fan gaurd for an 80mm fan") == 1  # a typo in a long word still fits
    assert rc.fit(r["planter"], "plant labels for my tomatoes") == 0  # plant is not planter
    assert rc.fit(r["hook"], "a stand for my hex keys that holds sizes from 1.5 to 10 mm") == 0
