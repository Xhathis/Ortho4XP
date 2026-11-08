"""#63: OSM files read without target tags (extents, custom water and
coastline, patches) where two relations share a way."""
import O4_OSM_Utils as OSM
import O4_UI_Utils as UI

# Two lakes side by side: relation -10 is the square (-1..-4), relation -11
# the square next to it (-2, -5, -6, -3); way -21 (-2 -> -3) is in both.
OSM_TEXT = """<?xml version='1.0' encoding='UTF-8'?>
<osm version='0.6' generator='JOSM'>
  <node id='-1' lat='55.50' lon='12.50' />
  <node id='-2' lat='55.50' lon='12.51' />
  <node id='-3' lat='55.51' lon='12.51' />
  <node id='-4' lat='55.51' lon='12.50' />
  <node id='-5' lat='55.50' lon='12.52' />
  <node id='-6' lat='55.51' lon='12.52' />
  <way id='-20'>
    <nd ref='-3' />
    <nd ref='-4' />
    <nd ref='-1' />
    <nd ref='-2' />
  </way>
  <way id='-21'>
    <nd ref='-2' />
    <nd ref='-3' />
  </way>
  <way id='-22'>
    <nd ref='-2' />
    <nd ref='-5' />
    <nd ref='-6' />
    <nd ref='-3' />
  </way>
  <relation id='-10'>
    <member type='way' ref='-20' role='outer' />
    <member type='way' ref='-21' role='outer' />
    <tag k='type' v='multipolygon' />
    <tag k='natural' v='water' />
  </relation>
  <relation id='-11'>
    <member type='way' ref='-22' role='outer' />
    <member type='way' ref='-21' role='outer' />
    <tag k='type' v='multipolygon' />
    <tag k='natural' v='water' />
  </relation>
</osm>
"""


def test_shared_way_is_read(tmp_path, monkeypatch):
    monkeypatch.setattr(UI, "lvprint", lambda *a: None)
    path = tmp_path / "two_lakes.osm"
    path.write_text(OSM_TEXT)
    layer = OSM.OSM_layer()
    assert layer.update_dicosm(str(path), None)
    assert len(layer.dicosmfirst["r"]) == 2
    # The member ways are no longer free-standing ways.
    assert not layer.dicosmfirst["w"]
    area = OSM.OSM_to_MultiPolygon(layer, 55, 12)
    assert len(area.geoms) == 2
