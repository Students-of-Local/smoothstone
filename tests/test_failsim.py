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
    assert -fs.droop([reach + 1.0], fan=False)[0] > 10 * tips[1]


def test_bead_cooling_matches_the_hand_numbers():
    c = fs.cooling("PLA", 0.2, 0.42, fan=False)
    area, per = (0.42 - 0.2) * 0.2 + math.pi * 0.04 / 4, 2 * 0.22 + math.pi * 0.2
    tau = 1240 * 1400 * (area / per * 1e-3) / 10  # rho cp (A / P) / h
    assert c["tau_s"] == pytest.approx(tau, rel=1e-9)
    assert c["soft_s"] == pytest.approx(tau * math.log((220 - 35) / (61 - 35)), rel=1e-9)


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
    assert fs.bond_stress("PETG") == pytest.approx(2 * 102 * lam / 25, rel=1e-9)  # 21.5 MPa, under PETG's 23
    assert fs.bond_stress("PLA") == 31  # 48.6 MPa from the peel, capped at PLA's Z strength
    m = fs.material("PLA")
    ts = np.linspace(m.bed, m.tg, 4001)
    sig = m.cte * m.e * np.trapezoid(m.ratio(ts), ts)
    assert fs.layer_stress("PLA") == pytest.approx(sig, rel=1e-4)
    assert fs.edge_stress("PLA", 12) == pytest.approx(6 * sig, rel=1e-4)
    assert fs.layer_stress("PETG") == 0.0  # the K2's 70 C plate is above PETG's 66 C Tg


def test_clean_plate_keeps_the_flat_plate_and_a_dirty_one_lets_go():
    plate = [_rect((130, 210), 5, 125, 5, 205)] * 10  # 100 x 60 x 2 mm at 0.5 mm cells
    clean = fs.predict(fs.Inputs(plate, 0.5))
    assert [f.kind for f in clean] == ["none"]
    dirty = fs.predict(fs.Inputs(plate, 0.5, clean=fs.fact("contamination")))
    first = dirty[0]
    assert (first.kind, first.layer, first.taxonomy) == ("detach", 0, "bed_adhesion")
    # hand: sqrt(3) x 1.38 MPa = 2.39 MPa at the edge against 31 MPa x 0.049 = 1.52 MPa
    assert first.numbers["edge_stress_mpa"] == pytest.approx(math.sqrt(3) * fs.layer_stress("PLA"), abs=0.01)
    assert first.numbers["bond_mpa"] == pytest.approx(31 * 0.049, abs=0.01)


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
