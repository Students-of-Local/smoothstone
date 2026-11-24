"""One strand of melt in the air: what plastic does from the nozzle until it sets.

A chain of nodes, each edge holding a fixed volume of plastic, stepped implicitly (no stiffness limit):
- it stretches and bends as a Maxwell solid: modulus E(T), relaxation time 3 eta(T) / E. Hot, it flows like
  a viscous thread (Trouton); cold, it is an elastic rod with whatever curve it set in, that turns, spins and
  twists freely (a discrete elastic rod: Bergou et al. 2008, twist without inertia). It thins as it stretches;
- its weight, the air's drag on the part of the wind square to it (measured on wires: NACA TN 84) and the
  part fan's jet move it; each node cools in the wind it feels (failsim.h_strand);

Inside: meters, kilograms, seconds, newtons. In and out: mm, C. A model, not a recording."""

from __future__ import annotations

import math

import numpy as np
from scipy.linalg import solveh_banded

from . import failsim
from .strength import NU

BIG = 1e7  # kg/s: a node held in place
SEG = 1.2e-3  # m between nodes
DT = 1 / 240  # s
TURN = 0.25  # of an edge's length its ends may move against each other in one step
SPIN = 1e-3  # m, where an edge's spin is solved as a speed


def drag_coefficient(re) -> np.ndarray:
    """A long cylinder across the wind: Wieselsberger's measured curve (NACA TN 84, Fig. 1), Lamb below it."""
    re = np.maximum(np.asarray(re, float), 1e-9)
    tab = np.asarray(failsim.fact("cylinder_drag"), float)
    lamb = 8 * math.pi / (re * (2.002 - np.log(np.minimum(re, 0.5))))
    return np.where(re < tab[0, 0], lamb, np.exp(np.interp(np.log(re), np.log(tab[:, 0]), np.log(tab[:, 1]))))


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


def _add(ab, e):
    """Add symmetric elements, one from each node on, to an upper band of 4 unknowns a node."""
    p, q = np.triu_indices(e.shape[1])
    at = (len(ab) - 1 - q + p) * ab.shape[1] + 4 * np.arange(len(e))[:, None] + q
    ab += np.bincount(at.ravel(), e[:, p, q].ravel(), ab.size).reshape(ab.shape)


class Strand:
    """points in mm. Nodes run from the first plastic out to the nozzle."""

    def __init__(self, points, diameter, mat="PLA", temp=None, air=None, fan=True, held=()):
        self.m = m = failsim._mat(mat)
        self.x = np.asarray(points, float) * 1e-3
        n = len(self.x)
        self.v = np.zeros_like(self.x)
        self.vol = math.pi / 4 * (np.full(n - 1, float(diameter)) * 1e-3) ** 2 * np.linalg.norm(np.diff(self.x, axis=0), axis=1)
        self.t = np.full(n, float(m.nozzle if temp is None else temp))
        self.air = m.chamber if air is None else float(air)
        self.es, self.eb = np.zeros(n - 1), np.zeros((n, 4))  # elastic stretch of edges, elastic curvature and twist of nodes (1/m)
        self.rate, self.tens = np.zeros(n - 1), np.zeros(n - 1)
        self.strength = failsim._props(m.name)[0]["tensile_xy"]["value"] * 1e6  # Pa
        self.e = np.full(n - 1, np.inf)  # Pa, the modulus its elastic strains were kept at
        self.fixed = np.zeros(n, bool)
        self.fixed[list(held)] = True
        self.fan, self.reach = (failsim.fact("fan_air_speed") if fan else 0.0), failsim.fact("fan_reach") * 1e-3
        self.rho = m.density * 1000

    # geometry
    def lengths(self):
        d = np.diff(self.x, axis=0)
        ln = np.maximum(_norm(d), 1e-7)
        return d / ln[:, None], ln

    def diameters(self) -> np.ndarray:
        """mm, of each edge."""
        return np.sqrt(4 * self.vol / (math.pi * self.lengths()[1])) * 1e3

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
        """One step. head: the nozzle's place, mm, where the fan blows. One that swings an edge too far is taken in halves."""
        was = {k: q.copy() if isinstance(q, np.ndarray) else q for k, q in self.__dict__.items()} if halve else None
        if self._step(dt, head, halve > 0):
            return
        self.__dict__.update(was)
        for _ in range(2):
            self.step(dt / 2, head, halve - 1)

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
        ab[-1] += np.where(np.c_[self.fixed, self.fixed, self.fixed, np.r_[self.fixed[1:] & self.fixed[:-1], False]], BIG, 0.0).ravel()
        kb = _series(e_mod * soft) * math.pi * ((d[1:] + d[:-1]) / 2) ** 4 / 64 * (ln[1:] + ln[:-1]) / 2
        kb = np.stack([kb, kb, kb, kb / (1 + NU)], 1)  # G J = E I / (1 + nu)
        way, gain, rest, tens = tan, np.ones(n - 1), 1.0, self.tens
        for _ in range(2):  # solved again along the mean of the edges' old and new directions: turning strains nothing
            tt = way[:, :, None] * way[:, None, :]
            stiff = dt * (ks * gain)[:, None, None] * tt + (rest * dt * np.maximum(tens, 0) / ln)[:, None, None] * (eye - tt)
            edge = np.zeros((n - 1, 7, 7))
            edge[:, :3, :3] = edge[:, 4:, 4:] = stiff
            edge[:, :3, 4:] = -stiff
            rh, band = np.c_[rhs, np.zeros(n)], ab.copy()
            _add(band, edge)
            pull = (ks * self.es * ln)[:, None] * way
            rh[:-1, :3] += pull
            rh[1:, :3] -= pull
            rows, spin = _rows(way, ln)
            if n > 2:
                _add(band, dt * rows.transpose(0, 2, 1) @ (kb[:, :, None] * rows))
                push = ((kb * self.eb[1:-1])[:, None] @ rows)[:, 0]
                rh[:-2] -= push[:, :4]
                rh[1:-1] -= push[:, 4:8]
                rh[2:, :3] -= push[:, 8:]
            u = solveh_banded(band, rh.ravel(), check_finite=False).reshape(n, 4)
            v = u[:, :3]
            move = np.diff(dt * v, axis=0)
            far = _norm(move) / ln
            tens = ks * (self.es * ln + gain * (way * move).sum(1))
            mid = tan * ln[:, None] + move / 2
            way, gain, rest = _unit(mid), 2 * _norm(mid) / (ln + _norm(mid + move / 2)), 0.5
        x = self.x + dt * v
        if check and far.max() > TURN:
            return False
        old_l, old_k, old_tn = ln, self._curve(tan, ln), tn
        self.v, self.x = v, x
        tan, ln = self.lengths()
        self.rate = (ln - old_l) / (old_l * dt)
        limit = np.minimum(1.0, self.strength / e_mod)  # past it the plastic gives
        self.es = np.clip(soft * (self.es + (ln - old_l) / old_l), -limit, limit)
        self.tens = np.minimum(tens, limit * e_mod * area)
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
        self._grow()
        return True

    def _grow(self):
        """Cut an edge that has been drawn long."""
        ln = self.lengths()[1]
        cut = ln > 1.5 * SEG
        at = np.flatnonzero(cut)
        if not len(at):
            return
        i = at + 1
        for k in ("x", "v", "eb"):
            q = getattr(self, k)
            setattr(self, k, np.insert(q, i, (q[at] + q[at + 1]) / 2, 0))
        self.t = np.insert(self.t, i, (self.t[at] + self.t[at + 1]) / 2)
        self.fixed = np.insert(self.fixed, i, self.fixed[at] & self.fixed[at + 1])
        for k in ("es", "rate", "tens", "e"):
            setattr(self, k, np.insert(getattr(self, k), i, getattr(self, k)[at]))
        self.vol[at] /= 2
        self.vol = np.insert(self.vol, i, self.vol[at])
