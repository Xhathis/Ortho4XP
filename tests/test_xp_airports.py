"""Airports X-Plane flattens, matched in step 1 (#115)."""
import json
import os
import types

import pytest
from shapely import geometry

import O4_File_Names as FNAMES
import O4_Vector_Map as VMAP
import O4_XP_Airports as XPAPT

APT_DAT = """I
1200 Version - data cycle 2026.11

1    282 0 0 BGGH Nuuk
1302 flatten 1
1302 datum_lat 64.19
100 44.81 1 627 0.00 0 3 0  04 64.18 -51.686 0 0 3 1 0 3 22 64.20 -51.672 0 0 3 1 0 3
110 1 0.25 0.00 Apron
111 64.185 -51.68
113 64.186 -51.68
130 Airport Boundary
111 64.18 -51.69
112 64.18 -51.67 64.181 -51.668
111 64.20 -51.67
113 64.20 -51.69
111 64.19 -51.685
111 64.19 -51.675
113 64.195 -51.68
1050 128250 ATIS

1    100 0 0 XNOF Not flattened
130 Airport Boundary
111 10.1 10.1
111 10.1 10.2
113 10.2 10.2

1    50 0 0 XNOB Flatten without boundary
1302 flatten 1
100 30 1 0 0 0 0 0 09 10.5 10.5 0 0 0 0 0 0 27 10.5 10.6 0 0 0 0 0 0

17   10 0 0 XHEL Heliport, flatten 0
1302 flatten 0
99
"""


@pytest.fixture
def tmp_index(tmp_path, monkeypatch):
    monkeypatch.setattr(FNAMES, "Tmp_dir", str(tmp_path / "tmp"))
    return tmp_path


def test_parse_keeps_only_flatten_airports_with_boundary():
    apts = XPAPT.parse_apt_dat(APT_DAT.splitlines())
    assert [a["icao"] for a in apts] == ["BGGH"]
    a = apts[0]
    assert a["elev_m"] == 85.95  # 282 ft
    # One boundary: the outline (the bezier row's node kept, its control
    # point dropped) and one hole; the apron (110) is not a boundary.
    assert len(a["polygons"]) == 1
    outline, hole = a["polygons"][0]
    assert outline == [[-51.69, 64.18], [-51.67, 64.18], [-51.67, 64.20],
                       [-51.69, 64.20]]
    assert hole == [[-51.685, 64.19], [-51.675, 64.19], [-51.68, 64.195]]


def test_parse_reads_bytes_and_skips_broken_rows():
    lines = [line.encode() for line in APT_DAT.splitlines()]
    lines.insert(13, b"111 64.18 notanumber")
    lines.insert(3, b"1 xx")
    assert XPAPT.parse_apt_dat(lines) == XPAPT.parse_apt_dat(
        APT_DAT.splitlines())


def test_find_apt_dat_next_to_overlay_source(tmp_path):
    gs = tmp_path / "Global Scenery"
    src = gs / "X-Plane 12 Global Scenery"
    src.mkdir(parents=True)
    assert XPAPT.find_apt_dat(["", str(src)]) is None
    apt = gs / "Global Airports" / "Earth nav data" / "apt.dat"
    apt.parent.mkdir(parents=True)
    apt.write_text(APT_DAT)
    assert XPAPT.find_apt_dat(["", str(src) + os.sep]) == str(apt)


def test_index_built_once_and_rebuilt_when_apt_dat_changes(
    tmp_index, monkeypatch
):
    apt = tmp_index / "apt.dat"
    apt.write_text(APT_DAT)
    calls = []
    real = XPAPT.parse_apt_dat
    monkeypatch.setattr(XPAPT, "parse_apt_dat",
                        lambda f: calls.append(1) or real(f))
    first = XPAPT.load_airports(str(apt))
    assert [a["icao"] for a in first] == ["BGGH"] and len(calls) == 1
    assert XPAPT.load_airports(str(apt)) == first and len(calls) == 1
    with open(XPAPT.index_path(), encoding="utf-8") as f:
        assert json.load(f)["source"]["size"] == apt.stat().st_size
    apt.write_text(APT_DAT.replace("1302 flatten 1\n1302 datum", "1302 datum"))
    assert XPAPT.load_airports(str(apt)) == [] and len(calls) == 2
    assert XPAPT.load_airports(str(tmp_index / "missing.dat")) is None


def test_broken_index_is_rebuilt(tmp_index):
    apt = tmp_index / "apt.dat"
    apt.write_text(APT_DAT)
    os.makedirs(os.path.dirname(XPAPT.index_path()))
    with open(XPAPT.index_path(), "w") as f:
        f.write("{not json")
    assert [a["icao"] for a in XPAPT.load_airports(str(apt))] == ["BGGH"]


def square(lon0, lat0, lon1, lat1):
    return [(lon0, lat0), (lon1, lat0), (lon1, lat1), (lon0, lat1)]


def test_tile_areas_clipped_inside_tile_and_in_tile_coordinates():
    apts = [
        {"icao": "EDGE", "elev_m": 10.0,
         "polygons": [[square(11.9, 55.4, 12.1, 55.6)]]},
        {"icao": "HOLE", "elev_m": 20.0,
         "polygons": [[square(12.2, 55.2, 12.4, 55.4),
                       square(12.25, 55.25, 12.35, 55.35)]]},
        {"icao": "AWAY", "elev_m": 30.0,
         "polygons": [[square(13.2, 55.2, 13.4, 55.4)]]},
    ]
    areas = {icao: (elev, area)
             for icao, elev, area in XPAPT.tile_flatten_areas(apts, 55, 12)}
    assert set(areas) == {"EDGE", "HOLE"}
    elev, edge = areas["EDGE"]
    assert elev == 10.0
    x0, y0, x1, y1 = edge.bounds
    assert x0 == pytest.approx(XPAPT.EDGE_INSET) and x0 > 0
    assert (y0, x1, y1) == pytest.approx((0.4, 0.1, 0.6))
    hole_area = areas["HOLE"][1]
    assert len(hole_area.geoms) == 1
    assert len(hole_area.geoms[0].interiors) == 1
    assert hole_area.area == pytest.approx(0.04 - 0.01)


def test_setting_off_or_no_xplane_gives_nothing(monkeypatch, tmp_path):
    tile = types.SimpleNamespace(lat=64, lon=-52)
    monkeypatch.setattr(XPAPT, "xp_flatten_airports", False)
    assert XPAPT.flatten_areas_for_tile(tile, [str(tmp_path)]) == []
    monkeypatch.setattr(XPAPT, "xp_flatten_airports", True)
    assert XPAPT.flatten_areas_for_tile(tile, [str(tmp_path), ""]) == []


class FakeVectorMap:
    def __init__(self):
        self.ways = []
        self.seeds = {}

    def insert_way(self, way, marker, check=True):
        self.ways.append((way, marker))


def airport(runway=None):
    empty = geometry.MultiPolygon()
    return {"runway": [runway or empty, [], []], "taxiway": [empty, []],
            "apron": [empty, []]}


def test_include_inserts_flat_rings_and_skips_osm_surfaces(monkeypatch):
    area = geometry.MultiPolygon([geometry.Polygon(
        square(0.3, 0.18, 0.33, 0.2), [square(0.31, 0.185, 0.32, 0.19)])])
    rwy = geometry.MultiPolygon([geometry.box(0.305, 0.181, 0.306, 0.199)])
    dico = {"BGGH": airport(rwy), "Other": airport(
        geometry.MultiPolygon([geometry.box(0.5, 0.5, 0.51, 0.51)]))}
    vm, patches_list = FakeVectorMap(), []
    tile = types.SimpleNamespace(lat=64, lon=-52)
    out = VMAP.include_xp_flatten_areas(
        vm, tile, [("BGGH", 85.95, area)], dico, geometry.Polygon(),
        patches_list)
    assert [m for _, m in vm.ways] == ["INTERP_ALT", "INTERP_ALT"]
    for way, _ in vm.ways:
        assert way.shape[1] == 3 and (way[:, 2] == 85.95).all()
        assert (way[0] == way[-1]).all()
    (seed,) = vm.seeds["INTERP_ALT"]
    assert area.contains(geometry.Point(seed))
    assert patches_list == ["BGGH"]  # its OSM runway is not levelled again
    assert out.area == pytest.approx(area.area)


def test_user_patch_named_after_airport_wins():
    area = geometry.MultiPolygon([geometry.box(0.3, 0.18, 0.33, 0.2)])
    vm, patches_list = FakeVectorMap(), ["BGGH"]
    out = VMAP.include_xp_flatten_areas(
        vm, types.SimpleNamespace(lat=64, lon=-52), [("BGGH", 85.95, area)],
        {"BGGH": airport()}, geometry.Polygon(), patches_list)
    assert vm.ways == [] and vm.seeds == {} and out.is_empty
    assert patches_list == ["BGGH"]


def test_setting_is_an_app_setting_on_by_default():
    import O4_Cfg_Vars as CV
    assert CV.cfg_vars["xp_flatten_airports"]["default"] is True
    assert "xp_flatten_airports" in CV.list_app_vars
    assert XPAPT.xp_flatten_airports is True


# --- #119: elevation data ramped around the flat areas -------------------

def flat_dem(n=1001, value=40.0):
    import numpy
    return numpy.full((n, n), value, dtype=numpy.float32)


def sample(dem, x, y, n=1001):
    """Sample at tile coordinates (x, y) of a DEM spanning 0..1."""
    return float(dem[round((1 - y) * (n - 1)), round(x * (n - 1))])


def test_ramp_flat_inside_linear_around_untouched_beyond():
    import O4_Geo_Utils as GEO
    dem = flat_dem()
    area = geometry.MultiPolygon([geometry.box(0.4, 0.4, 0.6, 0.6)])
    n = XPAPT.ramp_dem_around_areas(dem, (0, 0, 1, 1),
                                    [("BGGH", 86.0, area)], 64, width_m=100)
    assert n > 0
    assert sample(dem, 0.5, 0.5) == pytest.approx(86.0)
    assert sample(dem, 0.4, 0.5) == pytest.approx(86.0)  # on the boundary
    # 50 m north of the area (the grid is 0.001 deg: 111 m per row, so
    # check by distance: one row north is 111 m, beyond the ramp).
    assert sample(dem, 0.5, 0.601) == pytest.approx(40.0)
    # East: one column is 0.001 deg = ~48.8 m at 64 N, inside the ramp.
    d = 0.001 * GEO.lon_to_m(64)
    assert sample(dem, 0.601, 0.5) == pytest.approx(86 + (40 - 86) * d / 100,
                                                     abs=0.01)
    assert sample(dem, 0.603, 0.5) == pytest.approx(40.0)
    assert sample(dem, 0.1, 0.1) == pytest.approx(40.0)


def test_ramp_keeps_the_slope_gentle():
    import numpy
    import O4_Geo_Utils as GEO
    dem = flat_dem(value=40.0)
    area = geometry.MultiPolygon([geometry.box(0.4, 0.4, 0.6, 0.6)])
    XPAPT.ramp_dem_around_areas(dem, (0, 0, 1, 1), [("X", 86.0, area)], 64,
                                width_m=100)
    row = dem[500].astype(float)
    step_m = 0.001 * GEO.lon_to_m(64)
    worst = numpy.degrees(numpy.arctan(numpy.abs(numpy.diff(row)) / step_m))
    # 46 m over 100 m: 24.7 deg at most (before: one sample from 86 to 40).
    assert worst.max() < 25.5


def test_ramp_without_areas_or_outside_the_dem_changes_nothing():
    dem = flat_dem()
    assert XPAPT.ramp_dem_around_areas(dem, (0, 0, 1, 1), [], 64) == 0
    far = geometry.MultiPolygon([geometry.box(3, 3, 4, 4)])
    assert XPAPT.ramp_dem_around_areas(
        dem, (0, 0, 1, 1), [("X", 86.0, far)], 64) == 0
    assert (dem == 40.0).all()


def test_areas_without_user_patch(tmp_path):
    area = geometry.MultiPolygon([geometry.box(0.3, 0.18, 0.33, 0.2)])
    areas = [("BGGH", 85.95, area), ("BGSF", 50.0, area)]
    (tmp_path / "BGGH.patch.osm").write_text("<osm></osm>")
    assert XPAPT.areas_without_user_patch(areas, str(tmp_path)) == areas[1:]
    assert XPAPT.areas_without_user_patch(
        areas, str(tmp_path / "missing")) == areas
