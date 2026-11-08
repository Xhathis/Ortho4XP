"""#73: the airport smoothing window sits on the airport.

The DEM has nxdem samples from x0 to x1 inclusive. smooth_raster_over_airports
divided by nxdem instead of nxdem - 1, so its window was up to one sample
east/south of the airport (one sample at the east/north edge of the tile).
"""
import numpy
from shapely import geometry

import O4_Airport_Utils as APT
import O4_DEM_Utils as DEM


class _Dem:
    def __init__(self, n):
        self.x0, self.x1, self.y0, self.y1 = 0.0, 1.0, 0.0, 1.0
        self.nxdem = self.nydem = n
        self.alt_dem = numpy.zeros((n, n), dtype=numpy.float32)

    def write_to_file(self, path):
        pass


class _Tile:
    def __init__(self, n):
        self.dem = _Dem(n)
        self.apt_smoothing_pix = 1


def _window(monkeypatch, box):
    # Mark the window passed to smoothen, see where it lands in alt_dem.
    monkeypatch.setattr(
        DEM, "smoothen",
        lambda arr, pix, im, preserve_boundary=False: numpy.ones_like(arr),
    )
    monkeypatch.setattr(APT.FNAMES, "alt_file", lambda tile: "unused")
    tile = _Tile(101)  # samples every 0.01
    empty = geometry.Polygon()
    pol = geometry.box(*box)
    apt = {
        "boundary": pol, "runway": [empty], "hangar": empty,
        "taxiway": [empty], "apron": [empty],
    }
    APT.smooth_raster_over_airports(tile, {"X": apt}, preserve_boundary=False)
    rows, cols = numpy.nonzero(tile.dem.alt_dem)
    return cols.min(), cols.max(), rows.min(), rows.max()


def test_window_is_the_airport_plus_pix(monkeypatch):
    # x 0.50-0.60 -> columns 50-60, y 0.30-0.40 -> rows 60-70 (row 0 = y1);
    # plus pix = 1 on each side.
    assert _window(monkeypatch, (0.50, 0.30, 0.60, 0.40)) == (49, 61, 59, 71)


def test_window_at_the_north_east_corner(monkeypatch):
    # Old step: columns up to ceil(0.99 * 101) + 1, clipped to 100.
    assert _window(monkeypatch, (0.90, 0.90, 0.99, 0.99)) == (89, 100, 0, 11)
