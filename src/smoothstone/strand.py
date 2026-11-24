"""One strand of melt in the air: what plastic does from the nozzle until it lies still.

A chain of nodes, each edge holding a fixed volume of plastic, stepped implicitly (no stiffness limit):
- it stretches and bends as a Maxwell solid: modulus E(T), relaxation time 3 eta(T) / E. Hot, it flows like
  a viscous thread (Trouton); cold, it is an elastic rod with whatever curve it set in, that turns, spins and
  twists freely (a discrete elastic rod: Bergou et al. 2008, twist without inertia). It thins as it stretches;
- its weight, the air's drag on the part of the wind square to it (measured on wires: NACA TN 84) and the
  part fan's jet move it; each node cools in the wind it feels (failsim.h_strand);
- it rests on the ground with Coulomb friction, and welds where it lands on plastic hot enough;
- plastic comes out of the nozzle at the print's own flow, swollen past the bore, and the nozzle moves on. Held
  behind, the hot neck is drawn thin; not held, the strand is dragged along. Which one is the neck's
  viscosity against what holds the strand, so it differs by plastic, temperature, flow and speed.

Inside: meters, kilograms, seconds, newtons. In and out: mm, mm/s, mm3/s, C. A model, not a recording."""

from __future__ import annotations

import copy
import math
from functools import lru_cache

import numpy as np
from scipy.linalg import solveh_banded

from . import failsim
from .strength import NU

BIG = 1e7  # kg/s: a node held on a place or a speed
CREEP = 1e-4  # m/s: slower than this, friction holds
HEAP = 30.0  # mm of a set heap that follow each mm its end is pulled: folds 20 mm wide, stepped whole; loops 10 mm wide follow at once
DT = 1 / 240  # s
TURN = 0.25  # of an edge's length its ends may move against each other in one step
SPIN = 1e-3  # m, where an edge's spin is solved as a speed


def drag_coefficient(re) -> np.ndarray:
    """A long cylinder across the wind: Wieselsberger's measured curve (NACA TN 84, Fig. 1), Lamb below it."""
    re = np.maximum(np.asarray(re, float), 1e-9)
    tab = np.asarray(failsim.fact("cylinder_drag"), float)
    lamb = 8 * math.pi / (re * (2.002 - np.log(np.minimum(re, 0.5))))
    return np.where(re < tab[0, 0], lamb, np.exp(np.interp(np.log(re), np.log(tab[:, 0]), np.log(tab[:, 1]))))


def exit_diameter(bore: float = 0.4) -> float:
    """mm, the strand as it leaves the nozzle: the bore times the die swell."""
    return bore * failsim.fact("die_swell")


def payout(flow_mm3_s: float, bore: float = 0.4) -> float:
    """mm/s the strand leaves the nozzle at when nothing pulls it."""
    return flow_mm3_s / (math.pi / 4 * exit_diameter(bore) ** 2)


def draw_force(mat, flow_mm3_s: float, speed_mm_s: float, nozzle_c: float | None = None,
               neck_mm: float = 5.0, bore: float = 0.4) -> float:
    """N it takes to draw the hot neck from payout to the nozzle's speed over neck_mm: 3 eta Q ln(D) / L. A strand
    held by less than this is dragged by the nozzle, not drawn."""
    m = failsim._mat(mat)
    out = payout(flow_mm3_s, bore)
    if out <= 0:  # nothing comes out: it necks to a hair
        return 0.0
    ratio = speed_mm_s / out
    if ratio <= 1:
        return 0.0
    rate = (speed_mm_s - out) / neck_mm
    eta = float(failsim.viscosity(m.nozzle if nozzle_c is None else nozzle_c, math.sqrt(3) * rate, m))
    return failsim.fact("trouton") * eta * flow_mm3_s * 1e-9 * math.log(ratio) / (neck_mm * 1e-3)


def fall_speed(mat="PLA", d_mm: float | None = None, air_c: float = 25.0) -> float:
    """mm/s a strand lying flat falls at: where the air's drag on it equals its weight."""
    d, p = (exit_diameter() if d_mm is None else d_mm) * 1e-3, failsim.air(air_c)
    weight = failsim._mat(mat).density * 1000 * math.pi / 4 * d * d * failsim.fact("gravity")
    v = np.geomspace(1e-3, 50, 4000)
    drag = 0.5 * p["rho"] * drag_coefficient(v * d / p["nu"]) * d * v * v
    return float(np.interp(weight, drag, v)) * 1e3


def set_time(mat="PLA", d_mm: float | None = None, air_c: float | None = None, wind: float = 0.0, nozzle_c: float | None = None) -> float:
    """s a strand takes from the nozzle's heat to where it sets in that wind (m/s)."""
    m, d = failsim._mat(mat), exit_diameter() if d_mm is None else d_mm
    air_c = m.chamber if air_c is None else air_c
    if air_c >= m.set:
        return math.inf
    t = np.linspace(m.set, m.nozzle if nozzle_c is None else nozzle_c, 400)
    q = m.density * 1000 * m.cp * d * 1e-3 / 4 / (failsim.h_strand(d, t, air_c, wind) * (t - air_c))
    return float(((q[1:] + q[:-1]) / 2 * np.diff(t)).sum())


def numbers(mat, flow_mm3_s: float, speed_mm_s: float, bore: float = 0.4, air_c: float | None = None, nozzle_c: float | None = None,
            fan: float = 1.0) -> dict:
    """What decides where a strand goes: the hotend's hold on it, the air's, the plate's and its own heat."""
    m = failsim._mat(mat)
    d, air_c = exit_diameter(bore), m.chamber if air_c is None else air_c
    grip = failsim.fact("strand_friction") * m.density * 1000 * math.pi / 4 * (d * 1e-3) ** 2 * failsim.fact("gravity") * 0.1
    hold = failsim.nozzle_hold(m, nozzle_c, bore)
    return {"strand_mm": round(d, 2), "payout_mm_s": round(payout(flow_mm3_s, bore), 1), "nozzle_mm_s": round(speed_mm_s, 1),
            "draw_mn": round(draw_force(m, flow_mm3_s, speed_mm_s, nozzle_c, bore=bore) * 1e3, 2), "plate_grip_mn_per_100mm": round(grip * 1e3, 2),
            "nozzle_hold_mn": round(hold["hold_n"] * 1e3, 3), "melt_wets_the_tip": hold["wets"], "blob_mm3": round(hold["blob_mm3"], 1),
            "fall_mm_s": round(fall_speed(m, d, air_c)), "set_s_still_air": round(set_time(m, d, air_c, 0, nozzle_c), 2),
            "set_s_fan": round(set_time(m, d, air_c, fan * failsim.fact("fan_air_speed"), nozzle_c), 2)}


def _norm(v):
    return np.sqrt(np.einsum("ij,ij->i", v, v))


def _unit(v):
    return v / np.maximum(_norm(v), 1e-12)[:, None]


def _series(q):
    """What two edges give between them at a node: the softer one bends."""
    return 2 / (1 / q[1:] + 1 / q[:-1])


def _cross(a, b):
    (ax, ay, az), (bx, by, bz) = a.T, b.T
    return np.stack([ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx], 1)


def _turn(q, a, b):
    """q carried along as its tangent turns from a to b."""
    w = _cross(a, b)
    return q + _cross(w, q) + _cross(w, _cross(w, q)) / (1 + (a * b).sum(1))[:, None].clip(0.1)


def _rows(way, ln):
    """What each node's bend (3) and twist (1) gain per second from the speeds and spins around it, so that turning the
    strand as a whole gives neither; and what makes a node's spin of its edges' two."""
    lb = (ln[1:] + ln[:-1]) / 2
    both = np.maximum(_norm(way[1:] + way[:-1]), 1e-2)
    t = (way[1:] + way[:-1]) / both[:, None]
    one, two = (1 / ln[:-1])[:, None], (1 / ln[1:])[:, None]
    flat = (np.eye(3) - t[:, :, None] * t[:, None, :]) / lb[:, None, None]
    m = np.zeros((len(lb), 4, 11))  # node before, its edge's spin, node, its edge's spin, node after
    m[:, :3, :3], m[:, :3, 8:] = flat * one[:, None], flat * two[:, None]
    m[:, :3, 4:7] = -flat * (one + two)[:, None]
    m[:, :3, 3] = m[:, :3, 7] = -_cross(t, way[1:] - way[:-1]) / (lb * both * SPIN)[:, None]
    h = _cross(way[:-1], way[1:]) / (lb * np.maximum(both ** 2 / 2, 1e-2))[:, None]
    m[:, 3, :3], m[:, 3, 4:7], m[:, 3, 8:] = -h * one, h * (one - two), h * two
    m[:, 3, 7] = 1 / (lb * SPIN)
    m[:, 3, 3] = -m[:, 3, 7]
    return m, 1 / (both * SPIN)


@lru_cache(maxsize=64)
def _places(count, size, rows, width):
    p, q = np.triu_indices(size)
    return size * p + q, ((rows - 1 - q + p) * width + 4 * np.arange(count)[:, None] + q).ravel()


def _add(ab, e):
    """Add symmetric elements, one from each node on, to an upper band of 4 unknowns a node."""
    take, at = _places(*e.shape[:2], *ab.shape)
    ab += np.bincount(at, e.reshape(len(e), -1)[:, take].ravel(), ab.size).reshape(ab.shape)


class Strand:
    """ground(x, y) -> z and plastic(x, y) -> bool take mm. Nodes run from the first plastic out to the nozzle."""

    def __init__(self, points, diameter, mat="PLA", temp=None, air=None, flow=0.0, bore=0.4, fan=True, ground=None, plastic=None,
                 mu=None, seg=1.2, nozzle=False, held=()):
        self.m = m = failsim._mat(mat)
        self.x = np.asarray(points, float) * 1e-3
        n = len(self.x)
        self.v = np.zeros_like(self.x)
        self.vol = math.pi / 4 * (np.full(n - 1, float(diameter)) * 1e-3) ** 2 * np.linalg.norm(np.diff(self.x, axis=0), axis=1)
        self.t = np.full(n, float(m.nozzle if temp is None else temp))
        self.hot = float(m.nozzle if temp is None else temp)  # what comes out of the nozzle
        self.air = m.chamber if air is None else float(air)
        self.es, self.eb = np.zeros(n - 1), np.zeros((n, 4))  # elastic stretch of edges, elastic curvature and twist of nodes (1/m)
        self.rate, self.tens, self.press = np.zeros(n - 1), np.zeros(n - 1), np.zeros(n)
        self.strength = failsim._props(m.name)[0]["tensile_xy"]["value"] * 1e6  # Pa
        self.e = np.full(n - 1, np.inf)  # Pa, the modulus its elastic strains were kept at
        self.fixed = np.zeros(n, bool)
        self.fixed[list(held)] = True
        self.nozzle, self.flow, self.area = nozzle, flow * 1e-9, math.pi / 4 * (exit_diameter(bore) * 1e-3) ** 2
        self.fan, self.reach = fan * failsim.fact("fan_air_speed"), failsim.fact("fan_reach") * 1e-3
        self.ground, self.plastic = ground, plastic
        self.mu = failsim.fact("strand_friction") if mu is None else mu
        self.seg = seg * 1e-3
        self.rho = m.density * 1000
        self.force = 0.0  # N at the nozzle
        self.tail = None  # what lay() took off: rows of x, y, z, m along it from the cut, N of friction between
        self.tied = False  # that its far end is welded
        self.came = 0.0  # m3 out of the nozzle since it broke there
        self.touch = np.zeros(n, bool)

    # geometry
    def lengths(self):
        d = np.diff(self.x, axis=0)
        ln = np.maximum(_norm(d), 1e-7)
        return d / ln[:, None], ln

    def diameters(self) -> np.ndarray:
        """mm, of each edge; one slumped shorter than it is thick is the drop its plastic makes, not a disc."""
        return np.minimum(np.sqrt(4 * self.vol / (math.pi * self.lengths()[1])), np.cbrt(6 * self.vol / math.pi)) * 1e3

    def points(self) -> np.ndarray:
        return self.x * 1e3

    def _curve(self, tan, ln):
        k = np.zeros_like(self.x)
        k[1:-1] = 2 * (tan[1:] - tan[:-1]) / (ln[1:] + ln[:-1])[:, None]
        return k

    def _nodes(self, e):
        """An edge quantity shared out to its two nodes, half each."""
        out = np.zeros(len(e) + 1)
        out[:-1] += e / 2
        out[1:] += e / 2
        return out

    def step(self, dt: float = DT, head=None, halve: int = 4):
        """One step. head: the nozzle's new place, mm. One that swings an edge too far is taken in halves."""
        if len(self.x) < 2:
            return self._restart(dt, head)
        was = {k: q.copy() if isinstance(q, np.ndarray) else q for k, q in self.__dict__.items()} if halve else None
        if self._step(dt, head, halve > 0):
            return
        self.__dict__.update(was)
        start = self.x[-1] * 1e3
        for part in (0.5, 1.0):
            self.step(dt / 2, start + (np.asarray(head) - start) * part if self.nozzle and head is not None else head, halve - 1)

    def _restart(self, dt, head):
        """It broke at the nozzle: nothing hangs there until enough has come out, with room to hang or trail in."""
        if not self.nozzle:
            return
        at = self.x[-1] if head is None else np.asarray(head) * 1e-3
        back, self.x = (self.x[-1] - at) * [1, 1, 0], at[None].copy()
        self.came += self.flow * dt
        ln = min(self.came / self.area, self.seg)
        low = ln if self.ground is None else max(0.0, at[2] - float(self._top(at)) - math.sqrt(self.area / math.pi))
        if ln < self.seg / 6 or (low < ln and not back.any()):
            return
        trail = math.sqrt(max(0.0, ln * ln - low * low)) / max(float(np.linalg.norm(back)), 1e-12)
        self.x = np.array([at + back * trail - [0, 0, min(ln, low)], at])
        self.v, self.eb, self.t = np.zeros((2, 3)), np.zeros((2, 4)), np.full(2, self.hot)
        self.press, self.touch, self.fixed = np.zeros(2), np.zeros(2, bool), np.zeros(2, bool)
        self.es, self.rate, self.tens, self.e = np.zeros(1), np.zeros(1), np.zeros(1), np.full(1, np.inf)
        self.vol, self.came = np.array([self.came]), 0.0

    def _step(self, dt, head, check) -> bool:
        m, n = self.m, len(self.x)
        tan, ln = self.lengths()
        mass = self._nodes(self.vol * self.rho)
        area = self.vol / ln
        d = np.sqrt(4 * area / math.pi)
        te = (self.t[1:] + self.t[:-1]) / 2
        e_mod = m.e * 1e6 * m.ratio(te)
        if np.isfinite(self.e).all():  # as it sets, the stress stays, not the strain: stiffening adds no energy
            self.es *= np.minimum(1.0, self.e / e_mod)
            self.eb[1:-1] *= np.minimum(1.0, _series(self.e) / _series(e_mod))[:, None]
        self.e = e_mod
        eta = np.minimum(failsim.viscosity(te, math.sqrt(3) * np.abs(self.rate), m), 1e14)
        lam = failsim.fact("trouton") * eta / e_mod
        soft = lam / (lam + dt)
        ks = e_mod * area * soft / ln  # N per m of new length
        inflow = np.zeros(n - 1)
        if self.nozzle:
            inflow[-1] = self.flow / self.area * dt
        # the wind each node feels, across the strand
        tn = np.zeros_like(self.x)
        tn[:-1] += tan
        tn[1:] += tan
        tn = _unit(tn)
        wind = np.zeros_like(self.x)
        if self.fan and head is not None:
            away = self.x - np.asarray(head) * 1e-3
            near = (np.hypot(away[:, 0], away[:, 1]) < self.reach) & (away[:, 2] < 1e-4)
            wind[near, 2] = -self.fan
        rel = wind - self.v
        along = (rel * tn).sum(1)
        rel -= along[:, None] * tn
        speed = _norm(rel)
        dn = self._nodes(d * ln) / np.maximum(self._nodes(ln), 1e-12)
        p = failsim.air((self.t + self.air) / 2)
        cd = drag_coefficient(speed * dn / p["nu"])
        drag = 0.5 * p["rho"] * cd * dn * self._nodes(ln) * speed
        rhs = (mass / dt)[:, None] * self.v
        rhs[:, 2] -= mass * failsim.fact("gravity")
        rhs += drag[:, None] * (wind - (wind * tn).sum(1, keepdims=True) * tn)
        eye = np.eye(3)
        ab = np.zeros((11, 4 * n))  # upper band: 3 speeds a node and the spin of the edge after it
        _add(ab, (mass / dt)[:, None, None] * eye + drag[:, None, None] * (eye - tn[:, :, None] * tn[:, None, :]))
        ab[-1, 3::4] = np.r_[self.vol * self.rho * (d / SPIN) ** 2 / 8 / dt, 1.0]
        hold = self.fixed.copy()
        drawn = 0.0  # N, what was taken off holds with: the friction of what is straight or has had time to follow
        if self.tail is not None:
            apart = np.linalg.norm(self.x[0] - self.tail[:, :3], axis=1)
            out, left = _unit(self.x[:1] - self.tail[-1, :3]), (self.tail[-1, 3] - apart[-1]) / dt  # from its weld, and how fast it may go
            drawn = float(self.tail[(apart >= 0.98 * self.tail[:, 3]) | (self.tail[:, 3] <= HEAP * apart[0]), 4].max())
        vh = np.zeros((n, 3))
        if self.nozzle:
            hold[-1] = True
            vh[-1] = 0.0 if head is None else (np.asarray(head) * 1e-3 - self.x[-1]) / dt
        big = np.where(hold, BIG, 0.0)
        rhs += big[:, None] * vh
        ab[-1] += np.c_[big, big, big, np.where(np.r_[self.fixed[1:] & self.fixed[:-1], False], BIG, 0.0)].ravel()
        # ground: an active set of nodes kept from going below it, with friction
        r = dn / 2
        touch, floor = np.zeros(n, bool), None
        if self.ground is not None:
            floor = self._top(self.x) + r
            touch = (self.x[:, 2] <= floor + 1e-6) & ~hold
            to = (floor - self.x[:, 2]) / dt  # down onto the ground, or up out of it
        v = self.v
        kb = _series(e_mod * soft) * math.pi * ((d[1:] + d[:-1]) / 2) ** 4 / 64 * (ln[1:] + ln[:-1]) / 2
        kb = np.stack([kb, kb, kb, kb / (1 + NU)], 1)  # G J = E I / (1 + nu)
        way, gain, rest, tens, taut = tan, np.ones(n - 1), 1.0, self.tens, False
        for _ in range(2):  # solved again along the mean of the edges' old and new directions: turning strains nothing
            tt = way[:, :, None] * way[:, None, :]
            stiff = dt * (ks * gain)[:, None, None] * tt + (rest * dt * np.maximum(tens, 0) / ln)[:, None, None] * (eye - tt)
            edge = np.zeros((n - 1, 7, 7))
            edge[:, :3, :3] = edge[:, 4:, 4:] = stiff
            edge[:, :3, 4:] = -stiff
            rh, band = np.c_[rhs, np.zeros(n)], ab.copy()
            _add(band, edge)
            pull = (ks * (self.es * ln - inflow))[:, None] * way
            rh[:-1, :3] += pull
            rh[1:, :3] -= pull
            rows, spin = _rows(way, ln)
            if n > 2:
                _add(band, dt * rows.transpose(0, 2, 1) @ (kb[:, :, None] * rows))
                push = ((kb * self.eb[1:-1])[:, None] @ rows)[:, 0]
                rh[:-2] -= push[:, :4]
                rh[1:-1] -= push[:, 4:8]
                rh[2:, :3] -= push[:, 8:]
            for _ in range(5):
                ab2, rh2 = band.copy(), rh.copy()
                slip = _norm(v[:, :2])
                if tied := self.tied and (taut or v[0] @ out[0] > left):  # no farther; nearer, or round it
                    _add(ab2, BIG * (out[:, :, None] * out[:, None, :]))
                    rh2[0, :3] += BIG * left * out[0]
                if touch.any():
                    fr = np.where(touch, self.mu * np.maximum(self.press, 0) / np.maximum(slip, CREEP), 0.0)
                    fr[0] += touch[0] * drawn / max(slip[0], CREEP)
                    ab2[-1, 0::4] += fr
                    ab2[-1, 1::4] += fr
                    ab2[-1, 2::4] += np.where(touch, BIG, 0.0)
                    rh2[touch, 2] += BIG * to[touch]
                u = solveh_banded(ab2, rh2.ravel(), check_finite=False).reshape(n, 4)
                v = u[:, :3]
                taut, was = self.tied and bool(v[0] @ out[0] > left), tied
                if floor is None and taut == was:
                    break
                if floor is None:
                    continue
                push = np.where(touch, BIG * (to - v[:, 2]), 0.0)
                deep = ~hold & ~touch & (self.x[:, 2] + dt * v[:, 2] < floor - 1e-9)
                up = touch & (push < 0)
                self.press = np.maximum(push, 0)
                if taut == was and not deep.any() and not up.any() and (np.abs(_norm(v[:, :2]) - slip)[touch] < 0.1 * slip[touch] + 1e-3).all():
                    break
                touch = (touch | deep) & ~up
            move = np.diff(dt * v, axis=0)
            far = (_norm(move) / ln)[:-1 if self.nozzle else None].max(initial=0.0)  # the nozzle's edge grows by what comes out
            tens = ks * (self.es * ln - inflow + gain * (way * move).sum(1))
            mid = tan * ln[:, None] + move / 2
            way, gain, rest = _unit(mid), 2 * _norm(mid) / (ln + _norm(mid + move / 2)), 0.5
        x = self.x + dt * v
        if check and far > TURN:
            return False
        self.touch = touch
        if floor is not None:
            at, f2 = self._slide(self.x, x, r, floor)
            stop = ~hold & (at != x).any(1)
            x[stop], v[stop, :2] = at[stop], (at - self.x)[stop, :2] / dt
            v[touch & (to > 0), 2] = 0.0  # pushed out of the ground, not thrown
            low = ~hold & (x[:, 2] < f2)
            x[low, 2] = f2[low]
        if self.tied:
            gap = x[0] - self.tail[-1, :3]
            x[0] = self.tail[-1, :3] + gap * min(1.0, self.tail[-1, 3] / max(float(np.linalg.norm(gap)), 1e-12))
        old_l, old_k, old_tn = ln, self._curve(tan, ln), tn
        self.v, self.x = v, x
        tan, ln = self.lengths()
        self.rate = (ln - old_l - inflow) / (old_l * dt)
        limit = np.minimum(1.0, self.strength / e_mod)  # past it the plastic gives
        self.es = np.clip(soft * (self.es + (ln - old_l - inflow) / old_l), -limit, limit)
        self.tens = np.minimum(tens, limit * e_mod * area)
        if self.nozzle:
            self.force = float(self.tens[-1])
        tn = np.zeros_like(x)
        tn[:-1] += tan
        tn[1:] += tan
        tn = _unit(tn)
        ang = np.zeros((n, 1))
        ang[1:-1, 0] = dt * spin * (u[1:-1, 3] + u[:-2, 3])
        carry = lambda q: np.cos(ang) * (q := _turn(q, old_tn, tn)) + np.sin(ang) * _cross(tn, q)  # noqa: E731
        sn = np.ones((n, 1))
        sn[1:-1, 0] = _series(e_mod * soft) / _series(e_mod)
        twist = np.zeros(n)
        twist[1:-1] = dt * (rows[:, 3, None] @ np.c_[u[:-2], u[1:-1], u[2:, :3]][:, :, None])[:, 0, 0]
        self.eb = sn * np.c_[carry(self.eb[:, :3]) + self._curve(tan, ln) - carry(old_k), self.eb[:, 3] + twist]
        most = np.full(n, np.inf)
        most[1:-1] = 2 * np.minimum(limit[1:], limit[:-1]) / np.maximum(d[1:], d[:-1])  # 1/m, where its skin gives
        self.eb *= np.minimum(1.0, most / np.maximum(_norm(self.eb * [1, 1, 1, math.sqrt(3) / 2 / (1 + NU)]), 1e-9))[:, None]
        h = failsim.h_strand(dn * 1e3, self.t, self.air, speed, np.abs(along))
        self.t = self.air + (self.t - self.air) * np.exp(-4 * h * dt / (self.rho * m.cp * np.maximum(dn, 1e-6)))
        if self.nozzle:
            self.t[-1] = self.hot
            self.vol[-1] += self.flow * dt
        if floor is not None and self.plastic is not None:
            on = touch & (x[:, 2] < f2 + 1e-5) & (self.air + failsim.fact("weld_rule") * (self.t - self.air) > m.set)
            if on.any():
                at = self.x[on] * 1e3
                self.fixed[np.flatnonzero(on)[np.asarray(self.plastic(at[:, 0], at[:, 1]), bool)]] = True
            self.v[self.fixed] = 0
        self._grow()
        return True

    def _top(self, p):
        """m, the ground under p."""
        return np.asarray(self.ground(*p[..., :2].reshape(-1, 2).T * 1e3), float).reshape(p.shape[:-1]) * 1e-3

    def _slide(self, a, b, r, floor):
        """Where nodes going from a to b get, and the ground there: ground higher than they are stops them at its side,
        and they go on along it."""
        fine = max(r.min(), failsim.fact("thread_limit") * 1e-3 / 2)  # a thinner thread is about to break
        for k in (slice(0, 3), 0, 1):
            go = np.zeros_like(a)
            go[:, k] = (b - a)[:, k]
            s = np.linspace(0, 1, int(_norm(go[:, :2]).max() / fine) + 2)
            via = a + s[:, None, None] * go
            path = self._top(via) + r
            clear = ~np.logical_or.accumulate((path > via[:, :, 2] + r) & (path > floor + 1e-6))
            last = np.maximum(clear.sum(0) - 1, 0), np.arange(len(a))
            a, floor = via[last], path[last]
            if clear.all():
                break
            a[:, 2] = b[:, 2]
        return a, floor

    def _over(self, ln, f):
        """Edges about to lie across ground higher than under their ends, and, in f, where to put a node on it."""
        s = np.linspace(0, 1, 13)[1:-1, None]
        top, ends = self._top(self.x[:-1] + s[:, :, None] * np.diff(self.x, axis=0)), self._top(self.x)
        high, r = top.max(0), np.sqrt(self.vol / math.pi / ln)
        mid = s[np.where(top == high, np.abs(s - 0.5), np.inf).argmin(0), 0]
        z, vz = ((1 - mid) * q[:-1, 2] + mid * q[1:, 2] for q in (self.x, self.v))
        over = (high > np.maximum(ends[:-1], ends[1:]) + r) & (z > high) & (z < high + 2 * r - DT * np.minimum(vz, 0))
        over &= np.minimum(mid, 1 - mid) * ln > 1e-4
        f[over] = mid[over]
        return over

    def _grow(self):
        """Cut an edge that has grown: the nozzle's by what came out, a drawn one by its length. And one over a wall."""
        ln = self.lengths()[1]
        cut, f = ln > 1.5 * self.seg, np.full(len(ln), 0.5)
        if self.nozzle:
            cut[-1] |= self.vol[-1] > 1.5 * self.area * self.seg
            f[-1] = 2 / 3  # the edge at the nozzle stays the short one
        if self.ground is not None:
            cut |= self._over(ln, f)
        at = np.flatnonzero(cut)
        if not len(at):
            return
        f = f[at]
        i = at + 1
        for k in ("x", "v", "eb"):
            q = getattr(self, k)
            setattr(self, k, np.insert(q, i, q[at] * (1 - f[:, None]) + q[at + 1] * f[:, None], 0))
        self.t = np.insert(self.t, i, self.t[at] * (1 - f) + self.t[at + 1] * f)
        self.press, self.touch = np.insert(self.press, i, 0.0), np.insert(self.touch, i, self.touch[at] & self.touch[at + 1])
        self.fixed = np.insert(self.fixed, i, self.fixed[at] & self.fixed[at + 1])
        for k in ("es", "rate", "tens", "e"):
            setattr(self, k, np.insert(getattr(self, k), i, getattr(self, k)[at]))
        first = self.vol[at] * f
        rest = self.vol[at] - first
        self.vol[at] = first
        self.vol = np.insert(self.vol, i, rest)
        if self.ground is not None:  # the new node of an edge hung over a corner is not inside it
            new = i + np.arange(len(i))
            self.x[new, 2] = np.maximum(self.x[new, 2], self._top(self.x[new]) + np.sqrt(first / math.pi / ln[at] / f))

    def snap(self) -> list:
        """Where it is drawn thinner than a hair it breaks: the pieces off the nozzle, without the hairs between them.
        What is left here has one point when it broke at the nozzle."""
        thin = np.flatnonzero(4 * self.vol / (math.pi * self.lengths()[1]) < (failsim.fact("thread_limit") * 1e-3) ** 2)
        if not len(thin):
            return []
        cut, n, off = np.r_[-1, thin], len(self.x), []
        for a, b in zip(cut + 1, np.r_[thin, n - 1]):  # a piece's first and last node
            s = self if b == n - 1 else copy.copy(self)
            if s is not self and a == b:
                continue
            if s is not self:
                s.nozzle, s.force = False, 0.0
                if a:
                    s.tail, s.tied = None, False
                off.append(s)
            for q in ("x", "v", "t", "eb", "press", "touch", "fixed"):
                setattr(s, q, getattr(self, q)[a:b + 1].copy())
            for q in ("es", "rate", "tens", "vol", "e"):
                setattr(s, q, getattr(self, q)[a:b].copy())
            s.eb[[0, -1]] = 0.0  # an end carries no bend
        self.tail, self.tied = None, False
        if len(self.x) < 2:
            self.force = 0.0
        return off

    def lay(self, keep: float = 60.0):
        """Take off what lies still, from the far end to at most keep mm from the nozzle. It is cut between two welded
        nodes, or where as much lies behind the cut as hangs anywhere after it. What was taken off goes on holding the
        rest: its friction as the pull reaches it (HEAP), and its weld once it is straight. Returns its points and diameters, mm;
        they stay where they lay, whatever the rest does."""
        ln, n = self.lengths()[1], len(self.x)
        arc = np.r_[np.cumsum(ln[::-1])[::-1], 0.0]
        lies = self.fixed | self.touch
        still = (lies | (self.t < self.m.set)) & (_norm(self.v) < 20 * CREEP) & (arc > keep * 1e-3)
        ends = np.r_[np.flatnonzero(~lies), n - 1]  # of the run of lying nodes a node is in, and the next one that lies
        run = arc - arc[ends[np.searchsorted(ends, np.arange(n))]]
        rests = np.flatnonzero(lies)
        hang = np.r_[-np.diff(arc[np.r_[rests, n - 1]]) * (np.diff(np.r_[rests, n - 1]) > 1), 0.0]
        most = np.maximum.accumulate(hang[::-1])[::-1][np.searchsorted(rests, np.arange(n))]
        clamp = np.r_[self.fixed[:-1] & self.fixed[1:], False]
        k = int(np.flatnonzero((clamp | (lies & (run > most)))[:int(np.argmin(still))]).max(initial=0))
        if k < 1:
            return np.zeros((0, 3)), np.zeros(0)
        pts, d = self.points()[:k + 1], self.diameters()[:k]
        welds = np.flatnonzero(self.fixed[:k + 1])
        rub = self.mu * failsim.fact("gravity") * self.rho * self.vol[:k] * (lies[:k] & lies[1:k + 1])
        tail = np.c_[self.x[:k + 1], arc[:k + 1] - arc[k], np.r_[np.cumsum(rub[::-1])[::-1], 0.0]][::-1]
        if len(welds):  # only what lies past the last weld still slides
            tail = tail[:k + 1 - welds[-1]]
        elif self.tail is not None:
            tail = np.r_[tail, self.tail[1:] + [0, 0, 0, tail[-1, 3], tail[-1, 4]]]
        self.tied = (self.tied or len(welds) > 0) and not clamp[k]
        self.tail = None if clamp[k] else tail
        for q in ("x", "v", "t", "eb", "press", "touch", "fixed"):
            setattr(self, q, getattr(self, q)[k:].copy())
        for q in ("es", "rate", "tens", "vol", "e"):
            setattr(self, q, getattr(self, q)[k:].copy())
        self.eb[0] = 0.0
        return pts, d
