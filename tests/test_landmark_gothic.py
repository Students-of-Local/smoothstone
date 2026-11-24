"""Regression checks for open, self-supporting Gothic details."""
import manifold3d as m3
import numpy as np
import pytest

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


def test_west_piers_stand_on_the_bed_where_the_plinth_follows_the_plan():
    from smoothstone.landmark_style import WEST_PIER_REACH, _surveyed_west_facade

    facts = {"west_facade_profile": {"value": [[-.5, .5], [0, .9], [.5, .5]]},
             "west_buttress_spires": {"value": [[-.45, .7], [-.28, .8], [.28, .8], [.45, .7]]},
             "west_buttress_widths": {"value": [.10, .05, .05, .10]}, "spire_plan": {}}
    along, across = np.array([1., 0.]), np.array([0., 1.])
    block = m3.CrossSection([[(0, -43), (40, -43), (40, 43), (0, 43)]]).extrude(60)
    solid = _surveyed_west_facade(block, 86., 60., .2, 0., along, across, facts, [], [])
    ahead = m3.CrossSection([[(-9, -60), (-.02, -60), (-.02, 60), (-9, 60)]])
    foot = solid.slice(.2) ^ ahead
    for z in (1., 2., 2.3, 2.7, 3.5):
        assert ((solid.slice(z) ^ ahead) - foot.offset(.01)).area() < .05, z
    assert np.isclose(-solid.bounding_box()[0], WEST_PIER_REACH, atol=.02)


def test_the_print_size_leaves_room_for_the_west_piers():
    from smoothstone.landmark import _scale

    plan = m3.CrossSection([[(0, 0), (100, 0), (100, 40), (0, 40)]])
    records = [{"height": {"metres": 50.}}]
    long = _scale([plan], records, {"mode": "long", "mm": 200.}, 2.55)
    assert 199.9 < long * 100 + 2.55 <= 200
    fit = _scale([plan], records, {"mode": "fit", "bed": [100., 200., 300.]}, 2.55)
    assert fit * 100 + 2.55 <= 196


def _record(name, top, **more):
    from smoothstone.landmark import _fact

    return {"id": name, "height": _fact(top, "s"), "min_height": _fact(0, "s"), "roof_height": _fact(0, "s"),
            "roof_shape": "flat", "spire": False, "tags": {}, "source": "s", **more}


def _square(width, x=0.):
    return m3.CrossSection.square([width, width], True).translate([x, 0])


def test_a_mughal_building_with_no_pack_keeps_its_iwans():
    from smoothstone.landmark_style import decorate

    plan = _square(60.)
    block = plan.extrude(42)
    out, notes = decorate(block, [_record("body", 40., main_faces=True)], [plan], 1., ["Mughal architecture"])
    assert out.volume() < block.volume() - 100, notes


def test_a_small_iwan_keeps_its_arch_when_only_the_frame_is_too_thin():
    from smoothstone.landmark_style import _iwans

    plan = _square(40.)
    notes = []
    cuts, frames = _iwans(plan.extrude(42), plan, 2., 30., {}, notes)
    assert len(cuts) >= 4 and not frames
    assert any("frames" in note for note in notes)


@pytest.mark.parametrize("style", ["Romanesque architecture", "Baroque architecture"])
def test_a_bell_tower_outside_the_gothic_kit_keeps_its_windows(style):
    from smoothstone.landmark_style import decorate

    plan = _square(20.)
    block = plan.extrude(62)
    out, notes = decorate(block, [_record("campanile", 60., feature="bell_tower")], [plan], 1., [style])
    assert out.volume() < block.volume() - 5, notes


def test_the_window_kit_leaves_a_flying_buttress_alone():
    from smoothstone.landmark import _union
    from smoothstone.landmark_style import decorate

    plan = m3.CrossSection.square([14., .5], True)
    solid = _union([*flying_buttress(plan, {"tags": {"roof:direction": "270"}}, 2., 20., 37., []),
                    plan.offset(1.).extrude(2.02)])
    out, _ = decorate(solid, [_record("flyer", 35., flying_buttress=True, roof_height={"metres": 17.})], [plan], 1.,
                      ["Gothic architecture"])
    assert abs(out.volume() - solid.volume()) < .01


def test_a_taper_far_from_the_origin_stands_straight():
    from smoothstone.landmark_style import _tapered

    post = _tapered(m3.CrossSection.square([4., 4.], True), [150., -90.], 40., .5, 2.)
    x0, y0, _, x1, y1, _ = post.trim_by_plane((0, 0, 1), 41.5).bounding_box()
    assert np.allclose([(x0 + x1) / 2, (y0 + y1) / 2], [150, -90], atol=.01)


def test_a_pinnacle_keeps_its_mapped_peak_and_an_estimated_one_says_so():
    from smoothstone import landmark_refs
    from smoothstone.landmark_architecture import reconcile

    facts = landmark_refs.load_pack("Milan Cathedral")
    ring = [[-79., -46.], [79., -46.], [79., 46.], [-79., 46.], [-79., -46.]]
    plan = m3.CrossSection([ring[:-1]])
    pin = next(p for p in facts["spire_plan"]["value"]["pins"] if p[3] != "main")
    base, rise = facts["spire_plan"]["value"]["levels_m"][pin[3]]
    spot = [-79 + 158 * pin[1], -46 + 92 * pin[2]]
    peak = base + rise - 1.5
    records = [_record("body", base), _record("m", 108.5, roof_shape="pyramidal", spire=True),
               _record("p", peak, roof_shape="pyramidal", spire=True)]
    for r, roof in zip(records, (0., 20., 4.)):
        r["roof_height"]["metres"] = roof
    sections = [plan, _square(4.), _square(2.).translate(spot)]
    out, _, _ = reconcile(records, sections, {"outline": [ring], "height": 108.5}, facts, {"gothic"})
    spires = {r["spire_id"]: r for r in out if r.get("spire_id") is not None}
    mapped = spires[pin[0]]
    assert mapped["height"]["metres"] == peak and not mapped["height"]["guessed"]
    estimated = [r for n, r in spires.items() if r is not mapped and r["id"].startswith("terrace")]
    assert len(estimated) > 100 and all(r["height"]["guessed"] for r in estimated)
