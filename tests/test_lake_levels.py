"""Flat lakes (#148): VECT.lake_levels picks the water polygons whose DEM
is flat inside, MESH.level_lakes sets their vertices to that level."""
import numpy
from shapely import geometry

import O4_Mesh_Utils as MESH
import O4_Vector_Utils as VECT


class FakeDem:
    x0 = y0 = 0.0
    x1 = y1 = 1.0
    nxdem = nydem = 3601

    def __init__(self, f):
        self.f = f

    def alt_vec(self, points):
        p = numpy.asarray(points, dtype=float)
        return self.f(p[:, 0], p[:, 1])


def box(x0, y0, x1, y1):
    return geometry.box(x0, y0, x1, y1)


def test_flat_lake_with_steep_banks_gets_its_water_level():
    # 120 m of lake, banks rising right from the shore: the samples keep
    # away from the shore cells
    lake = box(0.5, 0.5, 0.51, 0.51)

    def f(x, y):
        out = numpy.full(len(x), 100.0)
        inside = (x > 0.5005) & (x < 0.5095) & (y > 0.5005) & (y < 0.5095)
        out[inside] = 42.0
        return out

    [(level, polygon)] = VECT.lake_levels([lake], FakeDem(f), 0)
    assert level == 42.0 and polygon.equals(lake)


def test_sloping_river_is_not_a_lake():
    river = box(0.2, 0.2, 0.4, 0.205)
    dem = FakeDem(lambda x, y: 50 + 100 * x)   # 20 m along it
    assert VECT.lake_levels([river], dem, 0) == []


def test_too_small_to_sample_and_area_limit():
    dem = FakeDem(lambda x, y: numpy.zeros(len(x)))
    assert VECT.lake_levels([box(0.5, 0.5, 0.5003, 0.5003)], dem, 0) == []
    assert VECT.lake_levels([box(0.5, 0.5, 0.51, 0.51)], dem, 1e-3) == []


def test_level_lakes_sets_water_vertices_only():
    lakes = [(10.0, box(0, 0, 1, 1)), (7.0, box(1, 0, 2, 1))]
    # vertices: inside lake 1, on the shared border, inside lake 2,
    # outside both (water), inside lake 1 but not a water vertex
    xy = [(0.5, 0.5), (1.0, 0.5), (1.5, 0.5), (3.0, 0.5), (0.2, 0.2)]
    vertices = numpy.zeros(6 * len(xy))
    for (i, (x, y)) in enumerate(xy):
        vertices[6 * i: 6 * i + 3] = (x, y, 99.0)
    n = MESH.level_lakes(vertices, {(0, 1, 2), (1, 2, 3)}, lakes, 1e-6)
    assert n == 3
    assert list(vertices[2::6]) == [10.0, 7.0, 7.0, 99.0, 99.0]


def test_level_lakes_catches_shore_nodes_within_tolerance():
    vertices = numpy.array([1.0 + 5e-7, 0.5, 3.0, 0, 0, 0])
    assert MESH.level_lakes(vertices, {(0, 0, 0)}, [(1.0, box(0, 0, 1, 1))], 1e-6) == 1
    assert vertices[2] == 1.0


def test_lake_file_roundtrip(tmp_path):
    path = str(tmp_path / "Data+60+010.lakes")
    lakes = [(12.5, box(0.1, 0.1, 0.2, 0.2).difference(box(0.14, 0.14, 0.16, 0.16)))]
    VECT.write_lake_levels(path, lakes)
    [(level, polygon)] = VECT.read_lake_levels(path)
    assert level == 12.5 and polygon.equals(lakes[0][1])
    assert VECT.read_lake_levels(str(tmp_path / "missing.lakes")) == []
    (tmp_path / "bad.lakes").write_text("{not json")
    assert VECT.read_lake_levels(str(tmp_path / "bad.lakes")) == []


def test_river_leaving_a_lake_keeps_its_slope():
    # one merged polygon: a flat lake at 42 m and a 30 m wide river that
    # drops 40 m to the east; only the lake (grown back to its shore) is
    # levelled
    lake = box(0.50, 0.50, 0.51, 0.51)
    river = box(0.51, 0.5049, 0.60, 0.5051)
    water = lake.union(river)

    def f(x, y):
        return numpy.where(x <= 0.51, 42.0, 42.0 - (x - 0.51) / 0.09 * 40)

    [(level, region)] = VECT.lake_levels([water], FakeDem(f), 0)
    assert level == 42.0
    assert region.contains(geometry.Point(0.505, 0.505))
    assert region.buffer(1e-9).contains(lake)
    assert not region.intersects(geometry.Point(0.53, 0.505))


def test_lake_flat_at_zero_is_left_to_smoothing():
    # the DEM's no-data over lakes, filled with 0
    dem = FakeDem(lambda x, y: numpy.zeros(len(x)))
    assert VECT.lake_levels([box(0.5, 0.5, 0.51, 0.51)], dem, 0) == []


def test_level_lakes_does_not_raise_an_outflow():
    vertices = numpy.zeros(18)
    for (i, z) in enumerate((60.0, 51.5, 30.0)):   # shore, near, outflow
        vertices[6 * i: 6 * i + 3] = (0.5, 0.5, z)
    n = MESH.level_lakes(vertices, {(0, 1, 2)}, [(53.0, box(0, 0, 1, 1))], 1e-6)
    assert n == 2
    assert list(vertices[2::6]) == [53.0, 53.0, 30.0]
