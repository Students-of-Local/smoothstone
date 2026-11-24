"""Print-failure physics (failsim.py), each model held to a hand calculation."""

import json
import math
from dataclasses import replace

import numpy as np
import pytest
import trimesh

from smoothstone import failsim as fs, printers
from smoothstone import strand as st


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


def test_the_flow_index_is_the_rigs_stress_over_its_rate():
    """8.8 g in ten minutes of PLA at 210 C under 2.16 kg, by hand: 19.5 kPa at the wall, 13 1/s there."""
    stress = 2.16 * 9.80665 / (math.pi / 8 * (9.5504e-3 ** 2 + 9.4742e-3 ** 2)) * 1.0475e-3 / 16e-3
    rate = 4 * (math.sqrt(77) / 600 / 1.24e6) / (math.pi * 1.0475e-3 ** 3)
    assert (stress, rate) == pytest.approx((19508, 13.1), rel=0.005)
    assert fs.flow_index("PLA") == pytest.approx((210, rate, stress / rate))


@pytest.mark.parametrize("mat", fs.MATERIALS)
def test_each_melt_passes_its_filaments_flow_index(mat):
    t, rate, eta = fs.flow_index(mat)
    assert float(fs.viscosity(t, rate, mat)) == pytest.approx(eta, rel=1e-6)
    kg = fs.fact("mfi_test")[mat][1]
    assert f"at {t:g} C, {kg:g} kg;" in fs._props(mat)[0]["mfi"]["note"]  # the weight the grams were measured under
    assert fs.note("mfi_rig") in fs.material(mat).stand_ins


def test_two_melts_agree_with_what_others_measured_on_them():
    """What sets a curve is the flow index. ABS's own curve, another filament on another rig, comes within twice of it;
    PETG's thickness at rest lies in the range a fit to stretch tests gave; PLA's injection grade does not (7 times too thin)."""
    def published(mat, t, rate):
        p = fs.fact(mat + ".cross_wlf")
        eta0 = p["D1_Pa_s"] * math.exp(-p["A1"] * (t + 273.15 - p["T_star_K"]) / (p["A2_K"] + t + 273.15 - p["T_star_K"]))
        return eta0 / (1 + (eta0 * rate / p["tau_star_Pa"]) ** (1 - p["n"]))
    ratio = {m: fs.flow_index(m)[2] / published(m.lower(), *fs.flow_index(m)[:2]) for m in ("PLA", "ABS")}
    assert 0.5 < ratio["ABS"] < 2 and 6 < ratio["PLA"] < 8
    q = fs.fact("petg.melt")
    assert q["eta0_Pa_s"] < float(fs.viscosity(q["at_C"], 0, "PETG")) < 3 * q["eta0_Pa_s"]
    assert float(fs.viscosity(240, 0, "PETG")) == pytest.approx(1730, rel=0.01)  # what its note says
    for m, own in (("PLA", "pla.cross_wlf"), ("PETG", "petg.melt"), ("ABS", "abs.cross_wlf")):  # whose curve it is, once each
        assert [n for n in fs.material(m).stand_ins if "changes with heat" in n or "moves with heat" in n] == [fs.note(own)]
    assert 43900 / float(fs.viscosity(240, 0, "ABS")) == pytest.approx(51, rel=0.01)  # and ABS's
    for m, a1, t_star, tau, n in (("PLA", 16.71, 373.15, 1.29e5, 0.3846), ("ABS", 28.3, 365, 41070, 0.341)):  # its shape is its own
        bend = [a1 * (t + 273.15 - t_star) / (51.6 + t + 273.15 - t_star) for t in (200, 240)]
        rest = [float(fs.viscosity(t, 0, m)) for t in (200, 240)]
        assert rest[0] / rest[1] == pytest.approx(math.exp(bend[1] - bend[0]), rel=1e-9)
        assert rest[1] / float(fs.viscosity(240, 1500, m)) == pytest.approx(1 + (rest[1] * 1500 / tau) ** (1 - n), rel=1e-9)
    shift = 17.44 * (240 - 66) / (51.6 + 240 - 66) - 17.44 * (200 - 66) / (51.6 + 200 - 66)
    assert float(fs.viscosity(200, 0, "PETG") / fs.viscosity(240, 0, "PETG")) == pytest.approx(10 ** shift)
    assert fs.material("PETG").k == 0.21


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
def test_pla_holds_on_the_beds_people_print_it_on_and_less_on_hotter_ones(bed):
    n = _box((60, 60, 4), 0.5, bed=bed)[0]
    assert n.kind == "none" and n.numbers["margin"] > 2  # 60 and 70 C let go when the cap fell with stiffness
    assert fs.bond_stress("PLA", bed=40) == fs.bond_stress("PLA", bed=bed) > fs.bond_stress("PLA", bed=90) > fs.bond_stress("PLA", bed=100)
    assert fs.bond_stress("PETG", bed=70) == fs.bond_stress("PETG", bed=96) >= fs.bond_stress("PETG", bed=110)


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


def test_the_hotend_holds_what_surface_tension_carries():
    assert fs.tension(240, "PETG") == pytest.approx(29.7e-3) and fs.tension(20, "ABS") == pytest.approx(42e-3)
    assert fs.wetting(200, "PLA") == 46 and fs.wetting(240, "ABS") == 95
    pla, abs_ = fs.nozzle_hold("PLA", 220), fs.nozzle_hold("ABS", 240)
    assert pla["wets"] and pla["hold_n"] == pytest.approx(2 * math.pi * 0.5e-3 * fs.tension(220))  # hangs from the flat's edge
    assert not abs_["wets"] and abs_["hold_n"] == pytest.approx(2 * math.pi * 0.2e-3 * fs.tension(240, "ABS"))  # from the bore
    assert pla["blob_mm3"] * 1e-9 * 1240 * 9.80665 == pytest.approx(pla["hold_n"])  # its own weight is all it carries
    assert not fs.nozzle_hold("ABS")["wets"] and "past 240 C" in fs.note("abs.contact_angle")  # 260 C, hotter than measured
    assert all("brass" in fs.note(f"{m}.contact_angle") for m in ("pla", "petg", "abs"))
    assert 5 < pla["blob_mm3"] < 12 and abs_["blob_mm3"] < pla["blob_mm3"] / 2


def test_nozzle_drag_is_small():
    drag = fs.nozzle_drag("PLA", 200, 0.2)
    eta = fs.viscosity(220, 1000.0)
    assert drag == pytest.approx(eta * 1000.0 * 1e-6 * math.pi * 0.25, rel=1e-9)
    assert 0.01 < drag < 0.3


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


@pytest.mark.parametrize("mat", fs.MATERIALS)
def test_the_melt_thickens_without_end_as_it_cools(mat):
    t = np.arange(20.0, 200.0, 0.01)
    for rate in (0.0, 1.0, 180.0):
        eta = fs.viscosity(t, rate, fs.material(mat))
        assert (eta[1:] <= eta[:-1] * (1 + 1e-12)).all() and eta[0] > 1e12  # no hole where the numbers overflow next to the pole


def test_the_nozzle_drags_by_each_plastics_own_melt():
    """300 mm/s over a 0.2 mm layer is 1500 1/s: each melt's stress there on the 1 mm tip."""
    drag = {m: fs.nozzle_drag(m, 300, 0.2) for m in fs.MATERIALS}
    for m, got in drag.items():
        assert got == pytest.approx(1500 * float(fs.viscosity(fs.material(m).nozzle, 1500, m)) * math.pi * 0.5e-3 ** 2)
    assert 0.03 < drag["ABS"] < drag["PETG"] < drag["PLA"] < 0.4


def test_half_the_fan_is_half_the_wind():
    one = lambda fan: fs.cooling("PLA", fan=fan)["soft_s"]
    assert one(0.0) > one(0.5) > one(1.0) == one(True)
    top = lambda fan: fs.column_temps("PLA", [400.0] * 20, [80.0] * 20, [1.0] * 20, bed=60, fan=fan)[-1]
    assert top(0) > top(0.25) > top(1) and top(0.005) == top(0)  # never below still air's


@pytest.mark.parametrize("mat", fs.MATERIALS)
def test_every_plastic_is_a_melt_then_a_solid_the_model_can_run(mat):
    m = fs.material(mat)
    t = np.linspace(m.set + 20, m.nozzle, 60)
    for rate in (0, 100):
        eta = fs.viscosity(t, rate, mat)
        assert np.isfinite(eta).all() and (eta > 0).all() and (np.diff(eta) < 0).all()
    assert m.tg <= m.set < m.nozzle and 1000 < m.cp < 3000 and 0.1 < m.k < 0.3
    assert len(m.stand_ins) == len(set(m.stand_ins)) and fs.note("mfi_rig") in m.stand_ins
    assert 0 < fs.cooling(mat)["soft_s"] < 5 and np.isfinite(fs.droop([1.0, 5.0], mat)).all() and 0 < fs.layer_stress(mat, 25) < 30
    assert 0 < fs.nozzle_hold(mat)["blob_mm3"] < 10 and 0 < fs.nozzle_drag(mat) < 1
    got = _box((20, 20, 8), 0.5, material=mat)[0].numbers
    assert ("margin" in got) is (m.peel is not None)
    if m.peel is not None:
        assert np.isfinite(got["margin"]) and got["margin"] > 0 and 0 < fs.bond_stress(mat) < 100


def test_what_a_plastic_borrows_is_the_one_it_is_like_and_its_own_is_its_own():
    asa, abs_, cf, pla = (fs.material(m) for m in ("ASA", "ABS", "PLA-CF", "PLA"))
    assert asa.peel == abs_.peel and cf.peel == pla.peel and (cf.cp, cf.k) == (pla.cp, pla.k)
    assert asa.k == 0.1642 and asa.tg == 98 and asa.set == asa.tg and cf.e == 3280.7
    assert fs.note("like") in asa.stand_ins and fs.note("abs.cross_wlf") in asa.stand_ins and fs.note("like") not in pla.stand_ins
    ratio = fs.viscosity(220, 0, "ASA") / fs.viscosity(220, 0, "ABS"), fs.viscosity(250, 0, "ASA") / fs.viscosity(250, 0, "ABS")
    assert ratio[0] == pytest.approx(ratio[1]) and ratio[0] > 2  # ABS's curve, at ASA's own thickness
    assert fs.tension(240, "ASA") == fs.tension(240, "ABS") and fs.wetting(240, "PLA-CF") == fs.wetting(240, "PLA")


def test_nylon_and_tpu_set_where_they_turn_solid_not_at_the_glass_transition():
    pa, tpu = fs.material("PA"), fs.material("TPU")
    assert (pa.tg, pa.set, tpu.tg, tpu.set) == (66, 148, -25, 101.6)
    glass = replace(pa, set=pa.tg)
    assert fs.cooling(pa)["soft_s"] < 0.5 * fs.cooling(glass)["soft_s"]
    for m, joules in (("PA", 72500), ("TPU", 144000)):
        n = fs.material(m)
        assert fs.viscosity(200, 0, m) / fs.viscosity(240, 0, m) == pytest.approx(math.exp(joules / 8.314 * (1 / 473.15 - 1 / 513.15)))
        assert fs.viscosity(n.set - 1, 0, m) == math.inf > fs.viscosity(n.set, 0, m)
        assert math.isfinite(st.set_time(n)) and (m == "TPU" or st.set_time(n) < 0.7 * st.set_time(glass))
        assert fs.layer_stress(n, n.set) == 0 < fs.layer_stress(n, n.set - 5)
    assert tpu.e * tpu.ratio(101.6) == pytest.approx(10 * 0.75 / (2 * math.sqrt(1 / math.pi)) / 1, rel=0.01)  # Vicat's 10 N on 1 mm2, 1 mm deep
    over = dict(ground=lambda x, y: 0 * x, plastic=lambda x, y: np.ones(np.shape(x), bool), fan=False)
    warm = [st.Strand([[x, 0, 0.22] for x in range(6)], 0.4, pa, temp=t, air=25, **over) for t in (240, 290)]
    for s in warm:
        s.step()
    assert [bool(s.fixed.any()) for s in warm] == [False, True]  # it meets the plastic at 132, over its glass transition and under where it sets, and at 157
    t = (148 + pa.nozzle) / 2 + 273.15
    assert pa.cp == pytest.approx((0.1526 * t + 223.95) / 113.16 * 1000)


def test_a_plastic_nobody_has_peeled_gets_no_verdict_on_its_corners():
    slab = trimesh.creation.box((150, 60, 10))
    slab.apply_translation((100, 100, 5))
    for m in ("PC", "PA", "TPU"):
        assert fs.bond_stress(m) is None and fs.note("no_peel") in fs.material(m).stand_ins and fs.note("no_angle") in fs.material(m).stand_ins
        got = fs.predict(fs.inputs_from_mesh(slab, cell=1.0, material=m, clean=0.05))
        assert [f.kind for f in got] == ["none"] and got[0].numbers["edge_stress_mpa"] > 0 and "bond_mpa" not in got[0].numbers
    assert fs.predict(fs.inputs_from_mesh(slab, cell=1.0, material="ABS", clean=0.05))[0].kind == "detach"


@pytest.mark.parametrize("text, plastic", [
    ("PLA", "PLA"), ("pla silk", "PLA"), ("PLA+", "PLA"), ("PolyTerra PLA", "PLA"), ("HTPLA", "PLA"), ("PETG HF", "PETG"), ("PCTG", "PETG"),
    ("ABS+", "ABS"), ("ASA", "ASA"), ("ASA+", "ASA"), ("PLA Silk Bronze", "PLA"), ("PLA Carbon Black", "PLA"),
    ("PLA-CF", "PLA-CF"), ("Carbon Fiber PLA", "PLA-CF"), ("PLA Carbonfiber", "PLA-CF"), ("PLA+CF", "PLA-CF"), ("PETG-CF10", "PETG-CF"), ("PETG-rCF08", "PETG-CF"),
    ("ASA-CF", None), ("PET", None), ("PLA/PHA", None), ("PC+ABS", None), ("Fiberglass PETG", None), ("PLA Bronzefill", None), ("Magnetic Iron PLA", None),
    ("PC Blend", None), ("nylon", "PA"), ("PA6", "PA"), ("PA 12", "PA"), ("CoPA", "PA"), ("TPU 95A", "TPU"), ("TPU95A", "TPU"),
    ("HIPS", None), ("PVA", None), ("PP", None), ("PA-CF", None), ("PET-CF", None), ("PC-ABS", None), ("ABS-GF", None), ("PLA-AERO", None),
    ("LW-PLA", None), ("wood", None), ("", None), (None, None)])
def test_a_plastic_by_the_name_people_give_it(text, plastic):
    assert fs.named(text) == plastic


@pytest.mark.parametrize("pid", printers.load())
@pytest.mark.parametrize("mat", fs.MATERIALS)
def test_a_plastic_at_the_heat_its_printers_profile_says(mat, pid):
    p = printers.get(pid)
    m, s, k2 = fs.material(mat, pid), printers.settings(p, mat), fs.material(mat)
    assert m.set < m.nozzle and replace(m, nozzle=k2.nozzle, bed=k2.bed, chamber=k2.chamber, cp=k2.cp, stand_ins=k2.stand_ins) == k2
    if pid == "creality_k2":
        assert m == k2
    elif s:
        assert (m.nozzle, m.bed) == (s["nozzle"], s["bed"]) and m.chamber == s.get("chamber", m.chamber)
        assert (fs.note("k2_air") in m.stand_ins) is ("chamber" not in s and p["enclosed"])


def test_a_printers_own_shells_weigh_its_layers():
    masks = [_rect((44, 44), 2, 42, 2, 42)] * 20
    three, two = (fs.printed_section(masks, 0.5, process=printers.process(printers.get(p)))["share"] for p in ("prusa_mini", "creality_k2"))
    assert (three > two).any() and np.allclose(two, fs.printed_section(masks, 0.5)["share"])
