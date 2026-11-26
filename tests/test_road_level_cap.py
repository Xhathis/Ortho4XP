"""Road levelling cap max_levelled_segs: the capped roads are counted (#150)."""
import numpy

import O4_Vector_Map as VMAP


class FakeDem:
    """Slope across x only: a road shifted sideways changes altitude."""

    def __init__(self, slope):
        self.slope = slope

    def alt_vec(self, way):
        return numpy.asarray(way)[:, 0] * self.slope


class FakeTile:
    def __init__(self, slope=100000.0, cap=10):
        self.dem = FakeDem(slope)
        self.lane_width = 4.0
        self.road_banking_limit = 0.5
        self.max_levelled_segs = cap


WAY = numpy.array([[0.5, 0.2], [0.5, 0.3]])
NO_AIRPORT = numpy.zeros((1001, 1001), dtype=bool)


def test_banked_road_is_levelled():
    f = VMAP.RoadBankingFilter(FakeTile(), NO_AIRPORT)
    assert f(WAY, 0) is True
    assert f.skipped == 0


def test_flat_road_is_not_levelled_nor_counted():
    f = VMAP.RoadBankingFilter(FakeTile(slope=0.0), NO_AIRPORT)
    assert f(WAY, 0) is False
    assert f.skipped == 0


def test_cap_reached_counts_skipped_roads():
    f = VMAP.RoadBankingFilter(FakeTile(cap=10), NO_AIRPORT)
    assert f(WAY, 10) is False
    assert f(WAY, 12) is False
    assert f.skipped == 2


def test_airport_road_levelled_past_the_cap():
    apt = NO_AIRPORT.copy()
    # way[0] = (0.5, 0.2): column 500, row 1000 - 200
    apt[800, 500] = True
    f = VMAP.RoadBankingFilter(FakeTile(slope=0.0, cap=10), apt)
    assert f(WAY, 50) is True
    assert f.skipped == 0
