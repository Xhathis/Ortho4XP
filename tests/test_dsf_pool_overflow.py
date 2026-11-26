"""A full DSF point pool continues in an overflow pool (#153)."""
import array

import O4_DSF_Utils as DSF


def test_points_go_to_their_pool():
    pools = DSF.PointPools([7, 9])
    assert pools.add(0, (1, 2, 3), (4, 5, 6, 7)) == (0, 0)
    assert pools.add(1, range(9)) == (1, 0)
    assert pools.add(0, range(7)) == (0, 1)
    assert pools.length == [2, 1]
    assert list(pools.points[0][:7]) == [1, 2, 3, 4, 5, 6, 7]
    assert len(pools) == 2


def test_full_pool_overflows(monkeypatch):
    monkeypatch.setattr(DSF, "POOL_MAX_POINTS", 3)
    pools = DSF.PointPools([2, 7])
    got = [pools.add(0, (i, i)) for i in range(7)]
    # 3 in pool 0, then pool 2 (planes and base of pool 0), then pool 3
    assert got == [(0, 0), (0, 1), (0, 2), (2, 0), (2, 1), (2, 2), (3, 0)]
    assert pools.planes == [2, 7, 2, 2]
    assert pools.base == [0, 1, 0, 0]
    assert pools.length == [3, 0, 3, 1]
    assert list(pools.points[3]) == [6, 6]
    # the other pool is not affected
    assert pools.add(1, range(7)) == (1, 0)


def test_positions_fit_the_16_bit_indices():
    pools = DSF.PointPools([1])
    for i in range(DSF.POOL_MAX_POINTS + 5):
        (k, pos) = pools.add(0, (i % 65536,))
    assert (k, pos) == (1, 4)
    assert pools.length == [DSF.POOL_MAX_POINTS, 5]
    tri = array.array("H")
    tri.extend((k, pos))  # what build_dsf stores: no OverflowError
