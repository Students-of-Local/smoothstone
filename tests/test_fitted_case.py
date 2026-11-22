"""fitted_case and the product catalog: a case for a real product, built from the maker's sizes.

The catalog holds each engineering spec's product block word for word, finds a product by the
names and model numbers people type, and the fitted case ranks first for a named product without
taking iPhone cases from phone_case. Stone's own NEXT lines, run one after another as evals/run.py
--driver next does, must reach a part the engineering grader passes for e01, e02, e03 and e10.
"""
import importlib.util
import json
import re
from pathlib import Path

import pytest

from smoothstone import catalog, cli, fitted, match
from smoothstone import recipes as rc

REPO = Path(__file__).resolve().parent.parent
SPECS = {json.loads(f.read_text())["id"]: json.loads(f.read_text()) for f in sorted((REPO / "evals" / "engineering").glob("*.json"))}

_g = importlib.util.spec_from_file_location("engineering_grade", REPO / "evals" / "engineering_grade.py")
grade = importlib.util.module_from_spec(_g)
_g.loader.exec_module(grade)


def test_catalog_holds_every_engineering_product_word_for_word():
    by_spec = {p["from_spec"]: p for p in catalog.all_products().values()}
    assert len(by_spec) == len(SPECS) == 10
    for sid, spec in SPECS.items():
        p = by_spec[f"evals/engineering/{sid}.json"]
        for k in ("name", "body", "body_sources", "features", "sources"):
            assert p[k] == spec["product"].get(k, [] if k == "features" else {}), (sid, k)
        assert p["set"] == "tuning"


def test_every_size_names_a_url_its_own_source_cites():
    for slug, p in catalog.all_products().items():
        src = catalog.sources(p)
        need = ["w", "d", "h", "corner_r"] + (["profile"] if p["body"].get("profile") else []) + \
            [f["name"] for f in p["features"]]
        own = dict(p["body_sources"]) | {f["name"]: f["source"] for f in p["features"]}
        for k in need:
            assert src.get(k) and src[k] in own[k], (slug, k)


@pytest.mark.parametrize("text,slug", [
    ("a case for my Flipper Zero", "flipper_zero"),
    ("A case for an ABX00080.", "arduino_uno_r4_minima"),
    ("a case for an abx00080", "arduino_uno_r4_minima"),
    ("a snug TPU sleeve for my Anker Power Bank (10000mAh, 22.5W)", "anker_a1388"),
    ("a sleeve for my anker a1388", "anker_a1388"),
    ("A snap together case for a Raspberry Pi 5, open on top", "raspberry_pi_5"),
    ("a case for a raspberry pi 4", "raspberry_pi_4"),
    ("a case for my Garmin watch", None),
])
def test_find_reads_names_and_model_numbers(text, slug):
    assert catalog.find(text) == slug


def _top(query: str) -> str:
    vis = rc.visible(rc.load_all(REPO / "recipes"), "S")
    ranked = rc.rank(vis, query)
    fits = {r.name: rc.fit(r, query) for _, r in ranked}
    ranked.sort(key=lambda sr: -fits[sr[1].name])
    return ranked[0][1].name


@pytest.mark.parametrize("query,want", [
    ("a case for my Flipper Zero", "fitted_case"),
    ("A case for an ABX00080.", "fitted_case"),
    ("a snug TPU sleeve for my Anker Power Bank (10000mAh, 22.5W)", "fitted_case"),
    ("a case for my iPhone 17 Pro", "phone_case"),
    ("a TPU case for my iPhone Air", "phone_case"),
    ("a box with a lid", "box"),
])
def test_a_named_product_ranks_fitted_case_first_but_iphones_stay_phone_case(query, want):
    assert _top(query) == want


def test_a_product_not_in_the_catalog_asks_for_its_size_and_ports():
    r = rc.load("fitted_case", REPO / "recipes")
    ask = match.missing_fit_size(r, "a case for my Garmin watch")
    assert ask and "width, depth and height in mm" in ask and "ports" in ask
    assert match.missing_fit_size(r, "a case for my Flipper Zero") is None
    assert match.missing_fit_size(r, "a case for it", ["product arduino uno r4 minima"]) is None
    assert match.missing_fit_size(r, "fitted_case defaults") is None  # no fit asked: the default product builds


def test_products_scad_is_generated_from_the_catalog():
    assert (REPO / "recipes" / "fitted_case" / "products.scad").read_text() == catalog.scad_table()


def test_engineering_json_reads_the_part_from_the_build_log():
    r = rc.load("fitted_case", REPO / "recipes")
    log = ('ECHO: stone_fit = [2.3, 2.3, 3.3, 0.3, 0, 2, 2, "snap"]\n'
           "ECHO: stone_snap = [66.8, 1.3, 7.98, 0, 1, 0, 6, 1, 2, 15]\n")
    eng = fitted.engineering(r, {"product": "raspberry_pi_5", "material": "PLA"}, log)
    assert eng["frame"][0][3] == 2.3 and eng["frame"][2][3] == 3.3
    assert eng["retention"] == {"type": "snap", "at": [66.8, 1.3, 7.98], "t_dir": [0, 1, 0], "L_dir": [0, 0, 1],
                                "w": 6.0, "y": 1.0, "t": 2.0, "L": 15}
    assert set(eng["clearance"]) == {"+x", "-x", "+y", "-y"}  # a board bears on standoffs: no -z gap
    assert eng["sources"]["usb_c_power"].startswith("https://datasheets.raspberrypi.com/")
    assert fitted.engineering(rc.load("box", REPO / "recipes"), {}, log) is None


def _follow_next(request: str, steps: int = 10) -> list[str]:
    """Run stone new, then every NEXT line stone prints, as evals/run.py --driver next does."""
    text, _ = cli.run(["new", request])
    nxt, ran = "stone status", []
    for _ in range(steps):
        if not nxt or "<" in nxt or nxt.startswith(("none", "ask the person")):
            break
        ran.append(nxt)
        import shlex
        text, _ = cli.run(shlex.split(nxt)[1:])
        found = re.findall(r"^NEXT: (.+)$", text, re.M)
        nxt = found[-1].strip() if found else nxt
    ran.append(nxt)
    return ran


@pytest.mark.parametrize("sid", ["e02_flipper_zero_case", "e10_model_number_case", "e03_power_bank_case",
                                 "e01_rpi5_case"])
def test_stones_own_path_makes_a_part_the_engineering_grade_passes(sid, jobenv, openscad, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    spec = SPECS[sid]
    ran = _follow_next(spec["request"])
    assert ran[-1].startswith("none, the part is ready"), ran
    assert any(c.startswith("stone show fitted_case") for c in ran), ran
    job = jobenv / "stone-job"
    res = grade.grade(job, spec, job / "fitted_case.stl")
    assert res["why"] == [], res["why"]


def test_a_catalog_product_a_tray_cannot_hold_is_named_not_measured_again():
    r = rc.load("fitted_case", REPO / "recipes")
    ask = match.missing_fit_size(r, "a case for an Apple AirTag (the 2021 one)")
    assert ask.startswith("I have the Apple AirTag (2021)'s sizes") and "round body" in ask
