"""A tile starts steps 2.5-3 once it and its batch neighbours are through
steps 1-2, not once the whole batch is (#82).

The 346-tile batch of 2026-11-08 held 178 finished tiles for phase 2
behind the slowest step 1 of the batch, Overpass outages included.
"""
import pytest

import O4_File_Names as FNAMES
import O4_Tile_Utils as TILE
from test_overpass_batch_retry import FakeTile

STEP1 = TILE.BATCH_STEPS[0]
A, B, C, D = (60, 0), (60, 1), (62, 5), (62, 6)  # A-B and C-D neighbours


def fake_workers(monkeypatch, durations, codes=None):
    """Workers that end after durations[(tile, phase)] polls (default 1)
    with codes[(tile, phase)] (default 0). Returns the event list
    [("start"|"end", phase, tile)]."""
    codes = codes or {}
    events = []

    class Proc:
        def __init__(self, args, **kw):
            i = args.index("--batch-worker")
            self.t = (int(args[i + 1]), int(args[i + 2]))
            self.phase = 0 if "1" in args[i + 3][:2] else 1
            self.left = durations.get((self.t, self.phase), 1)
            events.append(("start", self.phase, self.t))

        def poll(self):
            self.left -= 1
            if self.left > 0:
                return None
            events.append(("end", self.phase, self.t))
            return codes.get((self.t, self.phase), 0)

    monkeypatch.setattr(TILE.subprocess, "Popen", Proc)
    return events


@pytest.fixture
def batch(lines, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(FNAMES, "Tmp_dir", str(tmp_path))
    monkeypatch.setattr(TILE.time, "sleep", lambda s: None)
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 2)
    return lines


def index(events, *event):
    return events.index(event)


def max_running(events, phase):
    n = peak = 0
    for (what, p, _) in events:
        if p == phase:
            n += 1 if what == "start" else -1
            peak = max(peak, n)
    return peak


def test_phase2_ready():
    in_batch = {A, B, C}
    assert not TILE._phase2_ready(*A, in_batch, {A})  # B not through
    assert TILE._phase2_ready(*A, in_batch, {A, B})
    assert TILE._phase2_ready(*C, in_batch, {C})  # no neighbour in batch
    assert not TILE._phase2_ready(*C, in_batch, {A, B})
    # Across the antimeridian.
    assert not TILE._phase2_ready(10, 179, {(10, 179), (10, -180)},
                                  {(10, 179)})


def test_phase2_waits_for_neighbours_only(batch, monkeypatch):
    # B's step 1 is slow: A waits for it, C and D do not.
    events = fake_workers(monkeypatch, {(B, 0): 8})
    assert TILE.build_tile_list(FakeTile(), [A, B, C, D], 1, 1, 1, 1, 0, 0) == 1
    assert index(events, "start", 1, A) > index(events, "end", 0, B)
    assert index(events, "start", 1, C) < index(events, "end", 0, B)
    assert all(("end", 1, t) in events for t in (A, B, C, D))
    assert max_running(events, 0) <= 2 and max_running(events, 1) <= 2
    assert any("Tiles built: 4, failed: 0." in l for l in batch)


def test_failed_neighbour_releases_tile(batch, monkeypatch):
    events = fake_workers(monkeypatch, {(B, 0): 5}, {(B, 0): 11})
    assert TILE.build_tile_list(FakeTile(), [A, B], 1, 1, 1, 1, 0, 0) == 0
    assert index(events, "start", 1, A) > index(events, "end", 0, B)
    assert ("start", 1, B) not in events
    assert any("FAILED: +60+001 in step 2 (mesh)" in l for l in batch)


def test_sea_neighbour_releases_tile(batch, monkeypatch):
    events = fake_workers(monkeypatch, {(B, 0): 3},
                          {(B, 0): TILE.SEA_EXIT_CODE})
    assert TILE.build_tile_list(FakeTile(), [A, B], 1, 1, 1, 1, 0, 0) == 1
    assert ("end", 1, A) in events and ("start", 1, B) not in events


def test_requeued_neighbour_holds_tile(batch, monkeypatch):
    # B loses step 1 to Overpass and goes back into the queue: A must wait
    # for its second try, which builds it.
    monkeypatch.setattr(TILE, "overpass_retry_wait", 0)
    monkeypatch.setattr(TILE, "overpass_probe_interval", 0)  # pause (#83)
    codes = {(B, 0): TILE.OVERPASS_EXIT_CODE}
    events = fake_workers(monkeypatch, {}, codes)
    real_failed = TILE._OverpassGate.failed

    def failed_once(self, lat, lon):
        codes.pop((B, 0), None)  # the next try succeeds
        return real_failed(self, lat, lon)

    monkeypatch.setattr(TILE._OverpassGate, "failed", failed_once)
    assert TILE.build_tile_list(FakeTile(), [A, B], 1, 1, 1, 1, 0, 0) == 1
    ends_b = [i for i, e in enumerate(events) if e == ("end", 0, B)]
    assert len(ends_b) == 2
    assert index(events, "start", 1, A) > ends_b[1]


def test_one_phase_only(batch, monkeypatch):
    # Steps 2.5-3 alone (meshes from an earlier batch): no waiting at all.
    events = fake_workers(monkeypatch, {})
    assert TILE.build_tile_list(FakeTile(), [A, B, C], 0, 0, 1, 1, 0, 0) == 1
    assert [e for e in events if e[0] == "start"] == [
        ("start", 1, A), ("start", 1, B), ("start", 1, C)]


def test_stop_kills_both_phases(batch, monkeypatch):
    killed = []
    monkeypatch.setattr(TILE, "_kill_process_tree", killed.append)
    fake_workers(monkeypatch, {(B, 0): 50, (C, 1): 50})
    polls = [0]
    real_sleep_calls = []

    def sleep(s):
        real_sleep_calls.append(s)
        polls[0] += 1
        if polls[0] == 10:
            TILE.UI.stop_requested = True

    monkeypatch.setattr(TILE.time, "sleep", sleep)
    assert TILE.build_tile_list(FakeTile(), [A, B, C, D], 1, 1, 1, 1, 0, 0) == 0
    assert len(killed) == 2  # B in phase 1 and C in phase 2
    assert {(p.t, p.phase) for p in killed} == {(B, 0), (C, 1)}
    assert any("2 running tile(s) interrupted" in l for l in batch)
