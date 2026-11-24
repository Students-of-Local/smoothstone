"""One strand of melt in the air: what plastic does from the nozzle until it sets.

A chain of nodes, each edge holding a fixed volume of plastic, stepped implicitly (no stiffness limit):
- it stretches and bends as a Maxwell solid: modulus E(T), relaxation time 3 eta(T) / E. Hot, it flows like
  a viscous thread (Trouton); cold, it is an elastic rod with whatever curve it set in. It thins as it stretches;
- its weight, the air's drag on the part of the wind square to it (measured on wires: NACA TN 84) and the
  part fan's jet move it; each node cools in the wind it feels (failsim.h_strand);

Inside: meters, kilograms, seconds, newtons. In and out: mm, mm/s, mm3/s, C. A model, not a recording."""

from __future__ import annotations

import math

import numpy as np
from scipy.linalg import solveh_banded

from . import failsim

BIG = 1e7  # kg/s: a node held on a place or a speed
SEG = 1.2e-3  # m between nodes
DT = 1 / 240  # s
TURN = 0.5  # of an edge's length its ends may move against each other in one step


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


def _cross(a, b):
    (ax, ay, az), (bx, by, bz) = a.T, b.T
    return np.stack([ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx], 1)


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
        self.es, self.eb = np.zeros(n - 1), np.zeros((n, 3))  # elastic stretch of edges, elastic curvature of nodes (1/m)
        self.rate, self.tens = np.zeros(n - 1), np.zeros(n - 1)
        self.strength = failsim._props(m.name)[0]["tensile_xy"]["value"] * 1e6  # Pa
        self.e = np.full(n - 1, np.inf)  # Pa, the modulus its elastic strains were kept at
        self.fixed = np.zeros(n, bool)
        self.fixed[list(held)] = True
        self.fan, self.reach = (failsim.fact("fan_air_speed") if fan else 0.0), failsim.fact("fan_reach") * 1e-3
        self.rho, self.turn = m.density * 1000, np.zeros((n, 3))

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
            keep = np.minimum(1.0, self.e / e_mod)
            self.es *= keep
            self.eb[1:-1] *= np.minimum(keep[1:], keep[:-1])[:, None]
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
            near = np.hypot(*(self.x[:, :2] - np.asarray(head[:2]) * 1e-3).T) < self.reach
            wind[near, 2] = -self.fan
        rel = wind - self.v
        rel -= (rel * tn).sum(1, keepdims=True) * tn
        speed = _norm(rel)
        dn = self._nodes(d * ln) / np.maximum(self._nodes(ln), 1e-12)
        p = failsim.air((self.t + self.air) / 2)
        cd = drag_coefficient(speed * dn / p["nu"])
        drag = 0.5 * p["rho"] * cd * dn * self._nodes(ln) * speed
        # banded symmetric matrix: ab[6 - k, j] is (j - k, j)
        ab = np.zeros((7, 3 * n))
        rhs = (mass / dt)[:, None] * self.v
        rhs[:, 2] -= mass * failsim.fact("gravity")
        rhs += drag[:, None] * (wind - (wind * tn).sum(1, keepdims=True) * tn)
        eye = np.eye(3)
        block = (mass / dt)[:, None, None] * eye + drag[:, None, None] * (eye - tn[:, :, None] * tn[:, None, :])
        off = np.zeros((n - 1, 3, 3))
        tt = tan[:, :, None] * tan[:, None, :]
        stiff = dt * ks[:, None, None] * tt + (dt * np.maximum(self.tens, 0) / ln)[:, None, None] * (eye - tt)
        block[:-1] += stiff
        block[1:] += stiff
        off -= stiff
        pull = (ks * self.es * ln)[:, None] * tan
        rhs[:-1] += pull
        rhs[1:] -= pull
        curve = self._curve(tan, ln)
        if n > 2:
            lb = (ln[1:] + ln[:-1]) / 2
            a, c = 1 / (ln[:-1] * lb), 1 / (ln[1:] * lb)
            b = -(a + c)
            inertia = math.pi * ((d[1:] + d[:-1]) / 2) ** 4 / 64
            s2 = np.minimum(soft[1:], soft[:-1])
            kb = (e_mod[1:] + e_mod[:-1]) / 2 * inertia * s2 * lb
            part = self.eb[1:-1] - dt * _cross(self.turn[1:-1], curve[1:-1])  # the part that only turns with the strand
            mom = kb[:, None] * part
            rhs[:-2] -= a[:, None] * mom
            rhs[1:-1] -= b[:, None] * mom
            rhs[2:] -= c[:, None] * mom
            kd = kb * dt
            for k in range(3):
                block[:-2, k, k] += kd * a * a
                block[1:-1, k, k] += kd * b * b
                block[2:, k, k] += kd * c * c
                off[:-1, k, k] += kd * a * b
                off[1:, k, k] += kd * b * c
                ab[0, 6 + k::3][:n - 2] = kd * a * c
        for i in range(3):
            for j in range(i, 3):
                ab[6 - (j - i), j::3] = block[:, i, j]
        for i in range(3):
            for j in range(3):
                ab[6 - (3 + j - i), 3 + j::3] = off[:, i, j]
        ab[6] += np.repeat(np.where(self.fixed, BIG, 0.0), 3)
        v = solveh_banded(ab, rhs.ravel(), check_finite=False).reshape(n, 3)
        x = self.x + dt * v
        if check and n > 3 and (_norm(np.diff(dt * v, axis=0)) / ln).max() > TURN:
            return False
        old_l, old_k, old_tn = ln, curve, tn
        self.v, self.x = v, x
        tan, ln = self.lengths()
        self.rate = (ln - old_l) / (old_l * dt)
        limit = np.minimum(1.0, self.strength / e_mod)  # past it the plastic gives
        self.es = np.clip(soft * (self.es + (ln - old_l) / old_l), -limit, limit)
        self.tens = e_mod * area * self.es
        tn = np.zeros_like(x)
        tn[:-1] += tan
        tn[1:] += tan
        tn = _unit(tn)
        w = _cross(old_tn, tn)  # carry the curvature along as the strand turns
        rot = lambda q: q + _cross(w, q) + _cross(w, _cross(w, q)) / (1 + (old_tn * tn).sum(1))[:, None].clip(0.1)  # noqa: E731
        sn = np.ones(n)
        sn[1:-1] = np.minimum(soft[1:], soft[:-1])
        self.eb = sn[:, None] * (rot(self.eb) + self._curve(tan, ln) - rot(old_k))
        most = np.full(n, np.inf)
        most[1:-1] = 2 * np.minimum(limit[1:], limit[:-1]) / np.maximum(d[1:], d[:-1])  # 1/m, where its skin gives
        self.eb *= np.minimum(1.0, most / np.maximum(_norm(self.eb), 1e-9))[:, None]
        self.turn = w / dt
        h = failsim.h_strand(dn * 1e3, self.t, self.air, speed)
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
        for k in ("x", "v", "turn"):
            q = getattr(self, k)
            setattr(self, k, np.insert(q, i, (q[at] + q[at + 1]) / 2, 0))
        self.t = np.insert(self.t, i, (self.t[at] + self.t[at + 1]) / 2)
        self.eb = np.insert(self.eb, i, 0.0, 0)
        self.fixed = np.insert(self.fixed, i, self.fixed[at] & self.fixed[at + 1])
        for k in ("es", "rate", "tens", "e"):
            setattr(self, k, np.insert(getattr(self, k), i, getattr(self, k)[at]))
        self.vol[at] /= 2
        self.vol = np.insert(self.vol, i, self.vol[at])
