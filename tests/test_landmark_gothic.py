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


def test_west_piers_take_their_surveyed_widths_and_follow_the_facade():
    from smoothstone.landmark_style import _surveyed_west_facade

    facts = {"west_facade_profile": {"value": [[-.5, .5], [0, .9], [.5, .5]]},
             "west_buttress_spires": {"value": [[-.45, .7], [-.28, .8], [.28, .8], [.45, .7]]},
             "west_buttress_widths": {"value": [.10, .05, .05, .10]}, "spire_plan": {}}
    angle = np.radians(30)
    along = np.array([np.cos(angle), np.sin(angle)])
    across = np.array([-along[1], along[0]])
    block = m3.CrossSection([[(p * along + q * across).tolist() for p, q in
                              ((0, -43), (40, -43), (40, 43), (0, 43))]]).extrude(60)
    solid = _surveyed_west_facade(block, 86., 60., 0., 0., along, across, facts, [], [])
    # 1.6 mm in front of the wall, above the jambs' feet, only the piers are cut.
    strip = m3.CrossSection([[(p * along + q * across).tolist() for p, q in
                              ((-1.7, -50), (-1.6, -50), (-1.6, 50), (-1.7, 50))]])
    runs = []
    for piece in (solid.slice(26.) ^ strip).decompose():
        ends = np.concatenate(piece.to_polygons()) @ across
        runs.append((float(ends.mean()), float(np.ptp(ends))))
    middles, widths = zip(*sorted(runs))
    assert np.allclose(middles, [-38.7, -24.1, 24.1, 38.7], atol=.4)
    assert widths[0] > 1.8 * widths[1] and widths[3] > 1.8 * widths[2]
    assert .80 * 8.6 < widths[0] < 8.7


def test_a_taper_far_from_the_origin_stands_straight():
    from smoothstone.landmark_style import _tapered

    post = _tapered(m3.CrossSection.square([4., 4.], True), [150., -90.], 40., .5, 2.)
    x0, y0, _, x1, y1, _ = post.trim_by_plane((0, 0, 1), 41.5).bounding_box()
    assert np.allclose([(x0 + x1) / 2, (y0 + y1) / 2], [150, -90], atol=.01)
