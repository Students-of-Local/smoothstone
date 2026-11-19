"""The bar of the three figure modes (LOG.md, 2026-11-19), per held-out folder.

uv run python evals/bar.py <runs dir> [<runs dir> ...] [--card S]

For each of figure-research, figure-photo and figure-desc: the runs that pass every check and the
likeness bar, out of cases x 2 seeds, against 80%; and the blind craft judge's mean (judge.json)
against 8, with the seeded bad control's score. A run is a folder with log.json (evals/run.py);
the last run of a case and seed counts, and one not made counts as failed. A control is a folder
with control.json and judge.json (judge_control.py, then judge_views.py on it), of the mode of the
run it was seeded from; it must score under 8, or a craft pass means nothing. Exits 1 when a mode
is below its bar.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODES = ("figure-research", "figure-photo", "figure-desc")
SEEDS = (1, 2)
RATE = 0.8
CRAFT = 8.0


def _score(d: Path) -> float | None:
    p = d / "judge.json"
    return json.loads(p.read_text()).get("score") if p.exists() else None


def collect(dirs: list[Path], card: str = "S", evals: Path = ROOT / "evals") -> tuple[dict, dict]:
    """({mode: {(spec, seed): log with "dir"}}, {mode: [control scores]})."""
    runs: dict = {m: {} for m in MODES}
    controls: dict = {m: [] for m in MODES}
    for d in dirs:
        logs = [d / "log.json"] if (d / "log.json").exists() else sorted(d.glob("*/log.json"))
        for p in sorted(logs, key=lambda q: json.loads(q.read_text()).get("run_id", "")):
            log = json.loads(p.read_text())
            if log.get("suite") in MODES and log.get("driver") != "next" and str(log.get("card")) == card:
                runs[log["suite"]][(log["spec"], log["seed"])] = {**log, "dir": p.parent}
        for c in sorted(d.rglob("control.json")):
            job = Path(json.loads(c.read_text()).get("job", ""))
            spec = job.parent.name.split("__")[0]
            mode = next((m for m in MODES if (evals / m / f"{spec}.json").exists()), None)
            if mode and (s := _score(c.parent)) is not None:
                controls[mode].append(s)
    return runs, controls


def bar(dirs: list[Path], card: str = "S", evals: Path = ROOT / "evals") -> tuple[list[str], bool]:
    runs, controls = collect(dirs, card, evals)
    out, ok = [], True
    for mode in MODES:
        cases = sorted(p.stem for p in (evals / mode).glob("*.json"))
        want = [(c, s) for c in cases for s in SEEDS]
        got = runs[mode]
        passed = sum(bool(got[k]["pass"]) for k in want if k in got)
        rate = passed / len(want) if want else 0.0
        held = rate >= RATE
        out.append(f"{mode}: {passed} of {len(want)} runs pass checks and likeness "
                   f"({len(cases)} cases x {len(SEEDS)} seeds), {rate:.0%} (bar {RATE:.0%}): "
                   + ("holds" if held else "below"))
        miss = [f"{c} s{s}: " + ("; ".join(got[(c, s)]["why"])[:120] if (c, s) in got else "not run")
                for c, s in want if (c, s) not in got or not got[(c, s)]["pass"]]
        out += ["  " + m for m in miss]
        js = [j for k in want if k in got and (j := _score(got[k]["dir"])) is not None]
        mean = sum(js) / len(js) if js else None
        ctl = controls[mode]
        craft = mean is not None and mean >= CRAFT and bool(ctl) and max(ctl) < CRAFT
        ms = "no score" if mean is None else f"{mean:.2f} over {len(js)} runs"
        cs = ", ".join(f"{c:g}" for c in ctl) if ctl else "none judged"
        out.append(f"  craft judge mean {ms} (bar {CRAFT:g}), control {cs} (must be under {CRAFT:g}): "
                   + ("holds" if craft else "below"))
        ok = ok and held and craft
    return out, ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", type=Path)
    ap.add_argument("--card", default="S")
    a = ap.parse_args()
    lines, ok = bar(a.runs, a.card)
    print("\n".join(lines))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
