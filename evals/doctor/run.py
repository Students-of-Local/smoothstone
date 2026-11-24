"""Score stone doctor on a folder of cases: top-1, top-3 and the causes check.

uv run python evals/doctor/run.py [evals/doctor_heldout] [--json] [--show]

A case passes top-1 when its expected failure ranks first, and top-3 when the expected failure
and every failure in expect.top3_includes are in the first three. When a case names
expect.causes_top3_includes, those causes must be among the top three causes of its top failure.
--json prints the scores keyed the way evals/floor.json keeps them ("doctor/top1", "doctor/top3";
"doctor_heldout/..." for that folder).

evals/doctor holds the cases the words were tuned on (d: written first, h and b: two sets another model
wrote blind, each measured once before tuning). evals/doctor_heldout is a third blind set nobody tuned
on: keep it that way, or its number stops meaning anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from smoothstone import doctor, printers

HERE = Path(__file__).resolve().parent


def cases(folder: Path = HERE) -> list[dict]:
    return [json.loads(f.read_text()) for f in sorted(Path(folder).glob("*.json"))]


def score(case: dict) -> dict:
    exp = case["expect"]
    d = doctor.diagnose(case["said"], printers.get(case.get("printer")), case.get("material"))
    ranked = [fid for fid, _ in d["failures"]]
    top3 = ranked[:3]
    top1 = bool(ranked) and ranked[0] == exp["top"]
    in3 = exp["top"] in top3 and all(f in top3 for f in exp.get("top3_includes", []))
    want_causes = exp.get("causes_top3_includes") or []
    causes = [c for c, _ in doctor.top_causes(d["causes"])] if top1 else []
    causes_ok = all(c in causes for c in want_causes) if want_causes else None
    return {"id": case["id"], "top1": top1, "top3": in3, "causes": causes_ok, "ranked": top3,
            "want": exp["top"], "top_causes": causes}


def measure(rows: list[dict], suite: str = "doctor") -> dict:
    n = len(rows)
    return {f"{suite}/{k}": {"rate": round(sum(r[k] for r in rows) / n, 4), "judge": None, "total": n,
                             "passing": sorted(r["id"] for r in rows if r[k])} for k in ("top1", "top3")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder", nargs="?", default=str(HERE))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show", action="store_true", help="one line per case that misses")
    a = ap.parse_args(argv)
    folder = Path(a.folder).resolve()
    rows = [score(c) for c in cases(folder)]
    m = measure(rows, folder.name)
    t1, t3 = m[f"{folder.name}/top1"], m[f"{folder.name}/top3"]
    if a.json:
        print(json.dumps(m, indent=1, sort_keys=True))
        return 0
    if a.show:
        for r in rows:
            if not (r["top1"] and r["top3"] and r["causes"] is not False):
                print(f"{r['id']}: want {r['want']}, got {r['ranked']}, causes {r['top_causes']}")
    c = [r["causes"] for r in rows if r["causes"] is not None]
    print(f"{folder.name}: top-1 {t1['rate']:.0%} ({len(t1['passing'])}/{len(rows)}), "
          f"top-3 {t3['rate']:.0%} ({len(t3['passing'])}/{len(rows)}), "
          f"causes {sum(c)}/{len(c)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
