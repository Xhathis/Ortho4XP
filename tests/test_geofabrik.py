"""OSM data from Geofabrik first, Overpass as backup (#101)."""
import bz2
import hashlib
import os
import time

import pytest

osmium = pytest.importorskip("osmium")

from shapely import geometry  # noqa: E402

import O4_File_Names as FNAMES  # noqa: E402
import O4_Geofabrik as GEOFABRIK  # noqa: E402
import O4_OSM_Extract as EXTRACT  # noqa: E402
import O4_OSM_Utils as OSM  # noqa: E402
import O4_Tile_Utils as TILE  # noqa: E402
import O4_UI_Utils as UI  # noqa: E402
import O4_Vector_Map as VMAP  # noqa: E402
from test_osm_extract import osm_file  # noqa: E402

B = GEOFABRIK.BASE_URL


def region(rid, x0, y0, x1, y1, path=None):
    url = B + (path or f"europe/{rid}") + "-latest.osm.pbf"
    return GEOFABRIK.Region(rid, url, geometry.box(x0, y0, x1, y1))


@pytest.fixture
def gf(tmp_path, monkeypatch):
    """Geofabrik on, its folder and OSM_data in tmp, logs collected."""
    monkeypatch.setattr(GEOFABRIK, "osm_source", "geofabrik")
    monkeypatch.setattr(GEOFABRIK, "geofabrik_dir", str(tmp_path / "gf"))
    monkeypatch.setattr(FNAMES, "OSM_dir", str(tmp_path / "OSM_data"))
    monkeypatch.setattr(FNAMES, "Tmp_dir", str(tmp_path))
    monkeypatch.setattr(UI, "vprint", lambda *a: None)
    lines = []
    monkeypatch.setattr(UI, "lvprint",
                        lambda level, *a: lines.append(" ".join(map(str, a))))
    monkeypatch.setattr(UI, "stop_requested", False)
    monkeypatch.setattr(UI, "red_flag", False)
    return lines


# --- regions -----------------------------------------------------------------
REGIONS = GEOFABRIK.mark_containers([
    region("europe", -20, -20, 20, 20),          # continent: never chosen
    region("alps", -5, -5, 5, 5),                # big composite
    region("country-a", 0, -1, 0.5, 2),
    region("state-a1", 0, 0, 0.5, 1.5, "europe/country-a/state-a1"),
    region("country-b", 0.5, -1, 3, 2),
])


def test_smallest_files_cover_the_tile():
    (chosen, kind) = GEOFABRIK.choose_regions(0, 0, REGIONS)
    assert kind == "land"
    # state-a1 covers country-a's part of the tile and is smaller; alps
    # covers everything but is far bigger than the two together.
    assert [r.id for r in chosen] == ["country-b", "state-a1"]


def test_containers():
    assert {r.id for r in REGIONS if r.container} == {
        "europe", "alps", "country-a"}


def test_sea_only_in_a_container_needs_no_file():
    # +52+004: the provinces cover the land; netherlands adds North Sea.
    regions = GEOFABRIK.mark_containers([
        region("europe", -20, -20, 20, 20),
        region("netherlands", -1, -1, 2, 2),
        region("noord-holland", 0.3, 0.5, 1, 1.5, "europe/netherlands/nh"),
        region("zuid-holland", 0.3, -0.5, 1, 0.5, "europe/netherlands/zh")])
    (chosen, kind) = GEOFABRIK.choose_regions(0, 0, regions)
    assert (kind, [r.id for r in chosen]) == (
        "land", ["noord-holland", "zuid-holland"])


def test_redundant_choice_dropped():
    # Greedy takes the two halves first (best ratio), then needs "whole"
    # for the middle strip, which makes both halves redundant.
    regions = [region("west", 0, 0, 0.45, 1), region("east", 0.55, 0, 1, 1),
               region("whole", 0, 0, 1, 1.3)]
    (chosen, kind) = GEOFABRIK.choose_regions(0, 0, regions)
    assert [r.id for r in chosen] == ["whole"]


def test_only_containers_reach_the_tile():
    regions = GEOFABRIK.mark_containers([
        region("netherlands", -1, -1, 2, 2),
        region("province", 1.5, 1.5, 2, 2, "europe/netherlands/p")])
    (chosen, kind) = GEOFABRIK.choose_regions(0, 0, regions)
    assert (kind, [r.id for r in chosen]) == ("land", ["netherlands"])


def test_sea_and_continent_only():
    assert GEOFABRIK.choose_regions(40, 40, REGIONS) == ([], "sea")
    assert GEOFABRIK.choose_regions(10, 10, REGIONS) == ([], "continent")


def test_sea_beyond_a_country_needs_no_continent():
    regions = [region("europe", -20, -20, 20, 20),
               region("islands", 0, 0, 0.3, 0.3)]
    (chosen, kind) = GEOFABRIK.choose_regions(0, 0, regions)
    assert (kind, [r.id for r in chosen]) == ("land", ["islands"])


def test_parse_index_and_local_path():
    text = ('{"features": [{"type": "Feature", "properties": {"id": '
            '"us/georgia", "urls": {"pbf": "' + B + 'north-america/us/'
            'georgia-latest.osm.pbf"}}, "geometry": {"type": "Polygon", '
            '"coordinates": [[[0,0],[1,0],[1,1],[0,0]]]}}, {"type": '
            '"Feature", "properties": {"id": "x", "urls": {}}, "geometry": '
            'null}]}')
    (r,) = GEOFABRIK.parse_index(text)
    assert r.id == "us/georgia" and r.size == 0.5
    # Same file name as europe/georgia: kept apart by the server's folders.
    assert GEOFABRIK.local_path(r.url) == os.path.join(
        GEOFABRIK.data_dir(), "north-america", "us", "georgia-latest.osm.pbf")


def test_group_tiles_merges_subsets():
    (a, b, c) = ("a", "b", "c")
    plan = {(1, 1): frozenset({a}), (1, 2): frozenset({a, b}),
            (5, 5): frozenset({c}), (1, 3): frozenset({b})}
    assert sorted(GEOFABRIK.group_tiles(plan)) == [
        ([a, b], [(1, 1), (1, 2), (1, 3)]), ([c], [(5, 5)])]


# --- what a tile needs ----------------------------------------------------------
def test_needed_layers(gf):
    (lat, lon) = (55, 12)
    assert set(GEOFABRIK.needed_layers(lat, lon, 1)) == {
        "coastline", "airports", "water", "big_roads"}
    os.makedirs(FNAMES.osm_dir(lat, lon))
    open(FNAMES.osm_cached(lat, lon, "water"), "wb").close()
    open(EXTRACT.answer_path(lat, lon, "airports"), "wb").close()
    os.makedirs(FNAMES.custom_coastline_dir(lat, lon))
    assert set(GEOFABRIK.needed_layers(lat, lon, 4)) == {
        "big_roads", "small_roads"}
    assert set(GEOFABRIK.needed_layers(lat, lon, 4, force=True)) == {
        "airports", "water", "big_roads", "small_roads"}


# --- end to end with a fake Geofabrik ---------------------------------------------
@pytest.fixture
def fake_files(gf, tmp_path, monkeypatch):
    """Index with one country over +55+012; its 'download' is a small
    .osm file with a lake and a road. Returns the list of fetched URLs."""
    country = region("denmark", 11, 54, 13, 56)
    monkeypatch.setattr(GEOFABRIK, "load_index", lambda download=True:
                        [region("europe", -20, 30, 40, 80), country])
    src = osm_file(tmp_path / "dk.osm", [
        (1, 55.1, 12.1, {}), (2, 55.2, 12.1, {}), (3, 55.2, 12.2, {}),
        (4, 55.5, 12.5, {}), (5, 55.6, 12.6, {})],
        [(10, [1, 2, 3, 1], {"natural": "water", "name": "Sø"}),
         (11, [4, 5], {"highway": "primary"})])
    fetched = []

    def ensure_file(url):
        fetched.append(url)
        return src

    monkeypatch.setattr(GEOFABRIK, "ensure_file", ensure_file)
    return fetched


class FakeTile:
    def __init__(self, lat, lon, road_level=1):
        (self.lat, self.lon, self.road_level) = (lat, lon, road_level)


def test_prepare_tile_writes_answers_step1_reads(fake_files, gf):
    assert GEOFABRIK.prepare_tile(FakeTile(55, 12))
    assert fake_files == [B + "europe/denmark-latest.osm.pbf"]
    for layer in ("coastline", "airports", "water", "big_roads"):
        assert os.path.isfile(EXTRACT.answer_path(55, 12, layer))
    # Step 1 then reads the water answer, no Overpass.
    layer = OSM.OSM_layer()
    assert OSM.OSM_queries_to_OSM_layer(
        VMAP.WATER_QUERIES, layer, 55, 12, ["name"], cached_suffix="water")
    assert len(layer.dicosmw) == 1
    assert os.path.isfile(FNAMES.osm_cached(55, 12, "water"))
    # The answer goes once its cache is written; the others wait.
    assert not os.path.exists(EXTRACT.answer_path(55, 12, "water"))
    assert os.path.isfile(EXTRACT.answer_path(55, 12, "airports"))
    assert any("prepared for +55+012" in line for line in gf)


def test_nothing_missing_nothing_read(fake_files, gf):
    for layer in ("coastline", "airports", "water", "big_roads"):
        path = FNAMES.osm_cached(55, 12, layer)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").close()
    assert GEOFABRIK.prepare_tile(FakeTile(55, 12))
    assert fake_files == []


@pytest.mark.parametrize("source, prepared", [("overpass", False),
                                              ("geofabrik", True)])
def test_overpass_setting_and_batch_skip(fake_files, monkeypatch, source,
                                         prepared):
    monkeypatch.setattr(GEOFABRIK, "osm_source", source)
    monkeypatch.setattr(GEOFABRIK, "batch_prepared", prepared)
    assert GEOFABRIK.prepare_tile(FakeTile(55, 12))
    assert fake_files == []


def test_sea_tile_gets_empty_answers(fake_files, gf):
    assert GEOFABRIK.prepare_tile(FakeTile(-40, -30))
    assert fake_files == []
    (content, source) = EXTRACT.read_answer(
        EXTRACT.answer_path(-40, -30, "coastline"),
        EXTRACT.flat_statements(VMAP.COASTLINE_QUERIES))
    assert b"<way" not in content and "open sea" in source
    # #41 then finds no coastline: open sea, skipped.
    layer = OSM.OSM_layer()
    assert OSM.OSM_queries_to_OSM_layer(
        VMAP.COASTLINE_QUERIES, layer, -40, -30, [], cached_suffix="coastline")
    assert OSM.OSM_to_MultiLineString(layer, -40, -30).is_empty


def test_continent_only_left_to_overpass(fake_files, gf):
    assert GEOFABRIK.prepare_tile(FakeTile(60, 30))
    assert fake_files == []
    assert not os.path.exists(EXTRACT.answer_path(60, 30, "water"))
    assert any("no local OSM data for +60+030" in line
               and "Overpass will be asked" in line for line in gf)


def test_download_failure_left_to_overpass(fake_files, gf, monkeypatch):
    def broken(url):
        raise GEOFABRIK.GeofabrikError("HTTPError: 503")
    monkeypatch.setattr(GEOFABRIK, "ensure_file", broken)
    assert GEOFABRIK.prepare_tile(FakeTile(55, 12))
    assert not os.path.exists(EXTRACT.answer_path(55, 12, "water"))
    assert any("no extract file" in line and "503" in line for line in gf)


def test_no_index_left_to_overpass(gf, monkeypatch):
    def none(download=True):
        raise GEOFABRIK.GeofabrikError("no Geofabrik index (offline)")
    monkeypatch.setattr(GEOFABRIK, "load_index", none)
    assert GEOFABRIK.prepare_tile(FakeTile(55, 12))
    assert any("WARNING: Geofabrik extracts not used" in line for line in gf)


def test_stop_ends_step1(fake_files, gf, monkeypatch):
    monkeypatch.setattr(UI, "stop_requested", True)
    assert GEOFABRIK.prepare_tile(FakeTile(55, 12)) is False
    assert not os.path.exists(EXTRACT.answer_path(55, 12, "water"))


# --- files ------------------------------------------------------------------------
class FakeResp:
    def __init__(self, data, status=200):
        (self.data, self.status_code) = (data, status)
        self.text = data.decode("latin-1")
        self.headers = {"Content-Length": str(len(data))}

    def raise_for_status(self):
        if self.status_code != 200:
            raise GEOFABRIK_requests().HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, n):
        for i in range(0, len(self.data), 3):
            yield self.data[i:i + 3]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def GEOFABRIK_requests():
    import requests
    return requests


@pytest.fixture
def server(monkeypatch):
    files = {}

    class Session:
        headers = {}

        def get(self, url, timeout, stream=False):
            return FakeResp(*files[url]) if url in files else \
                FakeResp(b"", 404)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(GEOFABRIK, "_session", lambda: Session())
    return files


def test_download_checks_md5(gf, server):
    url = B + "europe/x-latest.osm.pbf"
    data = b"0123456789" * 10
    server[url] = (data,)
    server[url + ".md5"] = (hashlib.md5(data).hexdigest().encode()
                            + b"  x-latest.osm.pbf\n",)
    path = GEOFABRIK.local_path(url)
    GEOFABRIK._download(url, path)
    assert open(path, "rb").read() == data
    server[url + ".md5"] = (b"0" * 32 + b"  x\n",)
    os.remove(path)
    with pytest.raises(GEOFABRIK.GeofabrikError, match="MD5"):
        GEOFABRIK._download(url, path)
    assert os.listdir(os.path.dirname(path)) == []  # no temp file left


def test_download_http_error(gf, server):
    url = B + "europe/none-latest.osm.pbf"
    with pytest.raises(GEOFABRIK.GeofabrikError, match="none-latest"):
        GEOFABRIK._download(url, GEOFABRIK.local_path(url))


def test_ensure_file_downloads_once_then_updates(gf, monkeypatch):
    url = B + "europe/x-latest.osm.pbf"
    calls = []

    def download(u, path, md5=True):
        calls.append("download")
        with open(path, "wb") as f:
            f.write(b"pbf")

    monkeypatch.setattr(GEOFABRIK, "_download", download)
    monkeypatch.setattr(GEOFABRIK, "_update",
                        lambda path: calls.append("update") or True)
    age = [0.2]
    monkeypatch.setattr(GEOFABRIK, "_age_days", lambda path: age[0])
    monkeypatch.setattr(GEOFABRIK, "data_time", lambda path: __import__(
        "datetime").datetime(2026, 11, 12))
    path = GEOFABRIK.ensure_file(url)
    assert calls == ["download"]
    assert GEOFABRIK.ensure_file(url) == path and calls == ["download"]
    age[0] = 3  # older than geofabrik_max_age (1 day)
    GEOFABRIK.ensure_file(url)
    assert calls == ["download", "update"]
    # Geofabrik had nothing newer: not asked again within the hour.
    GEOFABRIK.ensure_file(url)
    assert calls == ["download", "update"]


def test_update_tool_is_there():
    from osmium.tools.pyosmium_up_to_date import main
    assert callable(main)


# --- batch -----------------------------------------------------------------------
def test_batch_prepares_once_and_workers_skip(fake_files, gf, monkeypatch):
    seen = {}

    class BatchTile(FakeTile):
        custom_build_dir = ""

        def read_from_config(self, use_global=False):
            self.road_level = 1

    def sequential(tile, tiles, flags):
        seen["prepared"] = GEOFABRIK.batch_prepared
        return 1

    monkeypatch.setattr(TILE, "_build_tile_list_sequential", sequential)
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)
    monkeypatch.setattr(TILE, "write_leftover_tiles", lambda tiles: None)
    monkeypatch.setattr(UI, "is_working", 0)
    tile = BatchTile(0, 0)
    assert TILE.build_tile_list(tile, [(55, 12), (-40, -30)],
                                1, 1, 0, 0, 0, 0) == 1
    assert fake_files == [B + "europe/denmark-latest.osm.pbf"]
    assert seen["prepared"] is True
    assert GEOFABRIK.batch_prepared is False  # reset after the batch
    assert (tile.lat, tile.lon) == (0, 0)  # the GUI's tile untouched
    assert os.path.isfile(EXTRACT.answer_path(55, 12, "big_roads"))
    assert os.path.isfile(EXTRACT.answer_path(-40, -30, "water"))


def test_batch_stop_while_preparing(fake_files, gf, monkeypatch):
    class BatchTile(FakeTile):
        custom_build_dir = ""

        def read_from_config(self, use_global=False):
            pass

    monkeypatch.setattr(TILE, "_build_tile_list_sequential",
                        lambda *a: pytest.fail("batch must not start"))
    monkeypatch.setattr(TILE, "write_leftover_tiles", lambda tiles: None)
    monkeypatch.setattr(UI, "exit_message_and_bottom_line", lambda *a: None)
    monkeypatch.setattr(UI, "is_working", 0)

    def stop(*a, **k):
        raise GEOFABRIK.Stopped()

    monkeypatch.setattr(GEOFABRIK, "prepare_tiles", stop)
    assert TILE.build_tile_list(BatchTile(0, 0), [(55, 12)],
                                1, 1, 0, 0, 0, 0) == 0
    assert UI.is_working == 0


# --- freshness ----------------------------------------------------------------------
def test_compare_with_cache(fake_files, gf, tmp_path):
    statements = EXTRACT.flat_statements(VMAP.WATER_QUERIES)
    (done, _) = GEOFABRIK.prepare_tiles({(55, 12): {"water": statements}},
                                       write=False)
    answer = done[(55, 12)]["water"]
    cache = FNAMES.osm_cached(55, 12, "water")
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    with bz2.open(cache, "wb") as f:
        f.write(GEOFABRIK.cache_bytes("water", statements, answer))
    assert GEOFABRIK.compare_with_cache(55, 12, "water", statements,
                                        answer) == (True, 0, 0)
    # The lake was renamed since the cache was made.
    with bz2.open(cache, "wb") as f:
        f.write(GEOFABRIK.cache_bytes(
            "water", statements, answer.replace("Sø".encode(), b"Old")))
    assert GEOFABRIK.compare_with_cache(55, 12, "water", statements,
                                        answer) == (False, 1, 1)


# --- robustness (2026-11-13 review) ------------------------------------------------
def test_group_tiles_reads_a_shared_file_once(monkeypatch):
    (n, s, f) = ("norway", "sweden", "finland")
    plan = {(60, 11): frozenset({n, s}), (69, 25): frozenset({n, f}),
            (66, 22): frozenset({s, f}), (59, 9): frozenset({n})}
    assert GEOFABRIK.group_tiles(plan) == [
        ([f, n, s], [(59, 9), (60, 11), (66, 22), (69, 25)])]
    # Above the cap groups that only share a file stay apart (borders
    # chain whole continents); a subset still joins as before.
    monkeypatch.setattr(GEOFABRIK, "MAX_MERGED_TILES", 2)
    (a, b, c, d) = ("a", "b", "c", "d")
    plan = {(1, 1): frozenset({a, b}), (1, 2): frozenset({b, c}),
            (1, 3): frozenset({c, d}), (1, 4): frozenset({c})}
    assert GEOFABRIK.group_tiles(plan) == [
        ([a, b], [(1, 1)]), ([b, c], [(1, 2), (1, 4)]), ([c, d], [(1, 3)])]
    monkeypatch.setattr(GEOFABRIK, "MAX_MERGED_TILES", 3)
    assert GEOFABRIK.group_tiles(plan) == [
        ([a, b, c], [(1, 1), (1, 2), (1, 4)]), ([c, d], [(1, 3)])]


INDEX = ('{"features": [{"type": "Feature", "properties": {"id": "dk", '
         '"urls": {"pbf": "' + B + 'europe/dk-latest.osm.pbf"}}, '
         '"geometry": {"type": "Polygon", "coordinates": '
         '[[[11,54],[13,54],[13,56],[11,56],[11,54]]]}}]}').encode()


def test_index_error_page_is_refused(gf, server):
    server[GEOFABRIK.INDEX_URL] = (b"<html>Server busy</html>",)
    with pytest.raises(GEOFABRIK.GeofabrikError, match="not a valid"):
        GEOFABRIK.load_index()
    assert not os.path.exists(GEOFABRIK.index_path())
    assert os.listdir(GEOFABRIK.data_dir()) == []  # no temp file
    # An old good index is kept and used.
    with open(GEOFABRIK.index_path(), "wb") as fh:
        fh.write(INDEX)
    old = os.path.getmtime(GEOFABRIK.index_path()) - 40 * 86400
    os.utime(GEOFABRIK.index_path(), (old, old))
    assert [r.id for r in GEOFABRIK.load_index()] == ["dk"]
    with open(GEOFABRIK.index_path(), "rb") as fh:
        assert fh.read() == INDEX


def test_broken_index_file_is_fetched_again(gf, server):
    os.makedirs(GEOFABRIK.data_dir())
    with open(GEOFABRIK.index_path(), "w") as fh:
        fh.write("<html>kept by an older version</html>")
    server[GEOFABRIK.INDEX_URL] = (INDEX,)
    assert [r.id for r in GEOFABRIK.load_index()] == ["dk"]
    with pytest.raises(GEOFABRIK.GeofabrikError, match="not a valid"):
        GEOFABRIK.read_index(__file__)  # not JSON
    # Without downloads a broken file is an error, not a crash.
    with open(GEOFABRIK.index_path(), "w") as fh:
        fh.write('{"no": "features"}')
    t = os.path.getmtime(GEOFABRIK.index_path()) - 10  # not the cached one
    os.utime(GEOFABRIK.index_path(), (t, t))
    with pytest.raises(GEOFABRIK.GeofabrikError, match="KeyError"):
        GEOFABRIK.load_index(download=False)


@pytest.mark.parametrize("answer", [b"", b"<html>404</html>", b"xyz  f\n"])
def test_md5_answer_without_checksum(gf, server, answer):
    url = B + "europe/x-latest.osm.pbf"
    server[url] = (b"data",)
    server[url + ".md5"] = (answer,)
    path = GEOFABRIK.local_path(url)
    with pytest.raises(GEOFABRIK.GeofabrikError, match="no checksum"):
        GEOFABRIK._download(url, path)
    assert os.listdir(os.path.dirname(path)) == []


class FakeUpdate:
    """pyosmium-up-to-date that writes its -o file and runs until killed
    (exit code 1 then, as on Windows) or ends with exit_code."""
    exit_code = None

    def __init__(self, args, **kw):
        import io
        self.tmp = args[args.index("-o") + 1]
        with open(self.tmp, "wb") as fh:
            fh.write(b"half a file")
        self.returncode = self.exit_code
        self.stdout = io.BytesIO(b"log")

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = 1

    def wait(self):
        return self.returncode


def test_stop_during_update_leaves_no_temp_file(gf, monkeypatch, tmp_path):
    path = str(tmp_path / "x-latest.osm.pbf")
    with open(path, "wb") as fh:
        fh.write(b"pbf")
    monkeypatch.setattr(GEOFABRIK.subprocess, "Popen", FakeUpdate)
    monkeypatch.setattr(GEOFABRIK.time, "sleep",
                        lambda s: setattr(UI, "stop_requested", True))
    with pytest.raises(GEOFABRIK.Stopped):
        GEOFABRIK._update(path)
    assert sorted(os.listdir(tmp_path)) == ["x-latest.osm.pbf"]
    with open(path, "rb") as fh:
        assert fh.read() == b"pbf"


def test_failed_update_leaves_no_temp_file(gf, monkeypatch, tmp_path):
    path = str(tmp_path / "x-latest.osm.pbf")
    with open(path, "wb") as fh:
        fh.write(b"pbf")
    monkeypatch.setattr(FakeUpdate, "exit_code", 3)
    monkeypatch.setattr(GEOFABRIK.subprocess, "Popen", FakeUpdate)
    assert GEOFABRIK._update(path) is False
    assert sorted(os.listdir(tmp_path)) == ["x-latest.osm.pbf"]
    assert any("could not update" in line for line in gf)


def test_ensure_file_removes_leftover_temp_files(gf, monkeypatch):
    url = B + "europe/x-latest.osm.pbf"
    path = GEOFABRIK.local_path(url)
    os.makedirs(os.path.dirname(path))
    for name in ("x-latest.osm.pbf", ".tmp12_34_x-latest.osm.pbf",
                 ".tmp56_78_y-latest.osm.pbf"):
        with open(os.path.join(os.path.dirname(path), name), "wb") as fh:
            fh.write(b"pbf")
    monkeypatch.setattr(GEOFABRIK, "_age_days", lambda p: 0.1)
    assert GEOFABRIK.ensure_file(url) == path
    assert sorted(os.listdir(os.path.dirname(path))) == [
        ".tmp56_78_y-latest.osm.pbf", "x-latest.osm.pbf",
        "x-latest.osm.pbf.lock"]


def test_prepare_tiles_writes_each_group_at_once(fake_files, gf):
    statements = EXTRACT.layer_statements(1)["water"]
    (done, left) = GEOFABRIK.prepare_tiles({(55, 12): {"water": statements}})
    assert left == {}
    size = done[(55, 12)]["water"]
    assert isinstance(size, int) and size > 0
    path = EXTRACT.answer_path(55, 12, "water")
    with bz2.open(path, "rb") as fh:
        assert len(fh.read()) == size


def test_unreadable_extract_answer_goes_to_overpass(gf, monkeypatch):
    statements = EXTRACT.layer_statements(1)["water"]
    EXTRACT.write_answer(EXTRACT.answer_path(55, 12, "water"),
                         EXTRACT.answer_xml(statements, "x", "2026", {}, {},
                                            {}))

    def half_read(self, content, *a):
        self.dicosmn[1] = (12.5, 55.5)
        return 0

    monkeypatch.setattr(OSM.OSM_layer, "update_dicosm", half_read)
    layer = OSM.OSM_layer()
    assert not OSM._layer_from_extract(
        VMAP.WATER_QUERIES, layer, 55, 12, {}, {}, "water",
        FNAMES.osm_cached(55, 12, "water"))
    assert layer.dicosmn == {}
    assert any("could not be read" in line for line in gf)


# --- refresh of old caches (osm_cache_max_age) -------------------------------------
DAY = 86400


def _old_cache(lat, lon, layer, days, layer_obj=None):
    path = FNAMES.osm_cached(lat, lon, layer)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    assert (layer_obj or OSM.OSM_layer()).write_to_file(path)
    t = time.time() - days * DAY
    os.utime(path, (t, t))
    return path


def test_cache_is_stale(gf, monkeypatch):
    path = _old_cache(55, 12, "water", 31)
    assert not GEOFABRIK.cache_is_stale(path)  # 0: never
    monkeypatch.setattr(GEOFABRIK, "osm_cache_max_age", 30.0)
    assert GEOFABRIK.cache_is_stale(path)
    assert not GEOFABRIK.cache_is_stale(path, now=time.time() - 2 * DAY)
    assert not GEOFABRIK.cache_is_stale(path + ".missing")


def test_needed_layers_takes_stale_caches(gf, monkeypatch):
    monkeypatch.setattr(GEOFABRIK, "osm_cache_max_age", 30.0)
    for layer in ("coastline", "airports", "big_roads"):
        _old_cache(55, 12, layer, 1)
    _old_cache(55, 12, "water", 40)
    assert set(GEOFABRIK.needed_layers(55, 12, 1)) == {"water"}
    # An answer already prepared for it: not again.
    open(EXTRACT.answer_path(55, 12, "water"), "wb").close()
    assert GEOFABRIK.needed_layers(55, 12, 1) == {}
    monkeypatch.setattr(GEOFABRIK, "osm_cache_max_age", 0.0)
    os.remove(EXTRACT.answer_path(55, 12, "water"))
    assert GEOFABRIK.needed_layers(55, 12, 1) == {}


def _all_cached(days, water_days=None):
    for layer in ("coastline", "airports", "big_roads"):
        _old_cache(55, 12, layer, days)
    return _old_cache(55, 12, "water", water_days or days)


def test_stale_cache_is_refreshed(fake_files, gf, monkeypatch):
    monkeypatch.setattr(GEOFABRIK, "osm_cache_max_age", 30.0)
    cache = _all_cached(1, water_days=40)
    assert GEOFABRIK.prepare_tile(FakeTile(55, 12))
    assert fake_files == [B + "europe/denmark-latest.osm.pbf"]
    assert os.path.isfile(EXTRACT.answer_path(55, 12, "water"))
    assert not os.path.exists(EXTRACT.answer_path(55, 12, "airports"))
    # Step 1 prefers the newer answer to the old (empty) cache.
    layer = OSM.OSM_layer()
    assert OSM.OSM_queries_to_OSM_layer(
        VMAP.WATER_QUERIES, layer, 55, 12, ["name"], cached_suffix="water")
    assert len(layer.dicosmw) == 1
    assert not os.path.exists(EXTRACT.answer_path(55, 12, "water"))
    assert time.time() - os.path.getmtime(cache) < 600
    reread = OSM.OSM_layer()
    assert reread.update_dicosm(cache, {}, {}) and len(reread.dicosmw) == 1
    assert any("water layer of +55+012 was 40 days old, refreshed" in line
               for line in gf)
    # Fresh now: nothing to prepare next time.
    assert GEOFABRIK.needed_layers(55, 12, 1) == {}


def test_refresh_failure_keeps_the_cache(fake_files, gf, monkeypatch):
    monkeypatch.setattr(GEOFABRIK, "osm_cache_max_age", 30.0)
    cache = _all_cached(40)
    before = open(cache, "rb").read()

    def broken(url):
        raise GEOFABRIK.GeofabrikError("HTTPError: 503")
    monkeypatch.setattr(GEOFABRIK, "ensure_file", broken)
    assert GEOFABRIK.prepare_tile(FakeTile(55, 12))
    assert any("+55+012 not refreshed" in line and "cached layers are used"
               in line for line in gf)
    assert not any("Overpass will be asked" in line for line in gf)
    layer = OSM.OSM_layer()
    assert OSM.OSM_queries_to_OSM_layer(
        VMAP.WATER_QUERIES, layer, 55, 12, ["name"], cached_suffix="water")
    assert open(cache, "rb").read() == before


def test_unusable_refresh_answer_keeps_the_cache(gf, monkeypatch):
    cache = _old_cache(55, 12, "water", 40)
    before = open(cache, "rb").read()
    # Made for other queries (as after a road_level change).
    EXTRACT.write_answer(EXTRACT.answer_path(55, 12, "water"),
                         EXTRACT.answer_xml(["way[x=y]"], "x", "2026",
                                            {}, {}, {}))
    layer = OSM.OSM_layer()
    assert OSM.OSM_queries_to_OSM_layer(
        VMAP.WATER_QUERIES, layer, 55, 12, ["name"], cached_suffix="water")
    assert open(cache, "rb").read() == before
    assert any("keeping the cached layer" in line for line in gf)


def test_answer_older_than_the_cache_is_not_used(fake_files, gf):
    assert GEOFABRIK.prepare_tile(FakeTile(55, 12))
    answer = EXTRACT.answer_path(55, 12, "water")
    t = time.time() - 2 * DAY
    os.utime(answer, (t, t))
    cache = _old_cache(55, 12, "water", 1)
    layer = OSM.OSM_layer()
    assert OSM.OSM_queries_to_OSM_layer(
        VMAP.WATER_QUERIES, layer, 55, 12, ["name"], cached_suffix="water")
    assert layer.dicosmw == {}
    assert os.path.isfile(answer)
    assert not any("refreshed" in line for line in gf)
    assert os.path.getmtime(cache) < time.time() - DAY / 2


def test_sea_refresh_never_empties_a_cache(fake_files, gf, monkeypatch):
    monkeypatch.setattr(GEOFABRIK, "osm_cache_max_age", 30.0)
    _old_cache(-40, -30, "coastline", 40)
    assert GEOFABRIK.prepare_tile(FakeTile(-40, -30))
    assert not os.path.exists(EXTRACT.answer_path(-40, -30, "coastline"))
    assert os.path.isfile(EXTRACT.answer_path(-40, -30, "water"))


def test_cache_write_is_atomic(gf, monkeypatch):
    layer = OSM.OSM_layer()
    layer.dicosmn[1] = (12.5, 55.5)
    cache = _old_cache(55, 12, "water", 1, layer)
    before = open(cache, "rb").read()
    folder = os.path.dirname(cache)

    def cut(self, fout):
        fout.write("<?xml")
        raise RuntimeError("killed")
    monkeypatch.setattr(OSM.OSM_layer, "_write", cut)
    with pytest.raises(RuntimeError):
        OSM.OSM_layer().write_to_file(cache)

    def full(self, fout):
        fout.write("<?xml")
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(OSM.OSM_layer, "_write", full)
    assert OSM.OSM_layer().write_to_file(cache) == 0
    assert open(cache, "rb").read() == before
    assert sorted(os.listdir(folder)) == [os.path.basename(cache)]
    assert any("could not write" in line for line in gf)


def test_osm_cache_max_age_setting():
    import O4_Cfg_Vars as VARS
    assert VARS.cfg_vars["osm_cache_max_age"]["default"] == 0.0
    assert "osm_cache_max_age" in VARS.gui_app_vars_short
    assert GEOFABRIK.osm_cache_max_age == 0.0
