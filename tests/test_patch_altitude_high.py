"""altitude_high patch polygons must be closed in both coordinates."""
import types

import numpy
import pytest

import O4_File_Names as FNAMES
import O4_UI_Utils as UI
import O4_Vector_Map as VMAP
import O4_Vector_Utils as VECT


def _patch(last_lat):
    return f"""<?xml version='1.0' encoding='UTF-8'?>
<osm version='0.6' generator='JOSM'>
  <node id='-1' lat='55.50' lon='12.50' />
  <node id='-2' lat='55.50' lon='12.51' />
  <node id='-3' lat='55.51' lon='12.51' />
  <node id='-4' lat='55.51' lon='12.50' />
  <node id='-6' lat='{last_lat}' lon='12.50' />
  <way id='-5'>
    <nd ref='-1' />
    <nd ref='-2' />
    <nd ref='-3' />
    <nd ref='-4' />
    <nd ref='-6' />
    <tag k='altitude_high' v='20' />
    <tag k='altitude_low' v='10' />
  </way>
</osm>
"""


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(FNAMES, "patch_dir", lambda lat, lon: str(tmp_path))
    said = []
    monkeypatch.setattr(UI, "vprint", lambda level, *a: said.append(
        " ".join(str(x) for x in a)))
    monkeypatch.setattr(UI, "lvprint", lambda level, *a: None)
    VECT.scalx = 0.57
    dem = types.SimpleNamespace(alt_vec=lambda way: numpy.zeros(len(way)))
    tile = types.SimpleNamespace(lat=55, lon=12, dem=dem)
    return tmp_path, tile, said


def test_way_open_in_latitude_only_is_skipped(setup):
    # Last node has the first node's longitude but another latitude: the
    # old test ((way[0] != way[-1]).all()) took it for closed.
    folder, tile, said = setup
    (folder / "ramp.patch.osm").write_text(_patch("55.52"))
    VMAP.include_patches(VECT.Vector_Map(), tile)
    assert any("non closed way" in line for line in said)
