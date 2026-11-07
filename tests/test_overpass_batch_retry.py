"""Batches try tiles once more whose step 1 lost to an Overpass outage (#44).

2026-11-06: overpass-api.de and the fallback server gave no answer for
about 3.5 hours, and 21 of 66 tiles failed in step 1 for that alone.
"""
import os

import pytest

import O4_File_Names as FNAMES
import O4_OSM_Utils as OSM
import O4_Tile_Utils as TILE
import O4_UI_Utils as UI

STEP1 = TILE.BATCH_STEPS[0]


@pytest.fixture
def lines(monkeypatch):
    monkeypatch.setattr(UI, "log", False)
    out = []
    monkeypatch.setattr(
        UI, "lvprint", lambda level, *a: out.append(" ".join(map(str, a))))
    monkeypatch.setattr(UI, "vprint", lambda *a: None)
    monkeypatch.setattr(UI, "exit_message_and_bottom_line", lambda *a: None)
    monkeypatch.setattr(TILE, "overpass_retry_wait", 0)
    monkeypatch.setattr(OSM, "overpass_gave_up", False)
    UI.is_working = False
    UI.stop_requested = False
    UI.red_flag = False
    yield out
    UI.stop_requested = False
    UI.red_flag = False


class FakeTile:
    custom_build_dir = ""
    default_website = "GO2"
    default_zl = 16
    zone_list = []
    lat = lon = 0


# --- O4_OSM_Utils ---------------------------------------------------------------
def test_layer_failure_sets_flag(lines, monkeypatch):
    def no_answer(query, bbox, **kw):
        OSM.get_overpass_data.last_error = "DE: ConnectTimeout"
        return 0

    monkeypatch.setattr(OSM, "get_overpass_data", no_answer)
    layer = OSM.OSM_layer()
    assert OSM.OSM_queries_to_OSM_layer(
        ['way["natural"="coastline"]'], layer, 64, -14) == 0
    assert OSM.overpass_gave_up is True
    assert UI.red_flag
    assert any("last: DE: ConnectTimeout" in l for l in lines)


def test_ipv4_only_without_ipv6_route(monkeypatch):
    import urllib3.util.connection as conn
    monkeypatch.setattr(conn, "HAS_IPV6", True)
    monkeypatch.setattr(OSM, "_no_ipv6_route", lambda: True)
    monkeypatch.setattr(OSM._prefer_ipv4_without_ipv6_route, "done", False,
                        raising=False)
    OSM._prefer_ipv4_without_ipv6_route()
    assert conn.HAS_IPV6 is False
    import socket
    assert conn.allowed_gai_family() == socket.AF_INET


def test_ipv6_kept_with_route(monkeypatch):
    import urllib3.util.connection as conn
    monkeypatch.setattr(conn, "HAS_IPV6", True)
    monkeypatch.setattr(OSM, "_no_ipv6_route", lambda: False)
    monkeypatch.setattr(OSM._prefer_ipv4_without_ipv6_route, "done", False,
                        raising=False)
    OSM._prefer_ipv4_without_ipv6_route()
    assert conn.HAS_IPV6 is True


def test_no_ipv6_route_returns_bool():
    assert OSM._no_ipv6_route() in (True, False)


# --- helpers --------------------------------------------------------------------
def test_failed_on_overpass(lines, monkeypatch):
    monkeypatch.setattr(OSM, "overpass_gave_up", True)
    assert TILE._failed_on_overpass(STEP1)
    assert not TILE._failed_on_overpass(TILE.BATCH_STEPS[1])
    assert not TILE._failed_on_overpass(None)
    UI.stop_requested = True
    assert not TILE._failed_on_overpass(STEP1)
    UI.stop_requested = False
    monkeypatch.setattr(OSM, "overpass_gave_up", False)
    assert not TILE._failed_on_overpass(STEP1)


def test_wait_counts_from_last_failure(lines, monkeypatch):
    slept = []
    clock = [1000.0]
    monkeypatch.setattr(TILE.time, "time", lambda: clock[0])

    def sleep(s):
        slept.append(s)
        clock[0] += s

    monkeypatch.setattr(TILE.time, "sleep", sleep)
    monkeypatch.setattr(TILE, "overpass_retry_wait", 600)
    assert TILE._wait_for_overpass_retry([(64, -14)], 1000.0 - 450)
    assert sum(slept) == pytest.approx(150)
    assert "+64-014" in lines[-1] and "once more in" in lines[-1]
    slept.clear()
    assert TILE._wait_for_overpass_retry([(64, -14)], 1000.0 - 3600)
    assert slept == []  # failed long ago: no wait


def test_wait_ends_on_stop(lines, monkeypatch):
    monkeypatch.setattr(TILE, "overpass_retry_wait", 600)

    def sleep(s):
        UI.stop_requested = True

    monkeypatch.setattr(TILE.time, "sleep", sleep)
    assert TILE._wait_for_overpass_retry([(64, -14)], TILE.time.time()) is False


def test_step1_resets_flag(lines, monkeypatch):
    seen = []

    class T(FakeTile):
        def read_from_config(self, use_global=False):
            pass

        def make_dirs(self):
            pass

    monkeypatch.setattr(OSM, "overpass_gave_up", True)  # from an earlier tile
    monkeypatch.setattr(TILE.FNAMES, "build_dir", lambda *a: "")
    monkeypatch.setattr(TILE.VMAP, "build_poly_file",
                        lambda tile: seen.append(OSM.overpass_gave_up) or 1)
    assert TILE._build_one_tile(T(), 1, 2, 1, 0, 0, 0, 0, 0) is None
    assert seen == [False]


# --- sequential batch -----------------------------------------------------------
def fake_one(calls, overpass_fails):
    """_build_one_tile whose step 1 fails on Overpass overpass_fails[t]
    times for tile t, then succeeds."""
    def one(tile, lat, lon, do_osm, *rest):
        calls.append(((lat, lon), do_osm))
        if do_osm and overpass_fails.get((lat, lon), 0):
            overpass_fails[(lat, lon)] -= 1
            OSM.overpass_gave_up = True
            UI.red_flag = True
            return STEP1
        OSM.overpass_gave_up = False
        return None
    return one


TILES = [(63, -17), (64, -14), (65, -20)]


def test_sequential_retry_succeeds(lines, monkeypatch):
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)
    calls = []
    monkeypatch.setattr(TILE, "_build_one_tile",
                        fake_one(calls, {(64, -14): 1}))
    assert TILE.build_tile_list(FakeTile(), TILES, 1, 1, 1, 1, 0, 0) == 1
    phase1 = [t for (t, osm) in calls if osm]
    assert phase1 == [(63, -17), (64, -14), (65, -20), (64, -14)]
    phase2 = [t for (t, osm) in calls if not osm]
    assert sorted(phase2) == sorted(TILES)  # the retried tile goes on
    assert any("tried again at the end of this phase" in l for l in lines)
    assert any("Tiles built: 3, failed: 0." in l for l in lines)
    assert not UI.red_flag


def test_sequential_retry_only_once(lines, monkeypatch):
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)
    calls = []
    monkeypatch.setattr(TILE, "_build_one_tile",
                        fake_one(calls, {(64, -14): 5}))
    assert TILE.build_tile_list(FakeTile(), TILES, 1, 1, 1, 1, 0, 0) == 0
    assert [t for (t, osm) in calls if osm].count((64, -14)) == 2
    assert (64, -14) not in [t for (t, osm) in calls if not osm]
    assert any(f"FAILED: +64-014 in step {STEP1}" in l for l in lines)


def test_sequential_other_step1_error_not_retried(lines, monkeypatch):
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)
    calls = []

    def one(tile, lat, lon, do_osm, *rest):
        calls.append((lat, lon))
        OSM.overpass_gave_up = False
        return STEP1 if (lat, lon) == (64, -14) else None

    monkeypatch.setattr(TILE, "_build_one_tile", one)
    assert TILE.build_tile_list(FakeTile(), TILES, 1, 0, 0, 0, 0, 0) == 0
    assert calls.count((64, -14)) == 1
    assert not any("tried again" in l for l in lines)


def test_sequential_stop_while_waiting(lines, monkeypatch):
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)
    monkeypatch.setattr(TILE, "overpass_retry_wait", 600)
    monkeypatch.setattr(TILE.time, "sleep",
                        lambda s: setattr(UI, "stop_requested", True))
    calls = []
    monkeypatch.setattr(TILE, "_build_one_tile",
                        fake_one(calls, {(64, -14): 1}))
    assert TILE.build_tile_list(FakeTile(), TILES, 1, 1, 1, 1, 0, 0) == 0
    assert all(osm for (_, osm) in calls)  # phase 2 never started
    assert any("stopped while waiting for Overpass" in l for l in lines)


# --- parallel batch -------------------------------------------------------------
def test_worker_exit_codes(lines, monkeypatch):
    def failed_step1(tile, lat, lon, *f):
        return STEP1

    monkeypatch.setattr(TILE, "_build_one_tile", failed_step1)
    monkeypatch.setattr(OSM, "overpass_gave_up", True)
    assert TILE.batch_worker(FakeTile(), "110000") == TILE.OVERPASS_EXIT_CODE
    monkeypatch.setattr(OSM, "overpass_gave_up", False)
    assert TILE.batch_worker(FakeTile(), "110000") == 10
    assert TILE.OVERPASS_EXIT_CODE not in (0, 1, 2, TILE.SEA_EXIT_CODE)
    assert TILE.OVERPASS_EXIT_CODE < 10


def fake_popen(monkeypatch, codes):
    """Workers whose exit codes come, per tile, from the lists in codes."""
    started = []

    class FakeProc:
        def __init__(self, args, **kw):
            i = args.index("--batch-worker")
            t = (int(args[i + 1]), int(args[i + 2]))
            started.append((t, args[i + 3]))
            self.code = codes[t].pop(0) if len(codes[t]) > 1 else codes[t][0]

        def poll(self):
            return self.code

    monkeypatch.setattr(TILE.subprocess, "Popen", FakeProc)
    return started


def test_parallel_phase_collects_retry(lines, monkeypatch, tmp_path):
    monkeypatch.setattr(FNAMES, "Tmp_dir", str(tmp_path))
    monkeypatch.setattr(TILE.time, "sleep", lambda s: None)
    fake_popen(monkeypatch, {(1, 0): [0], (2, 0): [TILE.OVERPASS_EXIT_CODE],
                             (3, 0): [10]})
    retry = {}
    result = TILE._run_batch_phase(
        FakeTile(), [(1, 0), (2, 0), (3, 0)], (1, 1, 0, 0, 0, 0), 3,
        last_phase=False, context_file="", retry=retry)
    assert result == [("+03+000", STEP1)]
    assert list(retry) == [(2, 0)]
    # Without a retry dict (the retry pass itself) it is a step 1 failure.
    result = TILE._run_batch_phase(
        FakeTile(), [(2, 0)], (1, 1, 0, 0, 0, 0), 3,
        last_phase=False, context_file="")
    assert result == [("+02+000", STEP1)]
    assert os.path.exists(tmp_path / "batch_+02+000.log")


@pytest.mark.parametrize("second, built_ok", [(0, True),
                                               (TILE.OVERPASS_EXIT_CODE, False)])
def test_parallel_batch_retries_once(lines, monkeypatch, tmp_path, second,
                                     built_ok):
    monkeypatch.setattr(FNAMES, "Tmp_dir", str(tmp_path))
    monkeypatch.setattr(TILE.time, "sleep", lambda s: None)
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 3)
    started = fake_popen(monkeypatch, {
        (63, -17): [0], (64, -14): [TILE.OVERPASS_EXIT_CODE, second, 0],
        (65, -20): [0]})
    r = TILE.build_tile_list(FakeTile(), TILES, 1, 1, 1, 1, 0, 0)
    assert r == (1 if built_ok else 0)
    phase1 = [t for (t, flags) in started if flags.startswith("11")]
    phase2 = [t for (t, flags) in started if flags.startswith("00")]
    assert phase1.count((64, -14)) == 2  # one retry, never more
    assert ((64, -14) in phase2) == built_ok
    summary = [l for l in lines if l.startswith("Tiles built")]
    assert summary == [f"Tiles built: {3 if built_ok else 2}, failed: "
                       f"{0 if built_ok else 1}."]
    assert any("Overpass gave no answer for 1 tile(s): +64-014" in l
               for l in lines)
