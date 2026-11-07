"""#54: a patch file that cannot be read is skipped, not partly applied."""
import types

import numpy
import pytest

import O4_File_Names as FNAMES
import O4_UI_Utils as UI
import O4_Vector_Map as VMAP
import O4_Vector_Utils as VECT

PATCH = """<?xml version='1.0' encoding='UTF-8'?>
<osm version='0.6' generator='JOSM'>
  <node id='-1' lat='55.50' lon='12.50' />
  <node id='-2' lat='55.50' lon='12.51' />
  <node id='-3' lat='55.51' lon='12.51' />
  <node id='-4' lat='55.51' lon='12.50' />
  <way id='-5'>
    <nd ref='-1' />
    <nd ref='-2' />
    <nd ref='-3' />
    <nd ref='-4' />
    <nd ref='-1' />
    <tag k='cst_alt_abs' v='12' />
  </way>
</osm>
"""


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(FNAMES, "patch_dir", lambda lat, lon: str(tmp_path))
    logged = []
    monkeypatch.setattr(UI, "lvprint", lambda level, *a: logged.append(
        " ".join(str(x) for x in a)))
    VECT.scalx = 0.57
    dem = types.SimpleNamespace(alt_vec=lambda way: numpy.zeros(len(way)))
    tile = types.SimpleNamespace(lat=55, lon=12, dem=dem)
    return tmp_path, tile, logged


def test_good_patch_is_applied(setup):
    folder, tile, logged = setup
    (folder / "good.patch.osm").write_text(PATCH)
    vector_map = VECT.Vector_Map()
    (area, names) = VMAP.include_patches(vector_map, tile)
    assert names == ["good"] and area.area > 0
    assert len(vector_map.seeds["INTERP_ALT"]) == 1
    assert logged == []


def test_truncated_patch_is_skipped_entirely(setup):
    folder, tile, logged = setup
    # Cut off after the way: the parser has read it, but there is no </osm>.
    (folder / "cut.patch.osm").write_text(PATCH.split("</osm>")[0])
    vector_map = VECT.Vector_Map()
    (area, names) = VMAP.include_patches(vector_map, tile)
    assert names == [] and area.is_empty
    assert "INTERP_ALT" not in vector_map.seeds
    # update_dicosm logs its own line first ("no ending </OSM> tag").
    assert "WARNING" in logged[-1] and "cut.patch.osm" in logged[-1]
