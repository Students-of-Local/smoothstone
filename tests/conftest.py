import json
import shutil
from pathlib import Path

import pytest

from smoothstone import config

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def no_user_config(tmp_path_factory, monkeypatch):
    """Keep the machine's own ~/.config/smoothstone/stone.toml out of every test."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("xdg")))
    # the face models download on first use: no test reaches the network for them
    monkeypatch.setenv("STONE_FACES", "0")


@pytest.fixture
def openscad():
    binary = config.find_openscad()
    if not binary:
        pytest.skip("no OpenSCAD binary")
    return binary


@pytest.fixture
def recipes_root(tmp_path, monkeypatch):
    """Recipe folder with _demo plus one visible S recipe and one hidden-by-tier L recipe."""
    root = tmp_path / "recipes"
    root.mkdir()
    shutil.copytree(REPO / "recipes" / "_demo", root / "_demo")
    for name, tier, title, tags in [
        ("fake_hook", "S", "Wall hook", ["hook", "wall"]),
        ("fake_gear", "L", "Spur gear", ["gear"]),
    ]:
        d = root / name
        d.mkdir()
        (d / "recipe.scad").write_text("size = 20;\ncube(size, center = false);\n")
        (d / "recipe.json").write_text(json.dumps({
            "name": name, "title": title, "summary": f"A {title.lower()}.",
            "tags": tags, "tier": tier,
            "params": [{"name": "size", "type": "number", "default": 20, "min": 5, "max": 100,
                        "unit": "mm", "help": "edge"}],
            "dims": {"x": "size", "y": "size", "z": "size"},
        }))
    monkeypatch.setenv("STONE_RECIPES", str(root))
    return root


@pytest.fixture
def jobenv(tmp_path, monkeypatch, recipes_root):
    """Clean cwd and job dir, tier S, no stray env."""
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.delenv("STONE_TIER", raising=False)
    monkeypatch.setenv("STONE_JOB", str(work / "stone-job"))
    return work


def pytest_collection_modifyitems(config, items):
    """A test marked network reaches a live site: it runs only with STONE_NETWORK=1."""
    import os

    if os.environ.get("STONE_NETWORK") == "1":
        return
    skip = pytest.mark.skip(reason="reaches the network; set STONE_NETWORK=1 to run it")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)
