"""O4_Geo_Utils: Web Mercator tile/pixel grids and distances."""
from math import pi

import pytest

import O4_Geo_Utils as GEO

R = GEO.earth_radius


def test_metres_per_degree():
    assert GEO.lat_to_m == pytest.approx(111319.4908, abs=1e-3)
    assert GEO.lon_to_m(0) == pytest.approx(GEO.lat_to_m)
    assert GEO.lon_to_m(60) == pytest.approx(GEO.lat_to_m / 2)
    assert GEO.m_to_lon(55) * GEO.lon_to_m(55) == pytest.approx(1)


def test_dist_is_great_circle():
    assert GEO.dist((0, 0), (0, 1)) == pytest.approx(GEO.lat_to_m)
    assert GEO.dist((12, 55), (12, 55)) == 0
    a, b = (12.5, 55.6), (-0.1, 51.5)  # Copenhagen - London
    assert GEO.dist(a, b) == pytest.approx(GEO.dist(b, a))
    # ~955 km on the WGS84 ellipsoid; this sphere uses the equatorial
    # radius and gives 948 km.
    assert GEO.dist(a, b) == pytest.approx(948162.42, abs=0.01)


def test_webmercator_pixel_size():
    assert GEO.webmercator_pixel_size(0, 0) == pytest.approx(2 * pi * R / 256)
    assert GEO.webmercator_pixel_size(60, 17) == pytest.approx(
        GEO.webmercator_pixel_size(0, 17) / 2)


@pytest.mark.parametrize("zl", [1, 12, 17, 19])
def test_gtile_corners(zl):
    lat, lon = GEO.gtile_to_wgs84(0, 0, zl)
    assert lon == -180
    assert lat == pytest.approx(85.0511287798, abs=1e-9)  # Web Mercator limit
    lat, lon = GEO.gtile_to_wgs84(2 ** (zl - 1), 2 ** (zl - 1), zl)
    assert (lat, lon) == pytest.approx((0, 0), abs=1e-9)


@pytest.mark.parametrize("lat,lon", [(55.5, 12.5), (-33.9, 151.2), (43.5, -66.5), (0.3, -0.3)])
@pytest.mark.parametrize("zl", [12, 16, 18])
def test_wgs84_to_gtile_contains_point(lat, lon, zl):
    tx, ty = GEO.wgs84_to_gtile(lat, lon, zl)
    top, left = GEO.gtile_to_wgs84(tx, ty, zl)
    bottom, right = GEO.gtile_to_wgs84(tx + 1, ty + 1, zl)
    # wgs84_to_gtile rounds to the nearest pixel first: allow half a pixel.
    half_pix_lon = 360 / 2 ** (zl + 9)
    assert left - half_pix_lon <= lon < right + half_pix_lon
    assert bottom - 1e-6 <= lat <= top + 1e-6


@pytest.mark.parametrize("pix", [(0, 0), (123456, 654321), (2 ** 24, 2 ** 24 + 17)])
def test_pixel_round_trip(pix):
    zl = 17
    lat, lon = GEO.pix_to_wgs84(*pix, zl)
    assert GEO.wgs84_to_pix(lat, lon, zl) == pix


def test_quadkey():
    # Example from Microsoft's "Bing Maps Tile System" documentation.
    assert GEO.gtile_to_quadkey(3, 5, 3) == "213"
    assert GEO.gtile_to_quadkey(0, 0, 1) == "0"
    assert GEO.gtile_to_quadkey(1, 1, 1) == "3"
    assert len(GEO.gtile_to_quadkey(69904, 40800, 17)) == 17


def test_orthogrid_matches_real_mask_names():
    # Masks of tile +55+012 at mask_zl 14 are named <y>_<x>.png with
    # y 5088..5168 and x 8736..8768 (frozen regression baseline).
    assert GEO.wgs84_to_orthogrid(56, 12, 14) == (8736, 5088)
    assert GEO.wgs84_to_orthogrid(55, 13, 14) == (8768, 5168)
    # Texture 40800_69904_Arc17.dds (<y>_<x>) of tile +55+012 at ZL17:
    # its centre maps back to it. Textures follow the Mercator grid, not
    # the 1 degree tiles: this one is the tile's north-west corner texture
    # and sticks out over both edges (56 N, 12 E).
    lat, lon = GEO.gtile_to_wgs84(69904 + 8, 40800 + 8, 17)
    assert GEO.wgs84_to_orthogrid(lat, lon, 17) == (69904, 40800)
    top, left = GEO.gtile_to_wgs84(69904, 40800, 17)
    bottom, right = GEO.gtile_to_wgs84(69904 + 16, 40800 + 16, 17)
    assert bottom < 56 < top and left < 12 < right


@pytest.mark.parametrize("zl", [14, 16, 17, 18])
def test_orthogrid_is_aligned_to_16(zl):
    x, y = GEO.wgs84_to_orthogrid(43.21, -65.43, zl)
    assert x % 16 == 0 and y % 16 == 0


def test_st_coord_in_texture():
    zl = 17
    x, y = GEO.wgs84_to_orthogrid(55.65, 12.02, zl)
    top, left = GEO.gtile_to_wgs84(x, y, zl)
    bottom, right = GEO.gtile_to_wgs84(x + 16, y + 16, zl)
    assert GEO.st_coord(top, left, x, y, zl, "Arc") == pytest.approx((0, 1))
    assert GEO.st_coord(bottom, right, x, y, zl, "Arc") == pytest.approx((1, 0), abs=1e-9)
    s, t = GEO.st_coord(55.65, 12.02, x, y, zl, "Arc")
    assert 0 <= s <= 1 and 0 <= t <= 1
    # Points outside the texture are clamped to its border.
    assert GEO.st_coord(0, 0, x, y, zl, "Arc") == (0, 0)
