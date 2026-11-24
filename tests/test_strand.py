"""One strand of melt (strand.py), each behavior held to its textbook formula."""

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
    assert (p[:, 2] > 0.1).all() and p[:, 2].max() < 0.5
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
    held, free = laid(True), laid(False)
    assert held.points()[0] == pytest.approx([0, 0, 0.24], abs=1e-3)
    assert np.median(held.diameters()) == pytest.approx(math.sqrt(4 * 10 / 200 / math.pi), rel=0.25)
    assert held.lengths()[1].sum() * 1e3 == pytest.approx(120, rel=0.1)  # it spans the whole path
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


def test_a_cold_strand_torn_back_and_forth_gives_instead_of_flying():
    """It froze with its stress, not its strain, so stiffening adds no energy, and it gives past its strength."""
    s = laid(True)
    for k in range(240):
        s.step(head=(120 + 60 * math.sin(k / 6), 40 * math.sin(k / 9), 5.0))
        assert np.abs(s.v).max() < 10 and np.abs(s.points()).max() < 400  # the nozzle reaches 2.7 m/s
    assert (np.abs(s.tens) <= s.strength * s.vol / s.lengths()[1] * 1.2 + 1e-9).all()
