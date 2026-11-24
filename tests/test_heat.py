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


def _small(monkeypatch):
    for k, v in (("VOXELS", 8_000), ("COARSE", 4_000), ("REFINE", 8_000)):
        monkeypatch.setattr(strength, k, v)


def test_stone_heat_resolves_a_load(jobenv, monkeypatch):
    _small(monkeypatch)
    trimesh.creation.box(extents=[60, 8, 8]).export(jobenv / "bar.stl")
    held = ["at=right", "dir=down", "fixed=left"]
    text, code, nxt = stone("heat", str(jobenv / "bar.stl"), "where=50C", "material=PETG", "load=5N", *held)
    assert "Load 5 N: deflection" in text and "-> " in text, text
    d = json.loads((jobenv / "heat.json").read_text())
    assert d["load"]["deflection_hot_mm"] == pytest.approx(d["load"]["deflection_room_mm"] / heat.retention("PETG", 50), rel=1e-2)
    assert not np.isnan(d["clamped_stress_mpa"])
    text, code, nxt = stone("heat", str(jobenv / "bar.stl"), "where=40C", "material=PC", "load=5N", "at=left", "fixed=left")
    assert "Load not checked: the load at left sits on the held place" in text, text
    assert "what holds the part still" in nxt and "fixed=<" in nxt and "load=5N" in nxt and "print it in" not in nxt, nxt
    for word, kept in (("load=heavy", "where=40C"), ("bed=hot", "where=40C"), ("where=lava", "material=PC")):
        text, code, nxt = stone("heat", str(jobenv / "bar.stl"), "where=40C", "material=PC", word)
        assert code == 1 and f"FIX: {word}" in text and kept in nxt and f"{word.split('=')[0]}=<" in nxt, (text, nxt)
        assert nxt.startswith("ask the person: "), nxt
    text, code, nxt = stone("heat", str(jobenv / "typo.stl"), "where=car")
    assert code == 1 and "no file at" in text and "where is the STL? Then: stone heat <the STL file> where=car" in nxt, (text, nxt)
    text, code, nxt = stone("heat", str(jobenv / "bar.stl"), "where=car", "temp=85C")
    assert code == 1 and "temp: not a strength word" in text and nxt == f"stone heat {jobenv / 'bar.stl'} where=car", (text, nxt)
    open_bar = trimesh.creation.box(extents=[60, 8, 8])
    trimesh.Trimesh(open_bar.vertices, open_bar.faces[2:]).export(jobenv / "open.stl")
    nxt = stone("heat", str(jobenv / "open.stl"), "where=40C", "material=PC", "load=5N", *held)[2]
    assert "a closed STL of it? Then: stone heat <the STL file> where=40C" in nxt and "load=5N" in nxt and "open.stl" not in nxt.partition("Then:")[2], nxt


def test_the_other_plastic_it_names_holds_the_load_there(jobenv, monkeypatch):
    """Strength and sag at the temperature both count, for this plastic and for the one offered in its place."""
    _small(monkeypatch)
    bar = trimesh.creation.box(extents=[60, 8, 8])
    case = strength.parse(["load=1N", "at=right", "dir=down", "fixed=left"])[0]
    st, res = strength.solve(bar, case, strength.material("PLA"), 8_000)
    one, mode = heat._moved(res, "PLA", "PLA", 50)
    r, k = heat.retention("PLA", 50), heat.strength_left("PLA", 50)
    assert k < r and mode != "sag"  # 50 C is most of the way from 23 to its glass temperature
    b = strength.material("PLA")
    solved = strength.solve(bar, case, heat.softened("PLA", 50), 8_000)[1]
    assert solved.deflection * r == pytest.approx(res.deflection, rel=1e-4)
    assert one == pytest.approx(solved.sf, abs=0.2) and mode == solved.mode  # scaling is what a new solve gives
    for load in (one / 2, one * 8):
        res = strength.solve(bar, strength.parse([f"load={load}N", *("at=right", "dir=down", "fixed=left")])[0], b, 8_000)[1]
        cure = heat._cure("PLA", 50, res)
        assert cure is None or heat._moved(res, "PLA", cure, 50)[0] >= strength.FINE
    assert heat._cure("PLA", 50, res) is None and heat._cure("PLA", 120) is None  # none holds that, none stands 120 C
    long = trimesh.creation.box(extents=[120, 10, 6])  # strong enough, but it bends past its limit
    long.export(jobenv / "long.stl")
    text, code, nxt = stone("heat", str(jobenv / "long.stl"), "where=40C", "material=ABS", "load=1N", "sag=2.5", "at=right",
                            "dir=down", "fixed=left")
    d = json.loads((jobenv / "heat.json").read_text())
    assert d["load"]["deflection_room_mm"] < 2.5 < d["load"]["deflection_hot_mm"] and d["verdict"] == "too hot" and "it will bend too far" in text, text
    assert nxt.startswith("ask the person: ") and "load leaves a safety factor" in nxt, nxt
    long.export(jobenv / "hot.stl")  # past its glass temperature no shape of PLA holds: never a stiffer part of the same
    held = ("at=right", "dir=down", "fixed=left")
    nxt = stone("heat", str(jobenv / "hot.stl"), "where=car", "material=PLA", "load=200N", *held)[2]
    assert "a cooler spot, or a part in PC strong enough for the load (not checked)?" in nxt and "stiffer" not in nxt, nxt
    text, code, nxt = stone("heat", str(jobenv / "hot.stl"), "where=23C", "material=PLA", "load=200N", *held)
    assert "even at room temperature" in nxt and "cooler" not in nxt and nxt.endswith("a stiffer part, or less load?"), (text, nxt)
    assert json.loads((jobenv / "heat.json").read_text())["verdict"] == "too weak"


def test_tpu_is_judged_by_its_vicat_and_its_load_is_not_waved_through(jobenv):
    trimesh.creation.box(extents=[40, 20, 10]).export(jobenv / "pad.stl")
    for where, want in (("150C", "too hot"), ("100C", "close"), ("40C", "fine")):
        text, code, nxt = stone("heat", str(jobenv / "pad.stl"), f"where={where}", "material=TPU")
        assert json.loads((jobenv / "heat.json").read_text())["verdict"] == want, text
    text, code, nxt = stone("heat", str(jobenv / "pad.stl"), "where=40C", "material=TPU", "load=5N", "at=right", "fixed=left")
    assert "Load not checked: no softening curve for TPU" in text and nxt.startswith("ask the person: "), (text, nxt)
    assert "MPa" not in next(ln for ln in text.splitlines() if ln.startswith("Expansion")), text  # no curve, no stress


def test_the_warp_fix_never_names_a_plastic(jobenv):
    """It knows neither the load nor the spot, so a plastic it named could be one that fails there."""
    strength_names = ("PLA", "PETG", "ABS", "ASA", "PC", "PA")
    trimesh.creation.box(extents=[200, 20, 5]).export(jobenv / "bar.stl")
    text, code, nxt = stone("heat", str(jobenv / "bar.stl"), "where=60C", "material=ABS")
    warp = next(ln for ln in text.splitlines() if ln.startswith("Warp risk"))
    assert "high" in warp and "enclosure" in warp and not any(m in warp.partition("Fix:")[2] for m in strength_names), warp
    assert nxt.startswith("ask the person: it is likely to warp") and "If so: " in nxt, nxt  # fine in the heat, still not waved on
    assert "an enclosure" not in heat.warp("PLA", trimesh.creation.box(extents=[350, 40, 5]), True, None)["fix"]
    text, code, nxt = stone("heat", str(jobenv / "bar.stl"), "where=120C", "material=ABS")  # nothing stands 120 C
    assert nxt.endswith("; a cooler spot?"), nxt
    two = trimesh.util.concatenate([trimesh.creation.box(extents=[20, 20, 5]).apply_translation([x, 0, 0]) for x in (-90, 90)])
    assert heat.warp("PLA", two, False, None)["level"] == "low"  # two small pieces, not one 200 mm one


def test_warp_bumps_for_a_cold_bed_a_thin_contact_and_nylon():
    small, thin = trimesh.creation.box(extents=[60, 60, 5]), trimesh.creation.box(extents=[100, 3, 5])
    assert heat.warp("PLA", small, True, 60)["level"] == "low" and heat.warp("PLA", small, True, 20)["level"] == "medium"
    assert heat.warp("PLA", small, True, 20)["fix"].startswith("bed at ")
    assert "thin first layer" in " ".join(heat.warp("PLA", thin, True, None)["why"])
    assert "nylon" in " ".join(heat.warp("PA", small, True, None)["why"])
    assert "needed" in " ".join(heat.warp("ABS", small, False, None)["why"])


def test_no_load_is_close_only_near_the_hdt_and_a_cold_part_shrinks(jobenv):
    trimesh.creation.box(extents=[40, 20, 10]).export(jobenv / "sign.stl")
    text, code, nxt = stone("heat", str(jobenv / "sign.stl"), "where=outdoor", "material=PLA")
    assert nxt == "none, the part takes the heat" and "Creep" not in text, text
    assert "within 5 C of the 55 C where PLA softens" in stone("heat", str(jobenv / "sign.stl"), "where=52C", "material=PLA")[2]
    text, code, nxt = stone("heat", str(jobenv / "sign.stl"), "where=-18C", "material=PLA")
    assert "it shrinks 0.1" in text and "it pulls with" in text, text
    assert "no file" not in text and stone("heat", "material=PLA")[2].startswith("ask the person: where does the part live?")


def test_the_job_keeps_its_load_and_its_plastic(jobenv, monkeypatch):
    from smoothstone import cli

    _small(monkeypatch)
    job = cli.Job(jobenv / "stone-job")
    job.create("a bar")
    job.build_dir.mkdir(parents=True, exist_ok=True)
    trimesh.creation.box(extents=[60, 8, 8]).export(job.build_dir / "part.stl")
    strength.report(job, ["load=5N", "at=right", "dir=down", "fixed=left", "material=PLA"], cli.Out(), "PETG")
    out = cli.Out()
    heat.report(job, ["where=40C"], out, "PETG")
    assert "(the load from the last stone strength)" in " ".join(out.lines) and "part.stl, PETG" in " ".join(out.lines), out.lines
    strength.report(job, ["load=5N", "at=right", "dir=down", "fixed=left", "material=PLA"], cli.Out(), "PETG")
    d = json.loads((job.build_dir / "strength.json").read_text())
    d["inputs"]["words"]["at"] = "left"  # on the held place now
    (job.build_dir / "strength.json").write_text(json.dumps(d))
    out = cli.Out()
    heat.report(job, ["where=40C"], out, "PETG")
    assert "where=40C load=5N dir=down at=<" in out.next and "fixed=<" in out.next, out.next  # the saved load is not lost
    trimesh.creation.box(extents=[30, 30, 30]).export(jobenv / "other.stl")
    out = cli.Out()
    heat.report(job, ["other.stl", "where=40C"], out, "PETG")
    assert "Load" not in " ".join(out.lines) and (jobenv / "heat.json").is_file(), out.lines  # another part: not that load
    out = cli.Out()
    heat.report(job, ["where=40C"], out, "PVB")
    assert out.code == 1 and "PVB" in out.next and "material=<" in out.next, out.next


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
