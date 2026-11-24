"""Massing read from mapped parts when a landmark has no reference pack."""
import manifold3d as m3
import numpy as np
import pytest

from smoothstone import landmark_massing


def _half(identifier, y0, y1, height=45.0):
    section = m3.CrossSection([[[0.0, y0], [80.0, y0], [80.0, y1], [0.0, y1]]])
    part = {"id": identifier, "source": "https://www.openstreetmap.org/way/1", "roof_shape": "gabled",
            "height": {"metres": height, "guessed": False}, "min_height": {"metres": 0.0},
            "roof_height": {"metres": 7.4}, "spire": False}
    return part, section


FRAME = np.eye(2)
CENTER = np.array([40.0, 0.0])


def test_a_nave_mapped_as_two_gabled_halves_gets_one_ridge():
    notes = []
    parts = [_half(1, -13.5, -.05), _half(2, .05, 13.5)]
    merged = landmark_massing._merge_split_nave(parts, FRAME, CENTER, notes)
    assert len(merged) == 1
    part, section = merged[0]
    assert part["merged_parts"] == [1, 2] and part["height"]["metres"] == 45
    assert part["roof_height"]["guessed"] and part["roof_height"]["metres"] == 7.4
    assert section.area() == pytest.approx(27 * 80, rel=.01)
    assert notes


@pytest.mark.parametrize("parts", [
    [_half(1, -13.5, -.05), _half(2, .05, 13.5, height=38.0)],   # different heights
    [_half(1, 4.0, 17.5), _half(2, 17.5, 31.0)],                 # both on one side of the axis
    [_half(1, -20.0, -6.0), _half(2, 6.0, 20.0)],                # a gap between them
])
def test_other_gabled_pairs_keep_their_own_roofs(parts):
    notes = []
    assert landmark_massing._merge_split_nave(parts, FRAME, CENTER, notes) == parts
    assert not notes


def test_only_a_church_has_a_nave_to_join():
    assert landmark_massing._is_church({"tags": {"building": "cathedral"}}, {})
    assert landmark_massing._is_church({}, {"label": "Florence Cathedral"})
    assert not landmark_massing._is_church({"tags": {"building": "warehouse"}}, {"label": "Albert Dock"})


def test_low_walls_fill_only_the_unmapped_plan():
    """A chapel mapped at 10 m keeps its height beside an apse nobody mapped."""
    def box(x0, y0, x1, y1):
        return m3.CrossSection([[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]])

    def part(identifier, top):
        return {"id": identifier, "source": "s", "roof_shape": "flat", "spire": False, "tags": {},
                "height": {"metres": top, "guessed": False}, "min_height": {"metres": 0.}, "roof_height": {"metres": 0.}}

    outline = box(0, 0, 100, 40)
    sections = [box(0, 0, 20, 40), box(20, 0, 80, 20), box(20, 20.02, 80, 40)]
    records, plans, _, _ = landmark_massing.infer_massing(
        [part(1, 60.), part(2, 45.), part(3, 10.)], sections, outline,
        {"tags": {"height": "30"}, "source": "s"}, {}, {"mode": "max", "mm": 200.}, set())
    (low, plan), = [(r, p) for r, p in zip(records, plans) if r["feature" if "feature" in r else "id"] == "lower_walls"]
    assert low["height"]["metres"] == 30
    assert (plan ^ sections[2]).area() < 8
    assert (box(80, 0, 100, 40) - plan).area() < 1


def _box(x0, y0, x1, y1):
    return m3.CrossSection([[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]])


def _mapped(identifier, top, base=0.):
    return {"id": identifier, "source": "s", "roof_shape": "flat", "spire": False, "tags": {},
            "height": {"metres": top, "guessed": False}, "min_height": {"metres": base}, "roof_height": {"metres": 0.}}


def test_a_low_part_mapped_off_the_ground_is_not_buried_in_the_walls():
    """An apse mapped from 8 to 12 m keeps its 12 m roof, on wall only up to its own base."""
    outline = _box(0, 0, 100, 40)
    apse = _box(60, 5, 80, 35)
    sections = [_box(0, 0, 60, 40), apse]
    records, plans, _, _ = landmark_massing.infer_massing(
        [_mapped(1, 60.), _mapped(2, 12., 8.)], sections, outline,
        {"tags": {"height": "30"}, "source": "s"}, {}, {"mode": "max", "mm": 200.}, set())
    walls = {r["height"]["metres"]: plan for r, plan in zip(records, plans) if r.get("feature") == "lower_walls"}
    assert set(walls) == {8., 30.}
    assert (walls[30.] ^ apse).area() < 8
    assert (apse - walls[8.]).area() < 1


def _tower_pair(x, top, first):
    return [(_mapped(first + i, top), _box(x - 4, y - 4, x + 4, y + 4)) for i, y in enumerate((-12, 12))]


def test_west_towers_are_at_the_west_end():
    """A taller pair beside the choir is not the west front, whichever way the long axis points."""
    spans, center = np.array([100., 40.]), np.zeros(2)
    west, east = _tower_pair(-44, 70., 1), _tower_pair(44, 75., 3)
    for frame in (np.eye(2), -np.eye(2)):
        both = [*west, *east]
        for part, _ in both:
            part.pop("feature", None)
        assert landmark_massing._west_towers(both, frame, center, spans, 75.) @ [1, 0] == pytest.approx(-1)
        assert [part.get("feature") for part, _ in both] == ["west_tower"] * 2 + [None] * 2
        assert landmark_massing._west_towers(east, frame, center, spans, 75.) is None


def test_a_north_south_church_takes_its_tower_pair_at_either_end():
    frame, spans = np.array([[0., 1.], [-1., 0.]]), np.array([100., 40.])
    for end in (-44, 44):
        pair = [(_mapped(i, 70.), _box(x - 4, end - 4, x + 4, end + 4)) for i, x in enumerate((-12, 12))]
        facing = landmark_massing._west_towers(pair, frame, np.zeros(2), spans, 70.)
        assert facing @ [0, np.sign(end)] == pytest.approx(1)
