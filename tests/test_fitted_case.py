"""fitted_case and the product catalog: a case for a real product, built from the maker's sizes.

The catalog holds each engineering spec's product block word for word, finds a product by the
names and model numbers people type, and the fitted case ranks first for a named product without
taking iPhone cases from phone_case. Stone's own NEXT lines, run one after another as evals/run.py
--driver next does, must reach a part the engineering grader passes for e01, e02, e03 and e10.
"""
import importlib.util
import json
import math
import re
from pathlib import Path

import pytest

import numpy as np

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


def test_a_product_not_in_the_catalog_is_asked_for_by_maker_and_model_only():
    r = rc.load("fitted_case", REPO / "recipes")
    ask = match.missing_fit_size(r, "a case for my Garmin watch")
    assert ask == "Which product is it, exactly (its maker and model number)?"  # no sizes: it takes none
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


# --- PR 67 review round 1 --------------------------------------------------------------------------

SIDE_FACES = ("+x", "-x", "+y", "-y")


def test_every_case_product_leaves_each_port_face_open_or_windowed():
    """first-F1 and second-F6: a fitted case walls each side face and floors the bottom, so every face
    the maker puts a port, button or slot on must be open (a side) or have its ports located (a window).
    A bottom whose ports are not located cannot be left open by a tray, so that product is no case."""
    for slug in catalog.case_slugs():
        p = catalog.get(slug)
        pf = p.get("port_faces")
        assert pf is not None, f"{slug}: a case product must say which faces have ports (port_faces)"
        open_faces = set(p.get("open_faces", []))
        located = {f["face"] for f in p["features"] if f["kind"] != "hole"}
        for face, state in pf.items():
            if state == "located":
                assert face in located, (slug, face, "says located but no feature is on it")
            else:
                assert face in open_faces and face != "-z", (slug, face, "ports not located, so the face must stay open")
        for face in SIDE_FACES:
            if face not in open_faces:
                assert pf.get(face, "located") == "located", (slug, face)


@pytest.mark.parametrize("text,slug", [("a case for a raspberry pi 4", "raspberry_pi_4"),
                                       ("a case for my Mac mini M4", "mac_mini_m4_2024")])
def test_a_product_with_unlocated_ports_a_tray_would_cover_is_refused(text, slug):
    assert slug not in catalog.case_slugs()
    assert _top(text) != "fitted_case" or match.missing_fit_size(rc.load("fitted_case", REPO / "recipes"), text)
    ask = match.missing_fit_size(rc.load("fitted_case", REPO / "recipes"), text)
    assert ask.startswith(f"I have the {catalog.get(slug)['name']}'s sizes"), ask


def _echo(openscad, **params) -> tuple[dict, str]:
    """Evaluate recipe.scad without rendering: its stone_* echoes, and the errors it raised."""
    import subprocess
    import tempfile
    from smoothstone import config
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "t.echo"
        cmd = [openscad, "-o", str(out)]
        for k, v in params.items():
            cmd += ["-D", f"{k}={json.dumps(v)}"]
        res = subprocess.run(cmd + [str(REPO / "recipes" / "fitted_case" / "recipe.scad")], capture_output=True,
                             text=True, env=config.openscad_env(), timeout=120)
        text = out.read_text() if out.exists() else ""
    echoes = {m[0]: json.loads(m[1]) for m in re.findall(r"ECHO: (stone_\w+) = (\[.*\])", text)}
    return echoes, text + res.stderr  # in echo-only mode OpenSCAD writes its errors to the .echo file


STRAIN = {"PLA": 0.02, "PETG": 0.03, "TPU": 0.2}


@pytest.mark.parametrize("material,fit", [("PLA", "slip"), ("PETG", "snug"), ("TPU", "snug")])
def test_every_snap_catch_bears_on_a_surface_the_catalog_locates(openscad, material, fit):
    """first-F2: a snap catch over air holds nothing. Each catch's plan footprint must lie over a located
    surface along the wall, reach past its edge by a real margin with the product pushed away by its
    side clearance, and sit no more than 0.5 mm above that surface's top; a product with no such surface
    is refused, not given a catch."""
    snapping = 0
    for slug in catalog.case_slugs():
        p = catalog.get(slug)
        e, err = _echo(openscad, product=slug, retention="snap", material=material, fit=fit)
        if not catalog.snap_arms(p):
            assert "a snap catch must bear on a part of the product the catalog locates" in err, (slug, err)
            assert "stone_snap" not in e
            continue
        assert "Assertion" not in err, (slug, err)
        snapping += 1
        # the travel the pins allow: each echoed pin in its catalog hole; with no pins nothing bounds it
        holes = {(round(s_[0], 2), round(s_[1], 2)): s_[3] for s_ in catalog.standoffs(p)}
        pins = e.get("stone_locate", [None, []])[1]
        shift = max(((holes[(round(x, 2), round(y, 2))] - pin) / 2 for x, y, _, pin in pins), default=math.inf)
        assert shift <= catalog.PIN_PLAY / 2 + 1e-9, (slug, shift)
        surfaces = catalog.catch_surfaces(p)
        for x0, x1, y0, y1, under in e["stone_catch"]:
            def bears(s):
                _, sx0, sx1, sy0, sy1, top = s
                if not 0 <= under - top <= 0.5:
                    return False
                # the overlap in each plan axis, after the product shifts away by its clearance
                ox = min(x1, sx1) - max(x0, sx0) - shift
                oy = min(y1, sy1) - max(y0, sy0) - shift
                return min(ox, oy) >= 0.2
            assert any(bears(s) for s in surfaces), (slug, material, [x0, x1, y0, y1, under], surfaces)
        s = e["stone_snap"]
        y, t, L = s[7], s[8], s[9]
        assert 1.5 * y * t / L ** 2 <= STRAIN[material], (slug, material, s)
    assert snapping >= 1  # the Pi 5 snaps over its rear USB stack


@pytest.mark.parametrize("material,fit,retention,want", [
    ("PLA", "slip", "friction", None),    # 0.3 mm a side grips nothing: refused
    ("PLA", "snug", "friction", None),    # 0.15 mm still a gap
    ("PLA", "snug", "auto", "none"),      # auto no longer claims friction for a gap
    ("PLA", "press", "auto", "friction"),
    ("TPU", "snug", "auto", "friction"),
    ("TPU", "slip", "auto", "none"),      # TPU slip leaves 0.05 mm
])
def test_friction_is_claimed_only_for_an_interference_fit(openscad, material, fit, retention, want):
    """first-F5: the grader checks only that a friction gap lies in the fit's band, so a slip gap would
    pass there; the part itself claims friction only where it is tighter than the product."""
    e, err = _echo(openscad, product="anker_a1388", material=material, fit=fit, retention=retention)
    if want is None:
        assert "grips nothing" in err and "stone_fit" not in e, err
    else:
        assert e["stone_fit"][7] == want
        if want == "friction":
            assert e["stone_fit"][3] <= 0


# --- PR 67 review round 2 --------------------------------------------------------------------------

def test_an_answer_naming_no_catalog_product_ends_the_ask():
    """second-S1: fitted_case takes no sizes, so after the person answers it must not ask again; it says
    what it builds for and points to box."""
    r = rc.load("fitted_case", REPO / "recipes")
    first = match.missing_fit_size(r, "an enclosure for my Garmin watch")
    again = match.missing_fit_size(r, "an enclosure for my Garmin watch", ["45 x 45 x 12 mm"])
    assert again and again != first
    assert "builds only for products whose sizes it has sourced" in again and "stone show box" in again
    assert "Raspberry Pi 5" in again or "Flipper Zero" in again


def _follow_from(nxt: str, steps: int = 10) -> str:
    import shlex
    for _ in range(steps):
        if not nxt.startswith("stone "):
            break
        text, _ = cli.run(shlex.split(nxt)[1:])
        found = re.findall(r"^NEXT: (.+)$", text, re.M)
        nxt = found[-1].strip() if found else ""
    return nxt


def test_an_uncatalogued_product_on_the_next_path_ends_at_a_clear_answer(jobenv, monkeypatch):
    """second-S1 on stone's own path: ask, note, show, set must end at a plain answer, not the same ask."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    cli.run(["new", "a case for my Garmin watch"])
    first = _follow_from("stone status")
    assert first == "ask the person: Which product is it, exactly (its maker and model number)?", first
    seen = [first]
    for answer in ("Garmin Venu 3, 45 x 45 x 12 mm", "it is about 45 mm square"):
        text, _ = cli.run(["note", answer])
        seen.append(_follow_from(re.findall(r"^NEXT: (.+)$", text, re.M)[-1].strip()))
    assert all(x.startswith("ask the person: fitted_case builds only for products") and "stone show box" in x
               for x in seen[1:]), seen


def test_pins_hold_the_board_so_it_slides_no_farther_than_the_pin_play(openscad, tmp_path):
    """first-F1 (round 2): the Pi 5 must sit on pins in its mounting holes, measured in the built part,
    so it slides at most half the pin play, the travel the snap catch is sized for. Without pins its
    port shells slide on into their windows, 1.93 mm toward -y, and the catch misses the USB shell."""
    import trimesh

    from smoothstone import scad
    r = rc.load("fitted_case", REPO / "recipes")
    params = {**r.defaults(), "product": "raspberry_pi_5", "retention": "snap"}
    run = scad.build_stl(openscad, r, params, tmp_path / "pi5.stl")
    assert run.ok, run.log[-500:]
    mesh = trimesh.load(tmp_path / "pi5.stl", force="mesh")
    ox, oy, oz = json.loads(re.findall(r"ECHO: stone_fit = (\[.*\])", run.log)[-1])[:3]
    travel = json.loads(re.findall(r"ECHO: stone_locate = (\[.*\])", run.log)[-1])[0]
    pcb = catalog.get("raspberry_pi_5")["board"]["pcb_underside_z"]
    for x, y, _, hole, _pin in catalog.standoffs(catalog.get("raspberry_pi_5")):
        z = oz + pcb + 0.3  # inside the hole, under the pin's chamfer
        c = np.array([x + ox, y + oy, z])
        assert mesh.contains(c[None])[0], ("no pin in the hole", x, y)
        radii = []
        for a in np.linspace(0, 2 * np.pi, 16, endpoint=False):
            d = np.array([np.cos(a), np.sin(a), 0.0])
            lo, hi = 0.0, hole / 2 + 0.5
            for _ in range(20):
                mid = (lo + hi) / 2
                lo, hi = (mid, hi) if mesh.contains((c + d * mid)[None])[0] else (lo, mid)
            radii.append(lo)
        slide = hole / 2 - min(radii)
        assert 0 <= slide <= catalog.PIN_PLAY / 2 + 0.02, (x, y, slide)
        assert slide <= travel + 0.02


def _stone(*argv):
    text, code = cli.run(list(argv))
    found = re.findall(r"^NEXT: (.+)$", text, re.M)
    return text, code, found[-1].strip() if found else None


def test_show_for_a_filled_request_is_short_and_leads_with_next(jobenv, monkeypatch):
    """Climb 3, LFM3-1.7B on e02: after stone show fitted_case it spent its whole 2048 token budget
    re-reading the parameter list (every choice and help line) and stopped with no tool call. When
    the request fills what the part needs, tier S show says the NEXT line is ready first and lists the
    rest one short line each; --all and tier M keep the full list."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    _stone("new", "a case for my Flipper Zero")
    text, code, nxt = _stone("show", "fitted_case")
    assert code == 0 and nxt == "stone set fitted_case product=flipper_zero", text
    lines = text.splitlines()
    ready = next(i for i, ln in enumerate(lines) if "NEXT line below already holds" in ln)
    params = next(i for i, ln in enumerate(lines) if ln.startswith("Parameters"))
    assert ready < params and lines.index("From the request: product=flipper_zero") < ready, text
    assert len(lines) <= 16, text
    assert "the snap arm" not in text and "Example:" not in text and "Tier S." not in text, text
    assert "style = tray  (tray | sleeve)" in text and "product =" not in text, text
    full, _, nxt2 = _stone("show", "fitted_case", "--all")
    assert nxt2 == nxt and "snap arm" in full and len(full.splitlines()) > len(lines), full
    monkeypatch.setenv("STONE_TIER", "M")
    full_m, _, _ = _stone("show", "fitted_case")
    assert "snap arm" in full_m, full_m


def test_a_product_the_request_must_name_shows_no_wrong_default(jobenv, monkeypatch):
    """Climb 3, LFM3-1.7B on e02: show printed product = raspberry_pi_5 as the default beside NEXT
    product=flipper_zero, and the model reasoned over which one was right. A product parameter shows
    no default, and an example for another product is left out."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    _stone("new", "a case for my Flipper Zero")
    text, _, nxt = _stone("show", "fitted_case", "--all")
    assert nxt == "stone set fitted_case product=flipper_zero"
    assert "raspberry_pi_5" not in text.replace("| raspberry_pi_5", ""), text
    assert "product = (no default" in text, text
    _stone("new", "a phone case", "--force")
    text, _, _ = _stone("show", "phone_case")
    assert "phone = (no default" in text and "phone = iphone_17_pro " not in text, text


@pytest.mark.parametrize("request_, want", [
    ("A case for an ABX00080.", "fitted_case"),
    ("a snug TPU sleeve for my Anker Power Bank (10000mAh, 22.5W)", "fitted_case"),
    ("a case for my Flipper Zero", "fitted_case"),
    ("a desk stand that holds my iPhone 17 Pro upright in portrait so I can plug in USB-C", "product_holder"),
])
def test_phone_case_sends_a_product_it_does_not_fit_to_the_recipe_that_does(request_, want, jobenv, monkeypatch):
    """Climb 3, LFM2.5-24B-A2B on e03 and e10: it skipped stone recipes, ran stone show phone_case for a
    power bank and an Arduino ("ABX00080"), set phone=iphone_17_pro and asked "What phone model...".
    show and set of a recipe that cannot take the catalog product the request names point to the one
    that can, and a made up recipe name goes to the request's recipe, not the nearest name."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    _stone("new", request_)
    text, code, nxt = _stone("show", "phone_case")
    assert code == 1 and nxt == f"stone show {want}", text
    text, code, nxt = _stone("set", "phone_case", "phone=iphone_17_pro")
    assert code == 1 and nxt == f"stone show {want}" and not (jobenv / "stone-job" / "plan.json").exists(), text
    text, code, nxt = _stone("show", "power_bank_case")
    assert code == 1 and nxt == f"stone show {want}", text


def test_an_iphone_case_still_goes_to_phone_case(jobenv, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    _stone("new", "A case for my iPhone 17 Pro Max in TPU.")
    text, code, nxt = _stone("show", "phone_case")
    assert code == 0 and nxt == "stone set phone_case phone=iphone_17_pro_max material=tpu", text
    text, code, nxt = _stone("show", "phone_cse")  # a typo still goes to the nearest name
    assert nxt == "stone show phone_case", text


@pytest.mark.parametrize("request_, shown, want, noun", [
    ("a desk stand that holds my iPhone 17 Pro upright in portrait so I can plug in USB-C", "phone_stand",
     "product_holder", "stand"),
    ("a snug TPU sleeve for my Anker Power Bank (10000mAh, 22.5W)", "product_holder", "fitted_case", "sleeve"),
])
def test_a_near_recipe_for_a_catalog_product_points_to_the_one_stone_picked(request_, shown, want, noun, jobenv,
                                                                           monkeypatch):
    """Climb 3, LFM3-1.7B before: stone recipes said NEXT: stone show product_holder for an iPhone desk
    stand and fitted_case for a power bank sleeve; the model read the titles ("Product holder", "Fitted
    case for a product"), judged the NEXT line a mistake and showed phone_stand (guessed sizes, no
    finished part) or product_holder (a PLA cradle for a TPU sleeve). stone recipes now says why its
    pick fits, and show of the near recipe sends the model back to it."""
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    _stone("new", request_)
    text, _, nxt = _stone("recipes")
    assert nxt == f"stone show {want}" and text.startswith(f"For this request: {want} makes the {noun} for the "), text
    text, code, nxt = _stone("show", shown)
    assert code == 1 and nxt == f"stone show {want}", text
