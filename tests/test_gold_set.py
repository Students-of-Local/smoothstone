"""The gold set must grade on a clean checkout: each part's engineering.json is tracked (PR 70 r1 F1)."""
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_every_gold_part_tracks_its_engineering_json():
    tracked = set(subprocess.run(["git", "ls-files", "evals/gold"], cwd=REPO, capture_output=True, text=True,
                                 check=True).stdout.split())
    parts = sorted(p.parent.name for p in (REPO / "evals" / "gold").glob("*/part.scad"))
    assert parts, "no gold parts"
    missing = [p for p in parts if f"evals/gold/{p}/build/engineering.json" not in tracked]
    assert missing == [], missing
