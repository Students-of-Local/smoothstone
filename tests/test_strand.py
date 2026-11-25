"""One strand of melt (strand.py), each behavior held to its textbook formula."""

import copy
import math

import numpy as np
import pytest

from smoothstone import failsim as fs
from smoothstone import strand as st

G = 9.80665
PLA = fs.material("PLA")


def rod(length, d=0.4, n=41, **kw):
    """A straight strand along x from 0, 30 mm up."""
    x = np.linspace(0, length, n)
    return st.Strand(np.c_[x, 0 * x, 0 * x + 30.0], d, kw.pop("mat", PLA), fan=False, **kw)


def quiet(s, monkeypatch):
    """No air: the closed forms have none."""
    monkeypatch.setattr(st, "drag_coefficient", lambda re: np.zeros_like(re))


def test_drag_curve_is_wieselsbergers():
    assert float(st.drag_coefficient(1)) == pytest.approx(10.5)
    assert float(st.drag_coefficient(20)) == pytest.approx(2.02)
    assert float(st.drag_coefficient(0.1)) == pytest.approx(8 * math.pi / (0.1 * (2.002 - math.log(0.1))))
    both = st.drag_coefficient(np.array([0.499, 0.501]))
    assert both[0] == pytest.approx(both[1], rel=0.1)


def test_a_flat_strand_falls_at_its_terminal_speed():
    s = rod(20, temp=25, air=25)
    s.fixed[:] = False
    for _ in range(600):
        s.step()
    v = -float(s.v[:, 2].mean())
    a = fs.air(25.0)
    cd = float(st.drag_coefficient(v * 0.4e-3 / a["nu"]))
    assert 0.5 * a["rho"] * cd * 0.4e-3 * v * v == pytest.approx(1240 * math.pi * 0.2e-3 ** 2 * G, rel=0.02)
    assert 1.0 < v < 4.0


def test_a_set_rod_sags_like_an_elastic_cantilever(monkeypatch):
    L, d = 30e-3, 0.4e-3
    s = rod(30, temp=25, air=25, held=(0, 1))
    quiet(s, monkeypatch)
    for _ in range(3000):
        s.step()
        s.v *= 0.9  # only the rest state matters
    q, i = 1240 * math.pi / 4 * d * d * G, math.pi * d ** 4 / 64
    free = L - L / 40
    assert 30 - s.points()[-1, 2] == pytest.approx(q * free ** 4 / (8 * PLA.e * 1e6 * i) * 1e3, rel=0.06)


def test_a_hot_strand_bends_at_the_viscous_rate(monkeypatch):
    L, d = 4e-3, 0.4e-3
    s = rod(4, temp=140, air=140, held=(0, 1))
    quiet(s, monkeypatch)
    for _ in range(4):
        s.step()
    z0 = s.points()[-1, 2]
    s.step()
    q, i = 1240 * math.pi / 4 * d * d * G, math.pi * d ** 4 / 64
    free = L - L / 40
    eta = float(fs.viscosity(140))
    assert (z0 - s.points()[-1, 2]) * 240 * 1e-3 == pytest.approx(q * free ** 4 / (8 * 3 * eta * i), rel=0.1)


def test_a_hanging_hot_thread_stretches_at_troutons_rate(monkeypatch):
    z = np.linspace(30, 10, 41)
    s = st.Strand(np.c_[0 * z, 0 * z, z], 0.4, PLA, temp=170, air=170, fan=False, held=(0,))
    quiet(s, monkeypatch)
    for _ in range(5):
        s.step()
    z0 = s.points()[-1, 2]
    s.step()
    want = 1240 * G * 0.02 ** 2 / (2 * 3 * float(fs.viscosity(170)))
    assert (z0 - s.points()[-1, 2]) * 240 * 1e-3 == pytest.approx(want, rel=0.05)


def test_friction_is_mu_w_l():
    s = st.Strand(np.c_[np.linspace(0, 100, 101), np.zeros(101), np.full(101, 0.2)], 0.4, PLA, temp=25, air=25, fan=False,
                  ground=lambda x, y: np.zeros(np.shape(x)), nozzle=True, flow=0.0)
    head = np.array([100.0, 0, 0.2])
    for _ in range(240):
        head = head + [50 / 240, 0, 0]
        s.step(head=head)
    w = 1240 * math.pi / 4 * 0.4e-3 ** 2 * G * 0.1
    assert s.force == pytest.approx(0.5 * w, rel=0.1)


def test_a_dropped_strand_lies_still_and_keeps_its_plastic():
    s = rod(20, ground=lambda x, y: np.zeros(np.shape(x)), temp=220)
    vol = s.vol.sum()
    for _ in range(960):
        s.step()
    p = s.points()
    assert np.abs(s.v).max() < 2e-3
    assert p[:, 2] == pytest.approx(np.r_[s.diameters()[0], s._nodes(s.diameters())[1:-1], s.diameters()[-1]] / 2, abs=0.01)
    assert s.vol.sum() == pytest.approx(vol, rel=1e-9)


def test_it_cools_as_a_strand_in_still_air(monkeypatch):
    s = rod(20, temp=220, held=range(41))
    for _ in range(240):
        s.step()
    t = 220.0
    for _ in range(1000):
        t -= 4 * float(fs.h_strand(0.4, t, 35.0)) * (t - 35) / (1240 * 1400 * 0.4e-3) * 1e-3
    assert float(s.t[20]) == pytest.approx(t, rel=0.02)


def laid(weld, speed=200.0, flow=10.0, mm=120.0):
    """A strand from a nozzle moving along x, 5 mm over a bed; its far end welded there or free."""
    s = st.Strand([[0, 0, 0.24], [0, 0, 5.0]], st.exit_diameter(), PLA, flow=flow, ground=lambda x, y: np.zeros(np.shape(x)), nozzle=True,
                  fan=False, held=(0,) if weld else ())
    for k in range(int(mm / speed * 240)):
        s.step(head=(speed * (k + 1) / 240, 0, 5.0))
    return s


def test_held_it_is_drawn_thin_and_free_it_is_dragged():
    held, free = laid(True, mm=360), laid(False, mm=360)
    assert held.points()[0] == pytest.approx([0, 0, 0.24], abs=1e-3)
    assert np.median(held.diameters()) == pytest.approx(math.sqrt(4 * 10 / 200 / math.pi), rel=0.01)
    assert held.lengths()[1].sum() * 1e3 == pytest.approx(360, rel=0.01)  # it spans the whole path
    assert free.points()[0, 0] > 40  # dragged along the bed
    assert np.median(free.diameters()) > 1.3 * np.median(held.diameters())
    assert held.force > 3 * free.force


def test_plastic_is_conserved_out_of_the_nozzle():
    s = laid(False)
    first = math.pi / 4 * st.exit_diameter() ** 2 * 4.76
    assert s.vol.sum() * 1e9 == pytest.approx(first + 10.0 * (int(120 / 200 * 240) / 240), rel=1e-6)


def test_it_welds_to_hot_enough_plastic_and_not_to_the_bed():
    kw = dict(ground=lambda x, y: np.zeros(np.shape(x)))
    on = rod(10, plastic=lambda x, y: np.ones(np.shape(x), bool), **kw)
    bed = rod(10, plastic=lambda x, y: np.zeros(np.shape(x), bool), **kw)
    cold = rod(10, plastic=lambda x, y: np.ones(np.shape(x), bool), temp=40, **kw)
    for s in (on, bed, cold):
        for _ in range(120):
            s.step()
    assert on.fixed.any() and not bed.fixed.any() and not cold.fixed.any()
    assert on.points()[on.fixed, 2] == pytest.approx(0.2, abs=0.02)  # where it lies, not where it was about to land
    step = lambda x, y: np.where(x < 10.2, 5.0, 0.0)  # noqa: E731  # plastic, 5 mm high up to its edge
    off = st.Strand([[9.5, 0, 5.3], [10, 0, 5.3], [10.1, 0, 5.3]], 0.4, PLA, temp=220, ground=step, fan=False,
                    plastic=lambda x, y: np.ones(np.shape(x), bool))
    off.v[:, 0] = 0.4
    for _ in range(24):
        off.step()
        assert off.points()[off.fixed, 2] == pytest.approx(step(off.points()[off.fixed, 0], 0) + 0.2, abs=0.05)


def fence(x, y):
    """A wall one line thick and 5 mm high, along x at y = 3."""
    return np.where(np.abs(np.c_[x, y][:, 1] - 3) < 0.21, 5.0, 0.0)


@pytest.mark.parametrize("z,along,across,fall", [(0.3, 0, 0.2, 0), (0.3, 0, 2, 0), (0.3, 0.3, 0.2, 0), (5.2, 0, 0.3, 0.35)])
def test_a_wall_one_line_thick_stops_it(z, along, across, fall):
    s = rod(10, ground=fence, temp=25, mu=0.0)
    s.x[:, 1:] = 2.4e-3, z * 1e-3
    s.v[:] = along, across, -fall
    for _ in range(60):
        s.step()
        assert s.points()[:, 1].max() < 2.8  # it stops at the wall's side, however fast, and does not hop it
    assert s.points()[:, 1].max() > 2.5
    assert s.points()[0, 0] == pytest.approx(along * 250, rel=0.1, abs=0.01)  # and slides along it


@pytest.mark.parametrize("shift", (0.0, 0.3, 0.6, 0.9))
def test_dropped_across_a_thin_wall_it_hangs_on_it(shift):
    y = np.arange(-12, 18, 1.2) + shift
    s = st.Strand(np.c_[0 * y, y, 0 * y + 12], 0.4, PLA, fan=False, ground=fence, temp=220)
    for _ in range(120):
        s.step()
        p = s.points()
        assert np.interp(3.0, p[:, 1], p[:, 2]) > 4.9
    assert p[0, 2] < 0.3 and p[-1, 2] < 0.3 and s.vol.sum() == pytest.approx(math.pi / 4 * 0.4e-3 ** 2 * 28.8e-3)


def test_cut_over_a_corner_the_new_node_lies_on_it():
    top = lambda x, y: np.where(x >= 0, 5.0, 0.0)  # noqa: E731
    s = st.Strand([[3.0, 0, 5.2], [1.6, 0, 5.2], [-0.4, 0, 3.9]], 0.4, PLA, fan=False, ground=top, temp=25)
    s._grow()
    new = s.points()[2]
    assert len(s.x) == 4 and new[0] == pytest.approx(0.6) and new[2] >= 5.1
    s = rod(10, ground=top, temp=25)
    s.x[:, 2] = 4.9e-3  # and what is inside comes out, but is not thrown
    for _ in range(20):
        s.step()
        assert s.points()[:, 2] == pytest.approx(5.2, abs=0.01)


def test_halved_the_fan_stays_where_the_nozzle_is(monkeypatch):
    s, heads = rod(10, temp=220), []
    step = s._step
    monkeypatch.setattr(s, "_step", lambda dt, head, check: heads.append(head) or (not check and step(dt, head, check)))
    s.step(head=(5.0, 0, 40.0), halve=1)
    assert heads == [(5.0, 0, 40.0)] * 3


def test_the_fan_blows_a_strand_down():
    out = []
    for fan in (True, False):
        s = st.Strand(np.c_[np.linspace(0, 8, 9), np.zeros(9), np.full(9, 30.0)], 0.4, PLA, temp=25, air=25, fan=fan)
        for _ in range(12):
            s.step(head=(4, 0, 30))
        out.append(30 - s.points()[:, 2].mean())
    assert out[0] > 2 * out[1]


def test_the_fans_air_is_under_the_nozzle_and_not_above_or_beside_it():
    def speed(x, z):
        s = st.Strand([[x + k, 0, z] for k in range(9)], 0.4, PLA, temp=25, air=25)
        s.step(head=(4, 0, 30))
        return -float(s.v[:, 2].mean())

    still = 9.80665 / 240
    assert speed(0, 5) > 3 * still and speed(0, 29) > 3 * still  # at any height below
    assert speed(0, 40) == pytest.approx(still, rel=0.05)  # above
    assert speed(20, 29) == pytest.approx(still, rel=0.05)  # beside


def test_air_along_a_strand_cools_it():
    """Kase and Matsuo: a strand hanging straight under the fan, whose air blows along it, cools faster than in still air."""
    d, t, air, v = 0.48e-3, 150.0, 35.0, 5.0
    p = fs.air((t + air) / 2)
    nu = 0.42 * (v * d / p["nu"]) ** 0.344
    still = float(fs.h_strand(0.48, t, air))
    a, b = t + 273.15, air + 273.15
    rad = fs.fact("emissivity") * fs.fact("stefan_boltzmann") * (a * a + b * b) * (a + b)
    assert float(fs.h_strand(0.48, t, air, 0.0, v)) == pytest.approx(nu * p["k"] / d + rad, rel=1e-6)
    assert float(fs.h_strand(0.48, t, air, 0.0, v)) > 1.3 * still
    z = np.linspace(30, 10, 41)
    end = []
    for fan in (True, False):
        s = st.Strand(np.c_[0 * z, 0 * z, z], 0.48, PLA, fan=fan, held=range(41))
        for _ in range(120):
            s.step(head=(0, 0, 30))
        end.append(float(s.t[20]))
    assert end[0] < end[1] - 15


def test_a_bent_cold_strand_keeps_the_bend_past_what_its_skin_takes():
    """Sharper than strength / E at the skin it stays bent; gentler, it springs back."""
    for radius, stays in ((2.0, True), (60.0, False)):
        a = np.arange(0, 12 / radius, 1 / radius)
        s = st.Strand(np.c_[np.arange(len(a)), 0 * a, 0 * a], 0.5, "PLA", temp=25.0, air=25.0, fan=False)
        s.x = np.c_[radius * np.sin(a), 0 * a, radius * (1 - np.cos(a))] * 1e-3
        k = s._curve(*s.lengths())
        s.eb[:, :3] = k
        s.fixed[:] = True  # held bent a moment
        s.step()
        most = 2 * s.strength / (s.m.e * 1e6 * float(s.m.ratio(25.0))) / 0.5e-3
        left = np.linalg.norm(s.eb[1:-1, :3], axis=1) / np.linalg.norm(k[1:-1], axis=1)
        assert left == pytest.approx(min(1.0, most * radius * 1e-3) if stays else 1.0, rel=0.05)


def bent(radius, **kw):
    """A quarter turn, straight when it was hot."""
    a = np.linspace(0, math.pi / 2, 21)
    s = st.Strand(np.c_[radius * np.sin(a), 0 * a, 30 + radius * (1 - np.cos(a))], 0.4, "PLA", fan=False, **kw)
    s.eb[:, :3] = s._curve(*s.lengths())
    return s


def turned(s):
    tan = s.lengths()[0]
    return math.degrees(math.acos(float(np.clip(tan[0] @ tan[-1], -1, 1))))


def rest(s, monkeypatch, steps=600):
    quiet(s, monkeypatch)
    fs.viscosity(200, 0, "PLA")  # a melt is as thick as its flow index test, which weighs it, says
    monkeypatch.setattr(st.failsim, "fact", lambda key, was=fs.fact: 0.0 if key == "gravity" else was(key))
    s.fixed[2:] = False
    for _ in range(steps):
        s.step()
        s.v *= 0.9
    return turned(s)


def test_a_strand_keeps_the_curve_it_set_in(monkeypatch):
    s = bent(12, temp=85, air=25, held=range(21))  # still holding part of its bend when it sets
    was = turned(s)
    stress = []
    for _ in range(2400):
        s.step()
        stress.append(float(np.linalg.norm(s.eb[10, :3]) * s.m.e * float(s.m.ratio(s.t[10]))))
    assert float(s.t.max()) < 40
    assert max(stress[5:]) <= stress[4] * 1.1  # E grows 300 times, the stress left in it does not
    assert rest(s, monkeypatch) == pytest.approx(was, rel=0.1)


def test_hot_and_cold_lengths_bend_in_series(monkeypatch):
    """Two hot edges and a cold one, over and over: the cold third alone is stiff, not the hot edges beside it."""
    def droop(temps):
        s = rod(4, temp=140, air=140, held=(0, 1))
        s.t[:] = temps
        quiet(s, monkeypatch)
        monkeypatch.setattr(fs, "h_strand", lambda *a, **k: np.zeros(41))
        for _ in range(5):
            s.step()
        return 30 - float(s.points()[-1, 2])

    some = droop(np.where(np.arange(41) % 3 == 0, 255.0, 25.0))  # an edge is at its ends' mean: 140, 25, 140
    assert some == pytest.approx(2 / 3 * droop(np.full(41, 140.0)), rel=0.15)


def test_a_cold_strand_springs_back(monkeypatch):
    s = bent(60, temp=25, air=25, held=range(21))
    assert turned(s) > 80
    s.step()
    assert rest(s, monkeypatch) < 15


def test_cutting_a_drawn_edge_keeps_its_plastic_and_its_bend():
    s = bent(12, temp=25, air=25, held=range(21))
    vol, eb = s.vol.sum(), s.eb.copy()
    s.x *= 2  # every edge 1.9 mm
    s._grow()
    assert len(s.x) == 41 and s.vol.sum() == pytest.approx(vol)
    assert s.eb[2:-2:2] == pytest.approx(eb[1:-1]) and s.eb[3:-3:2] == pytest.approx((eb[1:-2] + eb[2:-1]) / 2)


@pytest.mark.parametrize("n", (3, 11))
@pytest.mark.parametrize("speed", (30, 60, 110, 250))  # rad/s about its middle: 7 to 60 degrees a step
def test_a_whipping_strand_keeps_its_length(monkeypatch, n, speed):
    for temp in (25, 170):
        s = rod(12 if n > 3 else 3, temp=temp, air=temp, n=n)
        was = float(s.lengths()[1].sum())
        quiet(s, monkeypatch)
        s.v[:, 1] = speed * (s.x[:, 0] - was / 2)
        for _ in range(10):
            s.step()
            assert float(s.lengths()[1].sum()) == pytest.approx(was, rel=0.02)


def arc(radius, held=(), flat=False, n=21):
    """A cold quarter turn, set in that curve: upright, or lying flat in the air."""
    a = np.linspace(0, math.pi / 2, n)
    x, y = radius * np.sin(a), radius * (1 - np.cos(a))
    return st.Strand(np.c_[x, y, 0 * a + 30] if flat else np.c_[x, 0 * a, 30 + y], 0.4, PLA, temp=25, air=25, fan=False, held=held)


def inertia(s, about):
    m, r = s._nodes(s.vol * s.rho)[:, None], s.x - about
    return m, r, np.trace(i := (m * r).T @ r) * np.eye(3) - i


@pytest.mark.parametrize("axis", (0, 1, 2))
@pytest.mark.parametrize("speed", (2, 10))
def test_a_cold_strand_spins_on_in_its_own_shape(monkeypatch, axis, speed):
    """Straight or set in a curve, turned about any axis: nothing resists turning as a whole."""
    quiet(None, monkeypatch)
    fs.viscosity(200, 0, "PLA")  # a melt is as thick as its flow index test, which weighs it, says
    monkeypatch.setattr(st.failsim, "fact", lambda key, was=fs.fact: 0.0 if key == "gravity" else was(key))
    for s in (rod(12, temp=25, air=25, n=11), arc(12)):
        m, r, _ = inertia(s, (s._nodes(s.vol)[:, None] * s.x).sum(0) / s.vol.sum())
        s.v = speed * np.cross(np.eye(3)[axis], r)
        was, bend = np.cross(r, m * s.v).sum(0), s._curve(*s.lengths())
        for _ in range(10):
            s.step()
        now = np.cross(s.x - (m * s.x).sum(0) / m.sum(), m * s.v).sum(0)
        assert np.linalg.norm(now - was) <= 0.02 * np.linalg.norm(was) + 1e-15
        assert np.linalg.norm(s._curve(*s.lengths()), axis=1) == pytest.approx(np.linalg.norm(bend, axis=1), abs=0.1)


@pytest.mark.parametrize("dt", (st.DT, st.DT / 4))
def test_a_hinged_cold_strand_swings_as_its_weight_turns_it(monkeypatch, dt):
    for s in (rod(30, temp=25, air=25, held=(0,)), arc(12, held=(0,)), arc(12, held=(0,), flat=True)):
        quiet(s, monkeypatch)
        m, r, i = inertia(s, s.x[0].copy())
        torque = (m * np.cross(r, [0, 0, -G])).sum(0)
        for _ in range(round(3 * st.DT / dt)):
            s.step(dt)
        got = np.cross(r, m * s.v).sum(0)
        assert np.linalg.norm(got - torque * 3 * st.DT) < 0.02 * np.linalg.norm(got)
        assert np.linalg.norm(s.v[-1]) == pytest.approx(np.linalg.norm(np.cross(np.linalg.pinv(i) @ got, r[-1])), rel=0.1)


def test_a_set_curve_sags_sideways_by_bending_and_twisting(monkeypatch):
    """A quarter ring built in at one end, its weight across its plane: Castigliano, with GJ = EI / (1 + nu)."""
    s = arc(20, held=(0, 1), flat=True, n=41)
    quiet(s, monkeypatch)
    for _ in range(1500):
        s.step()
        s.v *= 0.9
    q, i = 1240 * math.pi / 4 * 0.4e-3 ** 2 * G, math.pi * 0.4e-3 ** 4 / 64
    free = math.pi / 2 * 39.5 / 40  # the second node bends over half of the held edge too
    bend = (1 - math.cos(free)) ** 2 / 2
    twist = free ** 2 / 2 - free * math.sin(free) + math.sin(free) ** 2 / 2
    want = q * 0.02 ** 4 / (PLA.e * 1e6 * i) * (bend + twist * (1 + st.NU))
    assert (30 - s.points()[-1, 2]) * 1e-3 == pytest.approx(want, rel=0.02)


@pytest.mark.parametrize("mat", fs.MATERIALS)
def test_it_runs_for_each_plastic(mat):
    s = st.Strand([[0, 0, 9.0], [0, 0, 10.0]], st.exit_diameter(), mat, flow=12, ground=lambda x, y: np.zeros(np.shape(x)), nozzle=True)
    for k in range(480):
        a = k / 240 * 2 * math.pi
        s.step(head=(20 * math.sin(a), 20 - 20 * math.cos(a), 10.0))
    p = s.points()
    assert np.isfinite(p).all() and (p[:, 2] > 0).all() and np.abs(p).max() < 60


def test_drawing_the_neck_takes_three_eta_q_ln_d_over_l():
    flow, speed = 10.0, 200.0
    eta = float(fs.viscosity(220, math.sqrt(3) * (speed - st.payout(flow)) / 5))
    want = 3 * eta * flow * 1e-9 * math.log(speed / st.payout(flow)) / 5e-3
    assert st.draw_force("PLA", flow, speed) == pytest.approx(want)
    assert st.draw_force("PLA", flow, 10.0) == 0.0
    # a strand lying on the bed holds far less than that, so the nozzle drags it
    assert 0.5 * 1240 * math.pi / 4 * (st.exit_diameter() * 1e-3) ** 2 * 0.1 * G < 0.2 * want


def test_the_falling_speed_and_setting_time_are_the_closed_forms(monkeypatch):
    v = st.fall_speed("PLA", 0.4, 25.0) * 1e-3
    a = fs.air(25.0)
    assert 0.5 * a["rho"] * float(st.drag_coefficient(v * 0.4e-3 / a["nu"])) * 0.4e-3 * v * v == pytest.approx(
        1240 * math.pi * 0.2e-3 ** 2 * G, rel=0.01)
    assert st.set_time("PLA") > 3 * st.set_time("PLA", wind=5.0)
    monkeypatch.setattr(fs, "h_strand", lambda d, t, air, wind=0.0: np.full(np.shape(t), 70.0))
    want = PLA.density * 1000 * PLA.cp * 0.4e-3 / (4 * 70) * math.log((220 - 35) / (PLA.tg - 35))
    assert st.set_time("PLA", 0.4, 35.0, nozzle_c=220) == pytest.approx(want, rel=0.01)


def test_what_is_taken_off_keeps_holding_the_rest_and_no_plastic_is_lost():
    s = st.Strand(np.c_[np.linspace(0, 200, 201), np.zeros(201), np.full(201, 0.2)], 0.4, PLA, temp=25, air=25, fan=False,
                  ground=lambda x, y: np.zeros(np.shape(x)), nozzle=True, flow=0.0)
    head = np.array([200.0, 0, 0.2])
    for _ in range(120):
        s.step(head=head)
    vol = s.vol.sum()
    pts, d = s.lay()
    off = float((math.pi / 4 * d ** 2 * np.linalg.norm(np.diff(pts, axis=0), axis=1)).sum()) * 1e-9
    assert s.vol.sum() + off == pytest.approx(vol, rel=1e-6)
    assert 130 < pts[-1, 0] <= 141 and s.points()[0] == pytest.approx(pts[-1])
    w = 1240 * math.pi / 4 * 0.4e-3 ** 2 * G * 0.2
    for _ in range(240):
        head = head + [50 / 240, 0, 0]
        s.step(head=head)
    assert s.force == pytest.approx(0.5 * w, rel=0.1)  # as hard to drag as the whole 200 mm


def _flat(n, **kw):
    """n mm of cold strand lying still on the plate, the nozzle at its end."""
    s = st.Strand(np.c_[np.linspace(0, n, n + 1), np.zeros(n + 1), np.full(n + 1, 0.2)], 0.4, PLA, temp=25, air=25, fan=False,
                  ground=lambda x, y: np.zeros(np.shape(x)), nozzle=True, flow=0.0, **kw)
    for _ in range(20):
        s.step(head=(n, 0, 0.2))
    return s


def test_slack_taken_off_is_taken_up_before_its_weld_holds_and_only_holds_one_way():
    ours = _flat(200, held=(0,))
    ours.lay()
    assert not ours.fixed[0] and ours.tied and ours.tail[-1, 3] == pytest.approx(ours.x[0, 0], rel=0.01)
    ours.tail[-1, 3] += 0.02  # as if 20 mm more of it lay there in a loop
    end, head = ours.tail[-1, 3] * 1e3, np.array([200.0, 0, 0.2])

    def to(s, at, speed):
        while np.linalg.norm(at - head) > 1e-9:
            head[:] += (at - head) * min(1.0, speed / 240 / np.linalg.norm(at - head))
            s.step(head=head)
    to(ours, (210, 0, 0.2), 50)
    assert ours.points()[0, 0] == pytest.approx(end - 10, abs=0.1) and ours.force < 1e-3  # still slack
    to(ours, (221, 0, 0.2), 50)
    assert ours.points()[0, 0] == pytest.approx(end, abs=0.01) and ours.force > 0.05  # cold, and 1 mm too short
    to(ours, (200, 0, 0.2), 50)
    assert ours.points()[0, 0] < end - 15  # the nozzle goes back, and the end with it
    to(ours, (218, 0, 0.2), 50)
    to(ours, (190, 0, 70), 50)
    assert ours.x[0, 2] > 0.005 and np.linalg.norm(ours.x[0] - ours.tail[-1, :3]) <= ours.tail[-1, 3] + 1e-6  # up in the air, no farther from its weld
    ours.vol[-1] = 1e-15
    off = ours.snap()[0]
    assert off.tied and not ours.tied and ours.tail is None
    for k in range(960):
        off.step()
    assert off.points()[[0, -1], 2].max() < 3  # down from 19 mm (it set bent): nothing holds it up in the air


@pytest.mark.parametrize("loops", (True, False))
def test_a_heap_taken_off_holds_as_it_did_whole(loops):
    """600 mm of set plastic in loops 10 mm wide, which drag as one, and in folds 20 mm wide, which open one by one:
    what the nozzle feels pulling its end, with and without lay()."""
    a = np.arange(600)
    p = np.c_[5 * np.cos(a / 5) + a / 30, 5 * np.sin(a / 5)] if loops else np.c_[a / 20, np.abs((a + 10) % 40 - 20)]
    out = np.c_[p[-1, 0] + np.arange(1, 131), np.full(130, p[-1, 1])]
    pts, got = np.c_[np.r_[p, out], np.full(730, 0.2)], []
    for lay in (False, True):
        s = st.Strand(pts, 0.4, PLA, temp=25, air=25, fan=False, ground=lambda x, y: np.zeros(np.shape(x)), nozzle=True)
        head, pull = pts[-1], []
        for _ in range(20):
            s.step(head=head)
        if lay:
            assert len(s.lay()[0]) > 600
        for k in range(240):
            head = head + [40 / 240, 0, 0]
            s.step(head=head)
            pull.append(s.force)
        got.append(np.array(pull).reshape(8, 30).mean(1))  # every 5 mm
    live, ours = got
    assert ours[5:] == pytest.approx(live[5:], rel=0.1)
    assert (ours[:5] < 1.2 * live[:5]).all() and (loops or ours[0] < 0.5 * ours[-1])


def test_taking_it_off_twice_adds_up_and_a_broken_strand_shares_it_out():
    s, once = _flat(400), _flat(400)
    once.lay()
    s.lay(200)
    s.step(head=(400, 0, 0.2))
    s.lay()
    assert s.points()[0] == pytest.approx(once.points()[0], abs=1e-3)
    assert s.tail[-1, 3:] == pytest.approx(once.tail[-1, 3:], rel=0.02)
    s.vol[[15, 30]] = 1e-15
    assert [q.tail is None for q in [*s.snap(), s]] == [False, True, True]


@pytest.mark.parametrize("loose", (0, 4, 30))
def test_a_built_in_end_stays_built_in_when_the_weld_before_it_is_taken_off(loose):
    """Cold, welded along its first 100 mm, some of it loose after that, 80 mm of it out in the air off the edge: it
    sags as a cantilever, not a hinge."""
    n = 181 + loose

    def beam(lay):
        s = st.Strand(np.c_[np.arange(n), np.zeros(n), np.full(n, 20.2)], 0.4, PLA, temp=25, air=25, fan=False,
                      ground=lambda x, y: np.where(np.asarray(x) <= 100.5 + loose, 20.0, 0.0), held=range(101))
        s.step()
        if lay:
            assert len(s.lay()[0]) > 90 and s.fixed[:2].all() and s.tail is None
        for _ in range(240):
            s.step()
        return s.points()[-1]
    was, now = beam(False), beam(True)
    assert now == pytest.approx(was, abs=0.1) and now[2] > 10


def test_what_hangs_between_two_rests_is_taken_off_too():
    """Over a step: on the part, down its side in the air, along the plate. And with its first tip curled up."""
    x = np.r_[np.linspace(0, 40, 41), np.linspace(40.2, 42, 9), np.linspace(43, 200, 158)]
    z = np.r_[np.full(41, 5.2), np.linspace(4.7, 0.7, 9), np.full(158, 0.2)]
    z[:4] += [1.5, 1.0, 0.6, 0.2]
    s = st.Strand(np.c_[x, 0 * x, z], 0.4, PLA, temp=25, air=25, fan=False, nozzle=True,
                  ground=lambda x, y: np.where(np.asarray(x) < 41, 5.0, 0.0))
    for _ in range(240):
        s.step(head=(200, 0, 0.2))
    pts, _ = s.lay()
    rests = np.linalg.norm(np.diff(pts, axis=0), axis=1)[(pts[:-1, 0] > 42) | (pts[1:, 0] < 40)].sum() * 1e-3  # not what hangs
    assert 0 < s.tail[-1, 4] < 0.5 * 1240 * math.pi / 4 * 0.4e-3 ** 2 * G * (rests + 1e-4)
    assert len(pts) and 100 < pts[-1, 0] <= 141 and pts[-1, 2] < 0.3


def test_a_lifted_end_has_no_friction_and_nothing_to_rest_on_is_no_error():
    with_, free = _flat(200), _flat(200)
    for s in (with_, free):
        s.lay()
        assert s.tail[-1, 4] > 0
        s.ground = lambda x, y: np.where(np.asarray(x) < 160, -500.0, 0.0)  # the plate is gone from under its end
    free.tail = None
    for k in range(60):
        for s in (with_, free):
            s.step(head=(200 + 50 / 240 * k, 0, 0.2))
    assert with_.points() == pytest.approx(free.points(), abs=1e-9)
    s = st.Strand(np.c_[np.linspace(0, 200, 201), np.zeros((201, 2))], 0.4, PLA, temp=25, air=25, held=range(101), nozzle=True)
    s.lay()
    s.step(head=(200, 0, 0))
    assert s.tail is None


def test_one_that_breaks_at_the_nozzle_starts_again_when_plastic_comes():
    s = laid(True)
    s.vol[-1] = 1e-15  # a hair at the nozzle
    s.force = 1.0
    off = s.snap()
    assert len(off) == 1 and len(s.x) == 1 and not len(s.vol) and s.force == 0
    s.flow = 0.0
    s.step(head=(125, 0, 5))
    assert s.points()[-1] == pytest.approx([125, 0, 5]) and not s.snap()
    s.flow = 10e-9
    for _ in range(60):
        s.step(head=(125, 0, 5))
    assert len(s.x) > 2 and np.isfinite(s.x).all() and s.vol.sum() == pytest.approx(10e-9 * 60 * st.DT, rel=0.01)


def test_the_closed_forms_where_nothing_flows_or_nothing_sets():
    assert st.draw_force("PLA", 0.0, 200) == 0.0 and st.numbers("PLA", 0.0, 200)["draw_mn"] == 0.0
    assert st.set_time("PLA", air_c=70) == math.inf


def test_a_travel_drags_a_free_strand_and_breaks_a_held_one():
    """The hotend holds the strand by its neck: with nothing coming out it pulls the strand along, or pulls it to a hair."""
    held, free = laid(True), laid(False)
    for s in (held, free):
        s.flow = 0.0
        for k in range(120):
            s.step(head=(120 + 1.5 * (k + 1), 0, 5.0))
            off = s.snap()
            if off:
                break
        if s is held:
            (far,) = off  # what it left, off the nozzle
            assert len(far.x) > 10 and not far.nozzle and min([*far.diameters(), *s.diameters()]) > 0.05
            assert len(s.x) + len(far.x) > 10 and s.nozzle and s.x[-1] == pytest.approx(np.array([120 + 1.5 * (k + 1), 0, 5]) * 1e-3)
    assert not off


def test_an_edge_slumped_to_nothing_is_a_drop():
    s = rod(20, n=5)
    was = s.diameters().copy()
    s.x[2] = s.x[1] + (s.x[2] - s.x[1]) * 1e-3
    assert s.diameters()[1] == pytest.approx((1.5 * was[1] ** 2 * 5) ** (1 / 3), rel=1e-6)  # 20 mm in four; the drop of its volume
    assert s.diameters()[0] == was[0] and not s.snap()
    s.vol[1] = 1e-16  # a hair is one by its own thickness, however short
    s.x[2] = s.x[1] + [5e-3, 0, 0]
    assert s.snap()


def test_a_cold_strand_torn_back_and_forth_gives_instead_of_flying():
    """It froze with its stress, not its strain, so stiffening adds no energy, and it gives past its strength."""
    s = laid(True)
    for k in range(240):
        s.step(head=(120 + 60 * math.sin(k / 6), 40 * math.sin(k / 9), 5.0))
        assert np.abs(s.v).max() < 10 and np.abs(s.points()).max() < 400  # the nozzle reaches 2.7 m/s
    assert (np.abs(s.tens) <= s.strength * s.vol / s.lengths()[1] * 1.2 + 1e-9).all()


@pytest.mark.parametrize("speed", (0, 20, 200))
def test_it_starts_again_just_over_the_plate_without_a_point_over_the_nozzle(speed):
    s = laid(True)
    s.ground, s.flow = lambda x, y: np.zeros(np.shape(x)), 10e-9
    s.force, s.vol[-1] = 1.0, 1e-15
    s.snap()
    assert s.force == 0
    r, head = math.sqrt(s.area / math.pi) * 1e3, np.array([*s.points()[-1, :2], 0.2])
    for k in range(60):
        head = head + [speed / 240, 0, 0]
        s.step(head=head)
        assert s.points()[:, 2].max() <= r + 0.02 and s.diameters().max(initial=0) < 4 * r
    assert (len(s.x) > 1) == (speed > 0)  # it has nowhere to go until the nozzle moves on
    off = laid(True).snap() or [laid(True)]
    off[0].nozzle, off[0].vol[-1] = False, 1e-15
    off[0].snap()
    was = off[0].points()
    off[0].step(head=(0, 0, 50))
    assert off[0].points() == pytest.approx(was)  # a scrap off the nozzle stays where it fell


def test_a_thread_about_to_break_does_not_slow_the_rest():
    asked = []
    s = rod(20, n=5, ground=lambda x, y: asked.append(len(x)) or np.zeros(len(x)))
    to, r = s.x + [0.016, 0, 0], np.array([2e-4, 2e-4, 3e-7, 2e-4, 2e-4])  # 3e-4 mm, what a hot TPU thread got to
    at, floor = s._slide(s.x, to, r, np.zeros(5))
    assert np.allclose(at, to) and max(asked) < 5 * 700
