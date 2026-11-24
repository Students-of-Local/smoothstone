"""Live availability check for landmark reference services."""
import pytest

from smoothstone.landmark_refs import fetch, resolve


@pytest.mark.network
def test_live_cologne_references(tmp_path):
    ref = resolve('Cologne Cathedral', tmp_path)
    result = fetch(ref, tmp_path)
    assert ref['id'] == 'Q4176'
    assert result['outline']
    assert len(result['parts']) > 2
    assert (tmp_path / 'refs' / 'landmark.json').is_file()
    assert (tmp_path / 'refs' / 'overpass.json').is_file()
