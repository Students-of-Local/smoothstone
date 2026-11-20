"""stone go: the whole job in one command, for a person.

It follows stone's own NEXT lines, the same loop CI runs on every tuning task (evals/run.py
--driver next), prints each step as it runs, and stops with a plain "Needs you:" line when a
step needs the person. `stone go` with no request goes on with the job in this folder.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from typing import Callable

MAX_STEPS = 30
SAME_STEP_MAX = 3  # the same command this many times without the job moving on: stop
# lines worth showing a person from each step; the rest stay in log.txt
SHOW = ("FIX:", "FAIL", "Plan:", "From the request:", "From the picture:", "Found ", "Credits:", "Figure:",
        "Size:", "Build failed", "ERROR", "Part ready:", "Painted:", "Colors:", "Not placed yet:")


def _open(path: str) -> bool:
    """Show the views to a person at a terminal. STONE_OPEN=0 turns it off."""
    if os.environ.get("STONE_OPEN", "1") == "0" or not sys.stdout.isatty():
        return False
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    try:
        subprocess.Popen([opener, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return True
    except OSError:
        return False


def _split(text: str) -> tuple[list[str], str]:
    lines = text.splitlines()
    nxt = lines[-1][len("NEXT: "):] if lines and lines[-1].startswith("NEXT: ") else ""
    return lines[:-1] if nxt else lines, nxt


def _value(lines: list[str], head: str) -> str | None:
    for ln in lines:
        if ln.startswith(head):
            return ln[len(head):].split(" (", 1)[0].strip()
    return None


def go(words: list[str], run: Callable[[list[str]], tuple[str, int]],
       say: Callable[[str], None] = lambda s: print(s, flush=True)) -> int:
    """words: the request and any new options (--image p), or nothing to go on. --job applies to every step."""
    words = list(words)
    job: list[str] = []
    if "--job" in words:
        i = words.index("--job")
        job = words[i:i + 2]
        del words[i:i + 2]
    if words:
        nxt = "stone new " + " ".join(shlex.quote(w) for w in words)
    else:
        nxt = _split(run(["status", *job])[0])[1]
    seen: dict[str, int] = {}
    stl = views = credits = None
    t0 = time.time()
    step = 0
    while True:
        if not nxt or not nxt.startswith("stone ") or "<" in nxt:
            break
        seen[nxt] = seen.get(nxt, 0) + 1
        if seen[nxt] > SAME_STEP_MAX or step >= MAX_STEPS:
            say(f"Stopped: {nxt} keeps coming back. stone status shows where the job stands.")
            say(f"NEXT: {nxt}")
            return 1
        step += 1
        say(f"[{step}] {nxt}")
        t = time.time()
        try:
            argv = shlex.split(nxt)[1:]
        except ValueError:
            break
        text, _ = run(argv + job)
        lines, after = _split(text)
        for ln in lines:
            if ln.startswith(SHOW):
                say(f"    {ln}")
        passed = sum(ln.startswith("PASS") for ln in lines)
        failed = sum(ln.startswith("FAIL") for ln in lines)
        if passed or failed:
            say(f"    {passed} print checks passed" + (f", {failed} failed" if failed else ""))
        stl = _value(lines, "Part ready:") or stl
        views = _value(lines, "Views:") or views
        credits = _value(lines, "Credits:") or credits
        took = time.time() - t
        if took >= 10:
            say(f"    ({took:.0f} s)")
        nxt = after
    mins = (time.time() - t0) / 60
    if nxt.startswith("none"):
        say(f"Ready in {mins:.1f} min: {stl}" if stl else f"Ready in {mins:.1f} min.")
        if views:
            say(f"Views: {views}" + (" (opened)" if _open(views) else ""))
        if credits:
            say(f"Photo credits: {credits} (name them when you share it)")
        say(f"NEXT: {nxt}")
        return 0
    if nxt.startswith("ask the person"):
        ask = nxt[len("ask the person"):].lstrip(": ")
        say(f"Needs you: {ask}")
        say("When that is done, run: stone go")
    elif "<" in nxt:
        say(f"Needs you: stone needs something only you have. Run {nxt} with it filled in, then stone go.")
    elif nxt:
        say(f"Stopped at a step stone go does not run: {nxt}")
    say(f"NEXT: {nxt or 'stone status'}")
    return 1
