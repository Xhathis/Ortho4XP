"""custom_dem rasters: a gap in the tile is reported, oversized rasters stop.

Outside a custom raster the altitude is the raster's nearest edge value
(alt_nostrict clamps, and so does Triangle4XP); the config hint used to say
zero, and nothing was logged.
"""
import numpy
import pytest
from osgeo import gdal, osr

import O4_DEM_Utils as DEM
import O4_UI_Utils as UI

gdal.UseExceptions()


def _write_tif(path, arr, west, north, step, nodata=-9999.0):
    """GeoTIFF (EPSG:4326, pixel is area) whose first sample centre is
    (west, north)."""
    ds = gdal.GetDriverByName("GTiff").Create(
        str(path), arr.shape[1], arr.shape[0], 1, gdal.GDT_Float32
    )
    ds.SetGeoTransform((west - step / 2, step, 0, north + step / 2, 0, -step))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(nodata)
    band.WriteArray(arr)
    band = ds = None
    return str(path)


@pytest.fixture
def warnings(monkeypatch):
    seen = []

    def fake_lvprint(level, *args):
        text = " ".join(str(a) for a in args)
        if "WARNING" in text:
            seen.append(text)

    monkeypatch.setattr(UI, "lvprint", fake_lvprint)
    return seen


# ---------------------------------------------------------------- pure helper
def test_whole_tile_has_no_gap():
    assert DEM.raster_gaps_in_tile(0, 0, 1, 1, 3601, 3601) == []


def test_larger_raster_has_no_gap():
    assert DEM.raster_gaps_in_tile(-0.01, -0.01, 1.01, 1.01, 3673, 3673) == []


def test_one_sample_short_is_no_gap():
    # Copernicus GLO-30 at 55N: 2400 columns of 1.5" and 3600 rows of 1",
    # the last ones one sample west of the east and north of the south edge.
    assert DEM.raster_gaps_in_tile(
        0, 1 / 3600, 1 - 1 / 2400, 1, 2400, 3600
    ) == []


def test_half_tile_reports_the_sides():
    assert DEM.raster_gaps_in_tile(0, 0, 0.5, 1, 501, 1001) == ["east"]
    assert DEM.raster_gaps_in_tile(0.2, 0.3, 0.8, 1, 601, 701) == [
        "west", "east", "south",
    ]


def test_two_samples_short_is_a_gap():
    step = 0.001
    assert DEM.raster_gaps_in_tile(0, 0, 1 - 2 * step, 1, 999, 1001) == ["east"]


# ------------------------------------------------------------ through DEM()
def test_half_tile_raster_warns_and_extends_edge(tmp_path, warnings):
    n, w, step = 1001, 501, 0.001
    arr = numpy.full((n, w), 100.0, dtype=numpy.float32)
    arr[:, -1] = 200.0
    path = _write_tif(tmp_path / "half.tif", arr, 12.0, 56.0, step)
    dem = DEM.DEM(55, 12, path, "to zero")
    assert len(warnings) == 1
    assert "+55+012" in warnings[0] and "east" in warnings[0]
    # The documented behaviour now: the edge value, not zero.
    pts = numpy.array([[0.25, 0.5], [0.75, 0.5], [1.0, 0.5]])
    assert list(dem.alt_vec(pts)) == [100.0, 200.0, 200.0]


def test_partial_ok_and_info_only_stay_quiet(tmp_path, warnings):
    arr = numpy.full((1001, 501), 100.0, dtype=numpy.float32)
    path = _write_tif(tmp_path / "half.tif", arr, 12.0, 56.0, 0.001)
    DEM.DEM(55, 12, path, "to zero", partial_ok=True)
    DEM.DEM(55, 12, path, "to zero", info_only=True)
    assert warnings == []


def test_composite_local_source_stays_quiet(tmp_path, warnings):
    full = numpy.full((101, 101), 50.0, dtype=numpy.float32)
    main = _write_tif(tmp_path / "main.tif", full, 12.0, 56.0, 0.01)
    part = numpy.full((101, 51), 70.0, dtype=numpy.float32)
    local = _write_tif(tmp_path / "local.tif", part, 12.0, 56.0, 0.01)
    dem = DEM.DEM(55, 12, main + ";" + local, "to zero")
    assert warnings == []
    pts = numpy.array([[0.25, 0.5], [0.75, 0.5]])
    assert list(dem.alt_vec(pts)) == [70.0, 50.0]


def test_whole_tile_raster_stays_quiet(tmp_path, warnings):
    arr = numpy.full((101, 101), 10.0, dtype=numpy.float32)
    path = _write_tif(tmp_path / "full.tif", arr, 12.0, 56.0, 0.01)
    DEM.DEM(55, 12, path, "to zero")
    assert warnings == []


def test_oversized_raster_stops(tmp_path, monkeypatch):
    # A real 65536-sample raster would take GBs; a smaller limit checks the
    # same path (the size is read before any sample).
    monkeypatch.setattr(DEM, "MAX_RASTER_SIDE", 100)
    arr = numpy.zeros((10, 101), dtype=numpy.float32)
    path = _write_tif(tmp_path / "wide.tif", arr, 12.0, 56.0, 0.01)
    with pytest.raises(DEM.DEMError, match="at most 100 per side"):
        DEM.DEM(55, 12, path, "to zero")


def test_too_many_samples_stop(tmp_path, monkeypatch):
    # Triangle4XP indexes the grid in a C int: the total counts, not only
    # each side (46341 x 46341 overflows it, though both sides fit uint16).
    monkeypatch.setattr(DEM, "MAX_RASTER_SAMPLES", 50 * 50)
    arr = numpy.zeros((51, 50), dtype=numpy.float32)
    path = _write_tif(tmp_path / "big.tif", arr, 12.0, 56.0, 0.02)
    with pytest.raises(DEM.DEMError, match="at most 2500 in all"):
        DEM.DEM(55, 12, path, "to zero")


def test_real_limits_fit_the_indices():
    assert DEM.MAX_RASTER_SIDE <= numpy.iinfo(numpy.uint16).max
    assert DEM.MAX_RASTER_SAMPLES <= numpy.iinfo(numpy.int32).max
    assert 46341 * 46341 > DEM.MAX_RASTER_SAMPLES >= 46340 * 46340
