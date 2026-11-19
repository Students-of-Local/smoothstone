import importlib.util
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("run_harness", ROOT / "evals" / "run.py")
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


class FakePopen:
    """Popen whose communicate() either answers or runs out of time."""
    seen = {}
    slow = False

    def __init__(self, argv, **kw):
        self.argv, self.pid, self.returncode = argv, -1, 0
        self.stdout = self.stderr = None
        FakePopen.seen.update(kw)

    def communicate(self, timeout=None):
        FakePopen.seen["timeout"] = timeout
        if FakePopen.slow:
            raise subprocess.TimeoutExpired(self.argv, timeout)
        return "ok", ""

    def wait(self, timeout=None):
        return 0


def test_a_figure_build_fits_in_the_command_time_limit(monkeypatch, tmp_path):
    # f3 and f5 (2026-11-18): the first figure build took 428 s and 429 s on the Mac (style, lift,
    # openscad), the old 420 s limit cut both, and f5 ran out of steps before `stone colors`.
    monkeypatch.delenv("STONE_CMD_TIMEOUT", raising=False)
    monkeypatch.setattr(FakePopen, "seen", {})
    monkeypatch.setattr(FakePopen, "slow", False)
    monkeypatch.setattr(run.subprocess, "Popen", FakePopen)
    assert run.run_stone("stone build", {}, tmp_path) == "ok"
    assert FakePopen.seen["timeout"] >= 2 * 429 and FakePopen.seen["start_new_session"]


def test_a_command_that_runs_too_long_is_run_again(monkeypatch, tmp_path):
    # A build resumes from its cached style and lift, so the way on is the same command, not status.
    monkeypatch.setattr(FakePopen, "seen", {})
    monkeypatch.setattr(FakePopen, "slow", True)
    monkeypatch.setattr(run.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(run.os, "killpg", lambda pgid, sig: None)
    out = run.run_stone("stone build", {}, tmp_path)
    assert out.startswith("FIX: the command ran too long")
    assert run.last_next(out) == "stone build"


def test_a_command_that_runs_too_long_takes_its_children_with_it(monkeypatch, tmp_path):
    """F2: a timeout killed stone alone; its model (mflux, the lift) ran on, and the rerun started a
    second 8 GB model beside it."""
    pidfile = tmp_path / "child.pid"
    stone = tmp_path / "stone"
    stone.write_text(f"#!/bin/sh\nsleep 30 &\necho $! > {pidfile}\nsleep 30\n")
    stone.chmod(0o755)
    monkeypatch.setattr(run, "STONE", str(stone))
    monkeypatch.setenv("STONE_CMD_TIMEOUT", "1")
    out = run.run_stone("stone build", dict(os.environ), tmp_path)
    assert run.last_next(out) == "stone build"
    pid = int(pidfile.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        os.kill(pid, 9)
        raise AssertionError(f"the child {pid} outlived the timeout")
