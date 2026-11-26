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
    # Their fake files are no PBFs; test_geofabrik_store checks that test.
    monkeypatch.setattr(GEOFABRIK, "_looks_like_pbf", lambda path: True)
    return lines


# --- regions -----------------------------------------------------------------
REGIONS = GEOFABRIK.mark_containers([
    region("europe", -20, -20, 20, 20),          # continent: never chosen
    region("alps", -1, -2, 4, 3),                # composite: 0.36 held
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
    # europe: its regions cover 2 % of it here (a continent is never read,
    # flag or not).
    assert {r.id for r in REGIONS if r.container} == {"alps", "country-a"}


def test_sea_only_in_a_container_needs_no_file():
    # +52+004: the provinces cover the land; netherlands adds North Sea.
    regions = GEOFABRIK.mark_containers([
        region("europe", -20, -20, 20, 20),
        region("netherlands", 0, -1, 1.5, 2),
        region("noord-holland", 0.3, 0.5, 1, 1.5, "europe/netherlands/nh"),
        region("zuid-holland", 0.3, -0.5, 1, 0.5, "europe/netherlands/zh")])
    (chosen, kind) = GEOFABRIK.choose_regions(0, 0, regions)
    assert (kind, [r.id for r in chosen]) == (
        "land", ["noord-holland", "zuid-holland"])


def test_enclave_does_not_make_a_container():
    # +35-006: ceuta lies inside morocco's outline; morocco is no composite
    # of it, its land must be read (it was taken for sea before).
    regions = GEOFABRIK.mark_containers([
        region("europe", -20, 0.6, 20, 20),
        region("africa", -20, -20, 20, 0.6),
        region("morocco", -1, -1, 2, 0.6, "africa/morocco"),
        region("ceuta", 0.4, 0.5, 0.45, 0.6, "europe/spain/ceuta"),
        region("andalucia", -1, 0.6, 2, 2, "europe/spain/andalucia")])
    assert not any(r.container for r in regions if r.id not in
                   ("europe", "africa"))
    (chosen, kind) = GEOFABRIK.choose_regions(0, 0, regions)
    assert (kind, [r.id for r in chosen]) == ("land", ["andalucia", "morocco"])


def test_container_by_regions_half_inside():
    # alps holds no country whole, yet they cover it: a composite.
    regions = GEOFABRIK.mark_containers([
        region("alps", 0, 0, 4, 4),
        region("country-a", -0.5, 0, 2, 4),
        region("country-b", 2, 0, 4.5, 4)])
    assert [r.id for r in regions if r.container] == ["alps"]
    assert GEOFABRIK.CONTAINER_MIN_SHARE == 0.25


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
        region("province", 1.2, -1, 2, 2, "europe/netherlands/p")])
    assert regions[0].container
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

    def ensure_extract(r):
        fetched.append(r.url)
        return src

    monkeypatch.setattr(GEOFABRIK, "ensure_extract", ensure_extract)
    return fetched


def ensure(url, rid=None):
    """ensure_extract of a region with url (id from the file name)."""
    rid = rid or url.rsplit("/", 1)[-1].split("-latest.", 1)[0]
    return GEOFABRIK.ensure_extract(
        GEOFABRIK.Region(rid, url, geometry.box(0, 0, 1, 1)))


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
    monkeypatch.setattr(GEOFABRIK, "ensure_extract", broken)
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

    def close(self):
        pass

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
                        lambda path, server=None: calls.append("update")
                        or True)
    age = [0.2]
    monkeypatch.setattr(GEOFABRIK, "_age_days", lambda path: age[0])
    monkeypatch.setattr(GEOFABRIK, "data_time", lambda path: __import__(
        "datetime").datetime(2026, 11, 12))
    path = ensure(url)
    assert path == GEOFABRIK.extract_path("x")
    assert calls == ["download"]
    assert ensure(url) == path and calls == ["download"]
    age[0] = 3  # older than geofabrik_max_age (1 day)
    ensure(url)
    assert calls == ["download", "update"]
    # Geofabrik had nothing newer: not asked again within the hour.
    ensure(url)
    assert calls == ["download", "update"]


@pytest.fixture
def fresh_failures(monkeypatch):
    monkeypatch.setattr(GEOFABRIK, "_failed_downloads", {}, raising=False)
    monkeypatch.setattr(GEOFABRIK, "_failed_updates", set(), raising=False)


def test_failed_download_not_asked_again(gf, monkeypatch, fresh_failures):
    # Several tile groups can share a file: a download cut at 90 % used to
    # start again in full for each of them.
    url = B + "europe/cut-latest.osm.pbf"
    calls = []

    def download(u, path, md5=True):
        calls.append(u)
        raise GEOFABRIK.GeofabrikError(f"{u}: ChunkedEncodingError: cut")

    monkeypatch.setattr(GEOFABRIK, "_download", download)
    with pytest.raises(GEOFABRIK.GeofabrikError, match="cut"):
        ensure(url)
    with pytest.raises(GEOFABRIK.GeofabrikError,
                       match="cut.*not asked again"):
        ensure(url)
    assert calls == [url]


def test_failed_update_not_asked_again(gf, monkeypatch, fresh_failures):
    url = B + "europe/old-latest.osm.pbf"
    path = GEOFABRIK.extract_path("old")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"pbf")
    calls = []
    monkeypatch.setattr(GEOFABRIK, "_update",
                        lambda p, server=None: calls.append(p) and False)
    monkeypatch.setattr(GEOFABRIK, "_age_days", lambda p: 3)
    monkeypatch.setattr(GEOFABRIK, "data_time", lambda p: __import__(
        "datetime").datetime(2026, 11, 12))
    # The file is used as it is (older data), the update tried once.
    assert ensure(url) == path
    assert ensure(url) == path
    assert calls == [path]


def test_next_preparation_tries_again(gf, monkeypatch, fresh_failures):
    monkeypatch.setattr(GEOFABRIK, "load_index", lambda download=True: [
        region("europe", -20, 30, 40, 80), region("denmark", 11, 54, 13, 56)])
    calls = []

    def download(u, path, md5=True):
        calls.append(u)
        raise GEOFABRIK.GeofabrikError(f"{u}: HTTPError: 503")

    monkeypatch.setattr(GEOFABRIK, "_download", download)
    wanted = {(55, 12): {"water": EXTRACT.layer_statements(1)["water"]}}
    for n in (1, 2):
        (done, left) = GEOFABRIK.prepare_tiles(wanted)
        assert "503" in left[(55, 12)] and len(calls) == n


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
    path = GEOFABRIK.extract_path("x")
    os.makedirs(os.path.dirname(path))
    for name in ("x.osm.pbf", ".tmp12_34_x.osm.pbf", ".tmp56_78_y.osm.pbf"):
        with open(os.path.join(os.path.dirname(path), name), "wb") as fh:
            fh.write(b"pbf")
    monkeypatch.setattr(GEOFABRIK, "_age_days", lambda p: 0.1)
    assert ensure(url) == path
    assert sorted(os.listdir(os.path.dirname(path))) == [
        ".lock", ".tmp56_78_y.osm.pbf", "x.osm.pbf"]


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
    monkeypatch.setattr(GEOFABRIK, "ensure_extract", broken)
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
    # Never used, and left in place it would block the next refresh.
    assert not os.path.exists(answer)
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

    def cut(self, fout, statements=()):
        fout.write("<?xml")
        raise RuntimeError("killed")
    monkeypatch.setattr(OSM.OSM_layer, "_write", cut)
    with pytest.raises(RuntimeError):
        OSM.OSM_layer().write_to_file(cache)

    def full(self, fout, statements=()):
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


# --- caches made for another road_level (#107) --------------------------------------
def _road_cache(values, days=1, statements=None):
    """An old-style (unstamped) small_roads cache with one way per value,
    or a stamped one when statements are given."""
    path = FNAMES.osm_cached(55, 12, "small_roads")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<osm version="0.6" generator="Ortho4XP">']
    if statements:
        lines.append(EXTRACT.cache_stamp(statements))
    for (i, v) in enumerate(values, 1):
        lines += [f'  <node id="-{2 * i}" lat="55.5" lon="12.{i}" version="1"/>',
                  f'  <node id="-{2 * i + 1}" lat="55.6" lon="12.{i}" '
                  'version="1"/>',
                  f'  <way id="-{i}" version="1">',
                  f'    <nd ref="-{2 * i}"/>', f'    <nd ref="-{2 * i + 1}"/>',
                  f'    <tag k="highway" v="{v}"/>', '  </way>']
    lines.append("</osm>")
    with bz2.open(path, "wt", encoding="utf-8") as f:
        f.write("\n".join(lines))
    t = time.time() - days * DAY
    os.utime(path, (t, t))
    return path


def _roads(level):
    return EXTRACT.flat_statements(VMAP.small_road_queries(level))


LEVEL4 = ["tertiary", "tertiary_link", "unclassified", "residential",
          "living_street", "service"]


def test_cache_stamp_written_and_read(gf):
    layer = OSM.OSM_layer()
    assert layer.update_dicosm(_road_cache(LEVEL4), {}, {})
    path = FNAMES.osm_cached(55, 12, "small_roads")
    assert layer.write_to_file(path, _roads(4))
    with bz2.open(path, "rt", encoding="utf-8") as f:
        assert "<o4xp_cache statements=" in f.read(400)
    assert EXTRACT.cache_fits(path, _roads(4)) is True
    assert EXTRACT.cache_fits(path, list(reversed(_roads(4)))) is True
    assert EXTRACT.cache_fits(path, _roads(5)) is False
    # The reader skips the stamp: the same layer as from an unstamped file.
    reread = OSM.OSM_layer()
    assert reread.update_dicosm(path, {}, {})
    assert (reread.dicosmn, reread.dicosmw, reread.dicosmtags) == (
        layer.dicosmn, layer.dicosmw, layer.dicosmtags)


def test_unstamped_cache_judged_by_its_road_values(gf):
    path = _road_cache(LEVEL4)
    assert EXTRACT.cache_fits(path, _roads(4)) is True
    assert EXTRACT.cache_fits(path, _roads(5)) is False   # no tracks
    assert EXTRACT.cache_fits(path, _roads(3)) is False   # has service
    assert EXTRACT.cache_fits(_road_cache(LEVEL4 + ["track", "path"]),
                              _roads(5)) is True          # path: not ours
    # Other layers' old caches pass as before; no file: unknown.
    assert EXTRACT.cache_fits(_old_cache(55, 12, "water", 1),
                              EXTRACT.flat_statements(VMAP.WATER_QUERIES)) \
        is None
    assert EXTRACT.cache_fits(path + ".missing", _roads(4)) is None


def test_needed_layers_takes_cache_of_other_road_level(gf):
    for layer in ("coastline", "airports", "water", "big_roads"):
        _old_cache(55, 12, layer, 1)
    _road_cache(LEVEL4)
    assert GEOFABRIK.needed_layers(55, 12, 4) == {}
    assert GEOFABRIK.needed_layers(55, 12, 5) == {"small_roads": _roads(5)}
    # An answer prepared at level 4 (+53+008 on 2026-11-15) does not
    # stand for level 5: prepared again.
    EXTRACT.write_answer(EXTRACT.answer_path(55, 12, "small_roads"),
                         EXTRACT.answer_xml(_roads(4), "x", "2026",
                                            {}, {}, {}))
    assert GEOFABRIK.needed_layers(55, 12, 5) == {"small_roads": _roads(5)}
    EXTRACT.write_answer(EXTRACT.answer_path(55, 12, "small_roads"),
                         EXTRACT.answer_xml(_roads(5), "x", "2026",
                                            {}, {}, {}))
    assert GEOFABRIK.needed_layers(55, 12, 5) == {}


def test_step1_warns_about_an_unrefreshed_mismatch(gf):
    cache = _road_cache(LEVEL4)
    before = open(cache, "rb").read()
    layer = OSM.OSM_layer()
    assert OSM.OSM_queries_to_OSM_layer(
        VMAP.small_road_queries(4), layer, 55, 12, [],
        cached_suffix="small_roads")
    assert not any("made for other queries" in line for line in gf)
    layer = OSM.OSM_layer()
    assert OSM.OSM_queries_to_OSM_layer(
        VMAP.small_road_queries(5), layer, 55, 12, [],
        cached_suffix="small_roads")
    assert len(layer.dicosmw) == len(LEVEL4)
    assert any("cached OSM small_roads layer of +55+012 was made for other "
               "queries" in line for line in gf)
    assert open(cache, "rb").read() == before


def test_road_level_raise_refreshes_the_cache(fake_files, gf):
    for layer in ("coastline", "airports", "water", "big_roads"):
        _old_cache(55, 12, layer, 1)
    cache = _road_cache(LEVEL4)
    assert GEOFABRIK.prepare_tile(FakeTile(55, 12, road_level=5))
    assert os.path.isfile(EXTRACT.answer_path(55, 12, "small_roads"))
    layer = OSM.OSM_layer()
    assert OSM.OSM_queries_to_OSM_layer(
        VMAP.small_road_queries(5), layer, 55, 12, [],
        cached_suffix="small_roads")
    assert EXTRACT.cache_fits(cache, _roads(5)) is True
    assert any("small_roads layer of +55+012 was 1 days old, refreshed"
               in line for line in gf)
    assert GEOFABRIK.needed_layers(55, 12, 5) == {}


# --- Geofabrik's folder layout of 2026-11 (#118) ------------------------------
@pytest.mark.parametrize("new, old", [
    ("europe/france/alsace/alsace-latest.osm.pbf",
     "europe/france/alsace-latest.osm.pbf"),
    ("europe/germany/germany-latest.osm.pbf", "europe/germany-latest.osm.pbf"),
    ("europe/germany/bayern/bayern-latest.osm.pbf",
     "europe/germany/bayern-latest.osm.pbf"),
    ("north-america/us/georgia/georgia-latest.osm.pbf",
     "north-america/us/georgia-latest.osm.pbf"),
    ("europe/georgia/georgia-latest.osm.pbf", "europe/georgia-latest.osm.pbf"),
    # region us-virgin-islands in folder us: its name starts with "us-"
    ("north-america/us/us-virgin-islands/us-virgin-islands-latest.osm.pbf",
     "north-america/us/us-virgin-islands-latest.osm.pbf"),
])
def test_local_path_same_in_both_layouts(gf, new, old):
    # The files downloaded before stay in use when the index (refreshed
    # every 30 days) gives the new URLs: no download of them all again.
    assert GEOFABRIK.local_path(B + new) == GEOFABRIK.local_path(B + old)
    assert GEOFABRIK.local_path(B + old) == os.path.join(
        GEOFABRIK.data_dir(), *old.split("/"))


@pytest.fixture
def redirecting(monkeypatch):
    """files {url: (data, headers)}; moved {url: url it redirects to}."""
    (files, moved, asked) = ({}, {}, [])

    class Resp(FakeResp):
        def __init__(self, url):
            final = moved.get(url, url)
            (data, headers) = files.get(final, (b"", {}))
            super().__init__(data, 200 if final in files else 404)
            self.headers.update(headers)
            self.url = final

    class Session:
        headers = {}

        def get(self, url, timeout, stream=False):
            asked.append(url)
            return Resp(url)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(GEOFABRIK, "_session", lambda: Session())
    return (files, moved, asked)


LATEST = B + "europe/france/alsace-latest.osm.pbf"
DATED = B + "europe/france/alsace/alsace-261119.osm.pbf"
DATA = b"pbf data " * 20


def md5_line(data, name="alsace-261119.osm.pbf"):
    return (hashlib.md5(data).hexdigest().encode() + b"  " + name.encode(), {})


def test_md5_of_the_dated_file(gf, redirecting):
    # The batch of 2026-11-20: the -latest .md5 is gone (404), the file
    # redirects to the dated one, which has its .md5.
    (files, moved, asked) = redirecting
    moved[LATEST] = DATED
    files[DATED] = (DATA, {})
    files[DATED + ".md5"] = md5_line(DATA)
    path = GEOFABRIK.local_path(LATEST)
    GEOFABRIK._download(LATEST, path)
    assert open(path, "rb").read() == DATA
    assert asked == [LATEST, DATED + ".md5"]
    files[DATED + ".md5"] = md5_line(b"other")
    os.remove(path)
    with pytest.raises(GEOFABRIK.GeofabrikError, match="MD5"):
        GEOFABRIK._download(LATEST, path)
    assert not os.path.exists(path)


def test_md5_of_the_old_name_still_used(gf, redirecting):
    (files, moved, asked) = redirecting
    moved[LATEST] = DATED
    files[DATED] = (DATA, {})
    files[LATEST + ".md5"] = md5_line(b"other")
    with pytest.raises(GEOFABRIK.GeofabrikError, match="MD5"):
        GEOFABRIK._download(LATEST, GEOFABRIK.local_path(LATEST))
    assert asked == [LATEST, DATED + ".md5", LATEST + ".md5"]


def test_no_md5_checks_the_size(gf, redirecting):
    (files, moved, asked) = redirecting
    files[LATEST] = (DATA, {})
    path = GEOFABRIK.local_path(LATEST)
    GEOFABRIK._download(LATEST, path)
    assert open(path, "rb").read() == DATA
    os.remove(path)
    files[LATEST] = (DATA, {"Content-Length": str(len(DATA) + 5)})
    with pytest.raises(GEOFABRIK.GeofabrikError, match="download cut"):
        GEOFABRIK._download(LATEST, path)
    assert os.listdir(os.path.dirname(path)) == []
    # A gzip answer is decoded: its Content-Length is the compressed size.
    files[LATEST] = (DATA, {"Content-Length": "7", "Content-Encoding": "gzip"})
    GEOFABRIK._download(LATEST, path, md5=False)
    assert open(path, "rb").read() == DATA


def test_md5_server_error_raises(gf, redirecting, monkeypatch):
    # Only a 404 means "no .md5"; a server error stops the download.
    (files, moved, asked) = redirecting
    files[LATEST] = (DATA, {})
    real = GEOFABRIK._session

    def session():
        s = real()
        get = s.get
        s.get = lambda url, timeout, stream=False: (
            FakeResp(b"", 503) if url.endswith(".md5") else get(url, timeout))
        return s

    monkeypatch.setattr(GEOFABRIK, "_session", session)
    with pytest.raises(GEOFABRIK.GeofabrikError, match="503"):
        GEOFABRIK._download(LATEST, GEOFABRIK.local_path(LATEST))


def test_failed_file_fails_only_its_tiles(gf, tmp_path, monkeypatch,
                                          fresh_failures):
    # +55+012 needs a only, +55+013 needs a and b: one group. b's download
    # failing used to send both tiles to Overpass.
    monkeypatch.setattr(GEOFABRIK, "load_index", lambda download=True: [
        region("europe", -20, 30, 40, 80), region("a", 11, 54, 13.5, 56),
        region("b", 13.5, 54, 15, 56)])
    src = osm_file(tmp_path / "a.osm", [
        (1, 55.1, 12.1, {}), (2, 55.2, 12.1, {}), (3, 55.2, 12.2, {})],
        [(10, [1, 2, 3, 1], {"natural": "water"})])
    fetched = []

    def ensure_extract(r):
        fetched.append(r.url)
        if r.id == "b":
            raise GEOFABRIK.GeofabrikError(f"{r.url}: HTTPError: 404")
        return src

    monkeypatch.setattr(GEOFABRIK, "ensure_extract", ensure_extract)
    wanted = {(55, 12): {"water": "w"}, (55, 13): {"water": "w"}}
    (plan, _, _) = GEOFABRIK.plan_tiles(wanted, GEOFABRIK.load_index())
    assert len(GEOFABRIK.group_tiles(plan)) == 1
    monkeypatch.setattr(EXTRACT, "extract_answers", lambda files, w, log: (
        {t: {"water": b"<osm/>"} for t in w}, {}))
    (done, left) = GEOFABRIK.prepare_tiles(wanted, write=False)
    assert set(done) == {(55, 12)} and set(left) == {(55, 13)}
    assert "b-latest" in left[(55, 13)]
    assert sorted(fetched) == [B + "europe/a-latest.osm.pbf",
                               B + "europe/b-latest.osm.pbf"]


# --- land only a continent file holds (#120) --------------------------------
def write_hgt(tmp_path, monkeypatch, lat, lon, land):
    """A 121 x 121 .hgt for the tile, 0 m except the boxes in land
    ((lon0, lat0, lon1, lat1) in degrees), 50 m there."""
    import numpy as np
    monkeypatch.setattr(FNAMES, "Elevation_dir", str(tmp_path / "dem"))
    n = 121
    a = np.zeros((n, n), dtype=">i2")
    ys = lat + 1 - np.arange(n) / (n - 1)
    xs = lon + np.arange(n) / (n - 1)
    for (x0, y0, x1, y1) in land:
        a[np.ix_((ys >= y0) & (ys <= y1), (xs >= x0) & (xs <= x1))] = 50
    path = FNAMES.viewfinderpanorama(lat, lon)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    a.tofile(path)


CARIBBEAN = [region("central-america", -20, -20, 20, 20, "central-america"),
             region("guadeloupe", 0, 0, 0.5, 1, "europe/france/guadeloupe")]


def test_island_only_in_a_continent_is_found(gf, tmp_path, monkeypatch):
    # +15-062: guadeloupe's outline reaches the tile, Dominica lies outside
    # it and only central-america holds it. It was taken for sea.
    write_hgt(tmp_path, monkeypatch, 0, 0, [(0.1, 0.1, 0.3, 0.3),
                                            (0.7, 0.2, 0.9, 0.6)])
    assert [r.id for r in GEOFABRIK.gap_continents(0, 0, CARIBBEAN)] == [
        "central-america"]


def test_gap_continent_read_when_on_disk(gf, tmp_path, monkeypatch):
    write_hgt(tmp_path, monkeypatch, 0, 0, [(0.7, 0.2, 0.9, 0.6)])
    wanted = {(0, 0): {"coastline": ("x",)}}
    (plan, left, sea) = GEOFABRIK.plan_tiles(wanted, CARIBBEAN)
    assert not plan and not sea
    assert "central-america" in left[(0, 0)] and "not downloaded" in left[(0, 0)]
    path = GEOFABRIK.extract_path(CARIBBEAN[0].id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").close()
    (plan, left, sea) = GEOFABRIK.plan_tiles(wanted, CARIBBEAN)
    assert plan == {(0, 0): frozenset(r.id for r in CARIBBEAN)} and not left


def test_sea_beyond_the_country_stays_sea(gf, tmp_path, monkeypatch):
    # Land only inside the country outline (and a sample on its edge):
    # the continent's part of the tile is sea, as before.
    write_hgt(tmp_path, monkeypatch, 0, 0, [(0.1, 0.1, 0.5, 0.3)])
    assert GEOFABRIK.gap_continents(0, 0, CARIBBEAN) == []
    (plan, left, sea) = GEOFABRIK.plan_tiles({(0, 0): {"water": ("x",)}},
                                             CARIBBEAN)
    assert plan == {(0, 0): frozenset([CARIBBEAN[1].id])} and not left


def test_gap_without_elevation_file_as_before(gf, tmp_path, monkeypatch):
    monkeypatch.setattr(FNAMES, "Elevation_dir", str(tmp_path / "dem"))
    assert GEOFABRIK.gap_continents(0, 0, CARIBBEAN) == []


def test_continent_only_tile_read_when_on_disk(gf, tmp_path, monkeypatch):
    # Diego Garcia: only asia holds it. Overpass unless the file is there.
    regions = [region("asia", -20, -20, 20, 20, "asia")]
    wanted = {(0, 0): {"coastline": ("x",)}}
    (plan, left, _) = GEOFABRIK.plan_tiles(wanted, regions)
    assert not plan and "not downloaded" in left[(0, 0)]
    path = GEOFABRIK.extract_path(regions[0].id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").close()
    (plan, left, _) = GEOFABRIK.plan_tiles(wanted, regions)
    assert plan == {(0, 0): frozenset([regions[0].id])} and not left


# --- the other folder layout when a URL is not found (#127) --------------------
@pytest.mark.parametrize("url, other", [
    ("asia/indonesia/papua-latest.osm.pbf",
     "asia/indonesia/papua/papua-latest.osm.pbf"),
    ("asia/indonesia/papua/papua-latest.osm.pbf",
     "asia/indonesia/papua-latest.osm.pbf"),
    ("europe/germany-latest.osm.pbf", "europe/germany/germany-latest.osm.pbf"),
    ("europe/germany/germany-latest.osm.pbf", "europe/germany-latest.osm.pbf"),
    # region us-virgin-islands in folder us (old form)
    ("north-america/us/us-virgin-islands-latest.osm.pbf",
     "north-america/us/us-virgin-islands/us-virgin-islands-latest.osm.pbf"),
])
def test_url_variants(gf, url, other):
    assert GEOFABRIK.url_variants(B + url) == [B + url, B + other]
    assert GEOFABRIK.local_path(B + url) == GEOFABRIK.local_path(B + other)


@pytest.mark.parametrize("url", [GEOFABRIK.INDEX_URL,
                                 "https://example.org/x-latest.osm.pbf",
                                 B + "asia/indonesia/papua-261123.osm.pbf"])
def test_url_variants_only_for_latest_extracts(gf, url):
    assert GEOFABRIK.url_variants(url) == [url]


PAPUA_OLD = B + "asia/indonesia/papua-latest.osm.pbf"
PAPUA_NEW = B + "asia/indonesia/papua/papua-latest.osm.pbf"
PAPUA_DATED = B + "asia/indonesia/papua/papua-261123.osm.pbf"


def test_broken_redirect_tries_the_new_folder(gf, redirecting):
    # 2026-11-21: the old URL redirected to a URL without "asia/" (404).
    (files, moved, asked) = redirecting
    moved[PAPUA_OLD] = B + "indonesia/papua/papua-latest.osm.pbf"
    moved[PAPUA_NEW] = PAPUA_DATED
    files[PAPUA_DATED] = (DATA, {})
    files[PAPUA_DATED + ".md5"] = md5_line(DATA, "papua-261123.osm.pbf")
    path = GEOFABRIK.local_path(PAPUA_OLD)
    GEOFABRIK._download(PAPUA_OLD, path)
    assert open(path, "rb").read() == DATA
    assert asked == [PAPUA_OLD, PAPUA_NEW, PAPUA_DATED + ".md5"]


def test_new_url_falls_back_to_the_old_one(gf, redirecting):
    (files, moved, asked) = redirecting
    files[PAPUA_OLD] = (DATA, {})
    files[PAPUA_OLD + ".md5"] = md5_line(DATA, "papua-latest.osm.pbf")
    GEOFABRIK._download(PAPUA_NEW, GEOFABRIK.local_path(PAPUA_NEW))
    assert asked == [PAPUA_NEW, PAPUA_OLD, PAPUA_OLD + ".md5"]


def test_found_url_asks_nothing_else(gf, redirecting):
    (files, moved, asked) = redirecting
    files[PAPUA_OLD] = (DATA, {})
    GEOFABRIK._download(PAPUA_OLD, GEOFABRIK.local_path(PAPUA_OLD))
    assert asked == [PAPUA_OLD, PAPUA_OLD + ".md5"]


def test_both_forms_missing_is_an_error(gf, redirecting):
    (files, moved, asked) = redirecting
    path = GEOFABRIK.local_path(PAPUA_OLD)
    with pytest.raises(GEOFABRIK.GeofabrikError, match="404"):
        GEOFABRIK._download(PAPUA_OLD, path)
    assert asked == [PAPUA_OLD, PAPUA_NEW]
    assert not os.path.exists(path)


# --- the index fetched again when an extract is gone (#128) ------------------
def index_bytes(urls):
    """An index with one region per {id: url}."""
    import json
    return json.dumps({"features": [
        {"type": "Feature", "properties": {"id": rid, "urls": {"pbf": url}},
         "geometry": {"type": "Polygon", "coordinates":
                      [[[11, 54], [13, 54], [13, 56], [11, 56], [11, 54]]]}}
        for (rid, url) in urls.items()]}).encode()


DK_OLD = B + "europe/dk-latest.osm.pbf"
DK_NEW = B + "extracts/2027/europe/dk.osm.pbf"  # a layout we cannot guess
SE_OLD = B + "europe/se-latest.osm.pbf"


def old_index(urls, age_days):
    os.makedirs(GEOFABRIK.data_dir(), exist_ok=True)
    with open(GEOFABRIK.index_path(), "wb") as fh:
        fh.write(index_bytes(urls))
    t = time.time() - age_days * 86400
    os.utime(GEOFABRIK.index_path(), (t, t))


@pytest.fixture
def no_refresh_error(monkeypatch):
    monkeypatch.setattr(GEOFABRIK, "_index_refresh_error", None)
    monkeypatch.setattr(GEOFABRIK, "_failed_downloads", {})


def test_gone_url_follows_the_refreshed_index(gf, redirecting,
                                             no_refresh_error, monkeypatch):
    (files, moved, asked) = redirecting
    old_index({"dk": DK_OLD}, 2)
    files[GEOFABRIK.INDEX_URL] = (index_bytes({"dk": DK_NEW}), {})
    files[DK_NEW] = (DATA, {})
    files[DK_NEW + ".md5"] = md5_line(DATA, "dk.osm.pbf")
    path = ensure(DK_OLD)
    assert path == GEOFABRIK.extract_path("dk")
    assert open(path, "rb").read() == DATA
    assert asked == [DK_OLD, B + "europe/dk/dk-latest.osm.pbf",
                     GEOFABRIK.INDEX_URL, DK_NEW, DK_NEW + ".md5"]
    assert any("is gone; the index now gives " + DK_NEW in line
               for line in gf)
    # The next plan uses the new URL, and finds the file on disk.
    assert [r.url for r in GEOFABRIK.load_index()] == [DK_NEW]
    asked.clear()
    monkeypatch.setattr(GEOFABRIK, "_age_days", lambda p: 0)  # fake .pbf
    assert ensure(DK_NEW, "dk") == path
    assert asked == []
    # The manifest names where the file came from.
    assert GEOFABRIK.read_manifest()["dk"]["url"] == DK_NEW


def test_young_index_is_not_fetched_again(gf, redirecting, no_refresh_error):
    (files, moved, asked) = redirecting
    old_index({"dk": DK_OLD}, 0.5)
    with pytest.raises(GEOFABRIK.GeofabrikNotFound, match="404"):
        ensure(DK_OLD)
    assert GEOFABRIK.INDEX_URL not in asked


def test_index_unchanged_keeps_the_404(gf, redirecting, no_refresh_error):
    (files, moved, asked) = redirecting
    old_index({"dk": DK_OLD}, 2)
    files[GEOFABRIK.INDEX_URL] = (index_bytes({"dk": DK_OLD}), {})
    with pytest.raises(GEOFABRIK.GeofabrikNotFound):
        ensure(DK_OLD)
    assert asked.count(GEOFABRIK.INDEX_URL) == 1
    # Not asked again in this preparation.
    with pytest.raises(GEOFABRIK.GeofabrikError, match="failed earlier"):
        ensure(DK_OLD)


def test_failed_index_fetch_is_tried_once(gf, redirecting, no_refresh_error):
    (files, moved, asked) = redirecting
    old_index({"dk": DK_OLD, "se": SE_OLD}, 2)
    for url in (DK_OLD, SE_OLD):
        with pytest.raises(GEOFABRIK.GeofabrikNotFound):
            ensure(url)
    assert asked.count(GEOFABRIK.INDEX_URL) == 1  # 404 for the index too
    assert GEOFABRIK._index_refresh_error


def test_region_gone_from_the_index(gf, redirecting, no_refresh_error):
    # Geofabrik dropped (merged or renamed) the region: the 404 stands.
    (files, moved, asked) = redirecting
    old_index({"dk": DK_OLD}, 2)
    files[GEOFABRIK.INDEX_URL] = (index_bytes({"se": SE_OLD}), {})
    with pytest.raises(GEOFABRIK.GeofabrikNotFound):
        ensure(DK_OLD)
    assert asked.count(GEOFABRIK.INDEX_URL) == 1


def test_other_download_errors_do_not_fetch_the_index(gf, redirecting,
                                                      no_refresh_error,
                                                      monkeypatch):
    (files, moved, asked) = redirecting
    old_index({"dk": DK_OLD}, 2)
    files[DK_OLD] = (DATA, {"Content-Length": str(len(DATA) + 5)})
    with pytest.raises(GEOFABRIK.GeofabrikError, match="download cut"):
        ensure(DK_OLD)
    assert GEOFABRIK.INDEX_URL not in asked


def test_preparation_clears_the_index_error(gf, monkeypatch):
    monkeypatch.setattr(GEOFABRIK, "_index_refresh_error", "earlier")
    monkeypatch.setattr(GEOFABRIK, "load_index", lambda: [])
    GEOFABRIK.prepare_tiles({(55, 12): {"water": "x"}}, write=False)
    assert GEOFABRIK._index_refresh_error is None


# --- review 2026-11-24: leftover answers must not block a refresh -------------
def test_rejected_answer_is_removed_and_prepared_again(gf, monkeypatch):
    monkeypatch.setattr(GEOFABRIK, "osm_cache_max_age", 30.0)
    for layer in ("coastline", "airports", "big_roads"):
        _old_cache(55, 12, layer, 1)
    cache = _old_cache(55, 12, "water", 40)
    path = EXTRACT.answer_path(55, 12, "water")
    with open(path, "wb") as f:  # cut: not even bz2
        f.write(b"BZh9 cut")
    # A present answer counts as prepared...
    assert GEOFABRIK.needed_layers(55, 12, 1) == {}
    layer = OSM.OSM_layer()
    assert OSM.OSM_queries_to_OSM_layer(
        VMAP.WATER_QUERIES, layer, 55, 12, ["name"], cached_suffix="water")
    assert any("not used" in line and "keeping the cached layer" in line
               for line in gf)
    # ...but step 1 rejected it: gone, so the next preparation asks again.
    assert not os.path.exists(path)
    assert set(GEOFABRIK.needed_layers(55, 12, 1)) == {"water"}
    assert os.path.isfile(cache)


def test_answer_older_than_the_cache_does_not_block(gf, monkeypatch):
    monkeypatch.setattr(GEOFABRIK, "osm_cache_max_age", 30.0)
    for layer in ("coastline", "airports", "big_roads"):
        _old_cache(55, 12, layer, 1)
    statements = EXTRACT.layer_statements(1)["water"]
    path = EXTRACT.answer_path(55, 12, "water")
    EXTRACT.write_answer(path, EXTRACT.answer_xml(statements, "x", "2026",
                                                  {}, {}, {}))
    t = time.time() - 50 * DAY
    os.utime(path, (t, t))
    _old_cache(55, 12, "water", 40)
    assert set(GEOFABRIK.needed_layers(55, 12, 1)) == {"water"}
    layer = OSM.OSM_layer()
    assert OSM.OSM_queries_to_OSM_layer(
        VMAP.WATER_QUERIES, layer, 55, 12, ["name"], cached_suffix="water")
    assert not os.path.exists(path)
