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


def test_it_cools_as_a_strand_in_still_air(monkeypatch):
    s = rod(20, temp=220, held=range(41))
    for _ in range(240):
        s.step()
    t = 220.0
    for _ in range(1000):
        t -= 4 * float(fs.h_strand(0.4, t, 35.0)) * (t - 35) / (1240 * 1400 * 0.4e-3) * 1e-3
    assert float(s.t[20]) == pytest.approx(t, rel=0.02)


def test_the_fan_blows_a_strand_down():
    out = []
    for fan in (True, False):
        s = st.Strand(np.c_[np.linspace(0, 8, 9), np.zeros(9), np.full(9, 30.0)], 0.4, PLA, temp=25, air=25, fan=fan)
        for _ in range(12):
            s.step(head=(4, 0, 30))
        out.append(30 - s.points()[:, 2].mean())
    assert out[0] > 2 * out[1]


def test_a_bent_cold_strand_keeps_the_bend_past_what_its_skin_takes():
    """Sharper than strength / E at the skin it stays bent; gentler, it springs back."""
    for radius, stays in ((2.0, True), (60.0, False)):
        a = np.arange(0, 12 / radius, 1 / radius)
        s = st.Strand(np.c_[np.arange(len(a)), 0 * a, 0 * a], 0.5, "PLA", temp=25.0, air=25.0, fan=False)
        s.x = np.c_[radius * np.sin(a), 0 * a, radius * (1 - np.cos(a))] * 1e-3
        k = s._curve(*s.lengths())
        s.eb = k.copy()
        s.fixed[:] = True  # held bent a moment
        s.step()
        most = 2 * s.strength / (s.m.e * 1e6 * float(s.m.ratio(25.0))) / 0.5e-3
        left = np.linalg.norm(s.eb[1:-1], axis=1) / np.linalg.norm(k[1:-1], axis=1)
        assert left == pytest.approx(min(1.0, most * radius * 1e-3) if stays else 1.0, rel=0.05)


def test_a_whipping_strand_keeps_its_length(monkeypatch):
    """Ten turns in ten steps: a step that swings an edge too far is taken in halves."""
    def spun(**kw):
        s = rod(12, temp=25, air=25, n=11)
        quiet(s, monkeypatch)
        s.v[:, 1] = 250 * (s.x[:, 0] - 6e-3)  # rad/s about its middle: 60 degrees a step
        longest = 0.0
        for _ in range(10):
            s.step(**kw)
            longest = max(longest, float(s.lengths()[1].sum()) * 1e3)
        return longest

    assert spun() == pytest.approx(12, rel=0.05)
    assert spun(halve=0) > 14
