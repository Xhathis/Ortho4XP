"""Open sea tiles are skipped after one check in step 1 (#41).

No network: Overpass and Viewfinder are replaced by fakes; Elevation_dir
and OSM_dir are the test sandbox (see conftest.py).
"""
import os
import shutil

import numpy
import pytest
from shapely import geometry

import O4_DEM_Utils as DEM
import O4_File_Names as FNAMES
import O4_OSM_Utils as OSM
import O4_Tile_Utils as TILE
import O4_UI_Utils as UI
import O4_Vector_Map as VMAP


@pytest.fixture(autouse=True)
def sandbox(monkeypatch):
    shutil.rmtree(FNAMES.Elevation_dir, ignore_errors=True)
    monkeypatch.setattr(UI, "log", False)
    yield
    shutil.rmtree(FNAMES.Elevation_dir, ignore_errors=True)


def world(monkeypatch, *land):
    tiles = numpy.zeros((180, 360), dtype=numpy.uint8)
    for (lat, lon) in land:
        tiles[89 - lat, (180 + lon) % 360] = 255
    monkeypatch.setattr(DEM.Image, "open", lambda path: tiles)


def put_hgt(lat, lon):
    path = FNAMES.viewfinderpanorama(lat, lon)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(bytes(10))


def no_download(monkeypatch, result=0, no_land=False):
    calls = []

    def fake(lat, lon, verbose=True):
        calls.append((lat, lon))
        if no_land:
            DEM._remember_no_land(
                os.path.basename(FNAMES.viewfinderpanorama(lat, lon)))
        return result

    monkeypatch.setattr(DEM, "_ensure_viewfinder", fake)
    return calls


# --- DEM.default_source_has_no_land ------------------------------------------
def test_sea_in_world_tiles_and_no_file(monkeypatch):
    world(monkeypatch)
    calls = no_download(monkeypatch)
    assert DEM.default_source_has_no_land(-7, 72)
    assert calls == []  # nothing downloaded for a world_tiles sea tile


def test_sea_in_world_tiles_but_file_in_library(monkeypatch):
    world(monkeypatch)
    no_download(monkeypatch)
    put_hgt(-7, 72)
    assert not DEM.default_source_has_no_land(-7, 72)


def test_land_in_world_tiles_with_viewfinder_data(monkeypatch):
    world(monkeypatch, (15, -62))
    calls = no_download(monkeypatch, result=1)
    assert not DEM.default_source_has_no_land(15, -62)
    assert calls == [(15, -62)]


def test_land_in_world_tiles_but_in_no_archive(monkeypatch):
    # +15-061: world_tiles says land, Viewfinder has no file (#40).
    world(monkeypatch, (15, -61))
    no_download(monkeypatch, no_land=True)
    assert DEM.default_source_has_no_land(15, -61)


def test_download_failure_is_not_sea(monkeypatch):
    world(monkeypatch, (15, -61))
    no_download(monkeypatch, result=0)
    assert not DEM.default_source_has_no_land(15, -61)


def test_generic_tif_is_not_sea(monkeypatch):
    world(monkeypatch)
    tif = FNAMES.generic_tif(-7, 72)
    os.makedirs(os.path.dirname(tif), exist_ok=True)
    open(tif, "wb").close()
    try:
        assert not DEM.default_source_has_no_land(-7, 72)
    finally:
        os.remove(tif)


# --- VMAP.sea_only_tile ------------------------------------------------------
class FakeTile:
    def __init__(self, lat=-7, lon=72, custom_dem=""):
        self.lat, self.lon, self.custom_dem = lat, lon, custom_dem


def overpass(monkeypatch, ok=True, coastline=False):
    queries = []

    def fake_query(queries_, layer, lat, lon, tags=[], cached_suffix=""):
        queries.append((queries_, cached_suffix))
        if not ok:
            UI.red_flag = True
        return 1 if ok else 0

    monkeypatch.setattr(OSM, "OSM_queries_to_OSM_layer", fake_query)
    line = geometry.MultiLineString([[(0.2, 0.2), (0.3, 0.3)]])
    monkeypatch.setattr(
        OSM, "OSM_to_MultiLineString",
        lambda layer, lat, lon: line if coastline else
        geometry.MultiLineString(),
    )
    return queries


def test_sea_tile(monkeypatch):
    world(monkeypatch)
    queries = overpass(monkeypatch)
    assert VMAP.sea_only_tile(FakeTile())
    # One request, cached under the name include_sea reads it from.
    assert queries == [(['way["natural"="coastline"]'], "coastline")]


def test_coastline_means_build(monkeypatch):
    world(monkeypatch)
    overpass(monkeypatch, coastline=True)
    assert not VMAP.sea_only_tile(FakeTile())


def test_land_elevation_means_build_without_query(monkeypatch):
    world(monkeypatch, (-7, 72))
    no_download(monkeypatch, result=1)
    queries = overpass(monkeypatch)
    assert not VMAP.sea_only_tile(FakeTile())
    assert queries == []


@pytest.mark.parametrize("custom_dem", ["NED1", "my.tif", "SRTM"])
def test_custom_dem_means_build(monkeypatch, custom_dem):
    world(monkeypatch)
    queries = overpass(monkeypatch)
    assert not VMAP.sea_only_tile(FakeTile(custom_dem=custom_dem))
    assert queries == []


def test_view_chosen_explicitly_is_checked(monkeypatch):
    world(monkeypatch)
    overpass(monkeypatch)
    assert VMAP.sea_only_tile(FakeTile(custom_dem=DEM.available_sources[1]))


def test_custom_coastline_means_build(monkeypatch):
    world(monkeypatch)
    queries = overpass(monkeypatch)
    path = FNAMES.custom_coastline(-7, 72)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").close()
    try:
        assert not VMAP.sea_only_tile(FakeTile())
        assert queries == []
    finally:
        os.remove(path)


def test_failed_query_is_not_sea_and_flags(monkeypatch):
    world(monkeypatch)
    overpass(monkeypatch, ok=False)
    UI.red_flag = False
    try:
        assert not VMAP.sea_only_tile(FakeTile())
        assert UI.red_flag
    finally:
        UI.red_flag = False


# --- batches -----------------------------------------------------------------
def capture_log(monkeypatch):
    lines = []
    monkeypatch.setattr(
        UI, "lvprint", lambda level, *a: lines.append(" ".join(map(str, a))))
    return lines


def test_sequential_batch_counts_sea_apart(monkeypatch):
    lines = capture_log(monkeypatch)
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)
    runs = []

    def fake_one(tile, lat, lon, *flags):
        runs.append((lat, lon, flags[:5]))
        if (lat, lon) == (-7, 72) and flags[0]:
            return TILE.SEA_SKIPPED
        return None

    monkeypatch.setattr(TILE, "_build_one_tile", fake_one)
    UI.is_working = False
    tiles = [(-8, 72), (-7, 72), (-1, 73)]
    assert TILE.build_tile_list(None, tiles, 1, 1, 1, 1, 0, 0) == 1
    # Phase 2 (masks, DSF) never runs for the sea tile.
    phase2 = [(lat, lon) for (lat, lon, f) in runs if f[2]]
    assert phase2 == [(-8, 72), (-1, 73)]
    assert "Tiles built: 2, skipped (open sea): 1, failed: 0." in lines
    assert any("+07+072" in l or "-07+072" in l for l in lines)


def test_summary_unchanged_without_sea(monkeypatch):
    lines = capture_log(monkeypatch)
    TILE._batch_summary(0, 3, [("+55+012", TILE.BATCH_STEPS[0])])
    assert "Tiles built: 2, failed: 1." in lines
    assert "   FAILED: +55+012 in step 1 (vector data)" in lines


def test_sea_and_failure_return_failure(monkeypatch):
    capture_log(monkeypatch)
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)
    monkeypatch.setattr(
        TILE, "_build_one_tile",
        lambda tile, lat, lon, *f: TILE.SEA_SKIPPED if lat == 1
        else TILE.BATCH_STEPS[1] if lat == 2 else None,
    )
    UI.is_working = False
    UI.stop_requested = False
    assert TILE.build_tile_list(None, [(1, 0), (2, 0), (3, 0)],
                                1, 1, 0, 0, 0, 0) == 0


def test_parallel_phase_counts_sea_apart(monkeypatch, tmp_path):
    # Fake worker processes with fixed exit codes: 0 built, 3 sea, 10 +
    # index for a failed step. Log files go to a temp Tmp_dir.
    capture_log(monkeypatch)
    monkeypatch.setattr(FNAMES, "Tmp_dir", str(tmp_path))
    monkeypatch.setattr(TILE.time, "sleep", lambda s: None)
    codes = {"1": 0, "2": TILE.SEA_EXIT_CODE, "3": 10}

    class FakeProc:
        def __init__(self, args, **kw):
            self.code = codes[args[args.index("--batch-worker") + 1]]

        def poll(self):
            return self.code

    monkeypatch.setattr(TILE.subprocess, "Popen", FakeProc)
    UI.stop_requested = False
    tile = type("T", (), {"custom_build_dir": ""})()
    result = TILE._run_batch_phase(
        tile, [(1, 0), (2, 0), (3, 0)], (1, 1, 0, 0, 0, 0), 3,
        last_phase=False, context_file="",
    )
    assert sorted(result) == [
        ("+02+000", TILE.SEA_SKIPPED), ("+03+000", TILE.BATCH_STEPS[0])]
    # The sea tile's worker log is removed like a built one's; the
    # failed tile's log is kept.
    assert sorted(os.listdir(tmp_path)) == ["batch_+03+000.log"]


def test_worker_exit_code(monkeypatch):
    monkeypatch.setattr(TILE, "_build_one_tile",
                        lambda tile, lat, lon, *f: TILE.SEA_SKIPPED)
    assert TILE.batch_worker(FakeTile(), "110000") == TILE.SEA_EXIT_CODE
    assert TILE.SEA_EXIT_CODE not in (0, 1, 2)
    assert TILE.SEA_EXIT_CODE < 10  # step failures are 10 + index
