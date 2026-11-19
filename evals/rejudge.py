"""Judge a finished figure run's likeness again, where `claude` is signed in.

uv run python evals/rejudge.py <run dir> [<run dir> ...]

A run on a host whose `claude` is not signed in fails with "the judge could not answer". Copy its
log.json and job/image/figure here and rejudge it: the other checks keep their verdict, only the
likeness is asked again, log.json is rewritten with "rejudged" set, and one more line goes to
scores.jsonl. A spec edited since the run is refused, as its verdict would not be the run's.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("run_evals", ROOT / "evals" / "run.py")
run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run)


def rejudge(rdir: Path) -> dict:
    log = json.loads((rdir / "log.json").read_text())
    spec_path = ROOT / "evals" / log["suite"] / f"{log['spec']}.json"
    if hashlib.sha256(spec_path.read_bytes()).hexdigest() != log.get("spec_sha256"):
        raise SystemExit(f"{spec_path.name} changed since run {log['run_id']}; run it again instead")
    spec = json.loads(spec_path.read_text())
    exp = spec["followups"][-1]["expect"] if spec.get("followups") else spec["expect"]
    if exp.get("recipe") != "figure":
        raise SystemExit(f"{log['spec']} is not a figure spec")
    other = [w for w in log.get("why", []) if not w.startswith("likeness")]
    grade = {"pass": not other, "why": other or ["all checks pass"]}
    grade = run.likeness_run(rdir, rdir / "job", spec["request"], grade, (exp.get("likeness") or {}).get("min"))
    if other:
        grade["pass"] = False
    log.update({k: grade[k] for k in ("pass", "why", "likeness")})
    log["rejudged"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    (rdir / "log.json").write_text(json.dumps(log, indent=1))
    run.append_score(log)
    return log


def main() -> int:
    bad = 0
    for d in sys.argv[1:]:
        log = rejudge(Path(d).resolve())
        print(("PASS  " if log["pass"] else "FAIL  ") + f"{log['run_id']}  likeness {log['likeness']}  "
              + "; ".join(log["why"])[:160], flush=True)
        bad += not log["pass"]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
