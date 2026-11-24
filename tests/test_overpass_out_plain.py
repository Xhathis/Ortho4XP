"""Overpass is asked with plain "out" (no meta): the cache is the same."""
import bz2

import O4_OSM_Utils as OSM
import O4_UI_Utils as UI
import O4_Vector_Map as VMAP

PLAIN = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="Overpass API">
<meta osm_base="2026-11-24T09:21:50Z"/>
  <node id="11" lat="55.6100000" lon="12.6400000"/>
  <node id="12" lat="55.6200000" lon="12.6500000"/>
  <node id="13" lat="55.6300000" lon="12.6600000">
    <tag k="aeroway" v="helipad"/>
    <tag k="name" v="O'Hare &quot;H&quot;"/>
  </node>
  <way id="21">
    <nd ref="11"/>
    <nd ref="12"/>
    <tag k="aeroway" v="runway"/>
    <tag k="ref" v="04L/22R"/>
  </way>
  <relation id="31">
    <member type="way" ref="21" role="outer"/>
    <tag k="aeroway" v="aerodrome"/>
    <tag k="type" v="multipolygon"/>
  </relation>
</osm>
"""
META = (PLAIN
        .replace('lon="12.6400000"/>', 'lon="12.6400000" version="3" '
                 'timestamp="2020-01-02T03:04:05Z" changeset="9" uid="7" '
                 'user="a lat= b"/>')
        .replace('lon="12.6600000">', 'lon="12.6600000" version="1" '
                 'timestamp="2021-01-01T00:00:00Z" changeset="8" uid="6" '
                 "user=\"O'Brien\">")
        .replace('<way id="21">', '<way id="21" version="5" '
                 'timestamp="2022-01-01T00:00:00Z" changeset="4" uid="3" '
                 'user="x">')
        .replace('<relation id="31">', '<relation id="31" version="2" '
                 'timestamp="2023-01-01T00:00:00Z" changeset="2" uid="1" '
                 'user="y">'))


def _cache(tmp_path, answer, name):
    layer = OSM.OSM_layer()
    layer.update_dicosm(answer.encode("utf-8"),
                        *OSM.layer_tags(VMAP.AIRPORT_QUERIES[0], ["all"]))
    path = str(tmp_path / name)
    layer.write_to_file(path)
    with bz2.open(path) as f:
        return f.read()


def test_meta_attributes_do_not_reach_the_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(UI, "vprint", lambda *a: None)
    assert META != PLAIN
    plain = _cache(tmp_path, PLAIN, "plain.osm.bz2")
    assert b"aeroway" in plain and b"helipad" in plain
    assert _cache(tmp_path, META, "meta.osm.bz2") == plain


def test_request_asks_plain_out(monkeypatch):
    asked = []

    def fake_request(session, key, url, timeout):
        asked.append(url)
        return (PLAIN.encode("utf-8"), None, "", 0)

    monkeypatch.setattr(OSM, "overpass_servers", {"DE": "http://de"})
    monkeypatch.setattr(OSM, "overpass_server_choice", "DE")
    monkeypatch.setattr(OSM, "_prefer_ipv4_without_ipv6_route", lambda: None)
    monkeypatch.setattr(OSM, "_overpass_request", fake_request)
    monkeypatch.setattr(OSM, "_record_server", lambda *a, **k: None)
    monkeypatch.setattr(OSM, "_skipped_servers", lambda: {})
    monkeypatch.setattr(OSM, "_acquire_overpass_slot", lambda: 0,
                        raising=False)
    monkeypatch.setattr(OSM, "_release_overpass_slot", lambda *a: None,
                        raising=False)
    monkeypatch.setattr(UI, "vprint", lambda *a: None)
    monkeypatch.setattr(UI, "red_flag", False)
    assert OSM.get_overpass_data('way["aeroway"]', (55, 12, 56, 13))
    assert asked and asked[0].endswith(");(._;>>;);out;")
    assert "out meta" not in asked[0]
