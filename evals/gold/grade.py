"""Grade one gold part: uv run python evals/gold/grade.py <spec id> [...]

Builds evals/gold/<id>/part.scad with OpenSCAD into a scratch folder laid out as the grader
expects (part.stl, build/engineering.json) and runs evals/engineering_grade.py on it against
evals/engineering/<id>.json. Prints one line per part; exits 1 if any fails.
Reference designs by GPT-6.1 Sol, smoothstone gold set.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "evals"))
sys.path.insert(0, str(REPO / "src"))
import engineering_grade as g  # noqa: E402
from smoothstone import config  # noqa: E402


def grade_one(sid: str) -> list[str]:
    spec = json.loads((REPO / "evals" / "engineering" / f"{sid}.json").read_text())
    binary = config.find_openscad()
    with tempfile.TemporaryDirectory() as d:
        job = Path(d)
        (job / "build").mkdir()
        shutil.copy(HERE / sid / "build" / "engineering.json", job / "build" / "engineering.json")
        subprocess.run([binary, "-o", str(job / "part.stl"), str(HERE / sid / "part.scad")], check=True,
                       capture_output=True, timeout=600)
        return g.grade(job, spec, job / "part.stl")["why"]


if __name__ == "__main__":
    ids = sys.argv[1:] or sorted(p.name for p in HERE.iterdir() if (p / "part.scad").is_file())
    bad = 0
    for sid in ids:
        why = grade_one(sid)
        bad += bool(why)
        print(f"{sid}  {'PASS' if not why else 'FAIL  ' + '; '.join(why)}", flush=True)
    sys.exit(1 if bad else 0)
