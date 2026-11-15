"""The request matcher on the tuning requests (never the held-out ones)."""
import json
from pathlib import Path

import pytest

from smoothstone import match
from smoothstone import recipes as rc

TUNING = sorted((Path(__file__).resolve().parents[1] / "evals" / "tuning").glob("*.json"))


@pytest.mark.parametrize("spec", TUNING, ids=lambda p: p.stem)
def test_suggestion_meets_the_spec(spec, monkeypatch):
    monkeypatch.delenv("STONE_RECIPES", raising=False)
    s = json.loads(spec.read_text())
    r = rc.load(s["expect"]["recipe"])
    got = {**r.merged({}), **match.suggest(r, s["request"])}
    for k, want in s["expect"]["params"].items():
        if isinstance(want, list):
            assert want[0] <= got[k] <= want[1], (k, got[k])
        else:
            assert got[k] == want, (k, got[k])


@pytest.mark.parametrize("request_text, want", [
    ("a small plate with one hole", {}),
    ("a 40 mm fan guard with a honeycomb grille", {"size": 40, "style": "honeycomb"}),
    ("fan guard, 2 inches", {"size": 50.8}),
])
def test_small_cases(request_text, want, monkeypatch):
    monkeypatch.delenv("STONE_RECIPES", raising=False)
    r = rc.load("fan_guard")
    assert match.suggest(r, request_text) == want
