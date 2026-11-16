"""0.5" and 1/3" .hgt files in Elevation_data (#113).

The combined View/SRTM raster takes 1" (3601) grids; a finer grid whose
posts include every 1" post is thinned to it instead of stopping the tile
(own file) or zeroing its margin (neighbour file).
"""
import numpy
import pytest

import O4_DEM_Utils as DEM


def _grid(n):
    i, j = numpy.indices((n, n))
    # Exact in float32 (< 2**24) and different at every 1" post nearby.
    return ((i % 997) * 1000 + (j % 991)).astype(numpy.float32)


def test_half_second_gives_the_1s_posts():
    a = _grid(7201)
    t = DEM.thin_to_grid(a, 3601)
    assert t.shape == (3601, 3601)
    assert t[0, 0] == a[0, 0] and t[-1, -1] == a[-1, -1]
    assert t[1800, 7] == a[3600, 14]


def test_third_second_gives_the_1s_posts():
    a = _grid(10801)
    t = DEM.thin_to_grid(a, 3601)
    assert t.shape == (3601, 3601)
    assert t[5, 9] == a[15, 27] and t[-1, -1] == a[-1, -1]


@pytest.mark.parametrize("shape", [(3601, 3601), (1201, 1201), (5000, 5000),
                                   (7200, 7200), (7201, 3601)])
def test_other_grids_are_not_thinned(shape):
    assert DEM.thin_to_grid(numpy.zeros(shape, numpy.float32), 3601) is None


@pytest.fixture
def files(monkeypatch):
    """All 9 tiles are land; read_elevation_from_file serves `grids`."""
    grids = {}
    monkeypatch.setattr(
        DEM.Image, "open", lambda path: numpy.full((180, 360), 255, numpy.uint8)
    )
    monkeypatch.setattr(DEM, "ensure_elevation", lambda *a, **k: True)

    def read(file_name, lat, lon, *a, **k):
        g = grids.get((lat, lon))
        if g is None:
            g = numpy.full((3601, 3601), 100, numpy.float32)
        return (4326, 0, 0, 1, 1, -32768, g.shape[1], g.shape[0], g)

    monkeypatch.setattr(DEM, "read_elevation_from_file", read)
    return grids


def test_own_half_second_file_builds(files):
    # +47+011 of the ZL16 pilot (2026-11-16) stopped with DEMError.
    a = _grid(7201)
    files[(47, 11)] = a
    alt = DEM.build_combined_raster("View", 47, 11, False)[-1]
    b = DEM.COMBINED_MARGIN
    assert numpy.array_equal(alt[b:-b, b:-b], a[::2, ::2])


def test_neighbour_half_second_margin_not_zero(files):
    # +48+011's south margin came from N47E011 (0.5") and was set to zero.
    a = _grid(7201)
    files[(47, 11)] = a
    alt = DEM.build_combined_raster("View", 48, 11, False)[-1]
    b = DEM.COMBINED_MARGIN
    # The south margin is the neighbour's rows 1..b (row 0 is the shared
    # edge, overlap 1) of the thinned grid.
    assert numpy.array_equal(alt[-b:, b:-b], a[::2, ::2][1:b + 1, :])
    assert (alt[:b, b:-b] == 100).all()


def test_unusable_grid_still_stops_the_tile(files):
    files[(47, 11)] = numpy.zeros((5000, 5000), numpy.float32)
    with pytest.raises(DEM.DEMError, match="5000 x 5000"):
        DEM.build_combined_raster("View", 47, 11, False)
