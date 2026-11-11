"""Batches and Overpass outages (#44, #46, #78, #81).

2026-11-06: overpass-api.de and the fallback server gave no answer for
about 3.5 hours, and 21 of 66 tiles failed in step 1 for that alone.
2026-11-08..10: about 40 of 53 hours; tiles kept starting into the
outage, and the retry pass at the end of the phase took 20.7 h (#81:
the batch now holds such tiles back until Overpass answers).
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
    # The probe runs at once, not in a thread (#81).
    monkeypatch.setattr(TILE, "_run_in_background", lambda fn: [bool(fn())])
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


class _Started(list):
    def __init__(self):
        super().__init__()
        self.starts = []


def fake_popen(monkeypatch, codes):
    """Workers whose exit codes come, per tile, from the lists in codes.

    Returns the list of (tile, flags) started; its .starts holds the
    time.time() of each start.
    """
    started = _Started()
    starts = started.starts

    class FakeProc:
        def __init__(self, args, **kw):
            i = args.index("--batch-worker")
            t = (int(args[i + 1]), int(args[i + 2]))
            started.append((t, args[i + 3]))
            starts.append(TILE.time.time())
            self.code = codes[t].pop(0) if len(codes[t]) > 1 else codes[t][0]

        def poll(self):
            return self.code

    monkeypatch.setattr(TILE.subprocess, "Popen", FakeProc)
    return started



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


# --- #81: the Overpass gate -----------------------------------------------------
SIX = [(60, 0), (60, 1), (60, 2), (60, 3), (60, 4), (60, 5)]
TILES = [(63, -17), (64, -14), (65, -20)]


def cached(monkeypatch, tiles):
    """All OSM layers of these tiles are cached (no Overpass needed)."""
    monkeypatch.setattr(
        TILE._OverpassGate, "needs_overpass",
        lambda self, lat, lon: (lat, lon) not in tiles)


def test_gate_pauses_after_three_in_a_row(lines, monkeypatch):
    clock = fake_clock(monkeypatch)
    cached(monkeypatch, [(60, 5)])
    monkeypatch.setattr(TILE, "overpass_retry_wait", 600)
    gate = TILE._OverpassGate()
    assert gate.failed(60, 0) and gate.failed(60, 1)
    assert gate.paused is None and gate.can_start(60, 3)
    gate.answered()  # a success in between resets the count
    assert gate.failed(60, 2) and gate.failed(60, 3)
    assert gate.paused is None
    assert gate.failed(60, 4)
    assert gate.paused == clock[0]
    assert any("failed 3 tiles in a row" in l for l in lines)
    # Held: needs Overpass. Cached tiles go on. A failed tile waits 600 s.
    assert not gate.can_start(60, 1)
    assert gate.can_start(60, 5)
    gate.answered()
    assert gate.paused is None
    assert gate.can_start(60, 1) is False  # still within its 600 s
    clock[0] += 600
    assert gate.can_start(60, 1)


def test_gate_tries_per_tile(lines, monkeypatch):
    gate = TILE._OverpassGate()
    assert TILE.overpass_tile_tries == 3
    assert gate.failed(64, -14)
    assert gate.failed(64, -14)
    assert gate.failed(64, -14) is False
    assert "+64-014 got no answer from Overpass in 3 tries." in lines[-2]
    assert any("try 2 of 3" in l for l in lines)


def test_gate_probe(lines, monkeypatch):
    clock = fake_clock(monkeypatch)
    asked = answers(monkeypatch, [False, True])
    monkeypatch.setattr(TILE, "overpass_probe_interval", 300)
    gate = TILE._OverpassGate()
    for t in SIX[:3]:
        gate.failed(*t)
    pending = [(60, 4), (61, 7)]
    gate.poll(pending)
    assert asked == []  # not before the first interval
    clock[0] += 300
    gate.poll(pending)  # starts the probe (synchronous here)
    assert asked == [(60, 4, 61, 5)]  # a real query on the first held tile
    gate.poll(pending)  # reads its result: no answer
    assert gate.paused is not None
    gate.poll(pending)
    assert len(asked) == 1  # the next one 300 s later
    clock[0] += 300
    gate.poll(pending)
    gate.poll(pending)
    assert len(asked) == 2 and gate.paused is None
    assert lines[-1].startswith("Overpass answers again after 10m0sec")


def test_gate_wait_max(lines, monkeypatch):
    clock = fake_clock(monkeypatch)
    answers(monkeypatch, [False])
    monkeypatch.setattr(TILE, "overpass_wait_max", 900)
    gate = TILE._OverpassGate()
    for t in SIX[:3]:
        gate.failed(*t)
    for _ in range(10):
        clock[0] += 300
        gate.poll(SIX)
        gate.poll(SIX)
        if gate.paused is None:
            break
    assert gate.paused is None
    assert "starting the held tiles anyway" in lines[-1]


def test_run_in_background_real_thread():
    # A probe that raises counts as no answer, never kills the batch.
    out = TILE._run_in_background(lambda: 1 / 0)
    for _ in range(100):
        if out:
            break
        TILE.time.sleep(0.01)
    assert out == [False]
    out = TILE._run_in_background(lambda: "yes")
    for _ in range(100):
        if out:
            break
        TILE.time.sleep(0.01)
    assert out == [True]


def test_next_startable(lines, monkeypatch):
    assert TILE._next_startable([(1, 0), (2, 0)], None) == 0
    assert TILE._next_startable([], None) is None
    cached(monkeypatch, [(2, 0)])
    gate = TILE._OverpassGate()
    gate.paused = 1.0
    assert TILE._next_startable([(1, 0), (2, 0)], gate) == 1
    assert TILE._next_startable([(1, 0)], gate) is None


def test_step1_passed():
    assert TILE._step1_passed(None)
    assert TILE._step1_passed(TILE.SEA_SKIPPED)
    assert TILE._step1_passed(TILE.BATCH_STEPS[2])
    assert not TILE._step1_passed(STEP1)
    assert not TILE._step1_passed("tile setup")


# --- sequential batch -----------------------------------------------------------
def fake_one(calls, overpass_fails, clock=None):
    """_build_one_tile whose step 1 fails on Overpass overpass_fails[t]
    times for tile t, then succeeds."""
    def one(tile, lat, lon, do_osm, *rest):
        calls.append(((lat, lon), do_osm))
        if clock is not None:
            calls[-1] += (clock[0],)
        if do_osm and overpass_fails.get((lat, lon), 0):
            overpass_fails[(lat, lon)] -= 1
            OSM.overpass_gave_up = True
            UI.red_flag = True
            return STEP1
        OSM.overpass_gave_up = False
        return None
    return one


def test_sequential_retry_succeeds(lines, monkeypatch):
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)
    calls = []
    monkeypatch.setattr(TILE, "_build_one_tile",
                        fake_one(calls, {(64, -14): 1}))
    assert TILE.build_tile_list(FakeTile(), TILES, 1, 1, 1, 1, 0, 0) == 1
    phase1 = [c[0] for c in calls if c[1]]
    assert phase1 == [(63, -17), (64, -14), (65, -20), (64, -14)]
    phase2 = [c[0] for c in calls if not c[1]]
    assert sorted(phase2) == sorted(TILES)  # the retried tile goes on
    assert any("try 1 of 3" in l for l in lines)
    assert any("Tiles built: 3, failed: 0." in l for l in lines)
    assert not UI.red_flag


def test_sequential_fails_after_three_tries(lines, monkeypatch):
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)
    calls = []
    monkeypatch.setattr(TILE, "_build_one_tile",
                        fake_one(calls, {(64, -14): 9}))
    assert TILE.build_tile_list(FakeTile(), TILES, 1, 1, 1, 1, 0, 0) == 0
    assert [c[0] for c in calls if c[1]].count((64, -14)) == 3
    assert (64, -14) not in [c[0] for c in calls if not c[1]]
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


def test_sequential_pause_holds_tiles(lines, monkeypatch):
    # The first 3 tiles lose step 1 to Overpass once: the batch pauses.
    # (60, 3) is cached and goes on; (60, 4) and (60, 5) wait for the
    # probe; the failed tiles come back 600 s after their failure.
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)
    monkeypatch.setattr(TILE, "overpass_retry_wait", 600)
    monkeypatch.setattr(TILE, "overpass_probe_interval", 300)
    clock = fake_clock(monkeypatch)
    asked = answers(monkeypatch, [True])
    cached(monkeypatch, [(60, 3)])
    calls = []
    monkeypatch.setattr(TILE, "_build_one_tile", fake_one(
        calls, {t: 1 for t in SIX[:3]}, clock))
    assert TILE.build_tile_list(FakeTile(), SIX, 1, 1, 0, 0, 0, 0) == 1
    order = [c[0] for c in calls]
    assert order == SIX + SIX[:3]
    when = {}
    for c in calls:
        when.setdefault(c[0], []).append(c[2])
    assert when[(60, 3)][0] == 1000.0  # cached: right away
    assert when[(60, 4)][0] >= 1300.0  # after the probe
    assert asked == [(60, 4, 61, 5)]
    assert when[(60, 0)][1] >= 1600.0  # 600 s after its failure
    assert any("Tiles built: 6, failed: 0." in l for l in lines)


def test_sequential_stop_while_paused(lines, monkeypatch):
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)

    def press_stop(now):
        if now >= 1100:
            UI.stop_requested = True

    fake_clock(monkeypatch, press_stop)
    answers(monkeypatch, [False])
    calls = []
    monkeypatch.setattr(TILE, "_build_one_tile",
                        fake_one(calls, {t: 9 for t in SIX}))
    assert TILE.build_tile_list(FakeTile(), SIX, 1, 1, 1, 1, 0, 0) == 0
    assert [c[0] for c in calls] == SIX[:3]  # held after 3 in a row
    assert all(c[1] for c in calls)  # phase 2 never started
    assert any("stopped while waiting for Overpass" in l for l in lines)


# --- parallel batch -------------------------------------------------------------
def test_parallel_phase_requeues(lines, monkeypatch, tmp_path):
    monkeypatch.setattr(FNAMES, "Tmp_dir", str(tmp_path))
    monkeypatch.setattr(TILE.time, "sleep", lambda s: None)
    started = fake_popen(monkeypatch, {
        (1, 0): [0], (2, 0): [TILE.OVERPASS_EXIT_CODE, 0], (3, 0): [10],
        (4, 0): [TILE.OVERPASS_EXIT_CODE]})
    result = TILE._run_batch_phase(
        FakeTile(), [(1, 0), (2, 0), (3, 0), (4, 0)], (1, 1, 0, 0, 0, 0), 3,
        last_phase=False, context_file="", gate=TILE._OverpassGate())
    assert sorted(result) == [("+03+000", STEP1), ("+04+000", STEP1)]
    tiles = [t for (t, _) in started]
    assert tiles.count((2, 0)) == 2 and tiles.count((4, 0)) == 3
    assert os.path.exists(tmp_path / "batch_+04+000.log")
    # Without a gate (phase 2 has no step 1) it is a step 1 failure.
    result = TILE._run_batch_phase(
        FakeTile(), [(4, 0)], (1, 1, 0, 0, 0, 0), 3,
        last_phase=False, context_file="")
    assert result == [("+04+000", STEP1)]


def test_parallel_pause_holds_tiles(lines, monkeypatch, tmp_path):
    monkeypatch.setattr(FNAMES, "Tmp_dir", str(tmp_path))
    monkeypatch.setattr(TILE, "overpass_retry_wait", 600)
    monkeypatch.setattr(TILE, "overpass_probe_interval", 300)
    fake_clock(monkeypatch)
    asked = answers(monkeypatch, [False, True])
    cached(monkeypatch, [(60, 5)])
    started = fake_popen(monkeypatch, {
        t: ([TILE.OVERPASS_EXIT_CODE, 0] if t in SIX[:3] else [0])
        for t in SIX})
    result = TILE._run_batch_phase(
        FakeTile(), SIX, (1, 1, 0, 0, 0, 0), 1, last_phase=False,
        context_file="", gate=TILE._OverpassGate())
    assert result == []
    when = {}
    for ((t, _), at) in zip(started, started.starts):
        when.setdefault(t, []).append(at)
    assert [t for (t, _) in started][:4] == SIX[:3] + [(60, 5)]
    assert when[(60, 5)][0] < 1010  # cached: not held
    assert when[(60, 3)][0] >= 1600  # second probe, 600 s into the pause
    assert asked == [(60, 3, 61, 4)] * 2
    assert all(len(when[t]) == 2 for t in SIX[:3])


def test_parallel_answer_reopens(lines, monkeypatch, tmp_path):
    # A tile that needed Overpass and got through step 1 (failed in step 2:
    # exit code 11) shows that Overpass answers: the count starts again.
    monkeypatch.setattr(FNAMES, "Tmp_dir", str(tmp_path))
    monkeypatch.setattr(TILE.time, "sleep", lambda s: None)
    codes = [TILE.OVERPASS_EXIT_CODE] * 2 + [11] + [TILE.OVERPASS_EXIT_CODE] * 2
    fake_popen(monkeypatch, {t: [c, 0] for t, c in zip(SIX, codes)})
    gate = TILE._OverpassGate()
    TILE._run_batch_phase(
        FakeTile(), SIX[:5], (1, 1, 0, 0, 0, 0), 1, last_phase=False,
        context_file="", gate=gate)
    assert not any("in a row" in l for l in lines)


@pytest.mark.parametrize("second, built_ok", [(0, True),
                                               (TILE.OVERPASS_EXIT_CODE, False)])
def test_parallel_batch_requeue(lines, monkeypatch, tmp_path, second,
                                built_ok):
    monkeypatch.setattr(FNAMES, "Tmp_dir", str(tmp_path))
    monkeypatch.setattr(TILE.time, "sleep", lambda s: None)
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 3)
    started = fake_popen(monkeypatch, {
        (63, -17): [0],
        (64, -14): [TILE.OVERPASS_EXIT_CODE, second, second, 0],
        (65, -20): [0]})
    r = TILE.build_tile_list(FakeTile(), TILES, 1, 1, 1, 1, 0, 0)
    assert r == (1 if built_ok else 0)
    phase1 = [t for (t, flags) in started if flags.startswith("11")]
    phase2 = [t for (t, flags) in started if flags.startswith("00")]
    assert phase1.count((64, -14)) == (2 if built_ok else 3)
    assert ((64, -14) in phase2) == built_ok
    summary = [l for l in lines if l.startswith("Tiles built")]
    assert summary == [f"Tiles built: {3 if built_ok else 2}, failed: "
                       f"{0 if built_ok else 1}."]
