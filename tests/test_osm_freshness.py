"""check_osm_cache.py's pure parts (src/O4_OSM_Freshness.py)."""
import os
import time

import pytest

import O4_File_Names as FNAMES
import O4_OSM_Freshness as FRESH
import O4_OSM_Utils as OSM
import O4_Vector_Map as VMAP


def test_parse_tile():
    assert FRESH.parse_tile("+55+012") == (55, 12)
    assert FRESH.parse_tile("-07+072") == (-7, 72)
    assert FRESH.parse_tile("+61-050") == (61, -50)
    assert FRESH.parse_tile("55,12") == (55, 12)
    assert FRESH.parse_tile("-42 174") == (-42, 174)
    for bad in ("", "55", "+95+000", "+10+180", "abc", "+55+012x"):
        assert FRESH.parse_tile(bad) is None, bad


def test_queries_unchanged_by_refactor():
    # The lists include_* used inline before they became constants.
    assert list(VMAP.small_road_queries(2)) == ['way["highway"="tertiary"]']
    assert VMAP.small_road_queries(5) == [
        'way["highway"="tertiary"]',
        'way["highway"="unclassified"]',
        'way["highway"="residential"]',
        'way["highway"="service"]',
        'way["highway"="track"]',
    ]
    assert len(VMAP.BIG_ROAD_QUERIES) == 6
    assert FRESH.layer_statements("airports", 4) == [
        'node["aeroway"]', 'way["aeroway"]', 'rel["aeroway"]'
    ]
    assert FRESH.layer_statements("water", 4)[0] == 'rel["natural"="water"]'
    assert len(FRESH.layer_statements("small_roads", 4)) == 4
    assert FRESH.layer_statements("small_roads", None) == [
        'way["highway"="tertiary"]'
    ]


def test_parse_statement():
    assert FRESH.parse_statement('way["highway"="track"]') == ("w", "highway", "track")
    assert FRESH.parse_statement('node["aeroway"]') == ("n", "aeroway", None)
    assert FRESH.parse_statement('rel["natural"="water"]') == ("r", "natural", "water")
    with pytest.raises(ValueError):
        FRESH.parse_statement('way["a"="b"](if:x)')


OSM_ANSWER = b"""<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6" generator="Overpass API">
<meta osm_base="2026-11-08T15:00:00Z"/>
  <node id="1" lat="10.1" lon="20.1" version="3"/>
  <node id="2" lat="10.2" lon="20.2" version="1"/>
  <node id="3" lat="10.3" lon="20.3" version="1"/>
  <node id="4" lat="10.4" lon="20.4" version="1"/>
  <node id="5" lat="10.5" lon="20.5" version="1"/>
  <way id="100" version="2">
    <nd ref="1"/><nd ref="2"/>
    <tag k="highway" v="service"/>
    <tag k="surface" v="gravel"/>
  </way>
  <way id="101" version="1">
    <nd ref="2"/><nd ref="3"/>
    <tag k="highway" v="tertiary"/>
    <tag k="bridge" v="yes"/>
  </way>
  <way id="102" version="1">
    <nd ref="3"/><nd ref="4"/>
    <tag k="highway" v="service"/>
  </way>
  <way id="103" version="1">
    <nd ref="4"/><nd ref="5"/>
    <tag k="highway" v="footway"/>
  </way>
</osm>
"""


def test_cache_counts_of_a_build_cache(monkeypatch):
    # Write the cache the way a build does, from a stubbed download.
    lat, lon = 10, 20
    os.makedirs(FNAMES.osm_dir(lat, lon), exist_ok=True)
    monkeypatch.setattr(OSM, "get_overpass_data", lambda *a, **k: OSM_ANSWER)
    statements = FRESH.layer_statements("small_roads", 4)
    layer = OSM.OSM_layer()
    assert OSM.OSM_queries_to_OSM_layer(
        VMAP.small_road_queries(4), layer, lat, lon,
        ["bridge", "tunnel"], cached_suffix="small_roads",
    )
    assert FRESH.cached_layers(lat, lon) == [
        ("small_roads", FNAMES.osm_cached(lat, lon, "small_roads"))
    ]
    counts, highways = FRESH.cache_counts(
        FNAMES.osm_cached(lat, lon, "small_roads"), statements
    )
    # The footway is in the answer but not queried: not counted.
    assert counts == {"n": 0, "w": 3, "r": 0}
    assert highways == {"service", "tertiary"}
    assert (lat, lon) in FRESH.cached_tiles()
    assert FRESH.road_level_gaps(4, highways) == ["unclassified", "residential"]


def test_road_level_gaps():
    full = {"tertiary", "unclassified", "residential", "service"}
    assert FRESH.road_level_gaps(4, full) == []
    assert FRESH.road_level_gaps(5, full) == ["track"]
    assert FRESH.road_level_gaps(2, set()) == []
    assert FRESH.road_level_gaps(None, set()) == []


def test_tile_config_wins(tmp_path):
    glob_cfg = tmp_path / "global.cfg"
    glob_cfg.write_text("road_level=4\noverpass_server_choice=DE\n")
    assert FRESH.tile_road_level(30, 40, str(glob_cfg)) == 4
    tile_dir = FNAMES.build_dir(30, 40, "")
    os.makedirs(tile_dir, exist_ok=True)
    with open(os.path.join(tile_dir, "Ortho4XP_+30+040.cfg"), "w") as f:
        f.write("min_angle=10\nroad_level=5\n")
    assert FRESH.tile_road_level(30, 40, str(glob_cfg)) == 5
    assert FRESH.read_config_value(str(glob_cfg), "overpass_server_choice") == "DE"
    assert FRESH.read_config_value(str(tmp_path / "missing.cfg"), "x") is None
    glob_cfg.write_text("road_level=many\n")
    assert FRESH.read_road_level(str(glob_cfg)) is None


def test_since_date(tmp_path):
    f = tmp_path / "x.osm.bz2"
    f.write_bytes(b"")
    t = 1_780_000_000  # 2026-05-28T20:26:40Z
    os.utime(f, (t, t))
    assert FRESH.since_date(str(f), 0) == "2026-05-28T20:26:40Z"
    assert FRESH.since_date(str(f), 3600) == "2026-05-28T19:26:40Z"
    assert time.strptime(FRESH.since_date(str(f)), "%Y-%m-%dT%H:%M:%SZ")


def test_count_query():
    q = FRESH.count_query(
        ['way["natural"="water"]', 'rel["natural"="water"]'],
        (55, 12, 56, 13), "2026-10-01T00:00:00Z",
    )
    assert q == (
        '[out:xml][timeout:300];'
        '(way["natural"="water"](55, 12, 56, 13);'
        'rel["natural"="water"](55, 12, 56, 13);)->.m;'
        '.m out count;(.m;>>;)->.a;'
        'nwr.a(newer:"2026-10-01T00:00:00Z");out count;'
    )


def _count(n, w, r):
    return (f'  <count id="0">\n    <tag k="nodes" v="{n}"/>\n'
            f'    <tag k="ways" v="{w}"/>\n    <tag k="relations" v="{r}"/>\n'
            f'    <tag k="total" v="{n + w + r}"/>\n  </count>\n')


HEAD = ('<?xml version="1.0" encoding="UTF-8"?>\n<osm version="0.6">\n'
        '<meta osm_base="2026-11-08T15:28:44Z"/>\n')


def test_parse_count_answer():
    answer = (HEAD + _count(0, 1234, 5) + _count(681, 63, 4) + "\n</osm>\n").encode()
    assert FRESH.parse_count_answer(answer) == (
        "2026-11-08T15:28:44Z",
        {"n": 0, "w": 1234, "r": 5},
        {"n": 681, "w": 63, "r": 4},
    )


@pytest.mark.parametrize("answer", [
    # Overpass reports a timeout with HTTP 200 and a remark.
    HEAD + '<remark> runtime error: Query timed out in "query" </remark>\n</osm>\n',
    HEAD + _count(0, 1, 0),  # cut
    HEAD + _count(0, 1, 0) + "</osm>\n",  # one count only
    HEAD + _count(0, 1, 0).replace('<tag k="ways" v="1"/>', "")
    + _count(0, 0, 0) + "</osm>\n",
])
def test_parse_count_answer_rejects(answer):
    with pytest.raises(ValueError):
        FRESH.parse_count_answer(answer.encode())


def test_layer_verdict():
    same = {"n": 0, "w": 10, "r": 2}
    zero = {"n": 0, "w": 0, "r": 0}
    assert FRESH.layer_verdict(same, same, zero) == (False, "unchanged")
    # A deleted way that newer: cannot see: the count shrinks.
    changed, text = FRESH.layer_verdict(same, {"n": 0, "w": 9, "r": 2}, zero)
    assert changed and text == "ways 10 -> 9"
    changed, text = FRESH.layer_verdict(same, same, {"n": 3, "w": 1, "r": 0})
    assert changed and text.startswith("4 edited/new (nodes 3, ways 1")


def test_check_server_date(tmp_path):
    f = tmp_path / "x.osm.bz2"
    f.write_bytes(b"")
    t = 1_780_000_000  # 2026-05-28T20:26:40Z
    os.utime(f, (t, t))
    FRESH.check_server_date("2026-05-28T20:26:40Z", str(f))
    FRESH.check_server_date("2026-11-11T05:10:00Z", str(f))
    # A lagging server (FR was a month behind) cannot see newer edits.
    with pytest.raises(ValueError, match="older than the cache"):
        FRESH.check_server_date("2026-05-28T20:26:39Z", str(f))
    with pytest.raises(ValueError):
        FRESH.check_server_date("", str(f))
