"""Batches and imagery outages (#112).

Overpass outages hold step 1 back (#81); nothing held step 3 back when the
imagery provider failed, so every tile downloaded into the outage and
failed. A tile that failed step 3 only on imagery now goes back into the
queue, and after imagery_pause_after such tiles in a row no tile starts
step 3 until the provider answers a probe.
"""
import pytest

import O4_File_Names as FNAMES
import O4_Imagery_Utils as IMG
import O4_Tile_Utils as TILE
import O4_UI_Utils as UI

from test_overpass_batch_retry import FakeTile, fake_clock, fake_popen

STEP3 = TILE.BATCH_STEPS[3]
SIX = [(60, 0), (60, 1), (60, 2), (60, 3), (60, 4), (60, 5)]
TILES = [(63, -17), (64, -14), (65, -20)]


# --- the signal -----------------------------------------------------------------
@pytest.mark.parametrize("dsf_ok, conv, down, white, expected", [
    (1, [], [("a",)], [], True),          # downloads failed
    (1, [], [], ["x.jpg"], True),         # partly white
    (1, [], [("a",)], ["x.jpg"], True),
    (0, [], [("a",)], [], False),         # the DSF failed too
    (1, ["x.dds"], [("a",)], [], False),  # a conversion failed too
    (1, [], [], [], False),               # nothing missing
])
def test_only_imagery_missing(dsf_ok, conv, down, white, expected):
    assert TILE.only_imagery_missing(dsf_ok, conv, down, white) is expected


def test_worker_exit_codes(lines, monkeypatch):
    monkeypatch.setattr(TILE, "_build_one_tile", lambda *a: STEP3)
    monkeypatch.setattr(TILE, "imagery_gave_up", True)
    assert TILE.batch_worker(FakeTile(), "001100") == TILE.IMAGERY_EXIT_CODE
    monkeypatch.setattr(TILE, "imagery_gave_up", False)
    assert TILE.batch_worker(FakeTile(), "001100") == 13
    assert TILE.IMAGERY_EXIT_CODE not in (
        0, 1, 2, TILE.SEA_EXIT_CODE, TILE.OVERPASS_EXIT_CODE)
    assert TILE.IMAGERY_EXIT_CODE < 10


def test_step3_passed():
    assert TILE._step3_passed(None)
    assert TILE._step3_passed(TILE.BATCH_STEPS[4])  # overlay after step 3
    assert not TILE._step3_passed(STEP3)
    assert not TILE._step3_passed(TILE.BATCH_STEPS[2])


# --- the gate -------------------------------------------------------------------
def test_gate_pauses_after_two_in_a_row(lines, monkeypatch):
    clock = fake_clock(monkeypatch)
    monkeypatch.setattr(TILE, "imagery_retry_wait", 600)
    assert TILE.imagery_pause_after == 2
    gate = TILE._ImageryGate("GO2", 16)
    assert gate.failed(60, 0)
    gate.answered()  # a success in between resets the count
    assert gate.failed(60, 1)
    assert gate.paused is None and gate.can_start(60, 3)
    assert gate.failed(60, 2)
    assert gate.paused == clock[0]
    assert any("Imagery failed for 2 tiles in a row" in l and "GO2" in l
               for l in lines)
    assert not gate.can_start(60, 3)  # held while paused
    gate.answered()
    assert gate.can_start(60, 3)
    assert not gate.can_start(60, 2)  # its own 600 s
    clock[0] += 600
    assert gate.can_start(60, 2)


def test_gate_tries_per_tile(lines):
    gate = TILE._ImageryGate("GO2", 16)
    assert TILE.imagery_tile_tries == 3
    assert gate.failed(64, -14)
    gate.answered()
    assert gate.failed(64, -14)
    gate.answered()
    assert gate.failed(64, -14) is False
    assert any("+64-014 did not get all its imagery in 3 tries." in l
               for l in lines)
    assert any("try 2 of 3" in l for l in lines)


def probes(monkeypatch, replies):
    asked = []

    def answer(lat, lon, zl, code):
        asked.append((lat, lon, zl, code))
        return replies.pop(0) if replies else False

    monkeypatch.setattr(IMG, "provider_answers", answer)
    return asked


def test_gate_probe(lines, monkeypatch):
    clock = fake_clock(monkeypatch)
    asked = probes(monkeypatch, [False, True])
    monkeypatch.setattr(TILE, "imagery_probe_interval", 300)
    gate = TILE._ImageryGate("GO2", 15)
    gate.failed(60, 0)
    gate.failed(60, 1)
    gate.poll([(60, 4)])
    assert asked == []  # not before the interval
    clock[0] += 300
    gate.poll([(60, 4)])  # starts the probe (synchronous in the tests)
    gate.poll([(60, 4)])  # reads it: no image
    assert asked == [(60, 4, 15, "GO2")] and gate.paused is not None
    clock[0] += 300
    gate.poll([(60, 4)])
    gate.poll([(60, 4)])
    assert gate.paused is None
    assert any("provider answers again after" in l for l in lines)


def test_gate_wait_max(lines, monkeypatch):
    clock = fake_clock(monkeypatch)
    probes(monkeypatch, [])
    gate = TILE._ImageryGate("GO2", 16)
    gate.failed(60, 0)
    gate.failed(60, 1)
    clock[0] += TILE.imagery_wait_max
    gate.poll([(60, 4)])
    assert gate.paused is None
    assert any("starting the held tiles anyway" in l for l in lines)


# --- sequential batch -----------------------------------------------------------
def fake_one(calls, imagery_fails, other_fails=()):
    """_build_one_tile whose step 3 fails on imagery imagery_fails[t] times
    for tile t (then succeeds), and otherwise for the tiles in other_fails."""
    def one(tile, lat, lon, do_osm, do_mesh, do_mask, do_dsf, *rest):
        calls.append(((lat, lon), do_dsf, TILE.time.time()))
        TILE.imagery_gave_up = False
        if do_dsf and imagery_fails.get((lat, lon), 0):
            imagery_fails[(lat, lon)] -= 1
            TILE.imagery_gave_up = True
            UI.red_flag = True
            return STEP3
        if do_dsf and (lat, lon) in other_fails:
            UI.red_flag = True
            return STEP3
        return None
    return one


def test_sequential_retry_succeeds(lines, monkeypatch):
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)
    calls = []
    monkeypatch.setattr(TILE, "_build_one_tile",
                        fake_one(calls, {(64, -14): 1}))
    assert TILE.build_tile_list(FakeTile(), TILES, 0, 1, 1, 1, 0, 0) == 1
    phase2 = [c[0] for c in calls if c[1]]
    assert phase2 == TILES + [(64, -14)]
    assert any("imagery missing, try 1 of 3" in l for l in lines)
    assert any("Tiles built: 3, failed: 0." in l for l in lines)


def test_sequential_fails_after_three_tries(lines, monkeypatch):
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)
    calls = []
    monkeypatch.setattr(TILE, "_build_one_tile",
                        fake_one(calls, {(64, -14): 9}))
    assert TILE.build_tile_list(FakeTile(), TILES, 0, 0, 1, 1, 0, 0) == 0
    assert [c[0] for c in calls].count((64, -14)) == 3
    assert any(f"FAILED: +64-014 in step {STEP3}" in l for l in lines)
    assert any("Tiles built: 2, failed: 1." in l for l in lines)


def test_sequential_other_step3_error_not_retried(lines, monkeypatch):
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)
    calls = []
    monkeypatch.setattr(TILE, "_build_one_tile",
                        fake_one(calls, {}, other_fails=[(64, -14)]))
    assert TILE.build_tile_list(FakeTile(), TILES, 0, 0, 1, 1, 0, 0) == 0
    assert [c[0] for c in calls].count((64, -14)) == 1
    assert not any("tried again" in l for l in lines)


def test_sequential_pause_holds_tiles(lines, monkeypatch):
    # The first 2 tiles lose step 3 to imagery once: the batch pauses until
    # the probe (300 s later) gets an image; the failed tiles come back
    # 600 s after their failure.
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)
    monkeypatch.setattr(TILE, "imagery_retry_wait", 600)
    monkeypatch.setattr(TILE, "imagery_probe_interval", 300)
    fake_clock(monkeypatch)
    asked = probes(monkeypatch, [True])
    calls = []
    monkeypatch.setattr(TILE, "_build_one_tile", fake_one(
        calls, {t: 1 for t in SIX[:2]}))
    tile = FakeTile()
    assert TILE.build_tile_list(tile, SIX, 0, 0, 1, 1, 0, 0) == 1
    order = [c[0] for c in calls]
    assert order == SIX + SIX[:2]
    when = {}
    for c in calls:
        when.setdefault(c[0], []).append(c[2])
    assert when[(60, 2)][0] >= 1300.0  # after the probe
    assert asked == [(60, 2, 16, "GO2")]
    assert when[(60, 0)][1] >= 1600.0
    assert any("Tiles built: 6, failed: 0." in l for l in lines)


def test_sequential_stop_while_paused(lines, monkeypatch):
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)

    def press_stop(now):
        if now >= 1100:
            UI.stop_requested = True

    fake_clock(monkeypatch, press_stop)
    probes(monkeypatch, [])
    calls = []
    monkeypatch.setattr(TILE, "_build_one_tile",
                        fake_one(calls, {t: 9 for t in SIX}))
    assert TILE.build_tile_list(FakeTile(), SIX, 0, 0, 1, 1, 0, 0) == 0
    assert [c[0] for c in calls] == SIX[:2]
    assert any("stopped while waiting for the imagery provider" in l
               for l in lines)


# --- parallel batch -------------------------------------------------------------
def test_parallel_phase_requeues(lines, monkeypatch, tmp_path):
    monkeypatch.setattr(FNAMES, "Tmp_dir", str(tmp_path))
    monkeypatch.setattr(TILE.time, "sleep", lambda s: None)
    started = fake_popen(monkeypatch, {
        (1, 0): [0], (2, 0): [TILE.IMAGERY_EXIT_CODE, 0], (3, 0): [13],
        (4, 0): [TILE.IMAGERY_EXIT_CODE]})
    result = TILE._run_batch_phase(
        FakeTile(), [(1, 0), (2, 0), (3, 0), (4, 0)], (0, 0, 1, 1, 0, 0), 3,
        last_phase=True, context_file="",
        igate=TILE._ImageryGate("GO2", 16))
    assert sorted(result) == [("+03+000", STEP3), ("+04+000", STEP3)]
    tiles = [t for (t, _) in started]
    assert tiles.count((2, 0)) == 2 and tiles.count((4, 0)) == 3
    # Without a gate the imagery exit code is a step 3 failure.
    result = TILE._run_batch_phase(
        FakeTile(), [(4, 0)], (0, 0, 1, 1, 0, 0), 3,
        last_phase=True, context_file="")
    assert result == [("+04+000", STEP3)]


def test_parallel_pause_holds_tiles(lines, monkeypatch, tmp_path):
    monkeypatch.setattr(FNAMES, "Tmp_dir", str(tmp_path))
    monkeypatch.setattr(TILE, "imagery_retry_wait", 600)
    monkeypatch.setattr(TILE, "imagery_probe_interval", 300)
    fake_clock(monkeypatch)
    asked = probes(monkeypatch, [False, True])
    started = fake_popen(monkeypatch, {
        t: ([TILE.IMAGERY_EXIT_CODE, 0] if t in SIX[:2] else [0])
        for t in SIX})
    result = TILE._run_batch_phase(
        FakeTile(), SIX, (0, 0, 1, 1, 0, 0), 1, last_phase=True,
        context_file="", igate=TILE._ImageryGate("GO2", 16))
    assert result == []
    when = {}
    for ((t, _), at) in zip(started, started.starts):
        when.setdefault(t, []).append(at)
    assert when[(60, 2)][0] >= 1600  # second probe, 600 s into the pause
    assert len(asked) == 2
    assert all(len(when[t]) == 2 for t in SIX[:2])


def test_parallel_batch_requeue_in_phase2(lines, monkeypatch, tmp_path):
    monkeypatch.setattr(FNAMES, "Tmp_dir", str(tmp_path))
    monkeypatch.setattr(TILE.time, "sleep", lambda s: None)
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 3)
    started = fake_popen(monkeypatch, {
        (63, -17): [0], (64, -14): [0, TILE.IMAGERY_EXIT_CODE, 0],
        (65, -20): [0]})
    assert TILE.build_tile_list(FakeTile(), TILES, 0, 1, 1, 1, 0, 0) == 1
    phase2 = [t for (t, flags) in started if flags.startswith("001")]
    assert phase2.count((64, -14)) == 2
    assert [l for l in lines if l.startswith("Tiles built")] == [
        "Tiles built: 3, failed: 0."]


# --- the probe ------------------------------------------------------------------
def test_provider_answers(monkeypatch):
    asked = []
    monkeypatch.setattr(IMG, "providers_dict", {
        "GO2": {"code": "GO2", "grid_type": "webmercator", "max_zl": 15},
        "WMS": {"code": "WMS"}})
    monkeypatch.setattr(IMG, "combined_providers_dict", {
        "MIX": [{"layer_code": "GO2"}, {"layer_code": "WMS"}]})

    def wmts(zl, til_x, til_y, provider, session):
        asked.append(("wmts", provider["code"], zl, til_x, til_y))
        return (1, None)

    def wms(bbox, epsg, size, provider):
        asked.append(("wms", provider["code"], epsg, size))
        return (0, None)

    monkeypatch.setattr(IMG, "get_wmts_image", wmts)
    monkeypatch.setattr(IMG, "build_texture_from_bbox_and_size", wms)
    assert IMG.provider_answers(55, 12, 16, "GO2") is True
    assert asked[-1][:3] == ("wmts", "GO2", 15)  # capped at max_zl
    assert asked[-1][3:] == IMG.GEO.wgs84_to_gtile(55.5, 12.5, 15)
    assert IMG.provider_answers(55, 12, 16, "MIX") is True  # first layer
    assert IMG.provider_answers(55, 12, 16, "WMS") is False
    assert asked[-1] == ("wms", "WMS", "3857", (256, 256))
    assert IMG.provider_answers(55, 12, 16, "nope") is False
