"""fea: voxel finite elements checked against beam theory and a known stress concentration."""

import time

import numpy as np
import pytest
import trimesh

from smoothstone import fea

E, NU, P = 2000.0, 0.35, 100.0  # MPa, -, N


def cantilever(pitch: float, e_z: float = E, build: int = 2):
    """100 x 10 x 10 mm beam along x, the x = 0 end held, P newtons down (-z) spread over the free end."""
    m = trimesh.creation.box(extents=[100, 10, 10])
    m.apply_translation([50, 5, 5])
    g = fea.voxelize(m, pitch)
    mdl = fea.Model(g, np.ones(g.solid.sum()), fea.stiffness(E, e_z, NU, build))
    x = mdl.coords
    fixed = np.nonzero(x[:, 0] <= x[:, 0].min() + 1e-6)[0]
    end = np.nonzero(x[:, 0] >= x[:, 0].max() - 1e-6)[0]
    f = np.zeros_like(x)
    f[end, 2] = -P / len(end)
    t = time.time()
    u, info = mdl.solve(fixed, f)
    info["seconds"] = time.time() - t
    return g, mdl, u, -u[end, 2].mean(), info, fixed


def beam_theory(e: float = E) -> float:
    """Tip deflection PL^3/3EI plus Timoshenko shear PL/(kGA), k = 5/6 for a rectangle."""
    i, g = 10 * 10 ** 3 / 12, e / (2 * (1 + NU))
    return P * 100 ** 3 / (3 * e * i) + P * 100 / (5 / 6 * g * 100)


def away(mdl: fea.Model, nodes: np.ndarray) -> np.ndarray:
    """Cells with no corner on the given nodes."""
    mark = np.zeros(len(mdl.nodes), dtype=bool)
    mark[nodes] = True
    return ~mark[mdl.elem].any(1)


def test_cantilever_tip_deflection_and_root_stress():
    g, mdl, u, tip, info, fixed = cantilever(1.0)
    assert abs(tip / beam_theory() - 1) < 0.10, (tip, beam_theory())
    assert info["residual"] < 1e-6
    s = mdl.stress(u)[:, 0]
    root = 6 * P * 100 / (10 * 10 ** 2)  # 6PL/bh^2 = 60 MPa
    peak = s[away(mdl, fixed)].max()
    assert abs(peak / root - 1) < 0.15, (peak, root)


def test_mesh_refinement_moves_the_tip_under_5_percent():
    coarse, fine = cantilever(1.0)[3], cantilever(0.5)[3]
    assert abs(fine / coarse - 1) < 0.05, (coarse, fine)


def test_plate_with_a_hole_concentrates_stress_about_3_times():
    """80 x 40 x 2 mm plate, 8 mm hole, pulled along x. Peterson's finite-width Kt on gross stress is about 3.1."""
    w, length, t, d = 40.0, 80.0, 2.0, 8.0
    plate = trimesh.creation.box(extents=[length, w, t]).difference(trimesh.creation.cylinder(radius=d / 2, height=3 * t, sections=128))
    plate.apply_translation([length / 2, w / 2, t / 2])
    g = fea.voxelize(plate, 0.5)
    mdl = fea.Model(g, np.ones(g.solid.sum()), fea.stiffness(E, E, NU))
    x = mdl.coords
    left = np.nonzero(x[:, 0] <= x[:, 0].min() + 1e-6)[0]
    right = np.nonzero(x[:, 0] >= x[:, 0].max() - 1e-6)[0]
    f = np.zeros_like(x)
    f[right, 0] = P / len(right)
    u, _ = mdl.solve(left, f)
    kt = mdl.stress(u)[:, 0].max() / (P / (w * t))
    assert 2.4 <= kt <= 3.4, kt


def test_a_beam_printed_standing_up_bends_by_its_weak_stiffness():
    """Layers across the beam (build axis x): bending stretches the weak direction, so the tip goes as E_xy / E_z further."""
    flat = cantilever(1.0, e_z=E / 2)[3]
    standing = cantilever(1.0, e_z=E / 2, build=0)[3]
    assert 1.6 < standing / flat < 2.1, (flat, standing)


def test_stiffness_puts_the_weak_axis_on_the_build_axis():
    for build in range(3):
        c = fea.stiffness(E, E / 2, NU, build)
        s = np.linalg.inv(c)
        assert np.isclose(1 / s[build, build], E / 2)
        assert all(np.isclose(1 / s[i, i], E) for i in range(3) if i != build)
        assert np.allclose(c, c.T)


def test_shell_is_solid_skin_over_infill():
    m = trimesh.creation.box(extents=[20, 20, 20])
    g = fea.voxelize(m, 0.5)
    wall, weight = fea.shell(g, 1.0, 0.15)
    assert np.isclose(wall.max(), 1) and np.isclose(wall.min(), 0)
    assert np.isclose(weight.min(), 0.15 ** 2)
    skin = (wall > 0).sum() / wall.size
    assert abs(skin - (1 - (18 / 20) ** 3)) < 0.03, skin  # 1 mm skin of a 20 mm cube


@pytest.mark.timing
def test_about_200k_voxels_solve_inside_a_minute():
    g, _, _, tip, info, _ = cantilever(10 / 28)  # a whole number of cells across, so the beam keeps its size
    print(f"{g.solid.sum()} voxels, {info['dofs']} unknowns, {info['seconds']:.1f} s ({info})")
    assert 150_000 < g.solid.sum() < 300_000
    assert info["seconds"] < 60
    assert abs(tip / beam_theory() - 1) < 0.10
