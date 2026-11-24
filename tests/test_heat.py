"""stone heat: sourced service temperatures, softening curves, expansion and warp risk."""

import json

import numpy as np
import pytest
import trimesh

from smoothstone import heat, refs, strength
from test_cli import stone

CURVED = ["PLA", "PETG", "ABS", "ASA", "PA", "PLA-CF", "PETG-CF"]


@pytest.mark.parametrize("name", CURVED)
def test_derating_hits_the_sourced_points(name):
    pts = refs.props(name)["modulus_vs_temp"]["value"]
    low = 1.0
    for t, r in pts:
        low = min(low, r)  # a rise in the DMA curve is not credited
        assert heat.retention(name, t) == pytest.approx(low), (name, t)
    t0, r0 = pts[2]
    t1, r1 = pts[3]
    mid = heat.retention(name, (t0 + t1) / 2)
    assert min(r0, r1) - 1e-9 <= mid <= max(r0, r1) + 1e-9


def test_pc_holds_its_glassy_stiffness_until_near_its_hdt():
    p = refs.props("PC")
    assert heat.retention("PC", 23) == 1.0
    assert heat.retention("PC", 80) > 0.5  # 111 C HDT: a car at 80 C leaves it most of its stiffness
    assert 0.10 <= heat.retention("PC", p["hdt_045"]["value"]) <= 0.62  # what the measured curves keep at HDT
    assert heat.retention("TPU", 50) is None


def test_service_temperatures_are_sourced():
    assert heat.service("dishwasher")[0] == 75 and heat.service("car")[0] == 85
    assert heat.service("sun")[0] == 70 and heat.service("outdoor")[0] == 41.5
    assert heat.service("60C")[0] == 60 and heat.service("60")[0] == 60
    with pytest.raises(ValueError):
        heat.service("oven-ish")


def test_clamped_expansion_stress_is_e_alpha_dt_for_a_bar():
    """PLA holds all its stiffness from 20 to 30 C, so a bar held at both ends from 23 to 30 C carries E alpha dT."""
    p = refs.props("PLA")
    e, alpha = p["e_xy"]["value"], p["cte"]["value"] * 1e-6
    assert heat.clamped_stress("PLA", alpha, 23, 30) == pytest.approx(e * alpha * 7, rel=1e-9)
    assert heat.clamped_stress("PLA", alpha, 23, 60) < e * alpha * 37  # softening relieves it


def test_softened_part_bends_as_one_over_its_retention():
    bar = trimesh.creation.box(extents=[60, 8, 8])
    case = strength.parse(["load=5N", "at=right", "dir=down", "fixed=left"])[0]
    p = strength.material("PETG")
    r = heat.retention("PETG", 50)
    hot = strength.Props("PETG", p.e_xy * r, p.e_z * r, p.s_xy * r, p.s_z * r, p.exponent)
    cold_d = strength.solve(bar, case, p, 8_000)[1].deflection
    hot_d = strength.solve(bar, case, hot, 8_000)[1].deflection
    assert hot_d * r == pytest.approx(cold_d, rel=1e-4)


def test_warp_risk_grows_with_length_and_falls_in_an_enclosure():
    long_abs = trimesh.creation.box(extents=[200, 20, 5])
    small = trimesh.creation.box(extents=[20, 20, 5])
    assert heat.warp("ABS", long_abs, False, None)["level"] == "high"
    assert heat.warp("PLA", small, False, None)["level"] == "low"
    shut = heat.warp("ABS", long_abs, True, None)
    assert shut["lift_mm"] < heat.warp("ABS", long_abs, False, None)["lift_mm"]
    assert heat.warp("PLA", small, False, None)["area_mm2"] == pytest.approx(400, rel=0.03)


def test_stone_heat_flags_pla_in_a_dishwasher(jobenv):
    trimesh.creation.box(extents=[40, 20, 10]).export(jobenv / "box.stl")
    text, code, nxt = stone("heat", str(jobenv / "box.stl"), "where=dishwasher", "material=PLA")
    assert "75 C" in text and "past it" in text and "Warp risk" in text, text
    assert nxt.startswith("ask the person: ") and "PLA softens" in nxt, nxt
    d = json.loads((jobenv / "heat.json").read_text())
    assert d["verdict"] == "too hot" and d["warp_risk"]["level"] in ("low", "medium", "high") and d["temp_ref"] == "service.dishwasher"
    text, code, nxt = stone("heat", str(jobenv / "box.stl"), "where=dishwasher", "material=PC")
    assert json.loads((jobenv / "heat.json").read_text())["verdict"] == "fine", text
    text, code, nxt = stone("heat", "where=lava")
    assert code == 1 and "FIX: " in text


def test_stone_heat_resolves_a_load(jobenv, monkeypatch):
    monkeypatch.setattr(strength, "VOXELS", 8_000)
    monkeypatch.setattr(strength, "COARSE", 4_000)
    trimesh.creation.box(extents=[60, 8, 8]).export(jobenv / "bar.stl")
    text, code, nxt = stone("heat", str(jobenv / "bar.stl"), "where=50C", "material=PETG", "load=5N", "at=right",
                            "dir=down", "fixed=left")
    assert "Load 5 N: deflection" in text and "-> " in text, text
    d = json.loads((jobenv / "heat.json").read_text())
    assert d["load"]["deflection_hot_mm"] == pytest.approx(d["load"]["deflection_room_mm"] / heat.retention("PETG", 50), rel=1e-2)
    assert not np.isnan(d["clamped_stress_mpa"])
    text, code, nxt = stone("heat", str(jobenv / "bar.stl"), "where=40C", "material=PC", "load=5N", "at=left", "fixed=left")
    assert "Load not checked: the load at left sits on the held place" in text and nxt.startswith("ask the person: "), text
    text, code, nxt = stone("heat", str(jobenv / "bar.stl"), "where=40C", "load=heavy")
    assert code == 1 and "FIX: " in text and "load" in text, text


def test_enclosure_comes_from_the_printer_profile(jobenv, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(jobenv / "cfg"))
    trimesh.creation.box(extents=[150, 20, 5]).export(jobenv / "bar.stl")
    stone("heat", str(jobenv / "bar.stl"), "where=40C", "material=ABS")
    open_ = json.loads((jobenv / "heat.json").read_text())["warp_risk"]
    assert open_["enclosed"] is False and open_["enclosed_from"].startswith("assumed open")
    (jobenv / "stone.toml").write_text('[printer]\nmodel = "bambu_x1c"\n')
    stone("heat", str(jobenv / "bar.stl"), "where=40C", "material=ABS")
    shut = json.loads((jobenv / "heat.json").read_text())["warp_risk"]
    assert shut["enclosed"] is True and "X1" in shut["enclosed_from"], shut
    assert shut["lift_mm"] < open_["lift_mm"]
    stone("heat", str(jobenv / "bar.stl"), "where=40C", "material=ABS", "enclosed=no")
    assert json.loads((jobenv / "heat.json").read_text())["warp_risk"]["enclosed"] is False
