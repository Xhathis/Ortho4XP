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
    # Never ask the real Overpass from a test (#46).
    monkeypatch.setattr(OSM, "overpass_answers", lambda bbox=None: True)
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


# --- waiting until Overpass answers (#46) --------------------------------------
def fake_clock(monkeypatch, on_sleep=None):
    clock = [1000.0]
    monkeypatch.setattr(TILE.time, "time", lambda: clock[0])

    def sleep(s):
        clock[0] += s
        if on_sleep:
            on_sleep(clock[0])

    monkeypatch.setattr(TILE.time, "sleep", sleep)
    return clock


def answers(monkeypatch, replies):
    asked = []

    def probe(bbox=None):
        asked.append(bbox)
        return replies[min(len(asked), len(replies)) - 1]

    monkeypatch.setattr(OSM, "overpass_answers", probe)
    return asked


def test_wait_until_overpass_answers(lines, monkeypatch):
    clock = fake_clock(monkeypatch)
    asked = answers(monkeypatch, [False, False, True])
    monkeypatch.setattr(TILE, "overpass_retry_wait", 600)
    monkeypatch.setattr(TILE, "overpass_probe_interval", 300)
    assert TILE._wait_for_overpass_retry([(64, -14)], 1000.0)
    assert len(asked) == 3
    assert clock[0] == pytest.approx(1000.0 + 600 + 2 * 300)
    assert any("checking again every" in l for l in lines)
    assert "answers again after" in lines[-1]


def test_no_message_when_overpass_answers_at_once(lines, monkeypatch):
    fake_clock(monkeypatch)
    answers(monkeypatch, [True])
    assert TILE._wait_for_overpass_retry([(64, -14)], 0.0)
    assert len(lines) == 1 and "as soon as Overpass answers" in lines[0]


def test_wait_gives_up_after_max(lines, monkeypatch):
    clock = fake_clock(monkeypatch)
    asked = answers(monkeypatch, [False])
    monkeypatch.setattr(TILE, "overpass_probe_interval", 300)
    monkeypatch.setattr(TILE, "overpass_wait_max", 900)
    assert TILE._wait_for_overpass_retry([(64, -14)], 1000.0)
    assert len(asked) == 4  # at 0, 300, 600 and 900 s
    assert clock[0] == pytest.approx(1900.0)
    assert "trying anyway" in lines[-1]


def test_stop_while_checking(lines, monkeypatch):
    def press_stop(now):
        if now >= 1600:
            UI.stop_requested = True

    fake_clock(monkeypatch, press_stop)
    answers(monkeypatch, [False])
    monkeypatch.setattr(TILE, "overpass_probe_interval", 300)
    assert TILE._wait_for_overpass_retry([(64, -14)], 1000.0) is False


class FakeResponse:
    def __init__(self, status, content=b""):
        self.status_code, self.content = status, content


def fake_session(monkeypatch, replies):
    """replies: per server URL, a FakeResponse or an exception to raise."""
    asked = []

    class Session:
        headers = {}

        def close(self):
            pass

        def get(self, url, timeout):
            asked.append(url)
            reply = replies[url.split("?")[0]]
            if isinstance(reply, Exception):
                raise reply
            return reply

    monkeypatch.setattr(OSM.requests, "Session", Session)
    monkeypatch.setattr(OSM, "overpass_servers",
                        {k: k for k in replies})
    return asked


OSM_EMPTY = b'<?xml version="1.0"?>\n<osm version="0.6">\n</osm>\n'


@pytest.mark.parametrize("first, second, expected", [
    (OSM.requests.ConnectionError("down"), FakeResponse(200, OSM_EMPTY), True),
    (FakeResponse(200, OSM_EMPTY), OSM.requests.ConnectionError("x"), True),
    (OSM.requests.ConnectTimeout("t"), FakeResponse(504, b"Gateway"), False),
    (FakeResponse(200, b"<html>busy</html>"), OSM.requests.ReadTimeout("r"),
     False),
])
def test_overpass_answers(monkeypatch, first, second, expected):
    monkeypatch.setattr(UI, "vprint", lambda *a: None)
    monkeypatch.setattr(OSM, "_prefer_ipv4_without_ipv6_route", lambda: None)
    asked = fake_session(monkeypatch, {"http://a": first, "http://b": second})
    assert OSM.overpass_answers() is expected
    # A tiny query, and the second server only when the first fails.
    assert all(u.endswith("?data=node(0,0,0,0);out;") for u in asked)
    assert len(asked) == (1 if first.__class__ is FakeResponse
                          and expected else 2)


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


def test_wait_asks_about_the_first_tile(lines, monkeypatch):
    # The check is a real query on the first tile to retry (#78), not the
    # empty box an overloaded server still answered.
    fake_clock(monkeypatch)
    asked = answers(monkeypatch, [True])
    assert TILE._wait_for_overpass_retry([(64, -14), (65, -14)], 0.0)
    assert asked == [(64, -14, 65, -13)]


COUNT_ANSWER = (b'<?xml version="1.0"?>\n<osm version="0.6">\n'
                b'  <count id="0"><tag k="total" v="12"/></count>\n</osm>\n')
REMARK_ANSWER = (b'<?xml version="1.0"?>\n<osm version="0.6">\n<remark> '
                 b'runtime error: Query timed out </remark>\n</osm>\n')


@pytest.mark.parametrize("first, second, expected, tries", [
    (FakeResponse(200, COUNT_ANSWER), None, True, 1),
    # HTTP 200 with a remark is Overpass's way of saying it failed.
    (FakeResponse(200, REMARK_ANSWER), FakeResponse(200, COUNT_ANSWER), True, 2),
    (FakeResponse(200, REMARK_ANSWER), OSM.requests.ReadTimeout("r"), False, 2),
    # The empty-box answer has no count: not an answer to the count query.
    (FakeResponse(200, OSM_EMPTY), FakeResponse(504, b"Gateway"), False, 2),
])
def test_overpass_answers_with_bbox(monkeypatch, first, second, expected, tries):
    monkeypatch.setattr(UI, "vprint", lambda *a: None)
    monkeypatch.setattr(OSM, "_prefer_ipv4_without_ipv6_route", lambda: None)
    asked = fake_session(monkeypatch, {"http://a": first, "http://b": second})
    assert OSM.overpass_answers((64, -14, 65, -13)) is expected
    assert len(asked) == tries
    assert all(u.endswith('?data=[out:xml][timeout:60];'
                          'nwr["aeroway"](64, -14, 65, -13);out count;')
               for u in asked)


# --- #78: the retry pass ends after overpass_retry_give_up failures in a row ---
SIX = [(60, 0), (60, 1), (60, 2), (60, 3), (60, 4), (60, 5)]


@pytest.mark.parametrize("second_try, tried_again, built", [
    # Outage still on: 3 tiles in a row fail again, the other 3 are not tried.
    ({}, SIX[:3], []),
    # A success resets the count: 60,1 builds, then 60,2-60,4 fail in a row.
    ({(60, 1): 0}, SIX[:5], [(60, 1)]),
])
def test_sequential_retry_gives_up(lines, monkeypatch, second_try,
                                   tried_again, built):
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)
    fails = {t: 2 for t in SIX}
    for t, n in second_try.items():
        fails[t] = 1 + n
    calls = []
    monkeypatch.setattr(TILE, "_build_one_tile", fake_one(calls, fails))
    TILE.build_tile_list(FakeTile(), SIX, 1, 1, 1, 1, 0, 0)
    phase1 = [t for (t, osm) in calls if osm]
    assert phase1 == SIX + tried_again
    assert [t for (t, osm) in calls if not osm] == built
    gave_up = [l for l in lines if "in a row again" in l]
    assert len(gave_up) == 1
    rest = [t for t in SIX if t not in tried_again]
    assert gave_up[0].endswith(
        " ".join(FNAMES.short_latlon(*t) for t in rest))


def test_sequential_retry_no_give_up_at_the_end(lines, monkeypatch):
    # Failing again on the last 3 tiles leaves nothing to give up.
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)
    calls = []
    monkeypatch.setattr(TILE, "_build_one_tile",
                        fake_one(calls, {t: 2 for t in SIX[:3]}))
    TILE.build_tile_list(FakeTile(), SIX[:3], 1, 1, 1, 1, 0, 0)
    assert [t for (t, osm) in calls if osm] == SIX[:3] * 2
    assert not any("in a row again" in l for l in lines)


@pytest.mark.parametrize("codes, started_n", [
    ([TILE.OVERPASS_EXIT_CODE] * 6, 3),
    # The success of the 2nd resets the count.
    ([TILE.OVERPASS_EXIT_CODE, 0] + [TILE.OVERPASS_EXIT_CODE] * 4, 5),
    # Another step 1 error is not an Overpass failure either.
    ([TILE.OVERPASS_EXIT_CODE, 10] + [TILE.OVERPASS_EXIT_CODE] * 4, 5),
])
def test_parallel_retry_gives_up(lines, monkeypatch, tmp_path, codes,
                                 started_n):
    monkeypatch.setattr(FNAMES, "Tmp_dir", str(tmp_path))
    monkeypatch.setattr(TILE.time, "sleep", lambda s: None)
    started = fake_popen(monkeypatch, {t: [c] for t, c in zip(SIX, codes)})
    result = TILE._run_batch_phase(
        FakeTile(), SIX, (1, 1, 0, 0, 0, 0), 1, last_phase=False,
        context_file="", give_up_after=TILE.overpass_retry_give_up)
    assert [t for (t, _) in started] == SIX[:started_n]
    # Every tile not built is in the result, tried or not.
    not_ok = [FNAMES.short_latlon(*t) for t, c in zip(SIX, codes) if c]
    not_ok += [FNAMES.short_latlon(*t) for t in SIX[started_n:]
               if FNAMES.short_latlon(*t) not in not_ok]
    assert sorted(c for (c, _) in result) == sorted(not_ok)
    assert sum("in a row again" in l for l in lines) == 1


def test_parallel_first_pass_never_gives_up(lines, monkeypatch, tmp_path):
    monkeypatch.setattr(FNAMES, "Tmp_dir", str(tmp_path))
    monkeypatch.setattr(TILE.time, "sleep", lambda s: None)
    started = fake_popen(monkeypatch,
                         {t: [TILE.OVERPASS_EXIT_CODE] for t in SIX})
    retry = {}
    TILE._run_batch_phase(
        FakeTile(), SIX, (1, 1, 0, 0, 0, 0), 1, last_phase=False,
        context_file="", retry=retry)
    assert len(started) == 6 and sorted(retry) == SIX
