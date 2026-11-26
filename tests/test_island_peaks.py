"""VECT_MAP.add_island_peaks: small islets with no inner node get one at
their DEM top, so that step 2's sea levelling does not flatten them (#147)."""
import types

import numpy
from shapely import geometry

import O4_Geo_Utils as GEO
import O4_Vector_Map as VMAP
import O4_Vector_Utils as VECT

LAT = 60


class FakeDem:
    x0 = y0 = 0.0
    x1 = y1 = 1.0
    nxdem = nydem = 3601

    def __init__(self, top, centre):
        (self.top, self.centre) = (top, centre)

    def alt_vec(self, points):
        p = numpy.asarray(points, dtype=float)
        d = numpy.hypot((p[:, 0] - self.centre[0]) * GEO.lon_to_m(LAT + 0.5),
                        (p[:, 1] - self.centre[1]) * GEO.lat_to_m)
        return numpy.maximum(self.top - d / 10, 0.0)  # a 10 % slope cone


def square(cx, cy, side_m):
    hx = side_m / 2 / GEO.lon_to_m(LAT + 0.5)
    hy = side_m / 2 / GEO.lat_to_m
    return [(cx - hx, cy - hy), (cx + hx, cy - hy), (cx + hx, cy + hy),
            (cx - hx, cy + hy)]


def sea_with_island(side_m, centre=(0.5, 0.5)):
    return geometry.MultiPolygon([geometry.Polygon(
        [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)],
        [square(*centre, side_m)])])


def tile(top, centre=(0.5, 0.5)):
    return types.SimpleNamespace(lat=LAT, dem=FakeDem(top, centre))


def test_islet_gets_its_top():
    vm = VECT.Vector_Map()
    assert VMAP.add_island_peaks(vm, sea_with_island(200), tile(15)) == 1
    [((x, y), node)] = vm.dico_nodes.items()
    assert abs(vm.data_nodes[node] - 15) < 2.5   # on the 1" grid near the top
    assert abs(x - 0.5) < 2e-4 and abs(y - 0.5) < 2e-4


def test_low_islet_is_left_flat():
    vm = VECT.Vector_Map()
    assert VMAP.add_island_peaks(vm, sea_with_island(200), tile(1.5)) == 0
    assert not vm.dico_nodes


def test_large_island_is_left_to_the_mesher():
    vm = VECT.Vector_Map()
    assert VMAP.add_island_peaks(vm, sea_with_island(1200), tile(40)) == 0


def test_island_with_a_node_inside_is_left_alone():
    # e.g. an airport or a road: a lone node in a levelled area would
    # raise it, and the island has inner points anyway
    vm = VECT.Vector_Map()
    vm.insert_node(0.5001, 0.5, 3.0)
    assert VMAP.add_island_peaks(vm, sea_with_island(200), tile(15)) == 0
    assert len(vm.dico_nodes) == 1


def test_islet_smaller_than_a_dem_cell():
    vm = VECT.Vector_Map()
    assert VMAP.add_island_peaks(vm, sea_with_island(12), tile(5)) == 1
