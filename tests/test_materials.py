"""materials.json: printed-part properties for stone strength and stone heat, every number with its source."""

import json
import re

import pytest

from smoothstone import refs
from test_cli import REPO, stone

DATA = json.loads((REPO / "recipes" / "lib" / "refs" / "materials.json").read_text())["entries"]
NINE = ["PLA", "PETG", "ABS", "ASA", "TPU", "PA", "PC", "PLA-CF", "PETG-CF"]
EVERY = ("density", "e_xy", "e_z", "tensile_xy", "tensile_z", "cte", "mfi")
RIGID = ("tg", "hdt_045", "modulus_vs_temp", "shrink", "creep")


@pytest.mark.parametrize("name", NINE)
def test_every_material_has_its_fields_with_sources(name):
    p = refs.props(name)
    need = EVERY + (() if name == "TPU" else RIGID) + (("vicat",) if name == "TPU" else ())
    for key in need:
        e = p.get(key)
        assert e, f"{name} has no {key}"
        for k in ("source", "cite", "quote", "url", "checked"):
            assert isinstance(e.get(k), str) and e[k].strip(), f"{e['id']}: no {k}"
        assert re.match(r"https?://\S+\.\S+", e["url"]) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", e["checked"])
        for o in e.get("others", []):
            assert o["url"].startswith("http") and o["cite"] and o["quote"], e["id"]


def _shown(v: float, quote: str) -> bool:
    """The number as a maker prints it: 2580, 35, 1.24, 69.7 (or 1.2 GPa for 1200 MPa)."""
    forms = {f"{v:g}", f"{v:.1f}", f"{v:.2f}", f"{v / 1000:g}"}
    return any(re.search(rf"(?<![\d.]){re.escape(f)}(?![\d])", quote) for f in forms)


def test_a_measured_number_is_in_its_quote():
    """A typo in the data (or a swapped column) shows: the value used and every other maker's value is in its quote."""
    checked = 0
    for e in DATA:
        if e.get("assumption") or not isinstance(e["value"], (int, float)) or e["key"] in ("shrink", "hdt_modulus"):
            continue
        if e["id"] == "tpu.density":  # the sheet gives 1.20-1.24; the middle is used
            continue
        assert _shown(e["value"], e["quote"]), (e["id"], e["value"], e["quote"])
        for o in e.get("others", []):
            assert _shown(o["value"], o["quote"]), (e["id"], o)
        checked += 1
    assert checked >= 60


def test_ranges_hold_the_value_used_and_layers_are_weaker():
    for e in DATA:
        if "range" in e:
            lo, hi = e["range"]
            assert lo <= e["value"] <= hi, e["id"]
    for name in NINE:
        p = refs.props(name)
        assert p["tensile_z"]["value"] <= p["tensile_xy"]["value"], name
        assert p["e_z"]["value"] <= p["e_xy"]["value"], name


def test_retention_curves_start_at_one_and_run_up_in_temperature():
    for name in NINE:
        e = refs.props(name).get("modulus_vs_temp")
        if not e or not isinstance(e["value"], list):
            continue
        pts = e["value"]
        assert pts[0] == [20, 1.0], name
        assert all(a[0] < b[0] for a, b in zip(pts, pts[1:])), name
        assert all(0 < r <= 1.0 for _, r in pts), name
    assert refs.get("pc.modulus_vs_temp")["assumption"]


def test_derived_numbers_follow_their_formula():
    assert refs.get("any.hdt_modulus")["value"] == round(800 * 0.45 / 1.82)
    for name in NINE:
        p = refs.props(name)
        if "shrink" in p:
            want = p["cte"]["value"] * 1e-6 * (p["tg"]["value"] - 25) * 100
            assert p["shrink"]["value"] == pytest.approx(want, abs=0.01), name


def test_material_words():
    assert refs.strength_material("petg-cf") == "PETG-CF"
    assert refs.strength_material("PLA_CF") == "PLA-CF"
    assert refs.strength_material("nylon") == "PA"
    assert refs.strength_material("PLA+") == "PLA"
    assert refs.strength_material("wood") is None


def test_stone_refs_shows_printed_strength(jobenv):
    text, code, nxt = stone("refs", "PLA-CF")
    assert code == 0 and "PLA-CF strength between layers: 15.1 MPa (Polymaker PolyLite PLA-CF datasheet)" in text
    text, code, nxt = stone("refs", "PETG")
    assert "PETG nozzle: 240 to 260 C (Prusament PETG datasheet)" in text
