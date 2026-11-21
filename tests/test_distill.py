"""evals/distill.py: the first divergence of a model run says whose fault a failure is."""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "evals"))
import distill  # noqa: E402


def call(cmd, result):
    return {"name": "stone", "args": {"command": cmd}, "result": result}


def log(steps, ok=False, why=(), card="a" * 64, started="2026-11-20T10:00:00", spec="t1", seed=1):
    out = []
    for i, s in enumerate(steps, 1):
        out.append({"step": i, "phase": 0, "tool_calls": s} if isinstance(s, list) else {"step": i, "phase": 0, **s})
    return {"spec": spec, "seed": seed, "driver": "lfm3", "card_sha256": card, "started": started,
            "pass": ok, "why": list(why), "max_steps": 10, "steps": out}


START = [[call("stone status", "NEXT: stone recipes")], [call("stone recipes", "NEXT: stone show bin")],
         [call("stone show bin", "From the request: x=2\nNot placed yet: 4 sections\nNEXT: stone set bin x=2")]]


def test_a_run_on_the_path_that_passes_is_pass():
    lg = log(START + [[call("stone set bin x=2 div=3", "NEXT: stone build")],
                      [call("stone build", "Part ready\nNEXT: none, the part is ready")], {"tool_calls": []}], ok=True)
    assert distill.walk(lg)["kind"] == "pass"


def test_adding_the_sizes_not_placed_yet_is_still_on_the_path():
    assert distill.follows("stone set bin x=2 div=3", "stone set bin x=2")
    assert not distill.follows("stone set bin x=3", "stone set bin x=2")
    assert distill.follows('stone find "Ada Lovelace"', 'stone find "<who or what>"')
    assert distill.follows("stone status", "stone build")  # the card's rule for a lost model


def test_running_something_else_is_the_card_s_fault():
    lg = log(START + [[call("stone set bin x=2", "NEXT: stone build")],
                      [call("stone build", "FIX: wall too thin\nNEXT: stone set bin wall=1.2")],
                      [call("stone build", "FIX: wall too thin\nNEXT: stone set bin wall=1.2")]])
    d = distill.walk(lg)
    assert d["kind"] == "off" and d["step"] == 6 and d["after"] == "wall too thin"


def test_stopping_while_next_is_a_command_is_stopped():
    lg = log(START + [{"tool_calls": [], "generated": "Done!"}])
    d = distill.walk(lg)
    assert d["kind"] == "stopped" and d["step"] == 4


def test_a_setup_fix_does_not_count_against_the_card():
    lg = log(START[:1] + [[call("stone build", "FIX: the style model is not set up, run tools/figure/setup.sh once")]])
    assert distill.walk(lg)["kind"] == "setup"


def test_following_every_next_line_to_a_failing_part_is_the_tool_s_fault():
    lg = log(START + [[call("stone set bin x=2", "NEXT: stone colors rest=white")],
                      [call("stone colors rest=white", "FIX: color boundary is jagged\nNEXT: none, the part is ready")],
                      {"tool_calls": []}], why=["top is white (want black)"])
    d = distill.walk(lg)
    assert d["kind"] == "tool" and "jagged" in d["what"]


def test_out_of_steps_on_the_path_is_a_long_path():
    steps = START + [[call("stone set bin x=2", "NEXT: stone build")]]
    steps += [[call("stone build", "FIX: x\nNEXT: stone build")] for _ in range(6)]
    d = distill.walk(log(steps, why=["no finished part"]))
    assert d["kind"] == "steps" and d["step"] == 10


def test_a_wrong_value_on_the_path_points_at_the_set_step():
    lg = log(START + [[call("stone set bin x=2", "NEXT: stone build")],
                      [call("stone build", "Part ready\nNEXT: none, the part is ready")], {"tool_calls": []}],
             why=["div=0 (want 3)"])
    d = distill.walk(lg)
    assert d["kind"] == "values" and d["step"] == 4


def test_the_ledger_flags_a_card_that_did_worse_on_the_same_specs(tmp_path, capsys):
    good = log(START + [[call("stone set bin x=2", "NEXT: none")], {"tool_calls": []}], ok=True)
    bad = log(START + [{"tool_calls": []}])
    runs = [("old", "2026-11-19", "t1", good), ("old", "2026-11-19", "t2", good),
            ("new", "2026-11-20", "t1", good), ("new", "2026-11-20", "t2", bad), ("new", "2026-11-20", "t9", good)]
    for i, (card, day, spec, lg) in enumerate(runs):
        d = tmp_path / f"r{i}"
        d.mkdir()
        (d / "log.json").write_text(json.dumps({**lg, "card_sha256": card * 8, "started": day + "T10:00", "spec": spec}))
    assert distill.main([str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "100% -> 50% on 2 specs  WORSE: revert" in out
    assert "under 2 counted runs" in out and "t1, t2, t9" in out


def test_the_next_driver_and_other_logs_are_skipped(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "log.json").write_text(json.dumps({**log(START), "driver": "next"}))
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "log.json").write_text("[]")
    assert distill.load([str(tmp_path)]) == []
