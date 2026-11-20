"""The reference library: every fact sourced, and stone applies it to the job on its own."""

import json
import re

import pytest

from smoothstone import refs
from test_cli import REPO, stone

REFS = REPO / "recipes" / "lib" / "refs"


def entries():
    for f in refs.FILES:
        for e in json.loads((REFS / f"{f}.json").read_text())["entries"]:
            yield f, e


def test_every_entry_has_a_source_url_and_date():
    ids = set()
    for f, e in entries():
        where = f"{f}.json {e.get('id')}"
        assert e["id"] not in ids, where
        ids.add(e["id"])
        assert re.match(r"https?://\S+\.\S+", e.get("url", "")), where
        for k in ("source", "cite", "quote"):
            assert isinstance(e.get(k), str) and e[k].strip(), f"{where}: no {k}"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", e.get("checked", "")), where
        assert e.get("value") not in (None, ""), where
    assert len(ids) > 100


def test_library_has_no_em_or_en_dashes():
    for f in refs.FILES:
        text = (REFS / f"{f}.json").read_text()
        assert "—" not in text and "–" not in text, f


def test_every_material_has_its_print_temperatures():
    for m in refs.MATERIALS.values():
        for key in ("nozzle", "bed"):
            e = refs.get(f"{m.key}.{key}")
            assert e["unit"] == "C" and e["value"][0] < e["value"][1], e["id"]


def test_patio_planter_in_full_sun_is_petg_or_asa_never_pla():
    pick = refs.material_for("a planter for my patio in full sun", "planter")
    assert pick.material in ("PETG", "ASA")
    line = pick.line()
    assert line.startswith("Material: PETG, nozzle 240 to 260 C, bed 70 to 90 C (outdoors in sun: PLA softens near 55 C")
    assert "Prusament PETG datasheet" in line
    # naming PLA does not get PLA into the sun
    pick = refs.material_for("a PLA planter for my patio in full sun", "planter")
    assert pick.material != "PLA" and pick.refused.startswith("Not PLA: it softens near 55 C")


def test_patio_planter_show_and_build_print_the_material(jobenv, openscad, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    stone("new", "A planter for my patio in full sun")
    text, code, nxt = stone("show", "planter")
    block = text.split("References:\n", 1)[1].split("\nParameters", 1)[0].splitlines()
    assert 1 <= len(block) <= 3 and all(ln.endswith(")") for ln in block), block
    assert block[0].startswith("Material: PETG") and "Material: PLA" not in text
    stone("set", "planter", "height=60", "top_d=60", "base_d=50", "quality=48")
    text, code, nxt = stone("build")
    assert code == 0 and nxt == "none, the part is ready", text
    mats = [ln for ln in text.splitlines() if ln.startswith("Material:")]
    assert len(mats) == 1 and mats[0].startswith("Material: PETG, nozzle 240 to 260 C"), text


def test_tpu_phone_case_gets_tpu_and_its_temperatures():
    pick = refs.material_for("a case for my iPhone 17 in TPU", "phone_case", {"material": "tpu"})
    assert pick.material == "TPU"
    assert pick.line().startswith("Material: TPU 95A, nozzle 220 to 240 C, bed 55 to 75 C (flexible")
    # a rigid case is cut 0.25 mm loose, so it never gets TPU
    assert refs.material_for("a phone case", "phone_case", {"material": "rigid"}).material != "TPU"


def test_tpu_phone_case_show(jobenv, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    stone("new", "A TPU case for my iPhone 17")
    text, code, nxt = stone("show", "phone_case")
    assert "material=tpu" in nxt
    assert "Material: TPU 95A, nozzle 220 to 240 C" in text


@pytest.mark.parametrize("request_", ["a clip for my dishwasher rack in PLA", "a dishwasher basket clip",
                                      "a PLA+ hook for inside the dishwasher"])
def test_dishwasher_part_refuses_pla(request_):
    pick = refs.material_for(request_, "hook")
    assert pick.material not in ("PLA", "PLA+")
    assert "dishwasher heat: PLA softens near 55 C" in pick.line()
    if "PLA" in request_:
        assert pick.refused.startswith("Not PLA") and "too soft for a dishwasher" in pick.refused


def test_uses_pick_their_material():
    cases = {
        ("a phone mount for my car dashboard", "phone_stand"): "ASA",
        ("a flexible bumper for a table leg", "box"): "TPU",
        ("a bracket for a heavy shelf", "hook"): "PC",
        ("a toy car for my kid", "box"): "PLA+",
        ("a box for my desk", "box"): "PLA",
        ("a box in PETG", "box"): "PETG",
    }
    for (req, recipe), want in cases.items():
        assert refs.material_for(req, recipe).material == want, req


def test_food_contact_never_overclaims():
    pick = refs.material_for("a cookie cutter shaped like my dog", "cookie_cutter")
    text = "\n".join(pick.lines())
    assert "no FDM print is certified food safe" in text
    # "food safe" only ever as the maker's words about the raw material, the denial, or a page title
    allowed = ("no FDM print is certified food safe", "raw material food safe per maker", "food safe FDM printing")
    for phrase in allowed:
        text = text.replace(phrase, "")
    assert "food safe" not in text


def test_contrast_ratio_follows_wcag():
    assert refs.contrast_ratio("#FFFFFF", "#000000") == pytest.approx(21.0)
    assert refs.contrast_ratio("#FFFFFF", "#FFFFFF") == pytest.approx(1.0)
    lines = [r.line() for r in refs.standards_for("sign", {"text": "HI"}, "a white sign with yellow letters")]
    assert any("Contrast of white and yellow filament" in ln and "under the 4.5:1" in ln for ln in lines)


def test_standards_for_parts():
    def texts(recipe, params, request=""):
        return " | ".join(r.line() for r in refs.standards_for(recipe, params, request))
    assert "screw holes 105 mm apart" in texts("fan_guard", {"size": 120})
    assert "12 mm across" in texts("fan_guard", {"size": 120})
    assert "M3 clearance hole: 3.2 fine, 3.4 medium, 3.6 coarse" in texts("panel", {"hole_d": 3.4})
    assert "14.7 x 19.3 mm" in texts("panel", {"hole_d": 3.4}, "a keystone panel")
    assert "6-32" in texts("panel", {}, "a light switch wall plate")
    assert "42 mm" in texts("gridfinity_bin", {})


def test_sign_build_with_small_text_prints_the_ada_line(jobenv, openscad, monkeypatch):
    monkeypatch.setenv("STONE_RECIPES", str(REPO / "recipes"))
    stone("new", "A small door sign that says OFFICE")
    stone("set", "sign", "text=OFFICE", "w=80", "h=30", "text_size=8", "holes=none")
    text, code, nxt = stone("build")
    assert code == 0, text
    ada = [ln for ln in text.splitlines() if "ADA 703.5.5" in ln]
    assert len(ada) == 1 and "Letters 8 mm high read up close only" in ada[0], text
    assert ada[0].endswith("(2010 ADA Standards, ADA.gov)")
    # letters big enough: no ADA line after the build
    stone("set", "sign", "text=OFFICE", "w=160", "h=50", "text_size=20", "holes=none")
    text, code, nxt = stone("build")
    assert code == 0 and "ADA" not in text, text


def test_stone_refs_lists_topics_and_facts(jobenv):
    text, code, nxt = stone("refs")
    assert code == 0 and "PETG" in text and nxt == 'stone new "<what to make>"'
    text, code, nxt = stone("refs", "PETG")
    assert "PETG nozzle: 240 to 260 C (Prusament PETG datasheet)" in text
    text, code, nxt = stone("refs", "fan")
    assert "fan.120: hole spacing 105 mm" in text
    text, code, nxt = stone("refs", "nonsense-topic")
    assert code == 1 and "No reference matches" in text
