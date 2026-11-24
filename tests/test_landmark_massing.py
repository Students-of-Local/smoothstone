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
