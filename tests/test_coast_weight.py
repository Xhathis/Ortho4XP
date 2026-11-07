"""#55: the coastline is only loaded for the weight map when it can matter."""
import types

import numpy
import pytest

import O4_Mesh_Utils as MESH
import O4_OSM_Utils as OSM
import O4_UI_Utils as UI


def _tile(curv, coast, apt=None):
    return types.SimpleNamespace(
        lat=55, lon=12, curvature_tol=curv, coast_curv_tol=coast,
        apt_curv_tol=curv if apt is None else apt, coast_curv_ext=0.5,
        apt_curv_ext=0.5,
    )


@pytest.fixture
def osm(monkeypatch):
    calls = []
    state = {"ok": 1}

    def queries(queries, layer, lat, lon, tags, cached_suffix=""):
        calls.append(cached_suffix)
        layer.dicosmn[-1] = (12.5, 55.5)
        return state["ok"]

    monkeypatch.setattr(OSM, "OSM_queries_to_OSM_layer", queries)
    monkeypatch.setattr(MESH.os.path, "isfile", lambda p: False)
    monkeypatch.setattr(MESH.os.path, "isdir", lambda p: False)
    monkeypatch.setattr(UI, "lvprint", lambda *a: None)
    return calls, state


def test_coarser_coast_tolerance_loads_no_coastline(osm):
    calls, state = osm
    weights = numpy.ones((1001, 1001), dtype=numpy.float32)
    assert MESH.build_curv_tol_weight_map(_tile(1.0, 10.0), weights) == 1
    assert calls == [] and (weights == 1).all()


def test_finer_coast_tolerance_refines_near_the_coast(osm):
    calls, state = osm
    weights = numpy.ones((1001, 1001), dtype=numpy.float32)
    assert MESH.build_curv_tol_weight_map(_tile(1.0, 0.5), weights) == 1
    assert calls == ["coastline"]
    assert weights[500, 500] == 2 and weights[0, 0] == 1


def test_coastline_failure_fails_the_map(osm):
    calls, state = osm
    state["ok"] = 0
    weights = numpy.ones((1001, 1001), dtype=numpy.float32)
    assert MESH.build_curv_tol_weight_map(_tile(1.0, 0.5), weights) == 0


def test_coarse_airports_still_get_the_coast_where_it_matters(osm, monkeypatch):
    # apt_curv_tol 4 > curvature_tol 1 puts weight 0.25 at airports; a
    # coast_curv_tol of 2 (ratio 0.5) is then still above it there.
    calls, state = osm
    weights = numpy.ones((1001, 1001), dtype=numpy.float32)
    weights[400:600, 400:600] = 0.25  # as if the airport part had run
    monkeypatch.setattr(MESH.pickle, "load", lambda f: {})
    MESH.build_curv_tol_weight_map(_tile(1.0, 2.0, apt=1.0), weights)
    assert calls == ["coastline"]
    assert weights[500, 500] == 0.5
