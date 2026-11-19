import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_harness", ROOT / "evals" / "run.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


def test_a_figure_build_fits_in_the_command_time_limit(monkeypatch, tmp_path):
    # f3 and f5 (2026-11-18): the first figure build took 428 s and 429 s on the Mac (style, lift,
    # openscad), the old 420 s limit cut both, and f5 ran out of steps before `stone colors`.
    seen = {}

    def fake(argv, **kw):
        seen["timeout"] = kw["timeout"]
        return subprocess.CompletedProcess(argv, 0, "ok", "")

    monkeypatch.delenv("STONE_CMD_TIMEOUT", raising=False)
    monkeypatch.setattr(run.subprocess, "run", fake)
    run.run_stone("stone build", {}, tmp_path)
    assert seen["timeout"] >= 2 * 429


def test_a_command_that_runs_too_long_is_run_again(monkeypatch, tmp_path):
    # A build resumes from its cached style and lift, so the way on is the same command, not status.
    def slow(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])

    monkeypatch.setattr(run.subprocess, "run", slow)
    out = run.run_stone("stone build", {}, tmp_path)
    assert out.startswith("FIX: the command ran too long")
    assert run.last_next(out) == "stone build"
