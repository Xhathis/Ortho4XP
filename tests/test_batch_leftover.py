"""The tiles a batch did not build are kept for the tile window (#79)."""
import os

import pytest

import O4_File_Names as FNAMES
import O4_OSM_Utils as OSM
import O4_Tile_Utils as TILE
import O4_UI_Utils as UI

from test_overpass_batch_retry import (  # noqa: F401 (lines is a fixture)
    FakeTile, fake_popen, lines,
)

SIX = [(60, 0), (60, 1), (60, 2), (60, 3), (60, 4), (60, 5)]


def path():
    return TILE.leftover_tiles_path()


@pytest.fixture(autouse=True)
def no_leftover_file():
    # Other tests run batches in the same sandbox folder too.
    if os.path.exists(path()):
        os.remove(path())
    yield


def test_write_read_roundtrip():
    TILE.write_leftover_tiles([(55, 12), (-7, 72), (61, -50)])
    assert os.path.dirname(path()) == os.path.abspath(".")
    text = open(path(), encoding="utf-8").read()
    assert text.startswith("# Tiles of the last batch")
    assert "+55+012\n-07+072\n+61-050\n" in text
    assert TILE.read_leftover_tiles() == [(55, 12), (-7, 72), (61, -50)]
    TILE.write_leftover_tiles([])
    assert not os.path.exists(path())
    assert TILE.read_leftover_tiles() == []
    TILE.write_leftover_tiles([])  # nothing to remove: no error


def test_read_skips_what_is_not_a_tile():
    with open(path(), "w", encoding="utf-8") as f:
        f.write("# comment\n+55+012\n\n  +56+010  \nrubbish\n+95+000\n"
                "+55+012\n+10-180\n+10+180\n55 12\n")
    assert TILE.read_leftover_tiles() == [(55, 12), (56, 10), (10, -180)]
    os.remove(path())


def fake_build(calls, fail=(), sea=()):
    def one(tile, lat, lon, *flags):
        calls.append((lat, lon))
        OSM.overpass_gave_up = False
        if (lat, lon) in sea:
            return TILE.SEA_SKIPPED
        if (lat, lon) in fail:
            UI.red_flag = True
            return TILE.BATCH_STEPS[1]
        return None
    return one


def test_sequential_batch_keeps_what_is_not_built(lines, monkeypatch):
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)
    seen = []

    def one(tile, lat, lon, *flags):
        # While the batch runs the file holds this tile and the later ones.
        seen.append(TILE.read_leftover_tiles())
        return fake_build([], fail={(60, 2)}, sea={(60, 4)})(
            tile, lat, lon, *flags)

    monkeypatch.setattr(TILE, "_build_one_tile", one)
    TILE.build_tile_list(FakeTile(), SIX, 1, 1, 0, 0, 0, 0)
    # One phase (steps 1-2): the failed tile stays, built and sea go.
    assert TILE.read_leftover_tiles() == [(60, 2)]
    assert seen[0] == SIX
    assert seen[3] == [(60, 2), (60, 3), (60, 4), (60, 5)]
    os.remove(path())


def test_sequential_two_phases(lines, monkeypatch):
    # A tile is done only after the last phase.
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)
    seen = []

    def one(tile, lat, lon, do_osm, *flags):
        seen.append((do_osm, TILE.read_leftover_tiles()))
        return None

    monkeypatch.setattr(TILE, "_build_one_tile", one)
    TILE.build_tile_list(FakeTile(), SIX[:2], 1, 1, 1, 1, 0, 0)
    assert seen == [(1, SIX[:2]), (1, SIX[:2]), (0, SIX[:2]), (0, [SIX[1]])]
    assert not os.path.exists(path())  # all built


def test_stop_keeps_the_rest(lines, monkeypatch):
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)

    def one(tile, lat, lon, *flags):
        if (lat, lon) == (60, 2):
            UI.stop_requested = True
            UI.red_flag = True
            return TILE.BATCH_STEPS[0]
        return None

    monkeypatch.setattr(TILE, "_build_one_tile", one)
    TILE.build_tile_list(FakeTile(), SIX, 1, 1, 0, 0, 0, 0)
    assert TILE.read_leftover_tiles() == SIX[2:]
    os.remove(path())


def test_a_new_batch_replaces_the_list(lines, monkeypatch):
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 1)
    TILE.write_leftover_tiles(SIX)
    monkeypatch.setattr(TILE, "_build_one_tile",
                        fake_build([], fail={(1, 1)}))
    TILE.build_tile_list(FakeTile(), [(1, 1), (1, 2)], 1, 0, 0, 0, 0, 0)
    assert TILE.read_leftover_tiles() == [(1, 1)]
    os.remove(path())


def test_busy_gui_writes_nothing(lines, monkeypatch):
    UI.is_working = True
    try:
        assert TILE.build_tile_list(FakeTile(), SIX, 1, 0, 0, 0, 0, 0) == 0
    finally:
        UI.is_working = False
    assert not os.path.exists(path())


def test_parallel_batch(lines, monkeypatch, tmp_path):
    monkeypatch.setattr(FNAMES, "Tmp_dir", str(tmp_path))
    monkeypatch.setattr(TILE.time, "sleep", lambda s: None)
    monkeypatch.setattr(TILE, "batch_parallel_tiles", 3)
    fake_popen(monkeypatch, {
        (60, 0): [0], (60, 1): [11], (60, 2): [TILE.SEA_EXIT_CODE],
        (60, 3): [0]})
    TILE.build_tile_list(FakeTile(), SIX[:4], 1, 1, 0, 0, 0, 0)
    assert TILE.read_leftover_tiles() == [(60, 1)]
    os.remove(path())
