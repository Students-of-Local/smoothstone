import ctypes
import gc
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

if sys.platform == "linux":  # M_ARENA_MAX: glibc's arena per thread kept 1.1 GB in a worker that two arenas hold at 0.2 GB
    try:
        ctypes.CDLL(None).mallopt(-8, 2)
    except AttributeError:
        pass  # another libc

from smoothstone import config

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def memory_returned_after():
    """A test's meshes hold their own caches in cycles, and glibc keeps what they free. A worker past
    test_parts.py held 1.7 GB and 0.2 GB once trimmed. Four such workers ran the suite out of memory."""
    yield
    gc.collect()
    trim = getattr(ctypes.CDLL(None), "malloc_trim", None) if sys.platform == "linux" else None
    if trim:
        trim(0)


@pytest.fixture(autouse=True)
def no_user_config(tmp_path_factory, monkeypatch):
    """Keep the machine's own ~/.config/smoothstone/stone.toml out of every test."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("xdg")))
    # the face models download on first use: no test reaches the network for them
    monkeypatch.setenv("STONE_FACES", "0")


@pytest.fixture(autouse=True)
def no_structure_lookup(monkeypatch):
    """A request no recipe fits asks Wikidata what its subject is: no test reaches the network for it."""
    from smoothstone import landmark_refs

    monkeypatch.setattr(landmark_refs, "is_structure", lambda name: False)


@pytest.fixture(autouse=True)
def shipped_catalog_after():
    """stone makes each command's job the current one, with its own products in the catalog
    (catalog.use_job): the next test starts from the shipped catalog."""
    yield
    from smoothstone import catalog

    catalog.use_job(None)


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
    """A test marked network reaches a live site: it runs only with STONE_NETWORK=1. A timing test measures
    this machine alone, and the largest takes 3.7 GB: beside other workers it fails on their load and runs
    the suite out of memory, so it runs only without them, as CI's own pass does."""
    skips = {}
    if os.environ.get("STONE_NETWORK") != "1":
        skips["network"] = "reaches the network; set STONE_NETWORK=1 to run it"
    if os.environ.get("PYTEST_XDIST_WORKER"):
        skips["timing"] = "runs without other workers: pytest -m timing"
    for item in items:
        for marker, reason in skips.items():
            if marker in item.keywords:
                item.add_marker(pytest.mark.skip(reason=reason))
