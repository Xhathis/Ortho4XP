"""min_area (km2) against polygons in tile-relative degrees (#149)."""
import pytest

import O4_Geo_Utils as GEO
import O4_Vector_Map as VMAP


@pytest.mark.parametrize("lat", [-56, 0, 55, 64, 75, 82])
def test_same_area_in_m2_at_every_latitude(lat):
    deg2 = VMAP.km2_to_tile_area(0.001, lat)
    m2 = deg2 * GEO.lat_to_m * GEO.lon_to_m(lat + 0.5)
    assert m2 == pytest.approx(1000)


def test_was_latitude_dependent():
    # the old threshold, min_area / 10000 square degrees, is not 1000 m2
    old_m2 = 0.001 / 10000 * GEO.lat_to_m * GEO.lon_to_m(75.5)
    assert old_m2 < 400
