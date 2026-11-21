"""The teacher's half of the eval loop: where each small-model run first left stone's path, and whose
fault that is.

uv run python evals/distill.py <run dir or folder of runs> ... [--json]

A run passes or fails; that alone does not say what to change. Every stone message ends with a NEXT
line, so a run is on stone's path while each command it runs is the NEXT stone printed last. This reads
each run's log.json and finds the first divergence: the earliest step that explains the result. Then it
says whose fault it is, because the fix goes in a different place:

  setup    a model or tool was not set up. Fix the trial's setup and run it again; it does not count.
  off      the model ran something other than the NEXT line. Fix the card (skill/tiers/<card>.md).
  stopped  the model stopped while NEXT was a command. Fix the card's stop rule.
  values   the model stayed on the path but set a number or name the spec does not want. Fix the card.
  steps    the model stayed on the path and ran out of steps. Shorten stone's path.
  tool     the model ran every NEXT line and stone still led it to a failing part. Fix stone, not the card.

Then a ledger: the pass rate per card version (the card's SHA-256, which every log records), counting
only specs both versions ran, so a card edit that did worse shows up and can be reverted. A spec with
fewer than 2 counted runs on a card proves nothing yet: one lucky run is not a pass rate.

Adapted from sybil-solutions/skill-distill (MIT): the teacher runs the student, judges the first
divergence, fixes the skill there, and reverts a version that scores worse.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from collections import defaultdict
from pathlib import Path

FIX = {
    "setup": "harness: set the trial up properly and run it again; it does not count",
    "off": "card: make the step it skipped a stop-and-check line, or show it in an example",
    "stopped": "card: the stop rule; stop only when NEXT says none or ask the person",
    "values": "card: name that parameter and its meaning in an example",
    "steps": "stone: its path is longer than the harness allows; make fewer steps reach the part",
    "tool": "stone: its own NEXT path ends in a failing part; the card is not the problem",
}
SETUP = re.compile(r"not set up|setup\.sh|server is not running|could not reach", re.I)
MIN_TRIALS = 2  # the bar runs 2 seeds per case


def words(cmd: str) -> list[str]:
    try:
        w = shlex.split(cmd)
    except ValueError:
        w = cmd.split()
    return w[1:] if w and w[0] == "stone" else w


def last_next(text: str) -> str | None:
    m = re.findall(r"^NEXT: (.+)$", text or "", re.M)
    return m[-1].strip() if m else None


def runnable(nxt: str | None) -> bool:
    return bool(nxt) and not nxt.startswith(("none", "ask the person"))


def follows(cmd: str, nxt: str | None) -> bool:
    """The command is the NEXT line, or one of the variants the card allows."""
    if nxt is None:
        return True  # before stone has said anything, or after the person spoke
    got, want = words(cmd), words(nxt)
    if got == want:
        return True
    if "<" in nxt:  # NEXT names a slot the model fills: the command word must match
        return got[:1] == want[:1]
    if want[:2] and got[:2] == want[:2] and want[0] == "set":
        return set(want[2:]) <= set(got[2:])  # the card's rule: add the sizes not placed yet
    if got[:1] == ["status"]:
        return True  # the card's rule for a model that lost track
    return False


def fix_line(text: str) -> str | None:
    lines = [ln for ln in (text or "").splitlines() if ln.startswith("FIX:")]
    return lines[-1][4:].strip() if lines else None


def walk(log: dict) -> dict:
    """The first divergence of one run: class, step, what happened, and the fix it calls for."""
    nxt: str | None = "stone status"
    phase = 0
    last_fix = None
    for st in log.get("steps", []):
        if st.get("phase", 0) != phase:  # the person spoke: the model may start anywhere
            phase, nxt = st.get("phase", 0), None
        calls = st.get("tool_calls") or []
        if not calls and st.get("stop_type") == "limit":
            continue  # a cut turn goes on in the next step
        if not calls and "compacted" not in st:
            if runnable(nxt):
                return {"kind": "stopped", "step": st["step"], "what": f"stopped while NEXT was {nxt!r}"}
            continue
        for c in calls:
            cmd = str((c.get("args") or {}).get("command", ""))
            res = c.get("result") or ""
            fx = fix_line(res)
            if fx and SETUP.search(fx):
                return {"kind": "setup", "step": st["step"], "what": fx}
            if c.get("name") != "stone" or not follows(cmd, nxt):
                return {"kind": "off", "step": st["step"], "what": f"ran {cmd!r}, NEXT was {nxt!r}",
                        "after": last_fix}
            last_fix = fx or last_fix
            nxt = last_next(res) or nxt
    if log.get("pass"):
        return {"kind": "pass", "step": None, "what": ""}
    why = log.get("why") or []
    bad = [w for w in why if re.match(r"^[a-z_]+=", w)]
    if bad and not any("no finished part" in w for w in why):
        return {"kind": "values", "step": set_step(log), "what": "; ".join(bad)}
    if runnable(nxt) and len(log.get("steps", [])) >= log.get("max_steps", 10):
        return {"kind": "steps", "step": len(log["steps"]), "what": f"out of steps, NEXT was {nxt!r}"}
    return {"kind": "tool", "step": None, "what": "; ".join(why) + (f" (last FIX: {last_fix})" if last_fix else "")}


def set_step(log: dict) -> int | None:
    for st in reversed(log.get("steps", [])):
        for c in st.get("tool_calls") or []:
            if words(str((c.get("args") or {}).get("command", "")))[:1] == ["set"]:
                return st["step"]
    return None


def load(paths: list[str]) -> list[dict]:
    runs = []
    for p in paths:
        for f in sorted(Path(p).rglob("log.json")) if Path(p).is_dir() else [Path(p)]:
            try:
                log = json.loads(f.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(log, dict) or "steps" not in log or log.get("driver") == "next":
                continue  # the next driver is stone alone, no model to teach
            runs.append({"path": str(f.parent), "spec": log.get("spec"), "seed": log.get("seed"),
                         "card": (log.get("card_sha256") or "none")[:8], "date": log.get("started", ""),
                         "pass": bool(log.get("pass")), **walk(log)})
    return runs


def ledger(runs: list[dict]) -> list[dict]:
    """Pass rate per card version, in the order the versions first ran. Each version is compared with
    the one before on the specs both ran; a lower rate there says to revert the change."""
    by: dict[str, list[dict]] = defaultdict(list)
    for r in runs:
        if r["kind"] != "setup":
            by[r["card"]].append(r)
    order = sorted(by, key=lambda k: min(r["date"] for r in by[k]))
    out, prev = [], None
    for k in order:
        rs = by[k]
        row = {"card": k, "first": min(r["date"] for r in rs)[:10], "runs": len(rs),
               "pass": sum(r["pass"] for r in rs), "specs": sorted({r["spec"] for r in rs})}
        if prev:
            common = set(row["specs"]) & set(prev["specs"])
            if common:
                rate = lambda v: (lambda xs: sum(x["pass"] for x in xs) / len(xs))(  # noqa: E731
                    [r for r in by[v] if r["spec"] in common])
                row["vs"] = {"card": prev["card"], "specs": sorted(common), "before": rate(prev["card"]),
                             "after": rate(k)}
        out.append(row)
        prev = row
    return out


def report(runs: list[dict]) -> str:
    lines = ["First divergence per run", ""]
    for r in sorted(runs, key=lambda r: (r["spec"] or "", r["date"])):
        at = f"step {r['step']}" if r["step"] else ""
        lines.append(f"  {'PASS' if r['pass'] else 'FAIL'}  {r['spec']:<24} s{r['seed']}  card {r['card']}  "
                     f"{r['kind']:<8} {at:<8} {r['what'][:110]}")
    lines += ["", "Where to fix (failing runs that count)"]
    kinds = defaultdict(list)
    for r in runs:
        if not r["pass"]:
            kinds[r["kind"]].append(r)
    for k in FIX:
        if kinds[k]:
            specs = sorted({r["spec"] for r in kinds[k]})
            lines.append(f"  {k:<8} {len(kinds[k]):>2} runs  {FIX[k]}")
            lines.append(f"           {', '.join(specs)}")
    lucky = [r for r in runs if r["pass"] and r["kind"] != "pass"]
    if lucky:
        lines.append(f"  {len(lucky)} passing runs left the path and passed anyway; that is luck, not the card")
    lines += ["", "Card versions (pass rate; vs the version before on the specs both ran)"]
    for row in ledger(runs):
        s = f"  {row['card']}  from {row['first']}  {row['pass']}/{row['runs']} pass"
        v = row.get("vs")
        if v:
            s += f"  vs {v['card']}: {v['before']:.0%} -> {v['after']:.0%} on {len(v['specs'])} specs"
            if v["after"] < v["before"]:
                s += "  WORSE: revert the change that caused it"
        lines.append(s)
    latest = ledger(runs)[-1]["card"] if runs else None
    thin = defaultdict(int)
    for r in runs:
        if r["card"] == latest and r["kind"] != "setup":
            thin[r["spec"]] += 1
    few = sorted(s for s, n in thin.items() if n < MIN_TRIALS)
    if few:
        lines.append(f"  card {latest}: under {MIN_TRIALS} counted runs, so no rate yet: {', '.join(few)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    runs = load(a.paths)
    if not runs:
        print("no model runs found (log.json from evals/run.py with a model driver)")
        return 1
    print(json.dumps({"runs": runs, "ledger": ledger(runs)}, indent=1) if a.json else report(runs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
