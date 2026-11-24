"""Regression checks for open, self-supporting Gothic details."""
import manifold3d as m3
import numpy as np

from smoothstone.landmark import _union
from smoothstone.landmark_gothic import flying_buttress, rose_profile


def test_flying_buttress_preserves_the_opening_under_its_arch():
    section = m3.CrossSection.square([14., .5], True)
    part = {"tags": {"roof:direction": "270"}}
    pier, arch = flying_buttress(section, part, 2., 20., 37., [])

    # The mapped 14 m wedge formerly occupied this part of the gap at 10 mm.
    midspan = m3.CrossSection.square([4., .4], True)
    solid = _union([pier, arch])
    assert (solid.slice(10.) ^ midspan).is_empty()
    assert (solid.slice(27.) ^ midspan).area() > .1
    assert len(solid.decompose()) == 1

    # Query the mesh soffit itself, including every sampled interval in the run.
    mesh = arch.to_mesh()
    vertices = np.asarray(mesh.vert_properties)[:, :3]
    triangles = vertices[mesh.tri_verts]
    normal = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    visible = (np.abs(triangles[:, :, 0]).max(axis=1) <= 7.01) & (normal[:, 2] < -1e-6)
    assert visible.sum() >= 12
    assert np.all(np.abs(normal[visible, 0]) >= -normal[visible, 2] - 1e-5)


def test_scaled_rose_retains_a_round_recess_after_dropping_tracery():
    small, traced = rose_profile(1.6)
    assert not traced
    assert len(small.decompose()) == 1

    regular, traced = rose_profile(8.)
    assert traced
    assert len(regular.decompose()) >= 4
    assert all(not sector.offset(-.4).is_empty() for sector in regular.decompose())
