"""#51: a coastline that cannot be closed stops step 1 instead of dropping the sea."""
import types

import numpy
import pytest
from shapely import geometry

import O4_OSM_Utils as OSM
import O4_UI_Utils as UI
import O4_Vector_Map as VMAP
import O4_Vector_Utils as VECT

# Tile-local coordinates (0..1). Sea to the right of the way (OSM rule).
CROSSING = geometry.MultiLineString([[(0.5, 0.0), (0.5, 1.0)]])
STOPS_INSIDE = geometry.MultiLineString([[(0.5, 0.0), (0.5, 0.6)]])


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(UI, "red_flag", False)
    logged = []
    monkeypatch.setattr(UI, "lvprint", lambda level, *a: logged.append(
        " ".join(str(x) for x in a)))
    VECT.scalx = 0.57
    return logged


def test_closed_coastline_gives_sea():
    sea = VECT.coastline_to_MultiPolygon(CROSSING, 55, 12)
    assert sea is not None and abs(sea.area - 0.5) < 1e-9


def test_coastline_stopping_inside_the_tile_is_an_error(_quiet):
    assert VECT.coastline_to_MultiPolygon(STOPS_INSIDE, 55, 12) is None
    assert "abruptly stops" in _quiet[0]


def _tile():
    dem = types.SimpleNamespace(alt_vec=lambda way: numpy.zeros(len(way)))
    return types.SimpleNamespace(lat=55, lon=12, dem=dem)


def _run_include_sea(monkeypatch, coastline):
    monkeypatch.setattr(OSM, "OSM_queries_to_OSM_layer", lambda *a, **k: 1)
    monkeypatch.setattr(OSM, "OSM_to_MultiLineString", lambda *a: coastline)
    monkeypatch.setattr(VMAP.os.path, "isfile", lambda p: False)
    monkeypatch.setattr(VMAP.os.path, "isdir", lambda p: False)
    vector_map = VECT.Vector_Map()
    result = VMAP.include_sea(vector_map, _tile())
    return result, vector_map


def test_include_sea_stops_step_1_on_a_broken_coastline(monkeypatch, _quiet):
    result, vector_map = _run_include_sea(monkeypatch, STOPS_INSIDE)
    assert result == 0 and UI.red_flag
    assert "SEA" not in vector_map.seeds
    assert any("+55+012" in line and "stopping" in line for line in _quiet)


def test_include_sea_seeds_the_sea_on_a_good_coastline(monkeypatch):
    result, vector_map = _run_include_sea(monkeypatch, CROSSING)
    assert not UI.red_flag
    assert len(vector_map.seeds["SEA"]) == 1
