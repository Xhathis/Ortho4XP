"""OSM layers from local extracts (#100): rules, gaps, the build hook."""
import bz2
import os
from xml.sax.saxutils import escape

import pytest

osmium = pytest.importorskip("osmium")

import O4_File_Names as FNAMES  # noqa: E402
import O4_OSM_Extract as EXTRACT  # noqa: E402
import O4_OSM_Utils as OSM  # noqa: E402
import O4_UI_Utils as UI  # noqa: E402
import O4_Vector_Map as VMAP  # noqa: E402

S = EXTRACT.SCALE
T = (55, 12)


@pytest.fixture
def osm_dir(tmp_path, monkeypatch):
    d = tmp_path / "OSM_data"
    d.mkdir()
    monkeypatch.setattr(FNAMES, "OSM_dir", str(d))
    monkeypatch.setattr(UI, "vprint", lambda *a: None)
    lines = []
    monkeypatch.setattr(UI, "lvprint",
                        lambda level, *a: lines.append(" ".join(map(str, a))))
    monkeypatch.setattr(UI, "red_flag", False)
    return lines


def osm_file(path, nodes, ways=(), rels=()):
    """nodes: (id, lat, lon, {tags}); ways: (id, [refs], {tags});
    rels: (id, [(type, ref, role)], {tags})."""
    def tags(t):
        return "".join(f'<tag k="{k}" v="{escape(v, {chr(34): "&quot;"})}"/>'
                       for (k, v) in t.items())
    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<osm version="0.6">']
    for (i, lat, lon, t) in nodes:
        out.append(f'<node id="{i}" version="1" lat="{lat}" lon="{lon}">'
                   f"{tags(t)}</node>")
    for (i, refs, t) in ways:
        out.append(f'<way id="{i}" version="1">'
                   + "".join(f'<nd ref="{r}"/>' for r in refs)
                   + f"{tags(t)}</way>")
    for (i, members, t) in rels:
        out.append(f'<relation id="{i}" version="1">'
                   + "".join(f'<member type="{ty}" ref="{r}" role="{ro}"/>'
                             for (ty, r, ro) in members)
                   + f"{tags(t)}</relation>")
    out.append("</osm>")
    path.write_text("\n".join(out), encoding="utf-8")
    return str(path)


# --- pure helpers -----------------------------------------------------------
def test_parse_statement():
    assert EXTRACT.parse_statement('way["highway"="motorway"]') == (
        "w", "highway", "motorway")
    assert EXTRACT.parse_statement('node["aeroway"]') == ("n", "aeroway", None)
    assert EXTRACT.parse_statement('rel["natural"="water"]') == (
        "r", "natural", "water")
    with pytest.raises(ValueError):
        EXTRACT.parse_statement('way["highway"~"mot"]')


@pytest.mark.parametrize("road_level, layers", [
    (0, {"coastline", "airports", "water"}),
    (1, {"coastline", "airports", "water", "big_roads"}),
    (5, {"coastline", "airports", "water", "big_roads", "small_roads"}),
])
def test_layer_statements_follow_the_build(road_level, layers):
    got = EXTRACT.layer_statements(road_level)
    assert set(got) == layers
    for statements in got.values():
        for st in statements:
            EXTRACT.parse_statement(st)  # every build query is understood
    if road_level == 5:
        assert got["small_roads"] == tuple(VMAP.small_road_queries(5))
        assert got["airports"] == ('node["aeroway"]', 'way["aeroway"]',
                                   'rel["aeroway"]')


def test_xml_escape_like_overpass():
    assert EXTRACT.xml_escape('A & "B" <c> it\'s\nx') == (
        "A &amp; &quot;B&quot; &lt;c&gt; it's&#x0a;x")


@pytest.mark.parametrize("v, text", [
    (555000000, "55.5000000"), (0, "0.0000000"), (-5, "-0.0000005"),
    (-1223038856, "-122.3038856"), (120000000, "12.0000000"),
])
def test_coord(v, text):
    assert EXTRACT.coord(v) == text
    assert float(text) == v / S


def test_point_tiles_include_edges():
    wanted = {(55, 12), (55, 11), (54, 12), (54, 11)}
    assert EXTRACT.point_tiles(int(12.5 * S), int(55.5 * S), wanted) == {
        (55, 12)}
    assert EXTRACT.point_tiles(12 * S, 55 * S, wanted) == wanted  # corner


def test_way_tiles_segment_crossing_corner():
    wanted = {(55, 12)}
    # Nodes outside the tile, the segment cuts its south-west corner.
    xs, ys = [int(11.9 * S), int(12.2 * S)], [int(55.1 * S), int(54.8 * S)]
    assert EXTRACT.way_tiles(xs, ys, wanted) == wanted
    # Same nodes, segment passing outside.
    xs, ys = [int(11.9 * S), int(12.2 * S)], [int(54.9 * S), int(54.6 * S)]
    assert EXTRACT.way_tiles(xs, ys, wanted) == set()
    assert EXTRACT.way_tiles([], [], wanted) == set()


def box(lon0, lat0, lon1, lat1):
    return {"type": "Polygon", "coordinates": [[
        [lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]]}


def index_file(path, regions):
    import json
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": geom, "properties": {
            "id": rid, "urls": {"pbf": "https://x/" + name}}}
        for (rid, name, geom) in regions]}), encoding="utf-8")
    return str(path)


def test_coverage_gaps(tmp_path):
    # Denmark covers lat 54-56.5 west of lon 12.6; Sweden east of 12.4;
    # nothing (open sea) north of 56.5 on lon 11.
    regions = EXTRACT.read_index(index_file(tmp_path / "i.json", [
        ("denmark", "denmark-latest.osm.pbf", box(8, 54, 12.6, 56.5)),
        ("sweden", "sweden-latest.osm.pbf", box(12.4, 55, 20, 60)),
        ("europe", "europe-latest.osm.pbf", box(-10, 35, 30, 60.0)),
    ]))
    assert [r[0] for r in regions] == ["denmark", "sweden", "europe"]
    dk = regions[0][2]
    gaps = EXTRACT.coverage_gaps([(55, 11), (55, 12), (56, 11)], [dk],
                                 regions[:2])
    # +55+012 reaches into Sweden; +56+011 is Denmark and open sea
    assert gaps == {(55, 12): ["sweden"]}
    # with Europe in the index the sea north of Denmark is a region too;
    # the smallest region that fills a gap comes first
    gaps = EXTRACT.coverage_gaps([(56, 11), (55, 12)], [dk], regions)
    assert gaps == {(56, 11): ["europe"], (55, 12): ["sweden", "europe"]}
    assert EXTRACT.coverage_gaps([(55, 12)], [dk, regions[1][2]],
                                 regions) == {}


# --- extraction ---------------------------------------------------------------
NODES = [
    (1, 55.5, 12.5, {"aeroway": "windsock"}),
    (2, 55.6, 12.6, {"ele": "5"}),
    (3, 56.2, 12.6, {}),           # outside, north
    (4, 55.1, 11.9, {}),           # outside, west
    (5, 54.8, 12.2, {}),           # outside, south
    (6, 55.2, 12.2, {}),
    (7, 55.3, 12.3, {}),
    (8, 57.5, 12.5, {}),           # far outside
    (9, 57.6, 12.5, {}),
    (10, 57.6, 12.6, {"aeroway": "x"}),
    (11, 55.4, 12.4, {"aeroway": "runway_end"}),
]
WAYS = [
    (100, [1, 2, 3], {"highway": "motorway", "name": 'A & "B"'}),
    (101, [4, 5], {"highway": "trunk"}),         # cuts the corner only
    (102, [6, 7], {"highway": "service"}),
    (103, [8, 9, 10], {"highway": "motorway"}),  # far outside
    (110, [6, 7, 2, 6], {}),                     # lake member, in tile
    (111, [8, 9, 8], {}),                        # lake member, far
    (120, [11, 3], {"aeroway": "runway"}),
]
RELS = [
    (200, [("way", 110, "outer"), ("way", 111, "inner")],
     {"natural": "water", "name": "Sø"}),
    (201, [("way", 111, "outer")], {"natural": "water"}),  # far away
]


def wanted(tiles=(T,), road_level=4):
    return {t: EXTRACT.layer_statements(road_level) for t in tiles}


def ids(content, kind):
    import re
    return sorted(int(i) for i in re.findall(
        rf'<{kind} id="(-?\d+)"'.encode(), content))


def test_extract_follows_overpass_rules(tmp_path):
    f = osm_file(tmp_path / "a.osm", NODES, WAYS, RELS)
    (answers, failed) = EXTRACT.extract_answers([f], wanted(), log=lambda *a: 0)
    assert failed == {}
    a = answers[T]
    assert set(a) == {"coastline", "airports", "water", "big_roads",
                      "small_roads"}
    # big roads: the motorway with its outside node, the trunk without any
    # node inside (segment); not the far motorway.
    assert ids(a["big_roads"], "way") == [100, 101]
    assert ids(a["big_roads"], "node") == [1, 2, 3, 4, 5]
    assert b'v="A &amp; &quot;B&quot;"' in a["big_roads"]
    assert ids(a["small_roads"], "way") == [102]
    # water: the lake with its far member way and that way's nodes; not 201
    assert ids(a["water"], "relation") == [200]
    assert ids(a["water"], "way") == [110, 111]
    assert ids(a["water"], "node") == [2, 6, 7, 8, 9]
    assert "Sø".encode() in a["water"]
    # airports: node 1 and 11 inside, runway 120 with its outside node 3;
    # node tags only here (node 2's ele is not in big_roads)
    assert ids(a["airports"], "node") == [1, 3, 11]
    assert ids(a["airports"], "way") == [120]
    assert b'k="aeroway" v="windsock"' in a["airports"]
    assert b'k="ele"' not in a["big_roads"]
    assert ids(a["coastline"], "way") == []
    assert a["coastline"].rstrip().endswith(b"</osm>")


def test_answer_read_as_overpass_gives_same_cache(tmp_path, osm_dir,
                                                  monkeypatch):
    """The whole point: a layer from the extract is cached exactly as if
    Overpass had sent the same answer."""
    f = osm_file(tmp_path / "a.osm", NODES, WAYS, RELS)
    (answers, _) = EXTRACT.extract_answers([f], wanted(), log=lambda *a: 0)
    for (layer, content) in answers[T].items():
        queries = {"water": VMAP.WATER_QUERIES,
                   "big_roads": VMAP.BIG_ROAD_QUERIES,
                   "small_roads": VMAP.small_road_queries(4),
                   "airports": VMAP.AIRPORT_QUERIES,
                   "coastline": VMAP.COASTLINE_QUERIES}[layer]
        toi = {"airports": ["all"], "water": ["name"],
               "big_roads": ["bridge", "tunnel"]}.get(layer, [])
        cache = FNAMES.osm_cached(*T, layer)
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        # 1) as an Overpass download
        monkeypatch.setattr(OSM, "get_overpass_data",
                            lambda *a, **k: content)
        assert OSM.OSM_queries_to_OSM_layer(
            queries, OSM.OSM_layer(), *T, toi, cached_suffix=layer) == 1
        with open(cache, "rb") as c:
            from_overpass = c.read()
        os.remove(cache)
        # 2) from the extract answer, Overpass must not be asked
        EXTRACT.write_answer(EXTRACT.answer_path(*T, layer), content)

        def no_overpass(*a, **k):
            raise AssertionError("Overpass asked")
        monkeypatch.setattr(OSM, "get_overpass_data", no_overpass)
        layer_obj = OSM.OSM_layer()
        assert OSM.OSM_queries_to_OSM_layer(
            queries, layer_obj, *T, toi, cached_suffix=layer) == 1
        with open(cache, "rb") as c:
            assert c.read() == from_overpass, layer
        assert bz2.decompress(from_overpass)  # a real bz2 cache


def test_tile_with_gaps_gets_no_answer(tmp_path):
    # node 9 missing from the file: way 111 (a member of lake 200) and the
    # far motorway are incomplete; the lake reaches into the tile.
    f = osm_file(tmp_path / "a.osm", [n for n in NODES if n[0] != 9],
                 WAYS, RELS)
    (answers, failed) = EXTRACT.extract_answers(
        [f], wanted(), log=lambda *a: 0)
    assert answers == {}
    assert "water: way 111 has nodes outside" in failed[T]
    # a lake member way missing from the file
    f = osm_file(tmp_path / "b.osm", NODES, [w for w in WAYS if w[0] != 111],
                 RELS)
    (answers, failed) = EXTRACT.extract_answers(
        [f], wanted(), log=lambda *a: 0)
    assert "relation 200 lacks member way 111" in failed[T]


def test_two_files_read_as_one(tmp_path):
    # The far lake member lives in another file (a neighbouring extract);
    # objects in both files count once.
    far = {8, 9, 10}
    a = osm_file(tmp_path / "a.osm", [n for n in NODES if n[0] not in far],
                 [w for w in WAYS if w[0] not in (103, 111)], RELS)
    b = osm_file(tmp_path / "b.osm", [n for n in NODES if n[0] in far | {2}],
                 [w for w in WAYS if w[0] in (103, 111)], RELS)
    (answers, failed) = EXTRACT.extract_answers(
        [a, b], wanted(), log=lambda *a: 0)
    assert failed == {}
    (single, _) = EXTRACT.extract_answers(
        [osm_file(tmp_path / "c.osm", NODES, WAYS, RELS)], wanted(),
        log=lambda *a: 0)
    for layer in single[T]:
        strip = (lambda c: c.split(b"\n", 4)[4])  # source line differs
        assert strip(answers[T][layer]) == strip(single[T][layer]), layer


# --- answers on disk and the build hook --------------------------------------
def test_read_answer_checks(tmp_path, osm_dir):
    path = EXTRACT.answer_path(*T, "water")
    st = EXTRACT.flat_statements(VMAP.WATER_QUERIES)
    assert EXTRACT.read_answer(path, st) == (None, "")
    content = EXTRACT.answer_xml(st, "x.pbf", "2026-11-12T00:00:00Z",
                                 {}, {}, {})
    EXTRACT.write_answer(path, content)
    assert EXTRACT.read_answer(path, st) == (content, "x.pbf")
    assert EXTRACT.read_answer(path, st[:2])[1].startswith("made for other")
    with open(path, "wb") as f:
        f.write(b"BZh9 broken")
    assert EXTRACT.read_answer(path, st)[1].startswith("unreadable")
    assert not [n for n in os.listdir(os.path.dirname(path))
                if n.startswith(".tmp")]


def test_mismatched_answer_falls_back_to_overpass(osm_dir, monkeypatch):
    st = EXTRACT.flat_statements(VMAP.small_road_queries(3))
    EXTRACT.write_answer(EXTRACT.answer_path(*T, "small_roads"),
                         EXTRACT.answer_xml(st, "x", "", {}, {}, {}))
    asked = []

    def fake(*a, **k):
        asked.append(a)
        return 0
    fake.last_error, fake.size_failure = "DE: test", False
    monkeypatch.setattr(OSM, "get_overpass_data", fake)
    monkeypatch.setattr(OSM, "overpass_gave_up", False)
    OSM.OSM_queries_to_OSM_layer(VMAP.small_road_queries(4), OSM.OSM_layer(),
                                 *T, [], cached_suffix="small_roads")
    assert asked  # road_level 4 wants service roads too
    assert any("not used: made for other queries" in l for l in osm_dir)


def test_old_extract_noted(osm_dir):
    st = EXTRACT.flat_statements(VMAP.WATER_QUERIES)
    EXTRACT.write_answer(EXTRACT.answer_path(*T, "water"),
                         EXTRACT.answer_xml(st, "x", "2026-01-01T00:00:00Z",
                                            {}, {}, {}))
    assert OSM.OSM_queries_to_OSM_layer(VMAP.WATER_QUERIES, OSM.OSM_layer(),
                                        *T, ["name"], cached_suffix="water")
    assert any("NOTE: OSM water layer of +55+012 has data of 2026-01-01 "
               "from server local extract" in l for l in osm_dir)


def test_gate_counts_answers_as_cached(osm_dir):
    import O4_Tile_Utils as TILE
    gate = TILE._OverpassGate()
    for layer in TILE.OSM_LAYERS[:-1]:
        EXTRACT.write_answer(EXTRACT.answer_path(*T, layer), b"x")
    assert gate.needs_overpass(*T)
    EXTRACT.write_answer(EXTRACT.answer_path(*T, "water"), b"x")
    assert not TILE._OverpassGate().needs_overpass(*T)


# --- the tool ----------------------------------------------------------------
def test_prepare_tool(tmp_path, osm_dir, monkeypatch, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "prepare_osm_extracts",
        os.path.join(os.path.dirname(__file__), "..", "prepare_osm_extracts.py"))
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    monkeypatch.setattr(FNAMES, "Tile_dir", str(tmp_path / "Tiles"))
    pbf = osm_file(tmp_path / "denmark-latest.osm", NODES, WAYS, RELS)
    assert tool.main([pbf, "--tiles", "+55+012"]) == 2  # no index
    index_file(tmp_path / "index-v1.json", [
        ("denmark", "denmark-latest.osm", box(11, 54, 14, 56)),
        ("norway", "norway-latest.osm.pbf", box(5, 56.5, 14, 60))])
    # a cached layer is left alone
    os.makedirs(os.path.dirname(FNAMES.osm_cached(*T, "water")))
    open(FNAMES.osm_cached(*T, "water"), "wb").close()
    assert tool.main([pbf, "--tiles", "+55+012", "+56+012",
                      "--road-level", "3", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert ("SKIP +56+012: reaches outside the given files; add one "
            "of: norway") in out
    assert "+55+012: coastline, airports, big_roads, small_roads" in out
    assert tool.main([pbf, "--tiles", "+55+012", "--road-level", "3"]) == 0
    assert "4 layer answer(s) written for 1 tile(s), 0 tile(s) failed" in \
        capsys.readouterr().out
    assert not os.path.exists(EXTRACT.answer_path(*T, "water"))
    small = EXTRACT.read_answer(
        EXTRACT.answer_path(*T, "small_roads"),
        EXTRACT.flat_statements(VMAP.small_road_queries(3)))[0]
    assert ids(small, "way") == []  # service roads only from level 4
    assert tool.main([pbf, "--tiles", "+55+012"]) == 0  # nothing to do
    assert "0 with layers to prepare" in capsys.readouterr().out
