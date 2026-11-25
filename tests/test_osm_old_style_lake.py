"""#145: a lake mapped as an old-style multipolygon (the outer way carries
natural=water too) kept its islands as water."""
import O4_OSM_Utils as OSM
import O4_UI_Utils as UI
import O4_Vector_Map as VMAP

# Lake 0.02 x 0.02 deg (nodes -1..-4) with an island (-5..-8). Way -20 is
# the outer ring, tagged natural=water itself; way -21 the island.
LAKE = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="Ortho4XP">
  <node id="-1" lat="64.50" lon="-51.50" version="1"/>
  <node id="-2" lat="64.50" lon="-51.48" version="1"/>
  <node id="-3" lat="64.52" lon="-51.48" version="1"/>
  <node id="-4" lat="64.52" lon="-51.50" version="1"/>
  <node id="-5" lat="64.505" lon="-51.495" version="1"/>
  <node id="-6" lat="64.505" lon="-51.485" version="1"/>
  <node id="-7" lat="64.515" lon="-51.485" version="1"/>
  <node id="-8" lat="64.515" lon="-51.495" version="1"/>
  <way id="-20" version="1">
    <nd ref="-1"/>
    <nd ref="-2"/>
    <nd ref="-3"/>
    <nd ref="-4"/>
    <nd ref="-1"/>
    <tag k="natural" v="water"/>
  </way>
  <way id="-21" version="1">
    <nd ref="-5"/>
    <nd ref="-6"/>
    <nd ref="-7"/>
    <nd ref="-8"/>
    <nd ref="-5"/>
  </way>
  <relation id="-10" version="1">
    <member type="way" ref="-20" role="outer"/>
    <member type="way" ref="-21" role="inner"/>
    <tag k="type" v="multipolygon"/>
    <tag k="natural" v="water"/>
  </relation>
  %s
</osm>
"""

# A pond elsewhere, a plain tagged way: must stay.
POND = """<node id="-30" lat="64.60" lon="-51.60" version="1"/>
  <node id="-31" lat="64.60" lon="-51.59" version="1"/>
  <node id="-32" lat="64.61" lon="-51.59" version="1"/>
  <way id="-40" version="1">
    <nd ref="-30"/>
    <nd ref="-31"/>
    <nd ref="-32"/>
    <nd ref="-30"/>
    <tag k="natural" v="water"/>
  </way>"""


def layer_of(tmp_path, text):
    path = tmp_path / "water.osm"
    path.write_text(text, encoding="utf-8")
    layer = OSM.OSM_layer()
    (input_tags, target_tags) = OSM.layer_tags(VMAP.WATER_QUERIES, ["name"])
    assert layer.update_dicosm(str(path), input_tags, target_tags)
    return layer


def test_island_stays_land(tmp_path, monkeypatch):
    monkeypatch.setattr(UI, "lvprint", lambda *a: None)
    layer = layer_of(tmp_path, LAKE % "")
    assert len(layer.dicosmfirst["w"]) == 1 and len(layer.dicosmfirst["r"]) == 1
    area = OSM.OSM_to_MultiPolygon(layer, 64, -52)
    assert len(area.geoms) == 1
    (lake,) = area.geoms
    assert len(lake.interiors) == 1
    assert abs(lake.area - (0.02 ** 2 - 0.01 ** 2)) < 1e-9


def test_other_ways_kept_and_order_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(UI, "lvprint", lambda *a: None)
    layer = layer_of(tmp_path, LAKE % POND)
    area = OSM.OSM_to_MultiPolygon(layer, 64, -52)
    # ways first, then relations, as before
    assert [len(p.interiors) for p in area.geoms] == [0, 1]
    assert abs(area.geoms[0].area - 0.01 * 0.01 / 2) < 1e-9


def test_filter_sees_both_kinds(tmp_path, monkeypatch):
    monkeypatch.setattr(UI, "lvprint", lambda *a: None)
    layer = layer_of(tmp_path, LAKE % POND)
    big = lambda pol, osmid, tags: pol.area > 1e-4
    (water, sea_equiv) = OSM.OSM_to_MultiPolygon(layer, 64, -52, big)
    assert len(water.geoms) == 1 and len(sea_equiv.geoms) == 1
    assert len(sea_equiv.geoms[0].interiors) == 1
