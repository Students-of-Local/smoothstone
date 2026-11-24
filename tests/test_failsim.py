"""Print-failure physics (failsim.py), each model held to a hand calculation."""

import json
import math

import numpy as np
import pytest
import trimesh

from smoothstone import failsim as fs


def _rect(shape, r0, r1, c0, c1):
    m = np.zeros(shape, bool)
    m[r0:r1, c0:c1] = True
    return m


def _length(x):
    return float(np.linalg.norm(np.diff(x, axis=0), axis=1).sum())


# model 1: falling strands

def test_dropped_strand_comes_to_rest_on_the_bed_and_keeps_its_length():
    flow, speed = 10.0, 200.0
    frames = fs.drop_strand(np.array([[0, 0, 10.0], [20, 0, 10.0]]), speed, flow, ground=0.0, steps=3000)
    r = math.sqrt(flow / speed / math.pi)  # the strand's own radius: it lies on the bed, not in it
    end = frames[-1]
    assert len(frames) < 3000, "never came to rest"
    assert len(end) == 41  # the whole 20 mm strand, 0.5 mm segments
    assert np.allclose(end[:, 2], r, atol=0.01)
    assert abs(_length(end) / 20.0 - 1) < 0.02


def test_dropped_strand_piles_on_the_printed_part():
    z = np.zeros((40, 60))
    z[:, 25:] = 5.0  # a 5 mm block from x = 7.5 mm on
    part = fs.Heightfield(z, 0.5, (-5.0, -10.0))
    frames = fs.drop_strand(np.array([[0, 0, 12.0], [20, 0, 12.0]]), 200, 10, ground=part, steps=3000)
    end, r = frames[-1], math.sqrt(10 / 200 / math.pi)
    assert len(frames) < 3000
    on = end[:, 0] > 8.0
    assert on.sum() > 20 and np.allclose(end[on, 2], 5.0 + r, atol=0.05)
    assert (end[:, 2] >= part(end[:, 0], end[:, 1]) + r - 1e-6).all()  # nothing inside the part


# model 2: droop and curl

def test_droop_is_zero_within_the_reach_and_grows_with_the_span():
    reach = fs.reach(0.2)
    assert reach == pytest.approx(0.2 * math.tan(math.radians(60)))
    assert not fs.droop(np.linspace(0, reach, 9)).any()
    tips = [-fs.droop([reach + s])[0] for s in (0.5, 1.0, 1.5, 2.0, 3.0)]
    assert all(b > a > 0 for a, b in zip(tips, tips[1:]))
    # a cantilever under its own weight: the tip goes as the free length to the fourth power
    assert tips[3] / tips[1] == pytest.approx(16.0, rel=1e-9)
    # still air keeps the bead soft longer than the fan does
    assert -fs.droop([reach + 1.0], fan=False)[0] > 3 * tips[1]


def test_air_and_a_hot_wire_match_lienhard():
    a = fs.air(26.85)  # 300 K, Table A.6
    assert [float(a[k]) for k in ("rho", "nu", "k", "pr")] == pytest.approx([1.177, 1.575e-5, 0.0264, 0.707])
    assert float(fs.air(101.85)["k"]) == pytest.approx((0.0300 + 0.0335) / 2)  # 375 K, halfway
    assert float(fs.nusselt(457.0, 0.712)) == pytest.approx(10.69, rel=0.002)  # example 7.8: a 0.1 mm wire in an air stream
    lo, hi = fs.nusselt(0.2 * 0.999 / 0.7, 0.7), fs.nusselt(0.2 * 1.001 / 0.7, 0.7)
    assert float(lo) == pytest.approx(float(hi), rel=0.2)  # the two fits meet near Re Pr = 0.2
    assert float(fs.nusselt(1e-3 / 0.7, 0.7)) == pytest.approx(1 / (0.8237 - math.log(1e-3 ** 0.5)))


def test_a_strand_in_still_air_loses_heat_by_rising_air_and_radiation():
    d, t, ta = 0.42e-3, 127.0, 25.0
    film = fs.air(76.0)
    ra = 9.80665 * (t - ta) / (76.0 + 273.15) * d ** 3 / (film["nu"] ** 2 / film["pr"])
    nu = 0.36 + 0.518 * ra ** 0.25 / (1 + (0.559 / film["pr"]) ** (9 / 16)) ** (4 / 9)
    rad = 0.92 * 5.670374e-8 * ((t + 273.15) ** 4 - (ta + 273.15) ** 4) / (t - ta)
    assert float(fs.h_strand(0.42, t, ta)) == pytest.approx(nu * film["k"] / d + rad, rel=1e-6)
    assert 50 < float(fs.h_strand(0.42, t, ta)) < 80  # a flat wall's 10 is for the part, not a strand
    assert fs.h_strand(0.42, t, ta, wind=5.0) > 3 * fs.h_strand(0.42, t, ta)


def test_bead_cooling_matches_the_hand_numbers():
    area, per = (0.42 - 0.2) * 0.2 + math.pi * 0.04 / 4, 2 * 0.22 + math.pi * 0.2
    for fan, wind in ((False, 0.0), (True, 5.0)):
        t, s = 220.0, 0.0  # step it down by hand, 1 ms at a time
        while t > 61:
            h = float(fs.h_strand(4 * area / per, t, 35.0, wind))
            t -= h * (t - 35) / (1240 * 1400 * area / per * 1e-3) * 1e-3
            s += 1e-3
        assert fs.cooling("PLA", 0.2, 0.42, fan)["soft_s"] == pytest.approx(s, rel=0.01)
    still, blown = fs.cooling("PLA", fan=False), fs.cooling("PLA", fan=True)
    assert blown["soft_s"] < still["soft_s"] / 3
    assert still["tau_s"] == pytest.approx(1240 * 1400 * area / per * 1e-3 / still["h"])


def test_each_plastic_melts_by_its_own_numbers():
    assert float(fs.viscosity(240, 0, "PETG")) == pytest.approx(600, rel=1e-9)
    shift = 17.44 * (240 - 66) / (51.6 + 240 - 66) - 17.44 * (200 - 66) / (51.6 + 200 - 66)
    assert float(fs.viscosity(200, 0, "PETG")) == pytest.approx(600 * 10 ** shift, rel=1e-9)
    abs0 = 2.54e12 * math.exp(-28.3 * (513.15 - 365) / (51.6 + 513.15 - 365))  # NIST Table 1 at 240 C
    assert float(fs.viscosity(240, 0, "ABS")) == pytest.approx(abs0, rel=1e-9) and 1500 < abs0 < 2500
    thin = abs0 / (1 + (abs0 * 500 / 41070) ** (1 - 0.341))
    assert float(fs.viscosity(240, 500, "ABS")) == pytest.approx(thin, rel=1e-9)
    assert fs.material("PETG").k == 0.21
    assert not any("viscosity" in s for s in fs.material("ABS").stand_ins)


def test_curl_lifts_the_ledge_by_the_bilayer_curvature():
    m = fs.material("PLA")
    e = fs.layer_stress(m, m.chamber) / m.e
    up = fs.curl([fs.reach(0.2) + 4.0], "PLA", 0.2, above=1)[0]
    assert up == pytest.approx(0.75 * e / 0.2 * 4.0 ** 2 / 2, rel=1e-9)  # kappa = 3 e / 4 t, dz = kappa x^2 / 2


# model 3: bridges

def test_bridge_sags_one_layer_at_the_usable_length():
    assert -fs.bridge_sag(10.0, [5.0], 0.2)[0] == pytest.approx(0.2, rel=1e-9)
    assert -fs.bridge_sag(20.0, [10.0], 0.2)[0] > 0.2


def test_hanging_strand_chain_matches_the_catenary_within_one_percent():
    span = 60.0
    a, arc = fs.catenary_a(0.2), fs.bridge_length(span, 0.2)
    closed = a * (math.cosh(span / (2 * a)) - 1)
    dip = math.sqrt((arc / 2) ** 2 - (span / 2) ** 2)  # start as a V of the same length
    path = np.array([[0, 0, 50.0], [span / 2, 0, 50.0 - dip], [span, 0, 50.0]])
    frames = fs.drop_strand(path, speed_mm_s=1e9, flow_mm3_s=1.0, ground=-1000.0, steps=20000, dt=2e-4, iters=20,
                            seg_mm=arc / 30 * (1 + 1e-9), pins=(0, -1), damping=0.02, rest_mm_s=0.05)
    end = frames[-1]
    assert len(frames) < 20000
    sag = 50.0 - end[15, 2]
    assert sag == pytest.approx(closed, rel=0.01)
    assert sag == pytest.approx(-fs.bridge_sag(span, [span / 2], 0.2)[0], rel=0.01)


# model 4: detachment and toppling

def test_bond_and_warp_stress_match_the_hand_numbers():
    lam = (3 / (0.5 * 0.5 ** 3)) ** 0.25  # Hetenyi, a 0.5 mm strip on a 0.5 mm first layer
    assert fs.bond_stress("PETG") == pytest.approx(2 * 102 * lam / 25, rel=1e-9)  # 21.5 MPa, under 23
    assert fs.bond_stress("ABS") == pytest.approx(2 * 60 * lam / 25, rel=1e-9)  # 12.6 MPa
    assert fs.bond_stress("PLA") == 31  # 48.6 MPa from the peel, capped at PLA's strength between layers
    # PLA peeled at 50 C, 11 C under its Tg: 58.85 N on the hold curve; 80 C is 19 past it: 48.5 N
    assert fs.bond_stress("PLA", bed=80) == pytest.approx(31 * 48.5 / 58.85, rel=1e-9)
    m = fs.material("PLA")
    ts = np.linspace(m.bed, m.tg, 4001)
    sig = m.cte * m.e * np.trapezoid(m.ratio(ts), ts)
    assert fs.layer_stress("PLA") == pytest.approx(sig, rel=1e-4)
    assert fs.layer_stress("PLA", 70) == 0.0  # above Tg: stress-free
    assert fs.layer_stress("PETG") == 0.0  # the K2's 70 C plate is above PETG's 66 C Tg
    assert np.allclose(fs.layer_stress("PLA", np.array([50.0, 70.0])), [sig, 0.0])
    # one stress through the stack: sigma x min(sqrt(3 n), 3), Hetenyi for thin stacks, the edge zone after
    for n, k in ((1, math.sqrt(3)), (2, math.sqrt(6)), (12, 3.0)):
        got = fs.edge_stress("PLA", [m.bed] * n)
        assert got["edge"] == pytest.approx(k * fs.layer_stress("PLA"), rel=1e-9), n
        assert got["moment"] == pytest.approx(fs.layer_stress("PLA") * (n * 0.2) ** 2 / 2, rel=1e-9)
    # a 40 mm stack on a 10 mm wide footprint: only the 50 layers within 10 mm of the plate load it
    tall = fs.edge_stress("PLA", [35.0] * 200, band=10.0)
    assert tall["moment"] == pytest.approx(fs.layer_stress("PLA", 35) * 10 ** 2 / 2, rel=1e-9)
    assert tall["edge"] == pytest.approx(3 * fs.layer_stress("PLA", 35), rel=1e-9)


def test_column_temperatures_match_the_fin_formula():
    # a 20 x 20 mm solid PLA column, 20 mm tall, fan on: a fin with a convective tip
    n, a, p, k, h, tb, ta = 100, 400.0, 80.0, 0.13, 100.0, 50.0, 35.0
    got = fs.column_temps("PLA", [a] * n, [p] * n, [1.0] * n, 0.2, tb, ta, True)
    mm = math.sqrt(h * p * 1e-3 / (k * a * 1e-6))  # 1/m
    big, x = n * 0.2e-3, (np.arange(n) + 0.5) * 0.2e-3
    r = h / (mm * k)
    fin = ta + (tb - ta) * (np.cosh(mm * (big - x)) + r * np.sinh(mm * (big - x))) / (np.cosh(mm * big) + r * np.sinh(mm * big))
    assert np.abs(got - fin).max() < 0.02 * (tb - ta)
    one = fs.column_temps("PLA", [a], [p], [1.0], 0.2, tb, ta, True)[0]
    g, loss = k * a / 0.2 * 1e-3, h * (p * 0.2 + a) * 1e-6  # one layer: half a layer down to the plate
    assert one == pytest.approx((2 * g * tb + loss * ta) / (2 * g + loss), rel=1e-12)
    sec = fs.printed_section([_rect((44, 44), 2, 42, 2, 42)] * 20, 0.5)  # 20 x 20 mm, 4 mm tall
    assert sec["area"][0] == pytest.approx(400) and sec["perimeter"][0] == pytest.approx(80)
    assert sec["share"][0] == sec["share"][-1] == 1.0  # bottom and top shells
    wall = 1 - (20 - 2 * 1.0) ** 2 / 400  # two loops, 0.87 mm, land on 2 cells of 0.5 mm
    assert sec["share"][8] == pytest.approx(wall + 0.15 * (1 - wall), rel=1e-9)


def _box(ext, cell, **kw):
    b = trimesh.creation.box(extents=ext)
    b.apply_translation([0, 0, ext[2] / 2])
    return fs.predict(fs.inputs_from_mesh(b, cell=cell, **kw))


# PLA on the K2 with a clean textured PEI plate at the profile's settings: these print fine in practice
@pytest.mark.parametrize("ext, cell, kw", [
    ((20, 20, 20), 0.25, {}),
    ((20, 20, 40), 0.25, {"infill": 100}),
    ((20, 20, 40), 0.25, {}),
    ((100, 60, 2), 0.5, {}),
    ((150, 20, 10), 0.5, {}),
    ((10, 10, 60), 0.25, {}),
], ids=["cube20", "block40_solid", "block40_15pct", "plate100x60x2", "bar150x20x10", "tower10x10x60"])
def test_pla_parts_that_print_fine_predict_none(ext, cell, kw):
    got = _box(ext, cell, **kw)
    assert [f.kind for f in got] == ["none"], got[0].numbers
    n = got[0].numbers
    assert n["edge_stress_mpa"] < n["bond_mpa"] and n["margin"] > 1.5
    assert n["tip_drive_nmm"] < n["tip_hold_nmm"]
    if ext == (10, 10, 60):  # no brim: the moment balance says it stands, 4.8 N mm against 200 N mm
        assert n["tip_drive_nmm"] == pytest.approx(n["push_n"] * 60, abs=0.01)
        assert n["tip_hold_nmm"] == pytest.approx(0.40 * 10 * 10 ** 2 / 2, abs=0.5)


@pytest.mark.parametrize("h", [0.2, 0.4, 0.6, 0.8])
def test_a_part_thinner_than_the_shells_predicts(h):
    assert [f.kind for f in _box((30, 20, h), 0.5)] == ["none"]  # a 1 to 4 layer tag or first-layer square


def test_clean_plate_keeps_the_flat_plate_and_a_dirty_one_lets_go():
    plate = [_rect((130, 210), 5, 125, 5, 205)] * 10  # 100 x 60 x 2 mm at 0.5 mm cells
    clean = fs.predict(fs.Inputs(plate, 0.5))
    assert [f.kind for f in clean] == ["none"]
    dirty = fs.predict(fs.Inputs(plate, 0.5, clean=fs.fact("contamination")))
    first = dirty[0]
    assert (first.kind, first.layer, first.taxonomy) == ("detach", 0, "bed_adhesion")
    # hand: one layer at T0 (just under the 50 C plate): sigma(T0) x sqrt(3 r_plate / r_T0) against 31 x 0.049
    m, t0 = fs.material("PLA"), first.numbers["bottom_c"]
    hand = fs.layer_stress("PLA", t0) * math.sqrt(3 * m.ratio(50) / m.ratio(t0))
    assert first.numbers["edge_stress_mpa"] == pytest.approx(hand, abs=0.02)
    assert first.numbers["bond_mpa"] == pytest.approx(31 * 0.049, abs=0.01)


def test_abs_slab_on_an_open_printer_lifts_and_pla_does_not():
    abs_ = _box((150, 150, 10), 0.5, material="ABS", enclosed=False)[0]
    assert (abs_.kind, abs_.taxonomy) == ("detach", "warping")
    assert abs_.numbers["air_c"] == 25 and abs_.numbers["edge_stress_mpa"] > abs_.numbers["bond_mpa"]
    assert abs_.layer < 50
    pla = _box((150, 150, 10), 0.5, enclosed=False)
    assert [f.kind for f in pla] == ["none"], pla[0].numbers


@pytest.mark.parametrize("bed", [50, 55, 60, 65, 70])
def test_pla_holds_on_the_beds_people_print_it_on_and_best_near_its_tg(bed):
    n = _box((60, 60, 4), 0.5, bed=bed)[0]
    assert n.kind == "none" and n.numbers["margin"] > 2  # 60 and 70 C let go when the cap fell with stiffness
    assert fs.bond_stress("PLA", bed=60) >= fs.bond_stress("PLA", bed=bed) > fs.bond_stress("PLA", bed=90) > fs.bond_stress("PLA", bed=100)


def test_an_open_printers_ledge_droops_and_curls_in_the_same_room_air():
    inp = fs.Inputs([np.ones((2, 2), bool)], 0.5, material="ABS", enclosed=False)
    assert inp.air == 25 and fs.Inputs([], 0.5, material="ABS").air == fs.material("ABS").chamber
    d, room = [3.0], fs.curl([3.0], "ABS", above=5, air_c=25)
    assert room[0] > fs.curl(d, "ABS", above=5)[0] > 0
    assert fs.ledge(d, "ABS", above=5, air_c=25) == pytest.approx(fs.droop(d, "ABS", air_c=25) + room)


def test_toppling_layer_of_a_block_matches_the_hand_moment_balance():
    side, cell, t, push = 5.0, 0.25, 0.2, 1.0
    block = [_rect((24, 24), 2, 22, 2, 22)] * 200  # 5 x 5 mm, 40 mm tall
    got = fs.predict(fs.Inputs(block, cell, t, drag=push))[0]
    # tips over its far edge at the first layer n where push x n t > pull-off x W L^2 / 2 + weight x L / 2
    hold = 0.40 * side * side ** 2 / 2
    w = 1.24e-6 * 9.80665 * side * side * t  # N per layer
    n = next(k for k in range(1, 201) if push * k * t > hold + w * k * side / 2)
    assert n == 126
    assert (got.kind, got.layer, got.taxonomy) == ("topple", n - 1, "toppled")
    assert got.numbers["adhesion_nmm"] == pytest.approx(hold, abs=0.01)
    assert got.numbers["drive_nmm"] == pytest.approx(push * n * t, abs=0.01)


def test_rigid_tip_ends_on_its_side_and_slide_moves_the_distance():
    frames = fs.rigid_tip((5.0, 0.0), (1.0, 0.0), (2.5, 2.5, 10.0))
    assert np.allclose(frames[0], np.eye(4))
    top = frames[-1] @ np.array([5.0, 0.0, 20.0, 1.0])  # the top of the far edge lands on the bed
    assert np.allclose(top[:3], [25.0, 0.0, 0.0], atol=1e-9)
    slide = fs.rigid_slide((0.0, 1.0), 12.0)
    assert np.allclose(slide[-1][:3, 3], [0, 12.0, 0])
    assert fs.blob_volume(8.0, 10.0) == pytest.approx(0.5 * 80.0)


def test_nozzle_drag_is_small():
    drag = fs.nozzle_drag("PLA", 200, 0.2)
    eta = fs.viscosity(220, 1000.0)
    assert drag == pytest.approx(eta * 1000.0 * 1e-6 * math.pi * 0.25, rel=1e-9)
    assert 0.01 < drag < 0.2


# predict

def test_predict_says_supports_for_a_t_without_supports_and_none_for_a_cube():
    stem = _rect((40, 180), 8, 32, 78, 102)  # 6 x 6 mm at 0.25 mm cells
    bar = _rect((40, 180), 8, 32, 10, 170)  # 40 x 6 mm
    tee = [stem] * 100 + [bar] * 10
    out = fs.predict(fs.Inputs(tee, 0.25))
    assert out[0].kind == "supports" and out[0].layer == 100
    assert out[0].numbers["droop_mm"] >= 0.2
    assert [f.kind for f in fs.predict(fs.Inputs(tee, 0.25, supports=True))] == ["none"]
    cube = trimesh.creation.box((20, 20, 20))
    cube.apply_translation((10, 10, 10))
    got = fs.predict(cube, cell=0.5)
    assert [f.kind for f in got] == ["none"]
    assert got[0].numbers["layers"] == 100
    assert got[0].numbers["edge_stress_mpa"] < got[0].numbers["bond_mpa"]


def test_predict_finds_a_long_bridge_and_reads_toolpath_segments():
    post = _rect((40, 120), 10, 30, 5, 15) | _rect((40, 120), 10, 30, 105, 115)
    deck = _rect((40, 120), 10, 30, 5, 115)  # 22.5 mm between the posts at 0.25 mm cells
    got = fs.predict(fs.Inputs([post] * 20 + [deck] * 3, 0.25))
    assert got[0].kind == "bridge" and got[0].numbers["span_mm"] > 20
    sq = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], float)
    inp = fs.inputs_from_segments(sq, np.roll(sq, -1, 0), [0.4] * 4, [0] * 4, [0.2], [12.0], cell=0.1)
    assert inp.masks[0].sum() * 0.01 == pytest.approx(40 * 0.4, rel=0.25)


def test_every_failsim_fact_has_a_source():
    doc = json.loads((fs.REFS / "failsim.json").read_text())
    for e in doc["entries"]:
        assert e["id"].startswith("failsim.")
        assert {"value", "source", "cite", "checked"} <= e.keys(), e["id"]
        assert e.get("assumption") or e.get("url") or e["cite"].startswith("stone"), e["id"]
        text = json.dumps(e, ensure_ascii=False)
        assert chr(0x2014) not in text and chr(0x2013) not in text, e["id"]  # no em or en dashes


def test_an_open_printer_cools_a_bead_in_room_air():
    warm, room = fs.cooling("ABS", fan=False), fs.cooling("ABS", fan=False, air_c=fs.fact("room_air"))
    assert room["soft_s"] < warm["soft_s"]
    a, b = np.zeros((60, 60), bool), np.zeros((60, 60), bool)
    a[10:50, 10:40] = b[10:50, 10:56] = True  # 3.2 mm past the layer below
    m = [a] * 5 + [b]
    soft = [next(f for f in fs.predict(fs.Inputs(m, 0.2, material="ABS", fan=False, enclosed=e)) if "soft_s" in f.numbers).numbers for e in (True, False)]
    assert soft[1]["soft_s"] == pytest.approx(round(room["soft_s"], 2)) and soft[1]["soft_s"] < soft[0]["soft_s"]


def test_the_nozzle_drags_by_each_plastics_own_melt():
    """300 mm/s over a 0.2 mm layer is 1500 1/s: ABS's Cross-WLF stress there on the 1 mm tip, by hand."""
    eta0 = 2.54e12 * math.exp(-28.3 * (260 + 273.15 - 365) / (51.6 + 260 + 273.15 - 365))
    tau = 1500 * eta0 / (1 + (eta0 * 1500 / 41070) ** (1 - 0.341))
    drag = {m: fs.nozzle_drag(m, 300, 0.2) for m in fs.MATERIALS}
    assert drag["ABS"] == pytest.approx(tau * math.pi * 0.5e-3 ** 2, rel=1e-3)
    assert drag["PLA"] < drag["ABS"] < drag["PETG"] < 0.2
